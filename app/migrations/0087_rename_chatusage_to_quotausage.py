"""ChatUsage sert à tous les services à quota (chat, étiquette, code-barres, photo) : le modèle prend un nom qui le dit."""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0086_integrity_achievement_slugs_and_indexes'),
    ]

    operations = [
        migrations.RenameModel(old_name='ChatUsage', new_name='QuotaUsage'),
        migrations.AlterModelOptions(
            name='quotausage',
            options={'verbose_name': "Utilisation d'un service à quota", 'verbose_name_plural': 'Utilisations des services à quota'},
        ),
        migrations.AlterField(
            model_name='quotausage',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='quota_usages', to=settings.AUTH_USER_MODEL),
        ),
    ]
