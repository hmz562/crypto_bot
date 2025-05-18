# crypto_bot/core/market_bot.py

import os
import sys
from dotenv import load_dotenv

# اضافه کردن مسیر پروژه و تنظیمات Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# مدل‌های Django
from core.models import Order

# بارگذاری متغیرهای محیطی
load_dotenv()
TOKEN2 = os.getenv('TELEGRAM_TOKEN2')
BOT1_USERNAME = os.getenv('BOT1_USERNAME')
BOT2_CHAT_ID = os.getenv('BOT2_CHAT_ID')

async def list_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    هندلر دستور /list:
    - سفارش‌های pending (فعال) را با ORM می‌خواند
    - هر سفارش را به زبان آلمانی نمایش می‌دهد
    """
    # فقط سفارش‌های pending را نمایش بده
    orders = Order.objects.filter(status='pending')
    if not orders:
        await update.message.reply_text('Keine aktiven Aufträge vorhanden.')
        return

    for order in orders:
        total = order.amount_crypto * order.price_per_unit
        text = (
            f"📢 Neuer Auftrag #{order.id}\n"
            f"{order.amount_crypto} {order.currency.symbol} → {total:.2f} €\n"
            f"Land: {order.country.name}\n"
            f"Zahlungsmethode: {order.fiat_method}"
        )
        # دکمه‌ی پروپوزال با deep link به بات اول
        deep_link = f"https://t.me/{BOT1_USERNAME}?start=propose_{order.id}"
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton('Vorschlag senden', url=deep_link)
        ]])
        await update.message.reply_text(text, reply_markup=markup)

def main():
    app = ApplicationBuilder().token(TOKEN2).build()
    app.add_handler(CommandHandler('list', list_orders))
    print("Bot2 läuft...")
    app.run_polling()

if __name__ == '__main__':
    main()
