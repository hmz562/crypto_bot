# models.py

from django.db import models
from django.conf import settings
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
from datetime import timedelta
from django.contrib.auth.models import (
    AbstractBaseUser, BaseUserManager, PermissionsMixin,
    Group, Permission
)
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    def create_user(self, telegram_id, email, country_code, password=None, **extra_fields):
        if not telegram_id:
            raise ValueError('The Telegram ID must be set')
        if not email:
            raise ValueError('The Email must be set')
        email = self.normalize_email(email)
        user = self.model(
            telegram_id=telegram_id,
            email=email,
            country_code=country_code,
            **extra_fields
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, telegram_id, email, country_code, password=None, **extra_fields):
        extra_fields.setdefault('is_admin', True)
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(telegram_id, email, country_code, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    telegram_id   = models.BigIntegerField(primary_key=True)
    username      = models.CharField(max_length=32, blank=True, null=True)
    email         = models.EmailField(unique=True)
    country_code  = models.CharField(max_length=2, blank=True, null=True)
    first_name    = models.CharField(max_length=30, blank=True)
    last_name     = models.CharField(max_length=30, blank=True)
    phone         = models.CharField(max_length=20, blank=True)
    is_verified   = models.BooleanField(default=False)

    is_active     = models.BooleanField(default=True)
    is_staff      = models.BooleanField(default=False)
    is_admin      = models.BooleanField(default=False)
    date_joined   = models.DateTimeField(auto_now_add=True)

    # Block and rating
    is_blocked    = models.BooleanField(default=False, help_text="مسدودسازی کاربر")
    rating        = models.DecimalField(
        max_digits=2,
        decimal_places=1,
        default=5.0,
        help_text="امتیاز کاربر از 0.0 تا 5.0 (نیم‌ستاره مجاز)"
    )

    # Override groups and permissions
    groups = models.ManyToManyField(
        Group,
        verbose_name=_('groups'),
        blank=True,
        help_text=_('The groups this user belongs to.'),
        related_name='core_user_groups',
        related_query_name='core_user_group'
    )
    user_permissions = models.ManyToManyField(
        Permission,
        verbose_name=_('user permissions'),
        blank=True,
        help_text=_('Specific permissions for this user.'),
        related_name='core_user_user_permissions',
        related_query_name='core_user_permission'
    )

    objects = UserManager()

    USERNAME_FIELD  = 'telegram_id'
    REQUIRED_FIELDS = ['email', 'country_code']

    def __str__(self):
        return f"User {self.telegram_id}"


class UserSettings(models.Model):
    user          = models.OneToOneField(User, on_delete=models.CASCADE)
    notify_method = models.CharField(max_length=20, default='telegram')
    language      = models.CharField(max_length=5, default='de')
    updated_at    = models.DateTimeField(auto_now=True)
    accepted_terms = models.BooleanField(default=False)
    
    def __str__(self):
        return f"Settings for {self.user}"


class Currency(models.Model):
    symbol = models.CharField(max_length=10, unique=True)
    name   = models.CharField(max_length=50)

    def __str__(self):
        return self.symbol


class Country(models.Model):
    code = models.CharField(max_length=2, primary_key=True)
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name

class Order(models.Model):
    user = models.ForeignKey(
         settings.AUTH_USER_MODEL,
         on_delete=models.CASCADE,
         related_name='orders'
    )

    currency        = models.ForeignKey(Currency, on_delete=models.PROTECT)
    BUY, SELL       = True, False
    TYPE_CHOICES    = [(BUY, 'Buy'), (SELL, 'Sell')]
    STATUS_CHOICES  = [
        ('pending',   'Pending'),
        ('matched',   'Matched'),
        ('completed', 'Completed'),
        ('canceled',  'Canceled'),
    ]

    is_buy          = models.BooleanField(choices=TYPE_CHOICES)
    country         = models.ForeignKey(Country, on_delete=models.PROTECT)
    fiat_method     = models.CharField(max_length=20)
    amount_crypto   = models.DecimalField(max_digits=20, decimal_places=8)
    price_per_unit  = models.DecimalField(max_digits=20, decimal_places=8)
    fee_total       = models.DecimalField(max_digits=20, decimal_places=8)
    net_total       = models.DecimalField(max_digits=20, decimal_places=8)

    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    is_completed    = models.BooleanField(default=False)

    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)
    expires_at      = models.DateTimeField()
    bot2_message_id = models.IntegerField(null=True, blank=True)

    assigned_admin  = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        limit_choices_to={'is_staff': True},
        related_name='assigned_orders',
        help_text="Admin currently handling this order"
    )
    lock_acquired_at= models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the order was reserved"
    )
    class Meta:
        indexes = [
            models.Index(fields=[
                'currency', 'is_buy', 'status',
                'assigned_admin', 'lock_acquired_at', 'expires_at'
            ]),
        ]

    def is_locked(self, timeout_minutes=15):
        if not self.assigned_admin or not self.lock_acquired_at:
            return False
        return timezone.now() - self.lock_acquired_at < timedelta(minutes=timeout_minutes)

    def __str__(self):
        typ = 'Buy' if self.is_buy else 'Sell'
        return f"Order {self.id} - {typ} {self.amount_crypto} {self.currency}"


class Order(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='orders'
    )
    currency        = models.ForeignKey(Currency, on_delete=models.PROTECT)
    BUY, SELL       = True, False
    TYPE_CHOICES    = [(BUY, 'Buy'), (SELL, 'Sell')]
    STATUS_CHOICES  = [
        ('pending',   'Pending'),
        ('matched',   'Matched'),
        ('completed', 'Completed'),
        ('canceled',  'Canceled'),
    ]

    is_buy          = models.BooleanField(choices=TYPE_CHOICES)
    country         = models.ForeignKey(Country, on_delete=models.PROTECT)
    fiat_method     = models.CharField(max_length=20)
    amount_crypto   = models.DecimalField(max_digits=20, decimal_places=8)
    price_per_unit  = models.DecimalField(max_digits=20, decimal_places=8)
    fee_total       = models.DecimalField(max_digits=20, decimal_places=8)
    net_total       = models.DecimalField(max_digits=20, decimal_places=8)

    status         = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    is_completed   = models.BooleanField(default=False)

    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)
    expires_at     = models.DateTimeField()
    bot2_message_id = models.IntegerField(null=True, blank=True)

    assigned_admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        limit_choices_to={'is_staff': True},
        related_name='assigned_orders',
        help_text="Admin currently handling this order"
    )
    lock_acquired_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the order was reserved"
    )
    class Meta:
        indexes = [
            models.Index(fields=[
                'currency', 'is_buy', 'status',
                'assigned_admin', 'lock_acquired_at', 'expires_at'
            ]),
        ]

    def is_locked(self, timeout_minutes=15):
        if not self.assigned_admin or not self.lock_acquired_at:
            return False
        return timezone.now() - self.lock_acquired_at < timedelta(minutes=timeout_minutes)

    def __str__(self):
        typ = 'Buy' if self.is_buy else 'Sell'
        return f"Order {self.id} - {typ} {self.amount_crypto} {self.currency}"


class ChatPrompt(models.Model):
    order      = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name='prompts'
    )
    from_user  = models.ForeignKey(
        User, related_name='sent_prompts', on_delete=models.CASCADE
    )
    to_user    = models.ForeignKey(
        User, related_name='received_prompts', on_delete=models.CASCADE, null=True
    )
    content    = models.TextField()
    status     = models.CharField(
        max_length=10,
        choices=[
            ('pending',  '⌛ Ausstehend'),
            ('accepted', '✅ Akzeptiert'),
            ('rejected', '🚫 Abgelehnt'),
        ],
        default='pending',
        help_text="Status des Vorschlags"
    )
    is_private = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


@receiver(post_save, sender=Order)

def on_order_changed(sender, instance, created, **kwargs):
    if not created and instance.status == 'matched':
        from core.tasks import update_bot2_ad
        update_bot2_ad.delay(instance.id)



class Proposal(models.Model):
    order        = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='proposals')
    proposer_id  = models.CharField(max_length=50)
    accepted     = models.BooleanField(null=True)
    message      = models.TextField(blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Proposal for Order #{self.order.id} by {self.proposer_id}"


class OrderMatch(models.Model):
    buy_order      = models.ForeignKey(
        Order, related_name='buy_matches', on_delete=models.CASCADE
    )
    sell_order     = models.ForeignKey(
        Order, related_name='sell_matches', on_delete=models.CASCADE
    )
    matched_at     = models.DateTimeField(auto_now_add=True)
    admin_notified = models.BooleanField(default=False)

    def __str__(self):
        return f"Match {self.id}: {self.buy_order.id} ⇄ {self.sell_order.id}"


class OrderReminder(models.Model):
    order       = models.ForeignKey(Order, on_delete=models.CASCADE)
    reminded_at = models.DateTimeField()
    next_remind = models.DateTimeField()

    class Meta:
        indexes = [models.Index(fields=['next_remind'])]


class Feedback(models.Model):
    order      = models.ForeignKey(Order, on_delete=models.CASCADE)
    from_user  = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='given_feedbacks',
        on_delete=models.CASCADE
    )
    to_user    = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='received_feedbacks',
        on_delete=models.CASCADE
    )
    rating = models.FloatField(
        default=0.0,
        help_text="امتیاز کاربر از 0 تا 5 (قابل نیم‌ستاره)"
    )
    comment    = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Feedback {self.rating} for {self.to_user} (Order {self.order.id})"


@receiver(post_save, sender=Order)
def on_order_changed(sender, instance: Order, created, **kwargs):
    # وقتی وضعیت تغییر کرد
    if not created and instance.status == 'matched':
        from core.tasks import update_bot2_ad
        # شِدول کنید در پس‌زمینه
        update_bot2_ad.delay(instance.id)