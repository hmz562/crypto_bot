# Generated by Django 5.2 on 2025-05-05 15:54

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_user_first_name_user_is_verified_user_last_name_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='chatprompt',
            name='order',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='prompts', to='core.order'),
        ),
    ]
