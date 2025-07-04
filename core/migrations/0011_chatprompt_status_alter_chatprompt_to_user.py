# Generated by Django 5.2 on 2025-05-08 15:10

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_remove_order_core_order_currenc_3ed6c4_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatprompt',
            name='status',
            field=models.CharField(choices=[('pending', '⌛ Ausstehend'), ('accepted', '✅ Akzeptiert'), ('rejected', '🚫 Abgelehnt')], default='pending', help_text='Status des Vorschlags', max_length=10),
        ),
        migrations.AlterField(
            model_name='chatprompt',
            name='to_user',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='received_prompts', to=settings.AUTH_USER_MODEL),
        ),
    ]
