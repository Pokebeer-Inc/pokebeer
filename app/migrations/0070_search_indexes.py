"""Recherche : extensions PostgreSQL (accents ignorés, tolérance aux fautes) et index trigramme sur les noms.

`unaccent` n'est pas IMMUTABLE, donc inutilisable dans un index tel quel : `f_unaccent` l'enveloppe. Les requêtes de
app/services/search.py emploient exactement la même expression `f_unaccent(lower(colonne))`, ce qui permet au planificateur
d'utiliser ces index pour les recherches « contient » (LIKE '%mot%') au lieu de lire toute la table.
"""
from django.db import migrations

INDEXES = {
    'beer_name_trgm': ('app_beer', 'name'),
    'beer_style_trgm': ('app_beer', 'style'),
    'brewery_name_trgm': ('app_brewery', 'name'),
    'bar_name_trgm': ('app_bar', 'name'),
    'beeruser_username_trgm': ('app_beeruser', 'username'),
}


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0069_email_campaigns_and_promotions'),
    ]

    operations = [
        migrations.RunSQL(
            "CREATE EXTENSION IF NOT EXISTS unaccent; CREATE EXTENSION IF NOT EXISTS pg_trgm;",
            migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            "CREATE OR REPLACE FUNCTION f_unaccent(text) RETURNS text AS $$ SELECT public.unaccent('public.unaccent', $1) $$ "
            "LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT;",
            "DROP FUNCTION IF EXISTS f_unaccent(text);",
        ),
        *[
            migrations.RunSQL(
                f"CREATE INDEX {name} ON {table} USING gin (f_unaccent(lower({column})) gin_trgm_ops);",
                f"DROP INDEX IF EXISTS {name};",
            )
            for name, (table, column) in INDEXES.items()
        ],
    ]
