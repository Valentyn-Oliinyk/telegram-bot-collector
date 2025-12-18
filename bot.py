import asyncio
import logging
import random

from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from openai import AsyncOpenAI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import config
from database import db
from export_jsonl import exporter

# Налаштування логування
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ініціалізація бота та диспетчера
bot = Bot(token=config.TELEGRAM_TOKEN)
dp = Dispatcher()

# Ініціалізація OpenAI клієнта
client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)

# Ініціалізація планувальника
scheduler = AsyncIOScheduler()

# Словник для зберігання історії розмов (тимчасово, в пам'яті)
user_conversions = {}


def get_conversation_history(user_id: int) -> list:
    """Отримати історію розмови користувача"""
    if user_id not in user_conversions:
        user_conversions[user_id] = [
            {"role": "system", "content": config.SYSTEM_PROMPT}
        ]
    return user_conversions[user_id]


def add_message_to_history(user_id: int, role: str, content: str):
    """Додати повідомлення до історії"""
    history = get_conversation_history(user_id)
    history.append({"role": role, "content": content})

    # Обмежуємо історію останніми 10 повідомленнями (без system prompt)
    if len(history) > 11:  # 1 system + 10 messages
        user_conversions[user_id] = [history[0]] + history[-10:]


async def get_ai_response(user_id: int, user_message: str) -> str:
    """Отримати відповідь від OpenAI"""
    try:
        # Зберігаємо повідомлення користувача
        save_result = await db.save_message(user_id, "user", user_message)

        #Перевіряємо чи досягнуто ліміт
        if save_result == 'limit_reached':
            stats = await db.get_user_stats(user_id)
            return (
                f"🎉 Witaj! Zebraliśmy wystarczającą ilość danych, aby stworzyć Twój osobisty model!\n\n"
                f"📊 Statystyki:\n"
                f"• Łączna liczba tokenów: {stats['total_tokens']:,}\n"
                f"• Wiadomości: {stats['message_count']}\n\n"
                f"Zbieranie danych zakończone. Teraz możemy przejść do szkolenia modelu w Twoim stylu! 🚀"
            )

        # Додаємо повідомлення користувача до історії
        add_message_to_history(user_id, "user", user_message)

        # Отримуємо історію для контексту
        history = get_conversation_history(user_id)

        # Запит до OpenAI API
        response = await client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=history,
            max_tokens=1000,
            temperature=0.7
        )

        # Отримуємо відповідь
        ai_message = response.choices[0].message.content

        # Зберігаємо відповідь асистента
        await db.save_message(user_id, "assistant", ai_message)

        # Додаємо відповідь асистента до історії
        add_message_to_history(user_id, "assistant", ai_message)

        return ai_message

    except Exception as e:
        logger.error(f"Помилка при отриманні відповіді від OpenAI: {e}")
        return "Przepraszamy, wystąpił błąd podczas przetwarzania Twojego zapytania. Spróbuj ponownie."


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    """Обробник команди /start"""
    user_name = message.from_user.first_name
    user_id = message.from_user.id

    # Отримуємо статистику користувача
    stats = await db.get_user_stats(user_id)

    if stats and not stats['collection_active']:
        await message.answer(
            f"Witaj ponownie, {user_name}! 👋\n\n"
            f"Zbieranie danych do Twojego osobistego modelu zostało zakończone.\n"
            f"Zebrano {stats['total_tokens']:,} tokenów z {stats['message_count']} wiadomości! 🎉"
        )
    else:
        await message.answer(
            f"Cześć {user_name}! Miło mi Cię powitać! 👋 Jestem Twoją osobistą, przyjazną asystentką AI, zawsze gotową Cię wysłuchać.\n\n"
            f"Zanim przejdziemy do rozmowy, proszę o chwilę uwagi: Znajduję się obecnie w fazie intensywnej nauki. Wszystkie nasze dotychczasowe konwersacje w języku polskim są rejestrowane i będą wykorzystane do dostrojenia (Fine-tuning) mojego modelu AI. Moim celem jest opanowanie Twojego unikalnego stylu komunikacji.\n\n"
            f"W przyszłości ten model, nauczony na Twoich wzorcach, ma służyć do komunikacji z klientami.\n\n"
            f"Pamiętaj: Kontynuując naszą rozmowę, automatycznie wyrażasz zgodę na wykorzystanie Twoich wiadomości w tym celu.\n\n"
            f"/stats - zobacz statystyki\n"
        )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Показати список всіх команд"""
    help_text = (
        "📚 *Dostępne polecenia:*\n\n"

        "*Podstawowe:*\n"
        "/start - Rozpocznij pracę z botem\n"
        "/help - Pokaż tę listę poleceń\n\n"

        "*Statystyki i analiza:*\n"
        "/stats - Wyświetl statystyki gromadzenia danych\n"
        "  └ Pokazuje postęp, liczbę tokenów i wiadomości\n\n"

        "/quality - Analiza jakości zebranych danych\n"
        "  └ Szczegółowy raport: tokeny, nastroje, rozkład wiadomości\n\n"

        "*Zarządzanie gromadzeniem danych:*\n"
        "/stop - zatrzymaj gromadzenie danych\n"
        "  └ Zaprzestaje zapisywania Twoich wiadomości\n\n"

        "*Przypomnienia:*\n"
        "/reminders - Zarządzanie przypomnieniami\n"
        "/reminders on - Włącz przypomnienia\n"
        "/reminders off - Wyłącz przypomnienia\n"
        "  └ Bot będzie przypominał o pisaniu co godzinę (jeśli jesteś nieaktywny)\n\n"

        "*Eksport danych:*\n"
        "/export - Eksportuj dane do Fine-tuning\n"
        "  └ Tworzy plik JSONL do szkolenia modelu osobistego\n"
        "  └ Dostępne po zebraniu ponad 200 000 tokenów\n\n"

        "💡 *Wskazówka:* Po prostu komunikuj się ze mną naturalnie – pisz o swoich przemyśleniach, "
        "emocjach, planach. Im bardziej zróżnicowana treść, tym lepiej model "
        "nauczy się Twojego stylu komunikacji!"
    )

    await message.answer(help_text, parse_mode="Markdown")


@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    """Показати статистику користувача"""
    user_id = message.from_user.id
    stats = await db.get_user_stats(user_id)

    if not stats:
        await message.answer("Nie masz jeszcze statystyk. Zacznij ze mną rozmawiać!")
        return

    progress = (stats['total_tokens'] / config.MIN_TOKEN_LIMIT) * 100
    progress_bar = "█" * int(progress / 10) + "░" * (10 - int(progress / 10))

    status = "✅ Zakończono" if not stats['collection_active'] else "🔄 Aktywny"

    await message.answer(
        f"📊 Twoje statystyki:\n\n"
        f"Status: {status}\n"
        f"Zebrano tokenów: {stats['total_tokens']:,} / {config.MIN_TOKEN_LIMIT:,}\n"
        f"Postęp: [{progress_bar}] {progress:.1f}%\n"
        f"Wiadomości: {stats['message_count']}\n"
        f"Rozpoczęto: {stats['created_at'].strftime('%d.%m.%Y %H:%M')}"
    )


@dp.message(Command("stop"))
async def cmd_stop(message: types.Message):
    """Зупинити збір даних"""
    user_id = message.from_user.id
    stats = await db.get_user_stats(user_id)

    if not stats or not stats['collection_active']:
        await message.answer("Gromadzenie danych zostało już wstrzymane lub nie zostało rozpoczęte.")
        return

    await db.stop_collection(user_id)
    await message.answer(
        f"⏸️ Zbieranie danych zostało wstrzymane.\n\n"
        f"Zebrano: {stats['total_tokens']:,} tokenów z {stats['message_count']} wiadomości."
    )


@dp.message(Command("reminders"))
async def cmd_reminders(message: types.Message):
    """Керування нагадуваннями"""
    user_id = message.from_user.id
    stats = await db.get_user_stats(user_id)

    # Якщо немає параметра, показуємо статус
    text = message.text.strip().split(maxsplit=1)

    if len(text) == 1:
        # Показуємо поточний статус
        if stats:
            status = "włączone ✅" if stats.get('reminders_enabled', True) else "wyłączyć ❌"
            await message.answer(
                f"📬 Przypomnienie teraz: {status}\n\n"
                f"Używaj:\n"
                f"/reminders on - włączyć\n"
                f"/reminders off - wyłączyć"
            )
        else:
            await message.answer(
                f"📬 Przypomnienie: włączone ✅ (domyślnie)\n\n"
                f"Używaj:\n"
                f"/reminders on - włączyć\n"
                f"/reminders off - wyłączyć"
            )
        return

    # Обробляємо параметр on/off
    param = text[1].lower()

    if param == "on":
        await db.toggle_reminders(user_id, True)
        await message.answer("✅ Przypomnienie włączone! Będę przypominać co godzinę.")
    elif param == "off":
        await db.toggle_reminders(user_id, False)
        await message.answer("❌ Przypomnienie wyłączone. Możesz je włączyć za pomocą polecenia /reminders on")
    else:
        await message.answer(
            "Nieprawidłowy parametr. Użyj:\n"
            "/reminders on - włączyć\n"
            "/reminders off - wyłączyć"
        )


@dp.message(Command("quality"))
async def cmd_quality(message: types.Message):
    """Перевірка якості зібраних даних"""
    user_id = message.from_user.id

    await message.answer("⏳ Analizuję jakość danych...")

    quality = await exporter.validate_data_quality(user_id)

    # Перевіряємо чи є помилка (коли немає даних взагалі)
    if 'error' in quality:
        await message.answer(f"❌ {quality['error']}")
        return

    # Якщо даних мало, але вони є - показуємо статистику
    if not quality.get('valid', False) and quality.get('total_messages', 0) == 0:
        await message.answer("❌ Brak danych do analizy. Zacznij ze mną rozmawiać!")
        return

    # Формуємо звіт
    sentiment_text = "\n".join([
        f"  • {s.capitalize()}: {c}"
        for s, c in quality['sentiment_distribution'].items()
    ])

    status_icon = "✅" if quality['is_sufficient'] else "⏳"

    report = (
        f"{status_icon} Raport dotyczący jakości danych:\n\n"
        f"📊 Ogólne statystyki:\n"
        f"• Tokeny: {quality['total_tokens']:,} / {config.MIN_TOKEN_LIMIT:,}\n"
        f"• Postęp: {quality['progress_percent']}%\n"
        f"• Wiadomości: {quality['total_messages']}\n"
        f"• Średnia długość: {quality['avg_tokens_per_message']} tokenów\n\n"
        f"💬 Rozdzielanie wiadomości:\n"
        f"• Twoje wiadomości: {quality['user_messages']}\n"
        f"• Odpowiedzi asystenta: {quality['assistant_messages']}\n\n"
        f"😊 Podział emocjonalny:\n{sentiment_text}\n\n"
    )

    if quality['is_sufficient']:
        report += "✅ Danych wystarczy do Fine-tuning!\nUżywaj /export do eksportu."
    else:
        remaining = config.MIN_TOKEN_LIMIT - quality['total_tokens']
        report += f"⏳ Potrzeba jeszcze ~{remaining:,} tokenów na początek Fine-tuning."

    await message.answer(report)


@dp.message(Command("export"))
async def cmd_export(message: types.Message):
    """Експорт даних у формат JSONL для Fine-tuning"""
    user_id = message.from_user.id

    await message.answer("⏳ Eksportuję dane... Może to chwilę potrwać.")

    result = await exporter.export_user_data(user_id)

    if not result['success']:
        error = result.get('error', 'Nieznany błąd')
        await message.answer(f"❌ Błąd eksportu: {error}")
        return

    stats = result['stats']

    response = (
        f"✅ Eksport zakończony!\n\n"
        f"📁 Plik: `{result['file']}`\n\n"
        f"📊 Statystyki eksportowe:\n"
        f"• Tokeny: {stats['total_tokens']:,}\n"
        f"• Wiadomości: {stats['total_messages']}\n"
        f"• Rozmowy (przykłady treningowe): {stats['total_conversations']}\n\n"
        f"🎯 Наступні кроки:\n"
        f"1. Pobierz plik na swój komputer\n"
        f"2. Przejdź do platform.openai.com\n"
        f"3. Fine-tuning → Upload training file\n"
        f"4. Stwórz Fine-tuning job z tym plikiem"
    )

    await message.answer(response, parse_mode="Markdown")

    # Відправляємо файл користувачу
    try:
        doc = types.FSInputFile(result['file'])
        await message.answer_document(doc, caption="📎 Twój plik dla Fine-tuning")
    except Exception as e:
        logger.error(f"Помилка відправки файлу: {e}")
        await message.answer(
            "⚠️ Nie udało się wysłać pliku przez Telegram.\n"
            f"Plik zapisany lokalnie: {result['file']}"
        )


@dp.message(F.text)
async def handle_message(message: types.Message):
    """Обробник текстових повідомлень"""
    user_id = message.from_user.id
    user_message = message.text

    # Показуємо, що бот "друкує"
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")

    # Отримуємо відповідь від AI
    ai_response = await get_ai_response(user_id, user_message)

    # Відправляємо відповідь користувачу
    await message.answer(ai_response)


async def send_hourly_reminders():
    """Функція для відправки щогодинних нагадувань"""
    try:
        # Отримуємо список користувачів з увімкненими нагадуваннями
        user_ids = await db.get_users_for_reminders()

        if not user_ids:
            logger.info("Немає користувачів для нагадувань")
            return

        logger.info(f"Відправка нагадувань для {len(user_ids)} користувачів")

        for user_id in user_ids:
            try:
                # Вибираємо випадкове повідомлення
                reminder_text = random.choice(config.REMINDER_MESSAGES)

                # Відправляємо нагадування
                await bot.send_message(user_id, reminder_text)

                # Оновлюємо час останнього нагадування
                await db.update_last_reminder(user_id)

                logger.info(f"Нагадування відправлено користувачу {user_id}")

                # Невелика затримка між повідомленнями
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"Помилка відправки нагадування користувачу {user_id}: {e}")

    except Exception as e:
        logger.error(f"Помилка в send_hourly_reminders: {e}")


async def main():
    """Головна функція запуску бота"""
    logger.info("Бот запускається...")
    try:
        # Підключаємося до бази даних
        await db.connect()

        # Налаштовуємо scheduler для нагадувань
        scheduler.add_job(
            send_hourly_reminders,
            trigger=IntervalTrigger(hours=config.REMINDER_INTERVAL_HOURS),
            id='hourly_reminders',
            name='Щогодинні нагадування',
            replace_existing=True
        )

        # Запускаємо scheduler
        scheduler.start()
        logger.info(f"✅ Планувальник запущено. Нагадування кожні {config.REMINDER_INTERVAL_HOURS} год.")

        # ----------Для локального використання бота--------------
        # # Видаляємо старі апдейти
        # await bot.delete_webhook(drop_pending_updates=True)
        # # Запускаємо polling
        # await dp.start_polling(bot)

        # ----------Для використання бота на Render-----------------

        # Перевіряємо чи є WEBHOOK_URL
        if config.WEBHOOK_URL:
            # WEBHOOK режим (для Render)
            logger.info("Запуск у WEBHOOK режимі")

            # Встановлюємо webhook
            webhook_path = f"/webhook/{config.TELEGRAM_TOKEN}"
            webhook_url = f"{config.WEBHOOK_URL}{webhook_path}"

            await bot.set_webhook(
                url=webhook_url,
                drop_pending_updates=True
            )
            logger.info(f"Webhook встановлено: {webhook_url}")

            # Створюємо web додаток
            app = web.Application()

            # Health check endpoint (щоб Render бачив що сервіс живий)
            async def health_check(request):
                return web.json_response({"status": "ok", "bot": "running"})

            app.router.add_get("/", health_check)
            app.router.add_get("/health", health_check)

            # Налаштовуємо webhook handler
            webhook_requests_handler = SimpleRequestHandler(
                dispatcher=dp,
                bot=bot,
            )
            webhook_requests_handler.register(app, path=webhook_path)
            setup_application(app, dp, bot=bot)

            # Запускаємо web сервер
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, host="0.0.0.0", port=config.PORT)
            await site.start()

            logger.info(f"Web сервер запущено на порті {config.PORT}")
            logger.info("Бот працює у webhook режимі. Для зупинки натисніть Ctrl+C")

            # Тримаємо сервер живим
            await asyncio.Event().wait()

        else:
            # POLLING режим (для локальної розробки)
            logger.info("Запуск у POLLING режимі (локальна розробка)")
            await bot.delete_webhook(drop_pending_updates=True)
            await dp.start_polling(bot)

    except Exception as e:
        logger.error(f"Помилка при запуску бота: {e}")
    finally:
        scheduler.shutdown()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
