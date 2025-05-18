# core/views.py

from django.db import transaction
from django.shortcuts import redirect
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from .models import Order
from django.shortcuts import render

@login_required
def acquire_next_order(request):
    with transaction.atomic():
        order = (
            Order.objects
            .select_for_update(skip_locked=True)
            .filter(assigned_admin__isnull=True, expires_at__gt=timezone.now())
            .earliest('created_at')
        )
        order.assigned_admin   = request.user
        order.lock_acquired_at = timezone.now()
        order.save(update_fields=['assigned_admin', 'lock_acquired_at'])
    return redirect('admin:core_order_change', order.id)

def page_not_found(request, exception):
    """
    Custom 404 handler.
    Renders the templates/404.html with status 404.
    """
    return render(request, '404.html', status=404)

def server_error(request):
    """
    Custom 500 handler.
    Renders the templates/500.html with status 500.
    """
    return render(request, '500.html', status=500)
