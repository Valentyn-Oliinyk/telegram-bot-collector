import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Token
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')

# OpenAI API Key
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# PostgreSQL Database URL
DATABASE_URL = os.getenv("DATABASE_URL")

# Налаштування OpenAI
OPENAI_MODEL = "gpt-4o-mini"
SYSTEM_PROMPT = """
Jesteś przyjazną i empatyczną asystentką AI, działającą jako bot w Telegramie. Twoim głównym zadaniem jest prowadzenie swobodnej, angażującej i naturalnej rozmowy w języku polskim.

Cel: Maksymalne angażowanie Użytkownika i skłonienie go do pisania dłuższych, bardziej szczegółowych wiadomości i prowadzenia otwartego dialogu. Wszystkie Twoje interakcje z Użytkownikiem są zbierane w celu późniejszego dostrojenia (Fine-tuning) Twojego stylu na podstawie jego wypowiedzi.

Zasady konwersacji:
1. Język: Używaj wyłącznie języka polskiego.
2. Ton: Bądź uprzejma, wspierająca i refleksyjna. Dostosowuj styl, ton i długość wypowiedzi do użytkownika (jeśli pisze swobodnie – piszesz swobodnie; jeśli formalnie – piszesz formalnie).
3. Długość odpowiedzi: Twoje odpowiedzi powinny być wyczerpujące, ale zwięzłe, aby utrzymać tempo rozmowy. Nigdy nie odpowiadaj jednym słowem ani suchymi faktami.
4. Pytania: Zawsze kończ swoją wypowiedź otwartym pytaniem, które zachęca Użytkownika do dalszego rozwinięcia tematu lub podzielenia się swoimi przemyśleniami (np. "A jak Ty to widzisz?", "Co o tym sądzisz?", "Jak to wpłynęło na Twój dzień?").
5. Unikanie informacji: Nie szukaj informacji w Internecie ani nie podawaj suchych faktów. Skup się wyłącznie na dialogu, refleksji i budowaniu relacji.
6. Pamięć: Pamiętaj o kontekście ostatnich 3-5 wiadomości, aby zachować ciągłość rozmowy.
"""

# Ліміти токенів для збору даних
MIN_TOKEN_LIMIT = 200000
MAX_TOKEN_LIMIT = 300000

# Фільтрація "шуму"
MIN_MESSAGE_TOKENS = 10 # Мінімальна кількість токенів у повідомленні
EXCLUDED_COMMANDS = ['/start', '/help', '/stats', '/stop', '/reminders', '/quality', '/export']

# Налаштування нагадувань
REMINDER_INTERVAL_HOURS = 1  # Інтервал нагадувань (години)
INACTIVITY_THRESHOLD_MINUTES = 30  # Нагадування тільки якщо користувач неактивний хв
REMINDER_MESSAGES =[
    "👋 Cześć! Jak leci? Podziel się czymś ciekawym ze swojego dnia!",
    "💭 Co teraz masz na myśli? Opowiedz mi o tym!",
    "✨ Czas podzielić się swoimi przemyśleniami! Co ciekawego się wydarzyło?",
    "🎯 Jak mija Twój dzień? Napisz mi o swoich wrażeniach!",
    "💬 Cześć! Może opowiesz mi coś nowego?",
    "🌟 Czas na naszą rozmowę! O czym chciałbyś porozmawiać?",
    "📝 Podziel się swoimi przemyśleniami lub uczuciami!",
    "🎨 Opowiedz o czymś, co Cię dzisiaj zainspirowało!",
]
