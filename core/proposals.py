# core/proposals.py

from asgiref.sync import sync_to_async
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from core.models import ChatPrompt, Order
from core.tasks import update_bot2_ad
from core.menu import main_menu_keyboard
from telegram.ext import ConversationHandler
from decimal import Decimal
from django.db import transaction
from telegram import Update
import logging
logger = logging.getLogger(__name__)


async def show_my_proposals(update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id

    # اینجا کل کوئری رو با select_related و در یک بلوک sync_to_async اجرا می‌کنیم
    prompts = await sync_to_async(lambda: list(
        ChatPrompt.objects
                  .filter(from_user__telegram_id=user_id)
                  .select_related('order', 'order__currency')
                  .order_by('created_at')
    ))()

    if not prompts:
        await q.message.reply_text(
            "Du hast noch keine Vorschläge gesendet.",
            reply_markup=main_menu_keyboard()
        )
        return

    buttons = []
    for p in reversed(prompts):
        ts    = p.created_at.strftime("%d/%m/%Y %H:%M")
        qty   = p.order.amount_crypto      # اینجا دیگر نیازی به کوئری اضافی نیست
        price = p.order.price_per_unit
        emoji = "🟢" if p.order.is_buy else "🔴"
        text  = f"{emoji} {qty} → {price:.2f} € um {ts}"
        buttons.append([InlineKeyboardButton(text, callback_data=f"myprop_{p.id}")])

    await q.message.reply_text(
        "🔍 Deine gesendeten Vorschläge:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def myprop_action_callback(update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    prop_id = int(q.data.split("_")[1])
    context.user_data['prop_id'] = prop_id

    keyboard = [
        [
            InlineKeyboardButton("✅ Ja, stornieren", callback_data="confirm_cancel"),
            InlineKeyboardButton("❌ Nein",           callback_data="keep"),
        ]
    ]
    await q.edit_message_text(
        "Möchtest du diesen Vorschlag wirklich stornieren?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
async def confirm_cancel_callback(update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    prop_id = context.user_data.get('prop_id')
    if not prop_id:
        # اگر خطایی بود، فقط پیام را پاک کن و برگرد
        await q.message.delete()
        return

    # واکشی ChatPrompt و سفارش مرتبط
    prop  = await sync_to_async(ChatPrompt.objects.select_related('order').get)(id=prop_id)
    order = prop.order

    # تغییر وضعیت سفارش به pending
    order.status = 'Pending'
    await sync_to_async(order.save)(update_fields=['status'])

    # به‌روزرسانی آگهی در بات دوم
    update_bot2_ad.delay(order.id)

    # حذف پیام تأیید قبلی
    await q.message.delete()

    # ارسال پیام موفقیت‌آمیز جدید (اختیاری)
    await context.bot.send_message(
        chat_id=q.message.chat_id,
        text="✅ Dein Vorschlag wurde storniert und der Auftrag wieder auf Pending gesetzt.",
        reply_markup=main_menu_keyboard()
    )


async def prop_cancel_callback(update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    prop_id = context.user_data.get('prop_id')
    prop = await sync_to_async(ChatPrompt.objects.get)(id=prop_id)

    order = prop.order
    logger.info(f"Before update: Order {order.id} status is {order.status}")
    await sync_to_async(
        Order.objects.filter(pk=order.id).update
    )(status='Pending')
    logger.info("Updated Pending")

    prop.status = 'rejected'
    await sync_to_async(prop.save)(update_fields=['status'])

    update_bot2_ad.delay(order.id)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="✅ Dein Vorschlag wurde storniert.",
        reply_markup=main_menu_keyboard()
    )

    return ConversationHandler.END

async def prop_keep_callback(update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "Dein Vorschlag bleibt bestehen.",
        reply_markup=main_menu_keyboard()
    )

async def show_received_proposals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("⚡ وارد show_received_proposals شدم")
    q = update.callback_query
    await q.answer()
    user_id = update.effective_user.id

    # همه پیشنهادهایی که برای سفارش‌های این کاربر آمده
    prompts = await sync_to_async(list)(
        ChatPrompt.objects
                  .filter(order__user__telegram_id=user_id)
                  .select_related('from_user', 'order')
                  .order_by('-created_at')
    )
    if not prompts:
        await q.edit_message_text(
            "📭 Du hast noch keine eingegangenen Vorschläge.",
            reply_markup=main_menu_keyboard()
        )
        return

    buttons = []
    for p in prompts:
        ts       = p.created_at.strftime("%d/%m %H:%M")
        amt      = p.order.amount_crypto
        price    = p.order.price_per_unit
        proposer = p.from_user.username or str(p.from_user.telegram_id)
        text = f"👤 {proposer}: {amt} → {price:.2f} € um {ts}"
        buttons.append([InlineKeyboardButton(text, callback_data=f"recvprop_{p.id}")])

    await q.edit_message_text(
        "📥 Eingegangene Vorschläge:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def recvprop_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    prop_id = int(q.data.split("_", 1)[1])
    context.user_data['recvprop_id'] = prop_id

    kb = [
        [
            InlineKeyboardButton("❌ Vorschlag ablehnen",    callback_data="recvprop_cancel"),
            InlineKeyboardButton("↩️ Behalten",             callback_data="recvprop_keep"),
        ]
    ]
    await q.edit_message_text(
        "Möchtest du diesen eingegangenen Vorschlag wirklich ablehnen?",
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def recvprop_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    prop_id = context.user_data.pop('recvprop_id', None)
    if not prop_id:
        return

    # ۱) واکشی پیشنهاد و سفارش
    prop = await sync_to_async(
        lambda pk: ChatPrompt.objects.select_related('order').get(pk=pk)
    )(prop_id)
    order = prop.order

    # ۲) تغییر وضعیت سفارش
    order.status = 'pending'
    await sync_to_async(order.save)(update_fields=['status'])

    # ۳) کاهش نیم‌ستاره برای مالکِ سفارش (کسی که معامله را لغو کرده)
    culprit = order.user
    if culprit.rating > Decimal('0.0'):
        culprit.rating = max(Decimal('0.0'), culprit.rating - Decimal('0.5'))
        await sync_to_async(culprit.save)(update_fields=['rating'])

    # ۴) به‌روزرسانی آگهی در بات دوم
    from core.tasks import update_bot2_ad
    update_bot2_ad.delay(order.id)

    # ۵) علامت‌گذاری وضعیت پیشنهاد
    prop.status = 'cancelled_by_owner'
    await sync_to_async(prop.save)(update_fields=['status'])

    # ۶) پاسخ به کاربر
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Zurück zum Menü", callback_data="back_to_main")]
    ])
    await q.edit_message_text(
        "✅ Dein Vorschlag wurde storniert und der Auftrag zurück auf Pending gestellt.",
        reply_markup=kb
    )

async def recvprop_keep_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "👍 Vorschlag bleibt bestehen.",
        reply_markup=main_menu_keyboard()
    )


def register_proposals_handlers(app):
    from telegram.ext import CallbackQueryHandler

    app.add_handler(CallbackQueryHandler(show_my_proposals,      pattern="^show_proposals$"))
    app.add_handler(CallbackQueryHandler(myprop_action_callback, pattern=r"^myprop_\d+$"))

    # اینجارو نگه دارید:
    app.add_handler(CallbackQueryHandler(confirm_cancel_callback, pattern="^confirm_cancel$"))
    app.add_handler(CallbackQueryHandler(prop_keep_callback,      pattern="^keep$"))

    app.add_handler(CallbackQueryHandler(show_received_proposals, pattern="^show_received$"))
    app.add_handler(CallbackQueryHandler(recvprop_action_callback, pattern=r"^recvprop_\d+$"))
    app.add_handler(CallbackQueryHandler(recvprop_cancel_callback,  pattern="^recvprop_cancel$"))
    app.add_handler(CallbackQueryHandler(recvprop_keep_callback,    pattern="^recvprop_keep$"))

