"""Amorce le référentiel des styles et y ramène les bières existantes (nom officiel, famille).

Idempotente : relancée, elle ne recrée pas les styles existants. Elle lit `domain/style_catalog.py` (données pures) et `domain/styles.py` (règles pures),
sans passer par les modèles : les vecteurs de recherche ne sont pas recalculés ici, `manage.py embed_beers` s'en charge pour les bières dont
le texte a changé."""
from django.db import migrations

from app.domain import style_catalog, styles


def seed_and_normalize(apps, schema_editor):
    Style = apps.get_model('app', 'Style')
    Beer = apps.get_model('app', 'Beer')

    for name, family, aliases in style_catalog.STYLE_CATALOG:
        Style.objects.get_or_create(name=name, defaults={'family': family, 'aliases': '\n'.join(aliases)})

    canonical_by_key, family_by_name = {}, {}
    for style in Style.objects.all():
        family_by_name[style.name] = style.family
        for written in (style.name, *(line.strip() for line in style.aliases.splitlines() if line.strip())):
            canonical_by_key[styles.style_key(written)] = style.name

    changed = []
    for beer in Beer.objects.exclude(style__isnull=True).exclude(style='').only('id', 'style', 'style_family'):
        beer.style = styles.canonicalize(beer.style, canonical_by_key)
        beer.style_family = styles.family_of(beer.style, family_by_name)
        changed.append(beer)
    Beer.objects.bulk_update(changed, ['style', 'style_family'], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [('app', '0093_tracking_styles_and_opt_out')]

    operations = [migrations.RunPython(seed_and_normalize, migrations.RunPython.noop)]
