# core/terms.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# Deutsche Nutzungsbedingungen (einmalige Anzeige vor Nutzung):
TERMS_TEXT = (
    "📜 Nutzungsbedingungen 📜\n\n"
    "1. Der Bot fungiert ausschließlich als treuhänderische Vermittlungsplattform für P2P-Krypto-Transaktionen.\n"
    "2. Der Admin übernimmt keinerlei Haftung für Kursänderungen oder das Verhalten der Handelsparteien.\n"
    "3. Der Nutzer ist allein verantwortlich für die korrekte Angabe von Wallet-Adresse und Blockchain-Netzwerk.\n"
    "   Bei falscher Angabe übernimmt der Nutzer sämtliche Risiken und Kosten.\n"
    "4. Der Nutzer muss wahrheitsgemäße Identitäts- und Zahlungsdaten bereitstellen.\n"
    "5. Der Bot kann gemäß EU-Vorschriften (AML/KYC) jederzeit zusätzliche Dokumente anfordern.\n"
    "6. Mit der Nutzung dieses Bots stimmen Sie diesen Bedingungen unwiderruflich zu.\n"
)

# Inline-Tasten zur Zustimmung oder Ablehnung

def terms_keyboard():
    """
    Erzeugt Inline-Tastatur mit zwei Tasten:
    - Zustimmung: callback_data 'accept_terms'
    - Ablehnung: callback_data 'reject_terms'
    """
    keyboard = [
        [
            InlineKeyboardButton(
                text="✅ Ich habe die Bedingungen gelesen und stimme zu",
                callback_data="accept_terms"
            )
        ],
        [
            InlineKeyboardButton(
                text="❌ Bot verlassen",
                callback_data="reject_terms"
            )
        ],
    ]
    return InlineKeyboardMarkup(keyboard)