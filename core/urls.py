# core/urls.py

from django.contrib import admin
from django.urls import path
from django.http import HttpResponse
from django.conf import settings
from django.conf.urls.static import static

def home(request):
    return HttpResponse("<h1>Welcome to Crypto Market!</h1>")

# تعریف urlpatterns اصلی
urlpatterns = [
    path('', home, name='home'),
    path('admin/', admin.site.urls),
]

# فقط در حالت DEBUG، استاتیک را سرو کن
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
