from django.db import migrations

from app.services.slugs import generate_slug

BATCH_SIZE = 500

# Modèle -> champ servant de libellé lisible (None : jeton opaque)
SLUGGED_MODELS = {
    'Beer': 'name',
    'Brewery': 'name',
    'Bar': 'name',
    'Drinks': None,
    'BeerSpot': None,
    'Report': None,
    'Notification': None,
    'CustomNotebook': None,
}


def regenerate_slugs(apps, schema_editor):
    """Donne un nouveau slug public à chaque ligne existante, y compris aux bières (anciens slugs devinables)."""
    for model_name, source in SLUGGED_MODELS.items():
        model = apps.get_model('app', model_name)
        max_length = model._meta.get_field('slug').max_length
        pending = []
        for obj in model.objects.all().iterator(chunk_size=BATCH_SIZE):
            obj.slug = generate_slug(getattr(obj, source) if source else '', max_length)
            pending.append(obj)
            if len(pending) == BATCH_SIZE:
                model.objects.bulk_update(pending, ['slug'])
                pending = []
        if pending:
            model.objects.bulk_update(pending, ['slug'])


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0047_add_public_slugs'),
    ]

    operations = [
        migrations.RunPython(regenerate_slugs, migrations.RunPython.noop),
    ]
