from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from app.models import Beer
from app.services.ai import get_embedding


class Command(BaseCommand):
    help = "Calcule les embeddings Gemini des bières qui n'en ont pas (recherche sémantique du chat IA)."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Recalcule aussi les bières déjà vectorisées.")

    def handle(self, *args, all, **options):
        if not settings.GEMINI_API_KEY:
            raise CommandError("GEMINI_API_KEY est absente : impossible de calculer les embeddings.")

        beers = Beer.objects.filter(is_deleted=False).select_related("brewery_id")
        if not all:
            beers = beers.filter(embedding__isnull=True)

        embedded = failed = 0
        for beer in beers.iterator():
            vector = get_embedding(beer.embedding_text)
            if vector:
                # update() plutôt que save() : save() recalculerait l'embedding une seconde fois
                Beer.objects.filter(pk=beer.pk).update(embedding=vector)
                embedded += 1
            else:
                failed += 1

        self.stdout.write(self.style.SUCCESS(f"{embedded} bière(s) vectorisée(s)."))
        if failed:
            self.stdout.write(self.style.WARNING(f"{failed} échec(s) : relancez la commande pour les reprendre."))
