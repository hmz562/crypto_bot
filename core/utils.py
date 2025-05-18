# core/utils.py

from telegram import ReplyKeyboardMarkup
from decimal import Decimal

async def noop_callback(update, context):
    """
    فقط پاسخ به callback query می‌دهد و کار دیگری نمی‌کند.
    """
    await update.callback_query.answer()

def main_menu_keyboard():
    """
    منوی اصلی بات با گزینه‌های:
    - Kaufauftrag erstellen
    - Verkaufsauftrag erstellen
    - Verkäufer anzeigen
    - Käufer anzeigen
    - Kryptopreise abrufen
    - Benutzereinstellungen
    - Diskussionsgruppe
    """
    buttons = [
        ["Kaufauftrag erstellen", "Verkaufsauftrag erstellen"],
        ["Verkäufer anzeigen", "Käufer anzeigen"],
        ["Kryptopreise abrufen"],
        ["Benutzereinstellungen"],
        ["Diskussionsgruppe"]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def format_stars(rating: Decimal, max_stars: int = 5) -> str:
    full = int(rating)                            # تعداد ستاره کامل
    half = 1 if (rating - full) >= Decimal('0.5') else 0
    empty = max_stars - full - half
    return '⭐' * full + '✬' * half + '☆' * empty

def auth_menu_keyboard():
    """
    منوی ورود/ثبت‌نام:
    - Anmelden
    - Einloggen
    """
    return ReplyKeyboardMarkup(
        [["Anmelden", "Einloggen"]],
        resize_keyboard=True
    )
