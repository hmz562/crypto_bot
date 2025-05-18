# core/order_management.py

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from asgiref.sync import sync_to_async
# بالای فایل
from django.utils import timezone
from core.menu import main_menu_keyboard
from core.constants import TOKEN2, BOT2_CHAT_ID, BOT1_USERNAME

from core.models import Order, User

# وضعیت‌ها
MANAGE_SELECT_ORDER, MANAGE_ACTION, MANAGE_EDIT_PRICE, MANAGE_DELETE_CONFIRM = range(4)

async def start_manage_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    user_obj, _ = await sync_to_async(User.objects.get_or_create)(
        telegram_id=q.from_user.id,
        defaults={'email': f"{q.from_user.id}@telegram.local"}
    )
    orders = await sync_to_async(list)(
        Order.objects.filter(
            user=user_obj,
            expires_at__gt=timezone.now()
        )
        .select_related('currency', 'country')
        .order_by('-created_at')
    )
    if not orders:
        await q.message.reply_text(
            "Du hast keine aktiven Aufträge.",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    buttons = [[InlineKeyboardButton(
        f"🔖 Auftrag {o.id:04d}  •  {o.amount_crypto} {o.currency.symbol} @ {o.price_per_unit:.2f} €",
        callback_data=f"manage_{o.id}"
    )] for o in orders]
    buttons.append([InlineKeyboardButton("⬅️ Zurück", callback_data="manage_back")])

    await q.message.reply_text(
        "Wähle einen Auftrag zur Verwaltung:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return MANAGE_SELECT_ORDER

async def select_my_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    if q.data in ("manage_back", "action_back"):
        await q.edit_message_text("Abgebrochen.")
        await q.message.reply_text("Bitte wähle eine Option:", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    order_id = int(q.data.split("_", 1)[1])
    context.user_data['manage_order_id'] = order_id

    kb = [
        [InlineKeyboardButton("Bearbeiten", callback_data="action_edit")],
        [InlineKeyboardButton("Verlängern", callback_data="action_extend")],
        [InlineKeyboardButton("Löschen",   callback_data="action_delete")],
        [InlineKeyboardButton("⬅️ Zurück",  callback_data="action_back")],
    ]
    await q.edit_message_text(
        f"Was möchtest du mit Auftrag {order_id:04d} machen?", 
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return MANAGE_ACTION

async def manage_choose_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    act = q.data
    await q.answer()

    if act == "action_back":
        return await start_manage_orders(update, context)

    oid = context.user_data.get('manage_order_id')
    if oid is None:
        await q.edit_message_text("❌ ID سفارش یافت نشد. لطفاً دوباره امتحان کنید.")
        return ConversationHandler.END

    order = await sync_to_async(Order.objects.get)(id=oid)

    if act == "action_edit":
        kb = [[InlineKeyboardButton("❌ Abbrechen", callback_data="action_back")]]
        await q.edit_message_text(
            "Bitte gib den neuen Preis pro Einheit ein:",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return MANAGE_EDIT_PRICE

    if act == "action_extend":
        order.expires_at += timedelta(days=1)
        await sync_to_async(order.save)(update_fields=['expires_at'])
        await q.edit_message_text(f"Auftrag {oid:04d} um 1 Tag verlängert.")
        return ConversationHandler.END

    if act == "action_delete":
        kb = [
            [InlineKeyboardButton("Ja, löschen",    callback_data="delete_confirm")],
            [InlineKeyboardButton("Nein, Abbrechen", callback_data="action_back")],
        ]
        await q.edit_message_text(
            f"Möchtest du Auftrag {oid:04d} wirklich löschen?",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return MANAGE_DELETE_CONFIRM

    return ConversationHandler.END

async def handle_edit_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    oid = context.user_data.get('manage_order_id')
    if oid is None:
        await update.message.reply_text(
            "❌ شناسه سفارش پیدا نشد. لطفاً دوباره از منوی مدیریت وارد شوید.",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    try:
        new_price = Decimal(text.replace(',', '.'))
    except InvalidOperation:
        await update.message.reply_text("Ungültiger Preis. Bitte erneut eingeben:")
        return MANAGE_EDIT_PRICE

    order = await sync_to_async(
        Order.objects.select_related('currency', 'country').get
    )(id=oid)
    order.price_per_unit = new_price
    total = order.amount_crypto * new_price
    if total < Decimal('100'):
        fee = Decimal('2')
    elif total <= Decimal('500'):
        fee = total * Decimal('0.015')
    elif total <= Decimal('1000'):
        fee = total * Decimal('0.01')
    else:
        fee = total * Decimal('0.0075')
    order.fee_total = fee
    order.net_total = total - fee
    await sync_to_async(order.save)(update_fields=['price_per_unit', 'fee_total', 'net_total'])

    # آماده‌سازی متن جدید برای پیام ربات دوم
    deep_link_to_bot1 = f"https://t.me/{BOT1_USERNAME}?start=propose_{order.id}"
    summary = (
        f"📢 Auftrag {order.id:04d}\n"
        f"{order.amount_crypto} {order.currency.symbol} → {total:.2f} €\n"
        f"Land: {order.country.name}\n"
        f"Zahlungsmethode: {order.fiat_method}\n"
        f"Beschreibung: {getattr(order, 'description', '–')}\n"
        f"‼️ Preis aktualisiert: {order.price_per_unit:.2f} €\n\n"
        "➡️ Klick unten, um deinen Vorschlag abzugeben:"
    )
    button = InlineKeyboardButton(text="🔘 Vorschlag senden", url=deep_link_to_bot1)
    markup = InlineKeyboardMarkup([[button]])

    bot2 = Bot(token=TOKEN2)
    await bot2.edit_message_text(
        chat_id=BOT2_CHAT_ID,
        message_id=order.bot2_message_id,
        text=summary,
        reply_markup=markup,
        parse_mode='Markdown'
    )

    # اطلاع به کاربر در ربات اول با لینک قابل کلیک و نام گروه
    group_username = BOT2_CHAT_ID.lstrip('@')
    code_str = f"Auftrag {order.id:04d}"
    group_link = f"https://t.me/{group_username}"
    await update.message.reply_text(
        f"✅ [{code_str}]({group_link}) wurde erfolgreich aktualisiert und in *Krypto Markt* angepasst.",
        reply_markup=main_menu_keyboard(),
        parse_mode='Markdown'
    )
    context.user_data.clear()
    return ConversationHandler.END

async def handle_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    oid = context.user_data.get('manage_order_id')
    if oid:
        await sync_to_async(Order.objects.filter(id=oid).delete)()
        await q.edit_message_text(f"Auftrag {oid:04d} wurde gelöscht.")
    else:
        await q.edit_message_text("❌ شناسه سفارش نامعتبر.")
    return ConversationHandler.END

manage_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(start_manage_orders, pattern="^show_orders$")],
    states={
        MANAGE_SELECT_ORDER:   [CallbackQueryHandler(select_my_order, pattern="^manage_\\d+$")],
        MANAGE_ACTION:         [CallbackQueryHandler(manage_choose_action, pattern="^action_")],
        MANAGE_EDIT_PRICE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_price)],
        MANAGE_DELETE_CONFIRM: [CallbackQueryHandler(handle_delete_confirm, pattern="^delete_confirm$")],
    },
    fallbacks=[CallbackQueryHandler(select_my_order, pattern="^(manage_back|action_back)$")],
allow_reentry=True, 
)


def register_order_management_handlers(app):
    # ایمپورت دیرهنگام تا حلقه شکسته شود
    from core.constants import TOKEN2, BOT2_CHAT_ID, BOT1_USERNAME

    # سپس handler را ثبت کن
    app.add_handler(manage_conv)