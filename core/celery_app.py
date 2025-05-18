# celery_app.py

import os
from celery import Celery

# تنظیم متغیر محیطی جنگو
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('crypto_bot')

# بارگذاری تنظیمات CELERY_*
app.config_from_object('django.conf:settings', namespace='CELERY')

# پیدا کردن و لود خودکار tasks در اپ‌ها
app.autodiscover_tasks()
