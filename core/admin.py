# Telegram Bot Source Code

##admin.py
import os
import sys
from dotenv import load_dotenv
import logging
import requests
from datetime import timedelta
from django.contrib.admin import SimpleListFilter
import django
from asgiref.sync import sync_to_async
from core.models import Order
from core.utils import format_stars
from core.tasks import update_bot2_ad
from django.db.models import Avg
from telegram.ext import MessageHandler, filters, CallbackQueryHandler
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
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

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

class AssignedFilter(SimpleListFilter):
    title = 'Assigned'
    parameter_name = 'assigned'

    def lookups(self, request, model_admin):
        return (
            ('me', 'My Orders'),
            ('free', 'Unassigned'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'me':
            return queryset.filter(assigned_admin=request.user)
        if self.value() == 'free':
            return queryset.filter(assigned_admin__isnull=True)
        return queryset

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

from django.contrib import admin, messages
from django.utils import timezone
from django.db.models import Q
from django.urls import path, reverse
from django.shortcuts import redirect

from django.shortcuts import render, redirect, get_object_or_404
from django import forms
from django.conf import settings
from django.utils.html import format_html  # ← اضافه شد
import requests

from core.models import Order, User, Currency, Country, ChatPrompt, Feedback
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserCreationForm, UserChangeForm

class CoreUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ('telegram_id', 'username', 'email', 'country_code')


class CoreUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = ('telegram_id', 'username', 'email', 'country_code',
                  'first_name', 'last_name', 'phone',
                  'is_active', 'is_blocked', 'is_staff', 'is_admin', 'is_superuser',
                  'groups', 'user_permissions')

@admin.register(User)
class CoreUserAdmin(BaseUserAdmin):
    form = CoreUserChangeForm
    add_form = CoreUserCreationForm

    model = User
    ordering = ('telegram_id',)
    list_display = ('telegram_id', 'username', 'email', 'country_code', 'rating', 'is_blocked')
    list_filter = ('country_code', 'is_blocked', 'is_staff', 'is_superuser')
    search_fields = ('telegram_id', 'username', 'email')

    fieldsets = (
        (None,               {'fields': ('telegram_id', 'password')}),
        ('Persönliche Daten', {'fields': ('username', 'email', 'country_code', 'first_name', 'last_name', 'phone')}),
        ('Berechtigungen',    {'fields': ('is_active', 'is_blocked', 'is_staff', 'is_admin', 'is_superuser',
                                          'groups', 'user_permissions')}),
        ('Wichtige Daten',    {'fields': ('date_joined',)}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('telegram_id', 'username', 'email', 'country_code', 'password1', 'password2'),
        }),
    )
    readonly_fields = ('date_joined',)

# فرم ساده برای ارسال پیام
class SendMessageForm(forms.Form):
    message = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 4, 'cols': 40}),
        label="Message to send"
    )


def send_message_button(obj, view_name):
    url = reverse(f'admin:core_order_{view_name}', args=[obj.pk])
    return format_html('<a class="button" href="{}">Send Message</a>', url)


# Helper برای ساخت لینک deep‑link تلگرام
def make_telegram_link(username, telegram_id):
    if username:
        url  = f"https://t.me/{username}"
        text = f"@{username}"
    else:
        url  = f"tg://user?id={telegram_id}"
        text = str(telegram_id)
    return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', url, text)



class CompletedFilter(admin.SimpleListFilter):
    title = 'Status'
    parameter_name = 'completed'

    def lookups(self, request, model_admin):
        return (
            ('1', 'Completed'),
            ('0', 'Pending'),
        )

    def queryset(self, request, queryset):
        if self.value() == '1':
            return queryset.filter(is_completed=True)
        if self.value() == '0':
            return queryset.filter(is_completed=False)
        return queryset


@admin.action(description='Mark selected orders as completed')
def mark_as_completed(modeladmin, request, queryset):
    queryset.update(is_completed=True)


@admin.action(description='Delete selected orders')
def delete_orders(modeladmin, request, queryset):
    queryset.delete()


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'user', 'currency', 'status', 'amount_crypto',
        'price_per_unit', 'net_total',
        'buyer_link', 'seller_link',
        'send_message_btn', 'status_display', 'created_at'
    )
    list_select_related = ('user', 'currency')
    list_filter        = (CompletedFilter, 'currency', 'status', 'created_at')
    search_fields      = ('id', 'user__telegram_id', 'prompts__from_user__telegram_id')
    readonly_fields    = ('id', 'created_at', 'expires_at')
    actions            = ()

    def save_model(self, request, obj, form, change):
        # نگه‌داشتن وضعیت قبلی برای مقایسه
        previous_status = None
        if change:
            previous_status = Order.objects.get(pk=obj.pk).status

        # ابتدا ذخیره‌ی اصلی را انجام بده
        super().save_model(request, obj, form, change)

        # اگر تغییر وضعیت به "matched" باشه
        if previous_status != 'matched' and obj.status == 'matched':
            update_bot2_ad.delay(obj.id)

        # اگر بازگشت به "pending" رخ داده
        if previous_status != 'pending' and obj.status == 'pending':
            update_bot2_ad.delay(obj.id)

        # اگر به "canceled" (با یک l) تغییر کرده
        if previous_status != 'canceled' and obj.status == 'canceled':
            update_bot2_ad.delay(obj.id)

        # اگر به "completed" تغییر کرده
        if previous_status != 'completed' and obj.status == 'completed':
            update_bot2_ad.delay(obj.id)

    @admin.display(description='Chat Buyer')
    def buyer_link(self, obj):
        prompt = obj.prompts.order_by('-created_at').first()
        if not prompt:
            return '—'
        user = prompt.from_user
        return make_telegram_link(getattr(user, 'username', None), user.telegram_id)

    @admin.display(description='Chat Seller')
    def seller_link(self, obj):
        user = obj.user
        return make_telegram_link(getattr(user, 'username', None), user.telegram_id)

    @admin.display(description='Send Message')
    def send_message_btn(self, obj):
        return send_message_button(obj, 'send_message')

    @admin.display(description='Status')
    def status_display(self, obj):
        return '✅ Completed' if obj.is_completed else '⌛ Pending'

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                '<int:order_id>/send_message/',
                self.admin_site.admin_view(self.send_message_view),
                name='core_order_send_message',
            ),
        ]
        return custom + urls

    def send_message_view(self, request, order_id, *args, **kwargs):
        order = get_object_or_404(Order, pk=order_id)
        user = order.prompts.order_by('-created_at').first().from_user if order.prompts.exists() else None
        if not user:
            self.message_user(request, "No target user to send message.", level=messages.ERROR)
            return redirect('..')

        if request.method == 'POST':
            form = SendMessageForm(request.POST)
            if form.is_valid():
                token   = settings.TELEGRAM_BOT_TOKEN
                chat_id = user.telegram_id
                text    = form.cleaned_data['message']
                resp = requests.post(
                    f'https://api.telegram.org/bot{token}/sendMessage',
                    data={'chat_id': chat_id, 'text': text}
                )
                if resp.ok:
                    self.message_user(request, "Message sent successfully.", level=messages.SUCCESS)
                else:
                    self.message_user(request, f"Error sending message: {resp.text}", level=messages.ERROR)
                return redirect('..')
        else:
            form = SendMessageForm()

        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'form': form,
            'order': order,
        }
        return render(request, 'admin/send_message.html', context)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(
            Q(assigned_admin__isnull=True) | Q(assigned_admin=request.user)
        )

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                '<int:order_id>/acquire/',
                self.admin_site.admin_view(self.acquire_view),
                name='core_order_acquire',
            ),
        ]
        return custom + urls

    def acquire_view(self, request, order_id):
        # atomic select_for_update to avoid race
        from django.db import transaction
        with transaction.atomic():
            order = Order.objects.select_for_update(skip_locked=True).get(pk=order_id)
            if order.assigned_admin and order.assigned_admin != request.user:
                self.message_user(request, "This order is already taken.", level=messages.ERROR)
            else:
                order.assigned_admin = request.user
                order.lock_acquired_at = timezone.now()
                order.save(update_fields=['assigned_admin', 'lock_acquired_at'])
                self.message_user(request, "Order assigned to you.", level=messages.SUCCESS)
        return redirect(request.META.get('HTTP_REFERER', '..'))

    @admin.display(description='Send Message')
    def send_message_btn(self, obj):
        return send_message_button(obj, 'send_message')

    @admin.display(description='Chat Buyer')
    def buyer_link(self, obj):
        prompt = obj.prompts.order_by('-created_at').first()
        if not prompt:
            return '—'
        user = prompt.from_user
        return make_telegram_link(getattr(user, 'username', None), user.telegram_id)

    @admin.display(description='Chat Seller')
    def seller_link(self, obj):
        user = obj.user
        return make_telegram_link(getattr(user, 'username', None), user.telegram_id)

    @admin.display(description='Status')
    def status_display(self, obj):
        return '✅ Completed' if obj.is_completed else '⌛ Pending'

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                '<int:order_id>/send_message/',
                self.admin_site.admin_view(self.send_message_view),
                name='core_order_send_message',
            ),
        ]
        return custom + urls

    def send_message_view(self, request, order_id, *args, **kwargs):
        order = get_object_or_404(Order, pk=order_id)
        user = order.prompts.order_by('-created_at').first().from_user if order.prompts.exists() else None
        if not user:
            self.message_user(request, "No target user to send message.", level=messages.ERROR)
            return redirect('..')

        if request.method == 'POST':
            form = SendMessageForm(request.POST)
            if form.is_valid():
                token = settings.TELEGRAM_BOT_TOKEN
                chat_id = user.telegram_id
                text = form.cleaned_data['message']
                resp = requests.post(
                    f'https://api.telegram.org/bot{token}/sendMessage',
                    data={'chat_id': chat_id, 'text': text}
                )
                if resp.ok:
                    self.message_user(request, "Message sent successfully.", level=messages.SUCCESS)
                else:
                    self.message_user(request, f"Error sending message: {resp.text}", level=messages.ERROR)
                return redirect('..')
        else:
            form = SendMessageForm()

        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'form': form,
            'order': order,
        }
        return render(request, 'admin/send_message.html', context)


admin.site.register(Currency)
admin.site.register(Country)
admin.site.register(Feedback)