import json
import logging
from datetime import datetime
from database import db
import config

logger = logging.getLogger(__name__)


class DataExporter:
    """Клас для експорту даних у формат JSONL для Fine-tuning OpenAI"""

    @staticmethod
    def format_conversation_for_finetuning(messages: list) -> dict:
        """
        Форматує повідомлення в формат для Fine-tuning OpenAI

        Формат:
        {
            "messages": [
                {"role": "system", "content": "..."},
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "..."}
            ]
        }
        """
        formatted_messages = []

        # Додаємо system prompt
        formatted_messages.append({
            "role": "system",
            "content": "Jesteś modelem językowym, który odtwarza styl komunikacji tego użytkownika. Używaj jego słownictwa, tonu, emocjonalności i sposobu formułowania myśli. Odpowiadaj naturalnie, tak jakby pisał to sam użytkownik, zachowując treść i charakter wypowiedzi."
        })

        # Додаємо повідомлення користувача та асистента
        for msg in messages:
            formatted_messages.append({
                "role": msg['role'],
                "content": msg['content']
            })

        return {"messages": formatted_messages}

    @staticmethod
    def group_messages_into_conversations(messages: list, max_context_length: int = 10) -> list:
        """
        Групує повідомлення в розмови (контекстні вікна)

        Args:
            messages: Список всіх повідомлень
            max_context_length: Максимальна кількість повідомлень в одній розмові

        Returns:
            Список розмов, кожна розмова - список повідомлень
        """
        conversations = []
        current_conversation = []

        for i, msg in enumerate(messages):
            current_conversation.append(msg)

            # Якщо досягли максимальної довжини або це останнє повідомлення
            if len(current_conversation) >= max_context_length or i == len(messages) - 1:
                # Перевіряємо що розмова має принаймні одну пару user-assistant
                if len(current_conversation) >= 2:
                    conversations.append(current_conversation.copy())

                # Зберігаємо перекриття для контексту (останні 2 повідомлення)
                if len(current_conversation) >= 4:
                    current_conversation = current_conversation[-2:]
                else:
                    current_conversation = []

        return conversations

    @staticmethod
    async def export_user_data(user_id: int, output_file: str = None) -> dict:
        """
        Експортує дані користувача у формат JSONL

        Returns:
            dict з інформацією про експорт
        """
        try:
            # Отримуємо статистику
            stats = await db.get_user_stats(user_id)

            if not stats:
                return {
                    'success': False,
                    'error': 'Користувача не знайдено'
                }

            if stats['total_tokens'] < config.MIN_TOKEN_LIMIT:
                return {
                    'success': False,
                    'error': f"Недостатньо токенів. Зібрано: {stats['total_tokens']}, потрібно: {config.MIN_TOKEN_LIMIT}"
                }

            # Отримуємо всі нефільтровані повідомлення
            messages = await db.get_user_messages(user_id)

            if not messages:
                return {
                    'success': False,
                    'error': 'Немає повідомлень для експорту'
                }

            # Сортуємо за часом (від старих до нових)
            messages.sort(key=lambda x: x['timestamp'])

            # Групуємо в розмови
            conversations = DataExporter.group_messages_into_conversations(messages)

            # Форматуємо для Fine-tuning
            jsonl_data = []
            for conversation in conversations:
                formatted = DataExporter.format_conversation_for_finetuning(conversation)
                jsonl_data.append(formatted)

            # Генеруємо ім'я файлу якщо не задано
            if not output_file:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                output_file = f'finetuning_data_{user_id}_{timestamp}.jsonl'

            # Зберігаємо в JSONL формат
            with open(output_file, 'w', encoding='utf-8') as f:
                for item in jsonl_data:
                    f.write(json.dumps(item, ensure_ascii=False) + '\n')

            # Статистика експорту
            total_conversations = len(jsonl_data)
            total_messages = sum(len(conv['messages']) - 1 for conv in jsonl_data)  # -1 для system prompt

            logger.info(f"Експорт завершено для користувача {user_id}: {output_file}")

            return {
                'success': True,
                'file': output_file,
                'stats': {
                    'total_tokens': stats['total_tokens'],
                    'total_messages': total_messages,
                    'total_conversations': total_conversations,
                    'user_messages': stats['message_count']
                }
            }

        except Exception as e:
            logger.error(f"Помилка експорту для користувача {user_id}: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    @staticmethod
    async def validate_data_quality(user_id: int) -> dict:
        """
        Перевіряє якість зібраних даних

        Returns:
            dict з метриками якості
        """
        try:
            stats = await db.get_user_stats(user_id)

            if not stats:
                return {
                    'valid': False,
                    'error': 'Користувача не знайдено в базі даних. Спершу відправ звичайне повідомлення боту (не команду).'
                }

            messages = await db.get_user_messages(user_id)

            if not messages:
                return {
                    'valid': False,
                    'error': f'Немає нефільтрованих повідомлень. Всього повідомлень у БД: {stats["message_count"]}, але всі були відфільтровані як "шум". Напиши більш змістовні повідомлення (10+ токенів).'
                }

            # Рахуємо метрики
            total_messages = len(messages)
            user_messages = [m for m in messages if m['role'] == 'user']
            assistant_messages = [m for m in messages if m['role'] == 'assistant']

            # Аналіз настроїв
            sentiments = {}
            for msg in user_messages:
                sentiment = msg.get('sentiment', 'neutral')
                sentiments[sentiment] = sentiments.get(sentiment, 0) + 1

            # Середня довжина повідомлень
            avg_tokens = stats['total_tokens'] / stats['message_count'] if stats['message_count'] > 0 else 0

            # Перевірка достатності даних
            is_sufficient = stats['total_tokens'] >= config.MIN_TOKEN_LIMIT
            is_balanced = len(user_messages) > 0 and len(assistant_messages) > 0

            return {
                'valid': is_sufficient and is_balanced,
                'total_tokens': stats['total_tokens'],
                'total_messages': total_messages,
                'user_messages': len(user_messages),
                'assistant_messages': len(assistant_messages),
                'avg_tokens_per_message': round(avg_tokens, 2),
                'sentiment_distribution': sentiments,
                'is_sufficient': is_sufficient,
                'is_balanced': is_balanced,
                'progress_percent': round((stats['total_tokens'] / config.MIN_TOKEN_LIMIT) * 100, 2)
            }

        except Exception as e:
            logger.error(f"Помилка валідації для користувача {user_id}: {e}")
            return {'valid': False, 'error': f'Технічна помилка: {str(e)}'}


# Глобальний екземпляр експортера
exporter = DataExporter()