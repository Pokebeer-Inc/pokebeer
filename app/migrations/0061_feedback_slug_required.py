from django.db import migrations

import app.fields


class Migration(migrations.Migration):
    """Le slug est rempli pour tous les feedbacks (0060) : on le rend obligatoire ; la réponse unique de l'équipe est
    désormais un message de l'échange (0060), son ancienne colonne disparaît."""

    dependencies = [
        ('app', '0060_backfill_feedback_conversations'),
    ]

    operations = [
        migrations.AlterField(model_name='feedback', name='slug', field=app.fields.PublicSlugField()),
        migrations.RemoveField(model_name='feedback', name='admin_reply'),
    ]
