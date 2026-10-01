from django.db import migrations

import app.fields

# Modèle -> champ servant de libellé lisible (None : jeton opaque, pour les contenus privés)
SLUGGED_MODELS = {
    'brewery': 'name',
    'bar': 'name',
    'drinks': None,
    'beerspot': None,
    'report': None,
    'notification': None,
    'customnotebook': None,
}


def _slug_field(source):
    # Colonne nullable le temps du remplissage (0048), puis rendue obligatoire (0049)
    return app.fields.PublicSlugField(null=True, blank=True, source=source)


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0046_report_reported_brewery'),
    ]

    operations = [
        migrations.AddField(model_name=model_name, name='slug', field=_slug_field(source))
        for model_name, source in SLUGGED_MODELS.items()
    ]
