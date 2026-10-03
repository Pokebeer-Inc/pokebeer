import os
import secrets

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from app.dev_seed import data
from app.dev_seed.seeder import DevDatabaseSeeder
from app.models import BeerUser
from pokebeer.database import assert_dev_database

PASSWORD_ENV = "DEV_SEED_PASSWORD"


class Command(BaseCommand):
    help = "Remplit la base de développement avec des données fictives (refusé hors DEBUG ou sur la prod)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Vide entièrement la base avant de la remplir.")
        parser.add_argument("--seed", type=int, default=42, help="Graine aléatoire (données reproductibles).")
        parser.add_argument("--embed", action="store_true", help="Calcule ensuite les embeddings Gemini (appels API réels).")

    def handle(self, *args, reset, seed, embed, **options):
        try:
            assert_dev_database(settings.DEBUG, settings.DATABASES["default"])
        except ImproperlyConfigured as exc:
            raise CommandError(str(exc)) from exc

        if reset:
            call_command("flush", interactive=False, verbosity=0)
        elif BeerUser.objects.exists():
            raise CommandError("La base contient déjà des utilisateurs. Relancez avec --reset pour la réinitialiser.")

        # Lu depuis l'environnement plutôt qu'en argument pour ne pas finir dans l'historique du shell
        password = os.environ.get(PASSWORD_ENV)
        counts = DevDatabaseSeeder(password, seed).run()

        for model_name, count in sorted(counts.items()):
            self.stdout.write(f"  {model_name:<28} {count}")
        self.stdout.write(self.style.SUCCESS("Base de développement remplie."))
        if embed:
            call_command("embed_beers", stdout=self.stdout)
        self.stdout.write(f"Comptes ({data.ADMIN_USERNAME} est superuser) : {', '.join(user['username'] for user in data.USERS)}")
        if not os.environ.get(PASSWORD_ENV):
            self.stdout.write(self.style.WARNING(f"Mot de passe généré (définissez {PASSWORD_ENV} pour le fixer) : {password}"))
