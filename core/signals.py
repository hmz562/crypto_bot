# core/signals.py

import os
from django.db.models.signals import post_save
from django.dispatch import receiver
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Bot
from .models import OrderMatch  # سیگنال روی OrderMatch ثبت می‌شود
from django.conf import settings

@receiver(post_save, sender=OrderMatch)
def ask_for_feedback(sender, instance, created, **kwargs):
    """
    وقتی یک ماتچ جدید ساخته شد (معامله کامل):
     - برای خریدار و فروشنده دکمه‌های 1-5 ستاره بفرست
     - ⚠️ توجه: ساخت Bot داخل تابع تا در زمان migrate اجرا نشود
    """
    if not created:
        return

    # اینجا متغیر محیطی قبلاً در core/bot.py با load_dotenv() بارگذاری شده،
    # پس وقتی ربات اصلی اجرا شود TOKEN1 ست شده.
    token = os.getenv("TELEGRAM_TOKEN1")
    if not token:
        return  # اگر هنوز token ست نشده، هیچ کاری نکن
    bot = Bot(token=token)

    buyer  = instance.buy_order.user
    seller = instance.sell_order.user

    for rater, rated in [(buyer, seller), (seller, buyer)]:
        keyboard = [
            [
                InlineKeyboardButton("⭐",    callback_data=f"rate_{instance.id}_{rated.telegram_id}_1"),
                InlineKeyboardButton("⭐⭐",   callback_data=f"rate_{instance.id}_{rated.telegram_id}_2"),
                InlineKeyboardButton("⭐⭐⭐",  callback_data=f"rate_{instance.id}_{rated.telegram_id}_3"),
            ],
            [
                InlineKeyboardButton("⭐⭐⭐⭐",  callback_data=f"rate_{instance.id}_{rated.telegram_id}_4"),
                InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data=f"rate_{instance.id}_{rated.telegram_id}_5"),
            ]
        ]
        bot.send_message(
            chat_id=rater.telegram_id,
            text=(
                f"Ihr Handel #{instance.buy_order.id} ist abgeschlossen.\n"
                "Bitte bewertet euren Handelspartner von 1 bis 5 Sternen:"
            ),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
