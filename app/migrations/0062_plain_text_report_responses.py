import html
import re

from django.db import migrations
from django.utils.html import strip_tags


def strip_markup(apps, schema_editor):
    """Les décisions de l'équipe étaient saisies avec un éditeur riche (balises <div>, <p>…) : on ne garde que le texte."""
    Report = apps.get_model('app', 'Report')
    for report in Report.objects.exclude(admin_response__isnull=True).exclude(admin_response=''):
        text = re.sub(r'<\s*br\s*/?>|</\s*(?:p|div|li|h[1-6]|tr)\s*>', '\n', report.admin_response, flags=re.IGNORECASE)
        lines = [' '.join(line.split()) for line in html.unescape(strip_tags(text)).splitlines()]
        cleaned = re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()
        if cleaned != report.admin_response:
            Report.objects.filter(pk=report.pk).update(admin_response=cleaned)


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0061_feedback_slug_required'),
    ]

    operations = [
        migrations.RunPython(strip_markup, migrations.RunPython.noop),
    ]
