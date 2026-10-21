from django.core.management.base import BaseCommand

from app.services.catalog import style_registry


class Command(BaseCommand):
    help = "Ramène le style de chaque bière aux noms officiels du référentiel (table Style) et renseigne sa famille. Sans effet si tout est déjà à jour."

    def handle(self, *args, **options):
        self.stdout.write(f"{style_registry.renormalize_all()} bière(s) mise(s) à jour.")
