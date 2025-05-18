# core/tasks.py

import logging
import re
import requests
from datetime import timedelta
from core.constants import BOT1_USERNAME
from decimal import Decimal
from core.utils import format_stars

from celery import shared_task
from django.conf import settings
from django.utils import timezone
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from core.models import Order

logger = logging.getLogger(__name__)

@shared_task
def expire_locks(timeout_minutes: int = 15) -> str:
    """
    آزادسازی قفل‌های قدیمی در Orders
    """
    cutoff = timezone.now() - timedelta(minutes=timeout_minutes)
    count = (
        Order.objects
        .filter(assigned_admin__isnull=False, lock_acquired_at__lt=cutoff)
        .update(assigned_admin=None, lock_acquired_at=None)
    )
    logger.info("Expired %d locks older than %d minutes", count, timeout_minutes)
    return f"Expired {count} locks"

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def update_bot2_ad(self, order_id: int):
    """
    دریافت سفارش، ساخت header و body پیام و ویرایش آن در بات دوم
    """
    try:
        # 1) واکشی سفارش
        order = Order.objects.select_related('currency', 'user', 'country').get(pk=order_id)
        token = settings.TELEGRAM_TOKEN2
        chat_id = settings.BOT2_CHAT_ID
        message_id = order.bot2_message_id

# 2) ساخت header
# اگر rating اعشاری است، حتما Decimal کنسرت کنید
        stars_line = format_stars(Decimal(order.user.rating))
        order_type = 'Kaufauftrag' if order.is_buy else 'Verkaufsauftrag'
        header = (
            f"📢 Auftrag {order.id:04d} – {order_type}    {stars_line}\n"
            f"{order.amount_crypto} {order.currency.symbol} → {order.net_total:.2f} €\n"
            f"Land: {order.country.name}\n"
            f"Zahlungsmethode: {order.fiat_method}\n\n"
        )


        # 3) جمع‌آوری پیشنهادها
        prompts = order.prompts.order_by('-created_at')
        lines = []
        for p in prompts:
            ts    = timezone.localtime(p.created_at).strftime("%d/%m/%Y %H:%M")
            user  = p.from_user.username or str(p.from_user.telegram_id)
            emoji = '❌' if order.status.lower() == 'cancelled' else '🔸'
            raw = re.sub(
            r'^[\U0001F300-\U0001F6FF\U0001F900-\U0001F9FF'
            r'\U00002700-\U000027BF\U0001F1E6-\U0001F1FF]+\s*',
            '',
            p.content
        )

        # فقط خط عدد و ارز رو جدا می‌کنیم
        # فرض می‌کنیم قسمت عددی آخرین خط raw باشد
        numeric_part = raw.splitlines()[-1].strip()

        # دیگر بین emoji و عدد فاصله نگذار
        lines.append(f"{emoji}{numeric_part} am {ts} von {user}")

    # 4) ساخت بدنه مثل قبل …
        body = ["Gesendete Angebote:"]
        body += ["", *lines] if lines else ["", "Noch keine Vorschläge."]

        # ← اضافه شده: نمایش وضعیت matching
        if order.status.lower() == 'matched':
            body.append("")
            body.append("❇ Diese Anfrage ist in Bearbeitung.")

        # 5) ساخت مارک‌آپ دکمه‌ها (برای pending/cancelled)
        status = order.status.lower()
        markup = None
        if status in ('pending', 'canceled'):
            # یک deep-link می‌سازیم که بات اول را با propose_args باز می‌کند
            deep_link = f"https://t.me/{BOT1_USERNAME}?start=propose_{order.id}"
            button    = InlineKeyboardButton(
                '🔘 Vorschlag senden',
                url=deep_link
            )
            markup    = InlineKeyboardMarkup([[button]])
            body.append("")  # فاصله
            body.append("🔄 Diese Anzeige ist wieder verfügbar.")

        elif status == 'completed':
            # حذف دکمه‌ها و اضافه کردن پیام اتمام
            body.append("") 
            body.append("✅ Dieser Auftrag wurde abgeschlossen.")    

        text = header + "\n".join(body)

        # 6) ارسال درخواست ویرایش پیام
        url = f"https://api.telegram.org/bot{token}/editMessageText"
        payload = {
            'chat_id': chat_id,
            'message_id': message_id,
            'text': text,
            'parse_mode': 'Markdown'
        }
        if markup:
            payload['reply_markup'] = markup.to_dict()

        resp = requests.post(url, json=payload, timeout=10)
        if not resp.ok:
            logger.error("Telegram API error: %s", resp.text)

    except Exception as exc:
        logger.exception("Error updating bot2 ad for order %s", order_id)
        # در صورت خطا مجدداً تلاش می‌کند
        raise self.retry(exc=exc)
