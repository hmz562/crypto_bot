import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from dotenv import load_dotenv
import logging
import requests
from datetime import timedelta
from core.tasks import update_bot2_ad
from core.models import Order, ChatPrompt, UserSettings
from core.proposals import confirm_cancel_callback
from core.proposals import (
    show_my_proposals, myprop_action_callback, prop_keep_callback,
    register_proposals_handlers
)
from core.terms import TERMS_TEXT, terms_keyboard
from core.order_management import start_manage_orders as show_user_orders, register_order_management_handlers

from asgiref.sync import sync_to_async
from django.utils import timezone
from django.db.models import Avg
from django.db.models import Q
from core.views import acquire_next_order
from telegram.ext import MessageHandler, filters, CallbackQueryHandler, ContextTypes

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

# پروژه


# بارگذاری متغیرهای محیطی و راه‌اندازی جنگو
load_dotenv()


# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# توکن‌ها و شناسه‌ها
token = os.getenv("TELEGRAM_TOKEN1")
TOKEN2 = os.getenv("TELEGRAM_TOKEN2")
BOT2_CHAT_ID = os.getenv("BOT2_CHAT_ID")
BOT1_USERNAME = os.getenv("BOT1_USERNAME")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))

# نگاشت سمبل → ID در CoinGecko
COINGECKO_IDS = {
    'BTC': 'bitcoin',
    'ETH': 'ethereum',
    'USDT': 'tether',
    'BNB': 'binancecoin',
    'SOL': 'solana',
}

# وضعیت‌های گفتگو
(
    SELECT_CURRENCY, SELECT_COUNTRY, SELECT_PAYMENT,
    ENTER_AMOUNT, ENTER_PRICE, ENTER_DESC, CONFIRM_ORDER,
    PROPOSE_MESSAGE, PROPOSE_AMOUNT, PROPOSE_PRICE,
    SHOW_SELECT_CURRENCY, SHOW_SELECT_PAYMENT, SHOW_ENTER_CITY
) = range(13)

# ساختار منوی اصلی
from core.menu import main_menu_keyboard

def require_terms(func):
    async def wrapper(update, context):
        # ۱) چک session
        if context.user_data.get("accepted_terms", False):
            return await func(update, context)
        # ۲) چک در دیتابیس
        user_id = update.effective_user.id
        accepted = await sync_to_async(
            lambda: UserSettings.objects.filter(
                user__telegram_id=user_id,
                accepted_terms=True
            ).exists()
        )()
        if accepted:
            context.user_data["accepted_terms"] = True
            return await func(update, context)
        # ۳) وگرنه نمایش قوانین
        await update.message.reply_text(
            TERMS_TEXT,
            reply_markup=terms_keyboard(),
            parse_mode="Markdown"
        )
    return wrapper

# فرمت ستاره‌ها

def format_stars(rating: int, max_stars: int = 5) -> str:
    filled = "⭐" * min(max(rating, 0), max_stars)
    empty = "☆" * (max_stars - len(filled))
    return filled + empty

# دریافت قیمت‌ها

def get_all_prices():
    ids = ','.join(COINGECKO_IDS.values())
    try:
        r = requests.get(
            'https://api.coingecko.com/api/v3/simple/price',
            params={'ids': ids, 'vs_currencies': 'eur', 'include_24hr_change': 'true'},
            timeout=5
        )
        return r.json()
    except Exception as e:
        logger.error(f"Error fetching prices: {e}")
        return {}
    

from core.auth import register_auth_handlers, auth_required, auth_menu_keyboard, logout
from core.utils import noop_callback
from core.order_management import register_order_management_handlers
from core.models import User, UserSettings, Order, Currency, Country, ChatPrompt, Feedback
from core.utils import format_stars 
from core.menu import main_menu_keyboard
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, MessageHandler, CallbackQueryHandler, filters

@auth_required
@require_terms 
async def fetch_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = get_all_prices()
    if not data:
        await update.message.reply_text("Preise konnten nicht abgerufen werden.")
    else:
        lines = []
        for sym, cid in COINGECKO_IDS.items():
            info   = data.get(cid, {})
            price  = info.get('eur')
            change = info.get('eur_24h_change')
            if price is not None and change is not None:
                arrow = "🔺" if change >= 0 else "🔻"
                lines.append(f"{sym}: {price:.2f} € | {arrow} {abs(change):.2f}%")
        await update.message.reply_text("\n".join(lines))
    await update.message.reply_text("Bitte wählen Sie eine Option:", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

async def accept_terms_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    # ۱) ست کردن پرچم توی سشن
    context.user_data["accepted_terms"] = True

    # ۲) واکشی User
    user_obj = await sync_to_async(User.objects.get)(
        telegram_id=update.effective_user.id
    )

    # ۳) get_or_create با استفاده از user=user_obj
    settings_obj, created = await sync_to_async(
        UserSettings.objects.get_or_create
    )(user=user_obj)

    settings_obj.accepted_terms = True
    await sync_to_async(settings_obj.save)(update_fields=["accepted_terms"])

    # ۴) ویرایش پیام قوانین
    await q.edit_message_text("✅ Du hast den Nutzungsbedingungen zugestimmt.")

    # ۵) اعلام فعال شدن
    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text="🎉 Super! Du kannst jetzt alle Funktionen des Bots nutzen."
    )

    # ۶) نمایش منوی اصلی
    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text="Bitte wählen Sie eine Option:",
        reply_markup=main_menu_keyboard()
    )

# وقتی خروج می‌زنه
async def reject_terms_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    # می‌تونید صرفاً پیام نمایش بدید و کاربر رو از ریپلای منو منع کنید
    await q.edit_message_text(text="❌ Um fortzufahren, musst du den Bot verlassen.")

# /start
@require_terms 
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # ۱) نگه داشتن پرچم
    accepted = context.user_data.get("accepted_terms", False)

# ۲) پاک‌سازی بقیه‌ی داده‌ها
    context.user_data.clear()

# ۳) بازگرداندن پرچم اگر قبلاً قبول شده
    if accepted:
        context.user_data["accepted_terms"] = True


        # اگر هنوز قوانین نپذیرفته:
    if not context.user_data.get("accepted_terms", False):
        await update.message.reply_text(
            TERMS_TEXT,
            reply_markup=terms_keyboard(),
            parse_mode="Markdown"
        )
        return

    # حالت deep link برای ارسال پیشنهاد
    if context.args and context.args[0].startswith('propose_'):
        order_id = int(context.args[0].split('_', 1)[1])
        order = await sync_to_async(
            Order.objects.select_related('currency', 'user').get
        )(id=order_id)

        # اگر کاربر صاحب آگهی باشه، ردش کن
        if order.user.telegram_id == update.effective_user.id:
            await update.message.reply_text(
                "⚠️ Du hast auf deine eigene Anzeige geklickt. "
                "Vorschläge auf die eigene Anzeige sind nicht möglich und wurden abgelehnt.",
                reply_markup=main_menu_keyboard()
            )
            return ConversationHandler.END    

        # محاسبه مقادیر
        amt    = float(order.amount_crypto)
        symbol = order.currency.symbol
        price  = float(order.price_per_unit)
        total  = amt * price
        if total < 100:
            fee = 2
        elif total <= 500:
            fee = total * 0.015
        elif total <= 1000:
            fee = total * 0.01
        else:
            fee = total * 0.0075
        net = total - fee

        context.user_data['propose_order_id'] = order_id

        # پیام کاربر به آلمانی
        msg = (
            f"Sie möchten {amt} {symbol} von Nutzer {order.user.telegram_id} kaufen.\n"
            f"Preis pro Einheit: {price:.2f} €\n"
            f"Gesamt: {total:.2f} €\n"
            f"Gebühr: {fee:.2f} €\n"
            f"Nettobetrag: {net:.2f} €\n\n"
            "Sind Sie einverstanden?"
        )
        keyboard = [
            ["Einverstanden", "Neuen Vorschlag senden"],
            ["Abbrechen"]
        ]

        # ← این دو خط باید داخل بلوک if باشند:
        sent_invoice_msg = await update.message.reply_text(
            msg,
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
        context.user_data['invoice_mid'] = sent_invoice_msg.message_id

        return PROPOSE_MESSAGE

    # حالت عادی /start
    welcome = (
        "👋 Willkommen!\n\n"
        "Mit diesem Bot können Sie Kryptowährungen sicher und direkt gegen Euro tauschen.\n\n"
        "Bitte wählen Sie eine Option:"
    )
    await update.message.reply_text(welcome, reply_markup=main_menu_keyboard())
    return ConversationHandler.END


def require_username(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user.username:
            await update.message.reply_text(
                "❌ Bitte richte zuerst einen Telegram-Benutzernamen (@username) in deinen Telegram-Einstellungen ein, "
                "damit wir fortfahren können."
            )
            return ConversationHandler.END
        return await func(update, context)
    return wrapper


# شروع خرید
@require_username
@auth_required
@require_terms 
async def start_buy_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "Kryptopreise abrufen":
        return await fetch_prices(update, context)

    # ۱) نگه داشتن پرچم
    accepted = context.user_data.get("accepted_terms", False)

# ۲) پاک‌سازی بقیه‌ی داده‌ها
    context.user_data.clear()

# ۳) بازگرداندن پرچم اگر قبلاً قبول شده
    if accepted:
        context.user_data["accepted_terms"] = True

    context.user_data["flow"] = "buy"
    symbols = await sync_to_async(list)(Currency.objects.values_list('symbol', flat=True))
    keyboard = [symbols[i:i+2] for i in range(0, len(symbols), 2)] + [["⬅️ Zurück"]]
    await update.message.reply_text(
        "Bitte wählen Sie die Kryptowährung aus, die Sie kaufen möchten:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return SELECT_CURRENCY


# شروع فروش
@require_username
@auth_required
@require_terms 
async def start_sell_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "Kryptopreise abrufen":
        return await fetch_prices(update, context)

    # ۱) نگه داشتن پرچم
    accepted = context.user_data.get("accepted_terms", False)

# ۲) پاک‌سازی بقیه‌ی داده‌ها
    context.user_data.clear()

# ۳) بازگرداندن پرچم اگر قبلاً قبول شده
    if accepted:
        context.user_data["accepted_terms"] = True

    context.user_data["flow"] = "sell"
    symbols = await sync_to_async(list)(Currency.objects.values_list('symbol', flat=True))
    keyboard = [symbols[i:i+2] for i in range(0, len(symbols), 2)] + [["⬅️ Zurück"]]
    await update.message.reply_text(
        "Bitte wählen Sie die Kryptowährung aus, die Sie verkaufen möchten:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return SELECT_CURRENCY


# انتخاب ارز
@auth_required
async def select_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "Kryptopreise abrufen":
        return await fetch_prices(update, context)
    if update.message.text == "⬅️ Zurück":
        await start(update, context)
        return ConversationHandler.END

    context.user_data["currency"] = update.message.text
    countries = ["Deutschland", "Österreich", "Schweiz"]
    keyboard = [countries[i:i+2] for i in range(0, len(countries), 2)] + [["⬅️ Zurück"]]
    await update.message.reply_text(
        "Bitte wählen Sie Ihr Land:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return SELECT_COUNTRY


# انتخاب کشور
@auth_required
async def select_country(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "Kryptopreise abrufen":
        return await fetch_prices(update, context)
    if update.message.text == "⬅️ Zurück":
        return await (start_buy_order if context.user_data["flow"] == "buy" else start_sell_order)(update, context)

    context.user_data["country"] = update.message.text
    methods = ["SEPA", "PayPal", "Revolut", "Barzahlung"]
    keyboard = [methods[i:i+2] for i in range(0, len(methods), 2)] + [["⬅️ Zurück"]]
    await update.message.reply_text(
        "Bitte wählen Sie die Zahlungsmethode:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return SELECT_PAYMENT


# انتخاب روش پرداخت
@auth_required
async def select_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "Kryptopreise abrufen":
        return await fetch_prices(update, context)
    if update.message.text == "⬅️ Zurück":
        return await select_country(update, context)

    context.user_data["payment"] = update.message.text
    keyboard = [["100", "200"], ["300", "400"], ["⬅️ Zurück"]]
    await update.message.reply_text(
        "Bitte Menge eingeben:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return ENTER_AMOUNT


# وارد کردن مقدار
@auth_required
async def enter_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "Kryptopreise abrufen":
        return await fetch_prices(update, context)
    if update.message.text == "⬅️ Zurück":
        return await select_payment(update, context)

    try:
        amt = float(update.message.text.replace(',', '.'))
    except ValueError:
        await update.message.reply_text("Ungültige Menge. Bitte erneut eingeben:")
        return ENTER_AMOUNT

    context.user_data["amount"] = amt
    data = get_all_prices()
    price = data.get(COINGECKO_IDS[context.user_data["currency"]], {}).get("eur", 0.0)
    context.user_data["market_price"] = price

    await update.message.reply_text(
        f"Preis pro Einheit: {price:.2f} €\nBitte bestätigen oder neuen Preis eingeben.",
        reply_markup=ReplyKeyboardMarkup([[f"Marktpreis: {price:.2f} €"], ["⬅️ Zurück"]], resize_keyboard=True)
    )
    return ENTER_PRICE


# وارد کردن قیمت
@auth_required
async def enter_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "Kryptopreise abrufen":
        return await fetch_prices(update, context)
    if update.message.text == "⬅️ Zurück":
        return await enter_amount(update, context)

    text = update.message.text
    if text.startswith("Marktpreis"):
        price = context.user_data["market_price"]
    else:
        try:
            price = float(text.replace("€", "").replace(',', '.').strip())
        except ValueError:
            await update.message.reply_text("Ungültiger Preis. Bitte erneut eingeben:")
            return ENTER_PRICE

    context.user_data["price"] = price
    total = context.user_data["amount"] * price
    if total < 100:
        fee = 2
    elif total <= 500:
        fee = total * 0.015
    elif total <= 1000:
        fee = total * 0.01
    else:
        fee = total * 0.0075
    net = total - fee
    context.user_data["fee"], context.user_data["net"] = fee, net

    await update.message.reply_text(
        "Bitte gib eine Beschreibung für Deinen Auftrag ein:",
        reply_markup=ReplyKeyboardMarkup(
            [["Ohne Beschreibung"], ["⬅️ Zurück"], ["❌ Abbrechen"]],
            resize_keyboard=True
        )
    )
    return ENTER_DESC


# هندلر توضیحات نهایی
@auth_required
async def enter_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    # کنترل لغو
    if text == "❌ Abbrechen":
        context.user_data.clear()
        await start(update, context)
        return ConversationHandler.END
    # کنترل بازگشت
    if text == "⬅️ Zurück":
        return await enter_price(update, context)

    # اگر بدون توضیحات انتخاب شد
    if text == "Ohne Beschreibung":
        context.user_data["description"] = ""
    else:
        context.user_data["description"] = text

    d = context.user_data
    preview = (
        f"🎯 Voransicht Ihres {'Kauf' if d['flow']=='buy' else 'Verkaufs'}auftrags:\n"
        f"Währung: {d['currency']}\n"
        f"Menge: {d['amount']}\n"
        f"Preis/Einheit: {d['price']:.2f} €\n"
        f"Beschreibung: {d['description'] or '–'}\n"
        f"Gesamtbetrag: {d['amount']*d['price']:.2f} €\n"
        f"Netto nach Gebühr: {d['net']:.2f} €\n\n"
        "Bitte wählen:"
    )
    await update.message.reply_text(
        preview,
        reply_markup=ReplyKeyboardMarkup(
            [["✅ Bestätigen", "❌ Abbrechen"], ["⬅️ Zurück"]],
            resize_keyboard=True
        )
    )
    return CONFIRM_ORDER


# تأیید نهایی و ایجاد سفارش
@require_username
@auth_required
async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "Kryptopreise abrufen":
        return await fetch_prices(update, context)

    if text == "❌ Abbrechen":
        context.user_data.clear()
        await start(update, context)
        return ConversationHandler.END

    if text == "⬅️ Zurück":
        return await enter_desc(update, context)

    if text == "✅ Bestätigen":
        d = context.user_data

        # آماده‌سازی کشور
        country_obj = await sync_to_async(Country.objects.get)(name=d['country'])

        # دریافت یا ایجاد کاربر به همراه ذخیره username
        user_obj, created = await sync_to_async(User.objects.get_or_create)(
            telegram_id=update.effective_user.id,
            defaults={
                'email':        f"{update.effective_user.id}@telegram.local",
                'country_code': country_obj.code,
                'username':     update.effective_user.username or ''
            }
        )
        # اگر از قبل موجود بود اما username تغییر کرده
        if (not created
                and update.effective_user.username
                and user_obj.username != update.effective_user.username):
            user_obj.username = update.effective_user.username
            await sync_to_async(user_obj.save)(update_fields=['username'])

        # خواندن و فرمت ستاره‌ها
        user_rating = await sync_to_async(lambda u: u.rating)(user_obj)
        stars_line  = format_stars(user_rating)

        # ایجاد سفارش
        currency_obj = await sync_to_async(Currency.objects.get)(symbol=d['currency'])
        order = await sync_to_async(Order.objects.create)(
            user           = user_obj,
            currency       = currency_obj,
            is_buy         = (d['flow'] == 'buy'),
            country        = country_obj,
            fiat_method    = d['payment'],
            amount_crypto  = d['amount'],
            price_per_unit = d['price'],
            fee_total      = d['fee'],
            net_total      = d['net'],
            expires_at     = timezone.now() + timedelta(days=1),
        )

        # لینک به ربات دوم و ربات اول
        bot2_username     = BOT2_CHAT_ID.lstrip('@')
        deep_link_to_bot2 = f"https://t.me/{bot2_username}?start=order_{order.id}"
        deep_link_to_bot1 = f"https://t.me/{BOT1_USERNAME}?start=propose_{order.id}"
        code_str          = f"Auftrag {order.id:04d}"
        order_type = "Kaufauftrag" if d['flow'] == 'buy' else "Verkaufsauftrag"
        # پیام به کاربر در ربات اول
        await update.message.reply_text(
            f"✅ Ihr Auftrag wurde erstellt!\n[{code_str}]({deep_link_to_bot2})",
            reply_markup = main_menu_keyboard(),
            parse_mode   = 'Markdown'
        )

        # ارسال به ربات دوم با دکمه
        bot2   = Bot(token=TOKEN2)
        summary = (
            f"📢 {code_str} – {order_type}\n"
            f"{order.amount_crypto} {order.currency.symbol} → "
            f"{(order.amount_crypto * order.price_per_unit):.2f} €\n"
            f"Land: {order.country.name}\n"
            f"Zahlungsmethode: {d['payment']}\n"
            f"Beschreibung: {d['description']}\n"
            f"Bewertung Verkäufer: {stars_line}\n\n"
            "➡️ Klick auf den Button unten, um deinen Vorschlag abzugeben:"
        )
        button  = InlineKeyboardButton(text="🔘 Vorschlag senden", url=deep_link_to_bot1)
        markup  = InlineKeyboardMarkup([[button]])
        sent_msg = await bot2.send_message(
            chat_id      = BOT2_CHAT_ID,
            text         = summary,
            reply_markup = markup,
            parse_mode   = 'Markdown'
        )

        # ذخیره‌ی message_id در سفارش
        order.bot2_message_id = sent_msg.message_id
        await sync_to_async(order.save)(update_fields=['bot2_message_id'])

    return ConversationHandler.END

@require_username
@auth_required
async def handle_proposal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text
    order_id = context.user_data.get('propose_order_id')

    # 1) حالت Einverstanden
    if choice == "Einverstanden":
        order = await sync_to_async(
            Order.objects.select_related('currency', 'user', 'country').get
        )(id=order_id)

        amt   = context.user_data.get('propose_new_amount', float(order.amount_crypto))
        price = context.user_data.get('propose_new_price', float(order.price_per_unit))
        total = amt * price

        country_code = order.country.code

        proposer, created = await sync_to_async(User.objects.get_or_create)(
            telegram_id=update.effective_user.id,
            defaults={
                'email':        f"{update.effective_user.id}@telegram.local",
                'country_code': country_code,
                'username':     update.effective_user.username or ''
            }
        )
        if (not created
                and update.effective_user.username
                and proposer.username != update.effective_user.username):
            proposer.username = update.effective_user.username
            await sync_to_async(proposer.save)(update_fields=['username'])

        content = (
            f"✅ Ich stimme dem Handel #{order.id:04d} zu:\n"
            f"{amt:.8f} {order.currency.symbol} → {total:.2f} €"
        )

        # فقط یک بار حذف
        await sync_to_async(
            lambda: ChatPrompt.objects.filter(order=order, from_user=proposer).delete()
        )()

        await sync_to_async(ChatPrompt.objects.create)(
            from_user=proposer,
            to_user=order.user,
            content=content,
            order=order
        )

        await update.message.reply_text(
            "✅ Dein Vorschlag wurde erfolgreich gesendet!",
            reply_markup=main_menu_keyboard()
        )

        amt_str   = f"{amt:.8f}"
        price_str = f"{price:.2f}"

        inline_kb = [[
            InlineKeyboardButton(
                "✅ Bestätigen",
                callback_data=f"owner_confirm_{order.id}_{amt_str}_{price_str}"
            ),
            InlineKeyboardButton(
                "❌ Ablehnen",
                callback_data=f"owner_reject_{order.id}"
            ),
        ]]

        await context.bot.send_message(
            chat_id=order.user.telegram_id,
            text=(
                f"🔔 Nutzer {update.effective_user.id} hat deinen Auftrag "
                f"#{order.id:04d} übernommen für "
                f"{amt_str} {order.currency.symbol} @ {price_str} €.\n\n"
                "Bitte bestätige den Handel:"
            ),
            reply_markup=InlineKeyboardMarkup(inline_kb)
        )

        invoice_mid = context.user_data.get('invoice_mid')
        if invoice_mid:
            new_inline = InlineKeyboardMarkup([[  
                InlineKeyboardButton("🔁 Vorschlag erneut senden", callback_data="resend_proposal"),
                InlineKeyboardButton("❌ Vorschlag abbrechen", callback_data="cancel_proposal"),
                InlineKeyboardButton("🏠 Hauptmenü", callback_data="back_to_main"),
            ]])
            await context.bot.edit_message_reply_markup(
                chat_id=update.effective_chat.id,
                message_id=invoice_mid,
                reply_markup=new_inline
            )
            await update.message.reply_text(
                "Bitte wählen Sie:",
                reply_markup=ReplyKeyboardMarkup(
                    [["Einverstanden", "Neuen Vorschlag senden", "❌ Vorschlag abbrechen"]],
                    resize_keyboard=True
                )
            )

        return PROPOSE_MESSAGE

    # 2) حالت Neuen Vorschlag senden
    elif choice == "Neuen Vorschlag senden":
        await update.message.reply_text(
            "Bitte geben Sie Ihre vorgeschlagene Menge ein:",
            reply_markup=ReplyKeyboardMarkup(
                [["🔢 Weiter mit derselben Menge"], ["⬅️ Zurück"], ["❌ Abbrechen"]],
                resize_keyboard=True
            )
        )
        return PROPOSE_AMOUNT

    # ✅ 3) حالت ❌ Abbrechen
    elif choice == "❌ Vorschlag abbrechen":
        context.user_data.clear()
        await start(update, context)
        return ConversationHandler.END

    context.user_data.clear()
    return ConversationHandler.END

# گام ۲: دریافت مقدار پیشنهادی
@require_username
@auth_required
async def handle_propose_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    order_id = context.user_data['propose_order_id']

    # کنترل لغو
    if text == "❌ Abbrechen":
        context.user_data.clear()
        await start(update, context)
        return ConversationHandler.END

    # کنترل بازگشت → برمی‌گردیم به منوی اصلی پیشنهاد (PROPOSE_MESSAGE)
    if text == "⬅️ Zurück":
        order = await sync_to_async(
            Order.objects.select_related('currency','user').get
        )(id=order_id)
        # مقدار/نرخ پیشنهادی فعلی یا پیش‌فرض
        amt   = context.user_data.get('propose_new_amount', float(order.amount_crypto))
        price = context.user_data.get('propose_new_price', float(order.price_per_unit))
        total = amt * price
        if total < 100:
            fee = 2
        elif total <= 500:
            fee = total * 0.015
        elif total <= 1000:
            fee = total * 0.01
        else:
            fee = total * 0.0075
        net = total - fee

        # همان پیش‌نمایش اولیه
        msg = (
            f"Sie möchten {amt} {order.currency.symbol} von Nutzer {order.user.telegram_id} kaufen.\n"
            f"Vorgeschlagener Preis pro Einheit: {price:.2f} €\n"
            f"Neues Gesamt: {total:.2f} €\n"
            f"Gebühr: {fee:.2f} €\n"
            f"Nettobetrag: {net:.2f} €\n\n"
            "Sind Sie mit Ihrem Vorschlag einverstanden?"
        )
        keyboard = [
            ["Einverstanden", "Neuen Vorschlag senden"],
            ["❌ Abbrechen"]
        ]
        await update.message.reply_text(
            msg,
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
        return PROPOSE_MESSAGE

    # ادامه با همان مقدار
    if text.startswith("🔢") and "Menge" in text:
        order = await sync_to_async(Order.objects.get)(id=order_id)
        context.user_data['propose_new_amount'] = float(order.amount_crypto)
        await update.message.reply_text(
            "Bitte geben Sie Ihren vorgeschlagenen Preis pro Einheit ein:",
            reply_markup=ReplyKeyboardMarkup(
                [["💶 Weiter mit dem gleichen Preis"], ["⬅️ Zurück"], ["❌ Abbrechen"]],
                resize_keyboard=True
            )
        )
        return PROPOSE_PRICE

    # وارد کردن مقدار جدید
    try:
        new_amt = float(text.replace(',', '.'))
    except ValueError:
        await update.message.reply_text("Ungültige Menge. Bitte erneut eingeben:")
        return PROPOSE_AMOUNT

    context.user_data['propose_new_amount'] = new_amt
    await update.message.reply_text(
        "Bitte geben Sie Ihren vorgeschlagenen Preis pro Einheit ein:",
        reply_markup=ReplyKeyboardMarkup(
            [["💶 Weiter mit dem gleichen Preis"], ["⬅️ Zurück"], ["❌ Abbrechen"]],
            resize_keyboard=True
        )
    )
    return PROPOSE_PRICE


# گام ۳: دریافت نرخ پیشنهادی و نمایش پیش‌نمایش
@require_username
@auth_required
async def handle_propose_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    order_id = context.user_data['propose_order_id']

    # کنترل لغو
    if text == "❌ Abbrechen":
        context.user_data.clear()
        await start(update, context)
        return ConversationHandler.END

    # کنترل بازگشت → برمی‌گردیم به مرحله مقدار (PROPOSE_AMOUNT)
    if text == "⬅️ Zurück":
        # بازنمایش منوی مقدار
        order = await sync_to_async(Order.objects.get)(id=order_id)
        amt = context.user_data.get('propose_new_amount', float(order.amount_crypto))
        await update.message.reply_text(
            "Bitte geben Sie Ihre vorgeschlagene Menge ein:",
            reply_markup=ReplyKeyboardMarkup(
                [["🔢 Weiter mit derselben Menge"], ["⬅️ Zurück"], ["❌ Abbrechen"]],
                resize_keyboard=True
            )
        )
        return PROPOSE_AMOUNT

    # ادامه با همان قیمت
    if text.startswith("💶") and "Preis" in text:
        order = await sync_to_async(Order.objects.get)(id=order_id)
        new_price = float(order.price_per_unit)
    else:
        try:
            new_price = float(text.replace('€', '').replace(',', '.').strip())
        except ValueError:
            await update.message.reply_text("Ungültiger Preis. Bitte erneut eingeben:")
            return PROPOSE_PRICE

    context.user_data['propose_new_price'] = new_price

    # محاسبه و پیش‌نمایش نهایی
    order = await sync_to_async(
        Order.objects.select_related('currency','user').get
    )(id=order_id)
    amt   = context.user_data['propose_new_amount']
    price = new_price
    total = amt * price
    if total < 100:
        fee = 2
    elif total <= 500:
        fee = total * 0.015
    elif total <= 1000:
        fee = total * 0.01
    else:
        fee = total * 0.0075
    net = total - fee

    msg = (
        f"Sie möchten {amt} {order.currency.symbol} von Nutzer {order.user.telegram_id} kaufen.\n"
        f"Vorgeschlagener Preis pro Einheit: {price:.2f} €\n"
        f"Neues Gesamt: {total:.2f} €\n"
        f"Gebühr: {fee:.2f} €\n"
        f"Nettobetrag: {net:.2f} €\n\n"
        "Sind Sie mit Ihrem Vorschlag einverstanden?"
    )
    keyboard = [
        ["Einverstanden", "Neuen Vorschlag senden"],
        ["❌ Abbrechen"]
    ]
    await update.message.reply_text(
        msg,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return PROPOSE_MESSAGE

# --------------------------------------------
# ۱) owner_confirm_callback (با select_related برای user و currency)
# --------------------------------------------

@require_username
@auth_required
async def owner_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from decimal import Decimal
    from core.models import ChatPrompt

    # 1) پاسخ به کلیک
    q = update.callback_query
    await q.answer()

    # 2) پارس کردن callback_data
    #    فرمت داده: "owner_confirm_<order_id>_<amount>_<price>"
    _, _, order_id_str, amt_str, price_str = q.data.split("_")
    order_id  = int(order_id_str)
    new_amt   = Decimal(amt_str)
    new_price = Decimal(price_str)

    # 3) واکشی و به‌روزرسانی سفارش
    order = await sync_to_async(
        Order.objects.select_related('user','currency','country').get
    )(id=order_id)
    order.amount_crypto  = new_amt
    order.price_per_unit = new_price
    order.net_total      = (new_amt * new_price) - order.fee_total
    order.status         = 'matched'
    await sync_to_async(order.save)(
        update_fields=['amount_crypto','price_per_unit','net_total','status']
    )

    # 4) ویرایش پیام inline برای مالک
    await q.edit_message_text("✅ Du hast den Handel bestätigt!")

    # 5) ارسال رسید نهایی به مالک
    receipt_text = (
        f"📄 *Handelsbestätigung*\n\n"
        f"Auftrag: #{order.id:04d}\n"
        f"Menge: `{new_amt}` {order.currency.symbol}\n"
        f"Preis/Einheit: `{new_price:.2f}` €\n"
        f"Netto gesamt: `{order.net_total:.2f}` €\n"
    )
    await context.bot.send_message(
        chat_id=order.user.telegram_id,
        text=receipt_text,
        parse_mode='Markdown'
    )

    # 5.1) اطلاع به مالک برای آنلاین ماندن و انتظار پیام ادمین
    await context.bot.send_message(
        chat_id=order.user.telegram_id,
        text=(
            "✅ Dein Handel ist bestätigt und dein Beleg wurde gesendet.\n"
            "Bitte bleib online und warte auf eine Nachricht vom Admin."
        )
    )

    # 6) یافتن آخرین ChatPrompt برای این سفارش
    prompt = await sync_to_async(
        lambda oid: ChatPrompt.objects
                            .filter(order__id=oid)
                            .order_by('-created_at')
                            .select_related('from_user')
                            .first()
    )(order_id)

    # 7) پیام به پیشنهاد‌دهنده (اگر پیدا شد)
    if prompt and prompt.from_user:
        await context.bot.send_message(
            chat_id=prompt.from_user.telegram_id,
            text=(
                "✅ Dein Vorschlag wurde angenommen!\n"
                "Bitte bleib online und warte auf eine Nachricht vom Admin."
            )
        )
    else:
        # برای دیباگ می‌توانی لاگ یا print کنی
        logger.warning(f"No ChatPrompt found for order {order_id}")

    # 8) اطلاع ادمین
    buyer_id = prompt.from_user.telegram_id if prompt and prompt.from_user else 'unbekannt'
    admin_text = (
        f"🛒 Neuer bestätigter Handel #{order.id:04d}\n"
        f"Käufer: {buyer_id}\n"
        f"Verkäufer: {order.user.telegram_id}\n"
        f"Netto gesamt: {order.net_total:.2f} €"
    )
    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_text)

    # 9) زمان‌بندی آپدیت در ربات دوم
    update_bot2_ad.delay(order.id)

    
# --------------------------------------------
# ۲) Reject-Price
# --------------------------------------------

@require_username
@auth_required
async def owner_reject_price_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    oid = int(q.data.rsplit("_", 1)[-1])

    # واکشی آخرین ChatPrompt از داخل sync_to_async
    last = await sync_to_async(
        lambda order_id: ChatPrompt.objects.filter(order__id=order_id)
                                            .select_related('from_user')
                                            .order_by('-created_at')
                                            .first()
    )(oid)
    if last:
        await context.bot.send_message(
            chat_id=last.from_user.telegram_id,
            text="❌ Dein Vorschlag wurde nur wegen des Preises abgelehnt."
        )
    await q.edit_message_text("Vorschlag abgelehnt: Preisgrund.")

# --------------------------------------------
# ۳) Reject-Amount
# --------------------------------------------

@auth_required
async def owner_reject_amount_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    oid = int(q.data.rsplit("_", 1)[-1])

    last = await sync_to_async(
        lambda order_id: ChatPrompt.objects.filter(order__id=order_id)
                                            .select_related('from_user')
                                            .order_by('-created_at')
                                            .first()
    )(oid)
    if last:
        await context.bot.send_message(
            chat_id=last.from_user.telegram_id,
            text="❌ Dein Vorschlag wurde nur wegen der Menge abgelehnt."
        )
    await q.edit_message_text("Vorschlag abgelehnt: Mengen-Grund.")

# --------------------------------------------
# ۴) Reject-Both
# --------------------------------------------


@auth_required
async def owner_reject_both_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    oid = int(q.data.rsplit("_", 1)[-1])

    last = await sync_to_async(
        lambda order_id: ChatPrompt.objects.filter(order__id=order_id)
                                            .select_related('from_user')
                                            .order_by('-created_at')
                                            .first()
    )(oid)
    if last:
        await context.bot.send_message(
            chat_id=last.from_user.telegram_id,
            text="❌ Dein Vorschlag wurde wegen Preis und Menge abgelehnt."
        )
    await q.edit_message_text("Vorschlag abgelehnt: Preis & Mengen-Grund.")

# --------------------------------------------
# ۵) Reject-Generic
# --------------------------------------------


@auth_required
async def owner_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    oid = int(q.data.rsplit("_", 1)[-1])

    last = await sync_to_async(
        lambda order_id: ChatPrompt.objects.filter(order__id=order_id)
                                            .select_related('from_user')
                                            .order_by('-created_at')
                                            .first()
    )(oid)
    if last:
        await context.bot.send_message(
            chat_id=last.from_user.telegram_id,
            text="❌ Dein Vorschlag wurde abgelehnt."
        )
    await q.edit_message_text("Vorschlag abgelehnt.")


# هندلر ستاره دادن

@auth_required
async def rating_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, order_id, to_user_id, rating = query.data.split("_")
    order     = await sync_to_async(Order.objects.get)(id=int(order_id))
    from_user = await sync_to_async(User.objects.get)(telegram_id=update.effective_user.id)
    to_user   = await sync_to_async(User.objects.get)(telegram_id=int(to_user_id))
    stars     = int(rating)

    await sync_to_async(Feedback.objects.create)(
        order=order, from_user=from_user, to_user=to_user, rating=stars
    )

    agg = await sync_to_async(lambda u: Feedback.objects.filter(to_user=u).aggregate(avg=Avg('rating')))(to_user)
    avg = agg['avg'] or 0
    to_user.rating = round(avg)
    await sync_to_async(to_user.save)(update_fields=['rating'])

    await query.edit_message_text("Danke für dein Feedback! ⭐")

    return ConversationHandler.END

# شروع فرایند نمایش آگهی‌ها

@require_username
@auth_required
@require_terms
async def start_show_listings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ۱) نگه داشتن پرچم
    accepted = context.user_data.get("accepted_terms", False)

# ۲) پاک‌سازی بقیه‌ی داده‌ها
    context.user_data.clear()

# ۳) بازگرداندن پرچم اگر قبلاً قبول شده
    if accepted:
        context.user_data["accepted_terms"] = True

    text = update.message.text
    # ذخیره نوع نمایش: فروشنده یا خریدار
    context.user_data["show_flow"] = "sellers" if text == "Verkäufer anzeigen" else "buyers"
    # پرسش اول: انتخاب ارز
    symbols = await sync_to_async(list)(Currency.objects.values_list('symbol', flat=True))
    keyboard = [symbols[i:i+2] for i in range(0, len(symbols), 2)] + [["⬅️ Zurück"]]
    await update.message.reply_text(
        "Bitte wählen Sie die gewünschte Kryptowährung:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return SHOW_SELECT_CURRENCY


@auth_required
async def show_select_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "⬅️ Zurück":
        # بازگشت به منوی اصلی
        await start(update, context)
        return ConversationHandler.END

    # ذخیره ارز انتخاب‌شده
    context.user_data["currency"] = update.message.text
    # پرسش دوم: روش پرداخت
    methods = ["SEPA", "PayPal", "Revolut", "Barzahlung"]
    keyboard = [methods[i:i+2] for i in range(0, len(methods), 2)] + [["⬅️ Zurück"]]
    await update.message.reply_text(
        "Bitte wählen Sie die Zahlungsmethode:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return SHOW_SELECT_PAYMENT

@require_username
@auth_required
async def show_select_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "⬅️ Zurück":
        # بازگشت به انتخاب ارز
        return await show_select_currency(update, context)

    # ذخیره روش پرداخت
    context.user_data["payment"] = text
    if text == "Barzahlung":
        # اگر نقدی، پرسش سوم: شهر
        await update.message.reply_text("Bitte geben Sie Ihre Stadt ein:")
        return SHOW_ENTER_CITY
    else:
        # مستقیماً نمایش لیست آگهی‌ها
        return await display_listings(update, context)

@require_username
@auth_required
async def show_enter_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ذخیره شهر
    context.user_data["city"] = update.message.text.strip()
    # نمایش لیست آگهی‌ها
    return await display_listings(update, context)

@require_username
@auth_required
@require_terms 
async def display_listings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = context.user_data
    is_buy = (d.get('show_flow') == 'buyers')
    direction = 'Kauf' if is_buy else 'Verkauf'
    # عنوان پویا با ایموجی بانک
    header = f"🏦 #Liste der Anfragen zum {direction} von {d['currency']} via {d['payment']}: 🏦"
    # آیدی ربات دوم قابل کلیک
    bot2_handle = BOT2_CHAT_ID if BOT2_CHAT_ID.startswith('@') else f"@{BOT2_CHAT_ID}"
    bot2_line = f"🔘 {bot2_handle} 🔘"
    qs = Order.objects.filter(
        is_buy=is_buy,
        currency__symbol=d['currency'],
        fiat_method=d['payment'],
        expires_at__gt=timezone.now()
    )
    if d.get('city'):
        qs = qs.filter(city__iexact=d['city'])
    listings = await sync_to_async(list)(qs.select_related('currency','country'))
    if not listings:
        content = 'Keine Angebote gefunden.'
    else:
        lines = []
        for o in listings:
            oid4 = str(o.id).zfill(4)
            country_code = o.country.code
            # ساخت هر خط با لینک شماره آگهی
            bot2_handle = BOT2_CHAT_ID.lstrip('@')
            pm_id       = o.bot2_message_id
            deep_link   = f"https://t.me/{bot2_handle}/{pm_id}" if pm_id else '#'
            lines.append(
                f"🔹 [Antrag {oid4}]({deep_link}) : Preis {o.price_per_unit:.2f} € | Menge {o.amount_crypto} | von {country_code}"
            )
        content = '\n'.join(lines)
    # فقط یک بار لینک ربات دوم بعد از هدر و یک بار بعد از محتوا
    message = (
        f"{header}\n"
        f"{bot2_line}\n"
        f"{content}\n"
        f"{bot2_line}"
    )

    # ارسال پیام با Markdown
    await update.message.reply_text(
        message,
        reply_markup=main_menu_keyboard(),
        parse_mode='Markdown'
    )
    return ConversationHandler.END

# 📢 هندلر گروه بحث و گفتگو
async def discussion_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # لینک یا آیدی گروه تلگرام خودتون
    group_link = "https://t.me/+X9P7EXkM4TAzNmIy"
    await update.message.reply_text(
        f"🔗 Tritt unserer Diskussionsgruppe bei:\n{group_link}",
        reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END

@auth_required
@require_terms
async def show_profile_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # واکشی کاربر
    user = await sync_to_async(User.objects.get)(telegram_id=update.effective_user.id)
    # مقداردهی امن به نام کاربر
    user_name = " ".join(filter(None, [user.first_name, user.last_name])) or "–"
    # امتیاز به ستاره
    stars = format_stars(user.rating)

    keyboard = [
        [InlineKeyboardButton(user_name, callback_data="noop")],
        [InlineKeyboardButton(stars, callback_data="noop")],
        # این دو دکمه جدید:
        [InlineKeyboardButton("📑 Meine Aufträge",    callback_data="show_orders")],
        [InlineKeyboardButton("💬 Meine Vorschläge", callback_data="show_proposals")],
        [InlineKeyboardButton("📥 Eingegangene Vorschläge", callback_data="show_received")],
        # دکمه‌ی خروج
        [InlineKeyboardButton("🚪 Abmelden", callback_data="logout")],
    ]
    await update.message.reply_text(
        "👤 Dein Profil:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


@auth_required
async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    keyboard = [
        [InlineKeyboardButton("Profil bearbeiten",   callback_data="edit_profile")],
        [InlineKeyboardButton("Sprache ändern",      callback_data="change_language")],
        [InlineKeyboardButton("Sicherheit",          callback_data="security_settings")],
        [InlineKeyboardButton("🏠 Zurück zum Menü", callback_data="back_to_main")],
    ]
    await update.callback_query.message.reply_text(
        "🔧 Einstellungen:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


@auth_required
async def back_to_main_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "Bitte wählen Sie eine Option:",
        reply_markup=main_menu_keyboard()
    )

# --- فانکشن خروج (Logout) ---
@auth_required
async def logout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("🚪 Du wurdest abgemeldet.")
    # پاک کردن تمام اطلاعات نشست کاربر
    context.user_data.clear()
    # نمایش کیبورد ورود/ثبت‌نام مجدد
    await update.callback_query.message.reply_text(
        "Du bist jetzt abgemeldet.",
        reply_markup=auth_menu_keyboard()
    )

async def list_orders_for_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    qs = Order.objects
    if not user.is_superuser:
        qs = qs.filter(
            Q(assigned_admin__isnull=True) | Q(assigned_admin__telegram_id=user.id)
        )
    orders = await sync_to_async(list)(qs.order_by('created_at')[:10])
    # Build message with acquire links
    lines = []
    for o in orders:
        text = f"ID {o.id} - {'Buy' if o.is_buy else 'Sell'} {o.amount_crypto} {o.currency.symbol}"
        url = f"https://your-admin-url/core/order/{o.id}/change/"
        lines.append(f"[{text}]({url})")
    await update.message.reply_text("\n".join(lines), parse_mode='Markdown')    

@auth_required
async def resend_proposal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    # اینجا منطق ارسال مجدد پیشنهاد رو پیاده کنید...
    await update.callback_query.message.reply_text(
        "🔁 Vorschlag wird erneut gesendet…",
        reply_markup=main_menu_keyboard()
    )

@auth_required
async def cancel_proposal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    order_id = context.user_data['propose_order_id']

    # ۱) علامت‌گذاری در دیتابیس
    prompt = await sync_to_async(
        ChatPrompt.objects.filter(order_id=order_id, from_user__telegram_id=update.effective_user.id)
                          .order_by('-created_at')
                          .first
    )()
    if prompt:
        prompt.status = 'cancelled_by_user'
        await sync_to_async(prompt.save)()

    # ۲) ویرایش پیام در ربات دوم
    order = await sync_to_async(Order.objects.get)(id=order_id)
    bot2 = Bot(token=TOKEN2)
    new_text = order.build_bot2_text().replace("🔸", "❌")
    deep_link = f"https://t.me/{BOT1_USERNAME}?start=propose_{order.id}"
    new_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔘 Vorschlag senden", url=deep_link)]])
    await bot2.edit_message_text(
        chat_id=BOT2_CHAT_ID,
        message_id=order.bot2_message_id,
        text=new_text,
        parse_mode='Markdown',
        reply_markup=new_markup
    )

    # ۳) اطلاع‌رسانی به ادمین
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"🛑 Nutzer {update.effective_user.id} hat seinen Vorschlag für Auftrag #{order.id:04d} zurückgezogen."
    )

    # ۴) تأیید به کاربر
    invoice_mid = context.user_data.get('invoice_mid')
    if invoice_mid:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=invoice_mid,
            text="❌ Dein Vorschlag wurde abgebrochen.",
            reply_markup=main_menu_keyboard()
        )
    else:
        await update.message.reply_text(
            "❌ Dein Vorschlag wurde abgebrochen.",
            reply_markup=main_menu_keyboard()
        )
        context.user_data.clear()
        await start(update, context)

    return ConversationHandler.END    



# 1. تعریف ConversationHandler اصلی (conv)

conv = ConversationHandler(
    entry_points=[
        CommandHandler("start", start),
        MessageHandler(filters.Regex("^Kaufauftrag erstellen$"), start_buy_order),
        MessageHandler(filters.Regex("^Verkaufsauftrag erstellen$"), start_sell_order),
        MessageHandler(filters.Regex("^Verkäufer anzeigen$|^Käufer anzeigen$"), start_show_listings),
    ],
    states={
        SELECT_CURRENCY:      [MessageHandler(filters.TEXT & ~filters.COMMAND, select_currency)],
        SELECT_COUNTRY:       [MessageHandler(filters.TEXT & ~filters.COMMAND, select_country)],
        SELECT_PAYMENT:       [MessageHandler(filters.TEXT & ~filters.COMMAND, select_payment)],
        ENTER_AMOUNT:         [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_amount)],
        ENTER_PRICE:          [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_price)],
        ENTER_DESC:           [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_desc)],
        CONFIRM_ORDER:        [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_order)],
        PROPOSE_MESSAGE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_proposal)],
        PROPOSE_AMOUNT:       [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_propose_amount)],
        PROPOSE_PRICE:        [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_propose_price)],
        SHOW_SELECT_CURRENCY: [MessageHandler(filters.TEXT & ~filters.COMMAND, show_select_currency)],
        SHOW_SELECT_PAYMENT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, show_select_payment)],
        SHOW_ENTER_CITY:      [MessageHandler(filters.TEXT & ~filters.COMMAND, show_enter_city)],
    },
    fallbacks=[CommandHandler("start", start)],
)

# 2. نقطهٔ شروع اصلی
if __name__ == '__main__':
    if not token:
        logger.error('TELEGRAM_TOKEN1 not set!')
        sys.exit(1)

    app = ApplicationBuilder().token(token).build()

    # ✅ ابتدا handlers اصلی
    register_auth_handlers(app)
    register_order_management_handlers(app)
    register_proposals_handlers(app)

    # ✅ سپس ConversationHandler را قبل از سایر handlers اضافه کن
    app.add_handler(conv)

    # ✅ سپس سایر handlers
    app.add_handler(CommandHandler('get_next', lambda u, c: c.bot.send_message(
        chat_id=u.effective_user.id,
        text='/acquire via admin panel'
    )))

    app.add_handler(CallbackQueryHandler(accept_terms_callback, pattern="^accept_terms$"))
    app.add_handler(CallbackQueryHandler(reject_terms_callback, pattern="^reject_terms$"))
    app.add_handler(CallbackQueryHandler(owner_confirm_callback, pattern=r"^owner_confirm_(\d+)_([\d\.]+)_([\d\.]+)$"))
    app.add_handler(CallbackQueryHandler(show_user_orders, pattern="^show_orders$"))
    app.add_handler(CallbackQueryHandler(show_my_proposals, pattern="^show_proposals$"))
    app.add_handler(CallbackQueryHandler(myprop_action_callback, pattern=r"^myprop_\d+$"))
    app.add_handler(CallbackQueryHandler(cancel_proposal_callback, pattern="^cancel_proposal$"))
    app.add_handler(CallbackQueryHandler(prop_keep_callback, pattern="^prop_keep$"))
    app.add_handler(MessageHandler(filters.Regex("^Benutzereinstellungen$"), show_profile_menu))
    app.add_handler(CallbackQueryHandler(back_to_main_callback, pattern="^back_to_main$"))
    app.add_handler(CallbackQueryHandler(owner_reject_price_callback, pattern=r"^owner_reject_price_\d+$"))
    app.add_handler(CallbackQueryHandler(owner_reject_amount_callback, pattern=r"^owner_reject_amount_\d+$"))
    app.add_handler(CallbackQueryHandler(owner_reject_both_callback, pattern=r"^owner_reject_both_\d+$"))
    app.add_handler(CallbackQueryHandler(owner_reject_callback, pattern=r"^owner_reject_\d+$"))
    app.add_handler(CallbackQueryHandler(noop_callback, pattern="^noop$"))
    app.add_handler(CallbackQueryHandler(settings_callback, pattern="^settings$"))
    app.add_handler(CallbackQueryHandler(logout_callback, pattern="^logout$"))
    app.add_handler(CallbackQueryHandler(rating_callback, pattern=r"^rate_"))

    # ✅ handler مستقل für Kryptopreise abrufen
    app.add_handler(MessageHandler(filters.Regex("^Kryptopreise abrufen$"), fetch_prices))

    # ✅ هندلر برای گروه بحث و گفتگو
    app.add_handler(MessageHandler(filters.Regex("^Diskussionsgruppe$"), discussion_group))

    # ✅ دستورات profile و settings
    app.add_handler(CommandHandler("profile", show_profile_menu))
    app.add_handler(CommandHandler("settings", settings_callback))
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(CommandHandler('orders', list_orders_for_admin))

    # ✅ دکمه‌های extra menu
    app.add_handler(CallbackQueryHandler(resend_proposal_callback, pattern="^resend_proposal$"))
    app.add_handler(CallbackQueryHandler(cancel_proposal_callback, pattern="^cancel_proposal$"))

    logger.info("Bot1 is polling...")
    app.run_polling()