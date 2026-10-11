from django.db import migrations


class Migration(migrations.Migration):
    """Les vecteurs Gemini (3072 dimensions) ne sont pas comparables à ceux de Mistral (1024) : on les efface avant de changer la colonne.
    `python manage.py embed_beers` recalcule ensuite tout le catalogue."""

    dependencies = [('app', '0081_onboarding')]

    operations = [migrations.RunSQL("UPDATE app_beer SET embedding = NULL WHERE embedding IS NOT NULL", migrations.RunSQL.noop)]
