"""Élargit le référentiel de styles (une centaine, rangés en familles) puis remet à jour les bières existantes.

Idempotente : un style déjà au référentiel garde ses alias et sa famille, un style « à valider » dont le nom est désormais officiel le devient, et les
bières dont le texte correspond à un nouvel alias sont ramenées au style officiel (les styles à valider devenus inutiles sont supprimés)."""
from django.db import migrations

from app.domain import style_catalog, style_structure


def seed_and_rebuild(apps, schema_editor):
    StyleFamily, Style = apps.get_model('app', 'StyleFamily'), apps.get_model('app', 'Style')
    Beer = apps.get_model('app', 'Beer')
    models_ = style_structure.Models(Style, apps.get_model('app', 'BeerStyle'), Beer)

    families = {}
    for position, name in enumerate(style_catalog.FAMILIES):
        families[name] = StyleFamily.objects.get_or_create(name=name, defaults={'position': position})[0]

    for name, family, aliases in style_catalog.STYLE_CATALOG:
        style, created = Style.objects.get_or_create(name=name, defaults={'family': families[family], 'aliases': '\n'.join(aliases), 'is_official': True})
        if not created and not style.is_official:  # saisi par un membre avant d'entrer au référentiel
            style.family, style.aliases, style.is_official = families[family], '\n'.join(aliases), True
            style.save(update_fields=['family', 'aliases', 'is_official'])

    registry = style_structure.Registry(Style.objects.all())
    style_structure.rebuild(Beer.objects.exclude(style__isnull=True).exclude(style=''), models_, registry)
    Style.objects.filter(is_official=False, beer_styles__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [('app', '0099_beer_style_structure')]

    # Marche arrière sans effet : les styles ajoutés restent, ils sont inoffensifs
    operations = [migrations.RunPython(seed_and_rebuild, migrations.RunPython.noop)]
