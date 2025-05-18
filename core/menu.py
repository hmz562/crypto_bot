# core/menu.py

from telegram import ReplyKeyboardMarkup

def main_menu_keyboard():
    buttons = [
        ["Kaufauftrag erstellen", "Verkaufsauftrag erstellen"],
        ["Verkäufer anzeigen",     "Käufer anzeigen"],
        ["Kryptopreise abrufen"],
        ["Benutzereinstellungen"],
        ["Diskussionsgruppe"]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)
