# core/auth.py

import logging
from datetime import timedelta
from random import randint
from functools import wraps
import os
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from django.conf import settings

from asgiref.sync import sync_to_async
from django.utils import timezone
from telegram import ReplyKeyboardRemove, Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

from core.models import Country, User
from core.utils import auth_menu_keyboard
from core.menu import main_menu_keyboard  # اضافه شده برای منوی اصلی

logger = logging.getLogger(__name__)

# وضعیت‌های گفتگو
(
    REG_NAME,
    REG_SURNAME,
    REG_PHONE,
    REG_EMAIL_ENTER,
    REG_EMAIL_OTP,
    REG_COUNTRY,
    LOGIN_EMAIL,
    LOGIN_OTP,
) = range(20, 28)

def generate_otp() -> str:
    return str(randint(100000, 999999))

def send_email(recipient: str, subject: str, text: str):
    """
    ارسال ایمیل OTP با استفاده از Sendinblue Transactional API.
    """
    logger.info(f"[DEBUG] send_email() using FROM = {settings.DEFAULT_FROM_EMAIL}")

    # ۱) تنظیم کلید
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = os.getenv("SENDINBLUE_API_KEY")

    # ۲) ساخت client
    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
        sib_api_v3_sdk.ApiClient(configuration)
    )

    # ۳) آماده‌سازی payload
    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        sender      = {"email": settings.DEFAULT_FROM_EMAIL},
        to          = [{"email": recipient}],
        subject     = subject,
        text_content= text
    )

    # ۴) ارسال
    try:
        response = api_instance.send_transac_email(send_smtp_email)
        # اگر نام صفتش message_id باشه:
        message_id = getattr(response, 'message_id', None) or getattr(response, 'messageId', None)
        logger.info(f"OTP email sent to {recipient}, messageId={message_id}")
    except ApiException as e:
        logger.error(f"Error sending OTP email via Sendinblue: {e}")
        # در صورت لازم می‌تونی خطا رو پرتاب کنی تا flow ثبت‌نام متوقف شه
        # raise

async def start_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # اگر کاربر قبلاً وارد شده، مستقیماً منوی اصلی را نمایش بده
    tg_id = update.effective_user.id
    is_verified = await sync_to_async(
        lambda uid: User.objects.filter(telegram_id=uid, is_verified=True).exists()
    )(tg_id)
    if is_verified:
        await update.message.reply_text(
            "Bitte wählen Sie eine Option:",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    # در غیر این صورت منوی احراز هویت
    await update.message.reply_text(
        "👋 Willkommen! Bitte anmelden (Anmelden) oder einloggen (Einloggen)",
        reply_markup=auth_menu_keyboard(),
    )
    return ConversationHandler.END

# ————————————— ثبت‌نام —————————————

async def start_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "Bitte gib deinen Vornamen ein:",
        reply_markup=ReplyKeyboardRemove()
    )
    return REG_NAME

async def reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['first_name'] = update.message.text.strip()
    await update.message.reply_text("Bitte gib deinen Nachnamen ein:")
    return REG_SURNAME

async def reg_surname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['last_name'] = update.message.text.strip()
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("📱 Telefonnummer senden", request_contact=True)]],
        resize_keyboard=True
    )
    await update.message.reply_text(
        "Bitte sende deine Telefonnummer **ausschließlich** über den Button 📱",
        reply_markup=kb
    )
    return REG_PHONE

async def reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.contact.phone_number
    context.user_data['phone'] = phone
    await update.message.reply_text(
        "✅ Telefonnummer erhalten.",
        reply_markup=ReplyKeyboardRemove()
    )
    await update.message.reply_text("Bitte gib deine E-Mail-Adresse ein:")
    return REG_EMAIL_ENTER  

async def reg_phone_invalid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ Bitte benutze nur den 📱-Button, um deine Telefonnummer zu senden."
    )
    return REG_PHONE

async def reg_email_enter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()

    # ۱) چک ایمیل تکراری
    is_used = await sync_to_async(
        lambda e, uid: User.objects.filter(email=e)
                                   .exclude(telegram_id=uid)
                                   .exists()
    )(email, update.effective_user.id)

    if is_used:
        # ایمیل تکراری: نمایش خطا و گزینه‌های شروع دوباره
        await update.message.reply_text(
            "❌ Diese E-Mail-Adresse wird bereits verwendet. Registrierung abgebrochen.\n\n"
            "Bitte wähle eine Option, um neu zu starten:",
            reply_markup=auth_menu_keyboard()
        )
        return ConversationHandler.END

    # اگر ایمیل آزاد بود، ادامه روند ثبت‌نام
    context.user_data['email'] = email

    code = generate_otp()
    context.user_data['otp'] = code
    context.user_data['otp_expires'] = timezone.now() + timedelta(minutes=2)

    # ارسال ایمیل ثبت‌نام
    send_email(email, "Dein Bestätigungscode", f"Dein Bestätigungscode: {code}")

    await update.message.reply_text(
        "Ein Bestätigungscode wurde gesendet. Bitte innerhalb 2 Minuten eingeben."
    )
    return REG_EMAIL_OTP

async def reg_email_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if timezone.now() > context.user_data['otp_expires']:
        await update.message.reply_text("Der Code ist abgelaufen. Bitte /start erneut.")
        return ConversationHandler.END
    if text != context.user_data['otp']:
        await update.message.reply_text("Falscher Code. Bitte erneut eingeben:")
        return REG_EMAIL_OTP

    countries = await sync_to_async(list)(Country.objects.values_list('name', flat=True))
    kb = [countries[i:i+2] for i in range(0, len(countries), 2)]
    await update.message.reply_text(
        "Bitte wähle dein Land oder gib es ein und sende:",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
    )
    return REG_COUNTRY

async def reg_country(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from django.db import IntegrityError
    from core.bot import main_menu_keyboard

    country_name = update.message.text.strip()
    country = await sync_to_async(Country.objects.get)(name=country_name)

    email = context.user_data['email']
    other = await sync_to_async(
        lambda e: User.objects.filter(email=e).exclude(telegram_id=update.effective_user.id).exists()
    )(email)
    if other:
        await update.message.reply_text(
            "❌ Diese E-Mail-Adresse wird bereits verwendet. Registrierung abgebrochen."
        )
        return ConversationHandler.END

    try:
        await sync_to_async(User.objects.update_or_create)(
            telegram_id=update.effective_user.id,
            defaults={
                'email':       email,
                'country_code': country.code,
                'first_name':  context.user_data['first_name'],
                'last_name':   context.user_data['last_name'],
                'phone':       context.user_data['phone'],
                'is_verified': True,
            }
        )
    except IntegrityError:
        await update.message.reply_text(
            "❌ Ein unerwarteter Fehler ist aufgetreten. Bitte später versuchen."
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "✅ Registrierung abgeschlossen und eingeloggt.",
        reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END

# ————————————— لاگین —————————————

async def start_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
    "Bitte gib deine E-Mail-Adresse ein:",
    reply_markup=ReplyKeyboardRemove()
    )
    return LOGIN_EMAIL

async def login_email_enter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    try:
        user = await sync_to_async(User.objects.get)(email=email)
    except User.DoesNotExist:
        await update.message.reply_text("Unbekannte E-Mail. Bitte /start erneut.")
        return ConversationHandler.END

    code = generate_otp()
    context.user_data['otp'] = code
    context.user_data['otp_expires'] = timezone.now() + timedelta(minutes=2)
    # اینجا از telegram_id به‌جای id استفاده می‌کنیم
    context.user_data['login_user_telegram_id'] = user.telegram_id

    # ارسال ایمیل لاگین
    send_email(email, "Dein Login-Code", f"Dein Login-Code: {code}")

    await update.message.reply_text("Ein Login-Code wurde gesendet. Bitte eingeben:")
    return LOGIN_OTP

async def login_email_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from core.bot import main_menu_keyboard

    text = update.message.text.strip()
    if timezone.now() > context.user_data.get('otp_expires', timezone.now()):
        await update.message.reply_text("Der Code ist abgelaufen. Bitte /start erneut.")
        return ConversationHandler.END
    if text != context.user_data.get('otp'):
        await update.message.reply_text("Falscher Code. Bitte erneut eingeben:")
        return LOGIN_OTP

    tg_id = context.user_data.get('login_user_telegram_id')
    # به‌روزرسانی با telegram_id
    await sync_to_async(
        User.objects.filter(telegram_id=tg_id).update
    )(is_verified=True)

    await update.message.reply_text(
        "✅ Erfolgreich eingeloggt.",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END

# ————————————— لاگ‌اوت —————————————

async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await sync_to_async(
        User.objects.filter(telegram_id=update.effective_user.id).update
    )(is_verified=False)
    context.user_data.clear()
    await update.message.reply_text("Ausgeloggt.", reply_markup=auth_menu_keyboard())

async def logout_callback(update, context):
    q = update.callback_query
    # ۱) پاسخ به کال‌بک با پیام لاگ‌اوت
    await q.answer("🚪 Du wurdest abgemeldet.")

    # ۲) ریست کردن وضعیت کاربر
    await sync_to_async(
        User.objects.filter(telegram_id=update.effective_user.id).update
    )(is_verified=False)
    context.user_data.clear()

    # ۳) حذف پیام منوی پروفایل قبلی
    await q.message.delete()

    # ۴) ارسال پیام جدید با کیبورد لاگین/ثبت‌نام
    await context.bot.send_message(
        chat_id=q.from_user.id,
        text="Du bist jetzt abgemeldet.",
        reply_markup=auth_menu_keyboard()
    )

def register_auth_handlers(app):
    conv = ConversationHandler(
        entry_points=[
            # تنها وقتی که کاربر دقیقا "/start" می‌فرستد (بدون args)، منوی auth نشان بده
            CommandHandler("start", start_auth, filters=filters.Regex(r"^/start$")),
            MessageHandler(filters.Regex("^Anmelden$"), start_registration),
            MessageHandler(filters.Regex("^Einloggen$"), start_login),
            MessageHandler(filters.Regex("^🚪 Abmelden$"), logout),  # تغییر متن دکمه
        ],
        states={
            REG_NAME:        [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_name)],
            REG_SURNAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_surname)],
            REG_PHONE: [
                MessageHandler(filters.CONTACT, reg_phone),
                MessageHandler(filters.TEXT & ~filters.COMMAND, reg_phone_invalid)],
            REG_EMAIL_ENTER: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_email_enter)],
            REG_EMAIL_OTP:   [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_email_otp)],
            REG_COUNTRY:     [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_country)],
            LOGIN_EMAIL:     [MessageHandler(filters.TEXT & ~filters.COMMAND, login_email_enter)],
            LOGIN_OTP:       [MessageHandler(filters.TEXT & ~filters.COMMAND, login_email_otp)],
        },
        fallbacks=[CommandHandler("start", start_auth)],
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("logout", logout))
    # کال‌بک دیتای "logout" هم همون می‌مونه چون callback_data تغییر نمی‌کنه
    app.add_handler(CallbackQueryHandler(logout_callback, pattern="^logout$"))

# ————————— دکوراتور احراز هویت —————————

def auth_required(handler):
    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        tg_id = update.effective_user.id
        is_verified = await sync_to_async(
            User.objects.filter(telegram_id=tg_id, is_verified=True).exists
        )()
        if not is_verified:
            return await start_auth(update, context)
        return await handler(update, context, *args, **kwargs)
    return wrapper
