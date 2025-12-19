import asyncpg
import logging
from datetime import datetime
from typing import Optional
import tiktoken
import config

logger = logging.getLogger(__name__)

# Ініціалізація токенізатора для підрахунку токенів
encoding = tiktoken.encoding_for_model(config.OPENAI_MODEL)


class Database:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Підключення до бази даних"""
        try:
            self.pool = await asyncpg.create_pool(
                config.DATABASE_URL,
                min_size=1,
                max_size=10,
                statement_cache_size=0  # Вимикаємо prepared statements для Supabase/pgbouncer
            )
            logger.info("✅ Підключення до бази даних успішне")
            await self.create_tables()
        except Exception as e:
            logger.error(f"❌ Помилка підключення до бази даних: {e}")
            raise

    async def create_tables(self):
        """Створення таблиць у базі даних"""
        async with self.pool.acquire() as conn:
            # Таблиця для повідомлень
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    role VARCHAR(20) NOT NULL,
                    content TEXT NOT NULL,
                    tokens_count INTEGER NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    sentiment VARCHAR(20),
                    is_filtered BOOLEAN DEFAULT FALSE
                )
            ''')

            # Таблиця для статистики користувачів
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS user_stats (
                    user_id BIGINT PRIMARY KEY,
                    total_tokens INTEGER DEFAULT 0,
                    message_count INTEGER DEFAULT 0,
                    collection_active BOOLEAN DEFAULT TRUE,
                    reminders_enabled BOOLEAN DEFAULT TRUE,
                    last_reminder_at TIMESTAMP,
                    last_activity_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    collection_completed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Індекси для швидшого пошуку
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id)
            ''')
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp)
            ''')

            logger.info("✅ Таблиці створено або вже існують")

    async def count_tokens(self, text: str) -> int:
        """Підрахунок токенів у тексті"""
        try:
            tokens = encoding.encode(text)
            return len(tokens)
        except Exception as e:
            logger.error(f"Помилка підрахунку токенів: {e}")
            return 0

    def analyze_sentiment(self, text: str) -> str:
        """Простий аналіз настрою (можна покращити пізніше)"""
        text_lower = text.lower()

        positive_words = ['добре', 'чудово', 'супер', 'класно', 'відмінно',
                         'люблю', 'радію', 'щасливий', '😊', '😄', '❤️', '👍']
        negative_words = ['погано', 'жахливо', 'сумно', 'боляче', 'не подобається',
                         'ненавиджу', 'сумую', '😢', '😞', '😠', '💔']

        positive_count = sum(1 for word in positive_words if word in text_lower)
        negative_count = sum(1 for word in negative_words if word in text_lower)

        if positive_count > negative_count:
            return 'positive'
        elif negative_count > positive_count:
            return 'negative'
        else:
            return 'neutral'

    def should_filter_message(self, text: str, tokens_count: int) -> bool:
        """Перевірка чи потрібно фільтрувати повідомлення"""
        # Фільтруємо команди
        if any(text.startswith(cmd) for cmd in config.EXCLUDED_COMMANDS):
            return True

        # Фільтруємо надто короткі повідомлення
        if tokens_count < config.MIN_MESSAGE_TOKENS:
            return True

        # Фільтруємо технічні тексти (можна розширити)
        technical_patterns = ['http://', 'https://', 'www.']
        if any(pattern in text for pattern in technical_patterns):
            return True

        return False

    async def save_message(self, user_id: int, role: str, content: str) -> bool:
        """Зберегти повідомлення у базу даних"""
        try:
            async with self.pool.acquire() as conn:
                # Перевіряємо чи активний збір для користувача
                stats = await conn.fetchrow(
                    'SELECT total_tokens, collection_active FROM user_stats WHERE user_id = $1', user_id
                )

                # Якщо користувача немає, створюємо запис
                if not stats:
                    await conn.execute(
                        'INSERT INTO user_stats (user_id) VALUES ($1)', user_id
                    )
                    stats = {'total_tokens': 0, 'collection_active': True}

                # Оновлюємо час останньої активності (тільки для повідомлень користувача)
                if role == 'user':
                    await conn.execute(
                        'UPDATE user_stats SET last_activity_at = CURRENT_TIMESTAMP WHERE user_id = $1',
                        user_id
                    )

                # Якщо збір неактивний, не зберігаємо
                if not stats['collection_active']:
                    return False

                # Підраховуємо токени
                tokens_count = await self.count_tokens(content)

                # Перевіряємо чи потрібно фільтрувати
                is_filtered = self.should_filter_message(content, tokens_count)

                # Аналізуємо настрій (тільки для повідомлень користувача)
                sentiment = self.analyze_sentiment(content) if role == 'user' else None

                # Зберігаємо повідомлення
                await conn.execute('''
                    INSERT INTO messages
                    (user_id, role, content, tokens_count, sentiment, is_filtered)
                    VALUES ($1, $2, $3, $4, $5, $6)
                ''', user_id, role, content, tokens_count, sentiment, is_filtered)

                # Оновлюємо статистику (тільки нефільтровані повідомлення)
                if not is_filtered:
                    new_total = stats['total_tokens'] + tokens_count
                    await conn.execute('''
                        UPDATE user_stats SET total_tokens = $1, message_count = message_count + 1
                        WHERE user_id = $2
                    ''', new_total, user_id)

                    # Перевіряємо ліміт
                    if new_total >= config.MIN_TOKEN_LIMIT:
                        await self.stop_collection(user_id)
                        return 'limit_reached'

                return True

        except Exception as e:
            logger.error(f"Помилка збереження повідомлення: {e}")
            return False

    async def stop_collection(self, user_id: int):
        """Зупинити збір повідомлень для користувача"""
        async with self.pool.acquire() as conn:
            await conn.execute('''
                UPDATE user_stats SET collection_active = FALSE, collection_completed_at = CURRENT_TIMESTAMP
                WHERE user_id = $1
            ''', user_id)
            logger.info(f"Збір даних для користувача {user_id} зупинено")

    async def get_user_stats(self, user_id: int) -> dict:
        """Отримати статистику користувача"""
        async with self.pool.acquire() as conn:
            stats = await conn.fetchrow(
                'SELECT * FROM user_stats WHERE user_id = $1', user_id
            )
            if stats:
                return dict(stats)
            return None


    async def get_user_messages(self, user_id: int, limit: int = None):
        """Отримати повідомлення користувача"""
        async with self.pool.acquire() as conn:
            query = '''
                SELECT * FROM messages WHERE user_id = $1 AND is_filtered = FALSE
                ORDER BY timestamp DESC
            '''
            if limit:
                query += f' LIMIT {limit}'

            messages = await conn.fetch(query, user_id)
            return [dict(msp) for msp in messages]

    async def toggle_reminders(self, user_id: int, enabled: bool):
        """Увімкнути/вимкнути нагадування для користувача"""
        async with self.pool.acquire() as conn:
            # Перевіряємо чи існує користувач
            exists = await conn.fetchval(
                'SELECT EXISTS(SELECT 1 FROM user_stats WHERE user_id = $1)',
                user_id
            )

            if not exists:
                # Створюємо запис якщо не існує
                await conn.execute(
                    'INSERT INTO user_stats (user_id, reminders_enabled) VALUES ($1, $2)',
                    user_id, enabled
                )
            else:
                # Оновлюємо налаштування
                await conn.execute(
                    'UPDATE user_stats SET reminders_enabled = $1 WHERE user_id = $2',
                    enabled, user_id
                )

            logger.info(f"Нагадування для користувача {user_id}: {'увімкнено' if enabled else 'вимкнено'}")


    async def update_last_reminder(self, user_id: int):
        """Оновити час останнього нагадування"""
        async with self.pool.acquire() as conn:
            await conn.execute('''
                UPDATE user_stats 
                SET last_reminder_at = CURRENT_TIMESTAMP
                WHERE user_id = $1
            ''', user_id)

 # "AND (
 #                    last_activity_at IS NULL
 #                    OR last_activity_at < NOW() - INTERVAL '{config.INACTIVITY_THRESHOLD_MINUTES} minutes'
 #                )"

    async def get_users_for_reminders(self):
        """Отримати список користувачів для нагадувань"""
        async with self.pool.acquire() as conn:
            users = await conn.fetch(f'''
                SELECT user_id FROM user_stats 
                WHERE reminders_enabled = TRUE 
                AND collection_active = TRUE
            
            ''')
            return [user['user_id'] for user in users]


    async def close(self):
        """Закрити з'єднання з базою даних"""
        if self.pool:
            await self.pool.close()
            logger.info("З'єднання з базою даних закрито")


# Глобальний екземпляр бази даних
db = Database()
