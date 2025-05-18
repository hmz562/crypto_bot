# config/celery.py

import os
from celery import Celery

# مطمئن می‌شویم Django settings لود شود
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# نام دلخواه برای اپ—but بهتر همانی باشد که در manage.py استفاده شده
app = Celery('crypto_bot')

# خواندن تنظیمات CELERY_… از settings.py
app.config_from_object('django.conf:settings', namespace='CELERY')

# خودکار پیدا کردن taskها در اپ‌های INSTALLED_APPS
app.autodiscover_tasks()
