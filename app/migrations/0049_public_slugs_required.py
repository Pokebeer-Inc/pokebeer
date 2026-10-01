from django.db import migrations

import app.fields

SLUGGED_MODELS = {
    'beer': 'name',
    'brewery': 'name',
    'bar': 'name',
    'drinks': None,
    'beerspot': None,
    'report': None,
    'notification': None,
    'customnotebook': None,
}


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0048_backfill_public_slugs'),
    ]

    operations = [
        migrations.AlterField(model_name=model_name, name='slug', field=app.fields.PublicSlugField(source=source))
        for model_name, source in SLUGGED_MODELS.items()
    ]
