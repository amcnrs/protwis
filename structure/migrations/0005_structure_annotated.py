# -*- coding: utf-8 -*-
# Generated by Django 1.11 on 2017-06-07 12:17
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('structure', '0004_auto_20170529_1307'),
    ]

    operations = [
        migrations.AddField(
            model_name='structure',
            name='annotated',
            field=models.BooleanField(default=True),
        ),
    ]
