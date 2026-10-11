import time
from itertools import islice

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from app.models import Beer
from app.services.assistant import llm


def batches(iterable, size):
    iterator = iter(iterable)
    while batch := list(islice(iterator, size)):
        yield batch


class Command(BaseCommand):
    help = "Calcule les embeddings Mistral des bières qui n'en ont pas (recherche sémantique du chat IA), par lots."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Recalcule aussi les bières déjà vectorisées.")
        parser.add_argument("--pause", type=float, default=1.0, help="Secondes d'attente entre deux lots (limites du plan gratuit).")

    def handle(self, *args, all, pause, **options):
        if not settings.MISTRAL_API_KEY:
            raise CommandError("MISTRAL_API_KEY est absente : impossible de calculer les embeddings.")

        beers = Beer.objects.filter(is_deleted=False).select_related("brewery")
        if not all:
            beers = beers.filter(embedding__isnull=True)

        embedded = failed = 0
        for index, batch in enumerate(batches(beers.iterator(), llm.EMBED_BATCH_SIZE)):
            if index:
                time.sleep(pause)
            vectors = llm.embed([beer.embedding_text for beer in batch], budgeted=False)
            if vectors is None:
                failed += len(batch)
                continue
            for beer, vector in zip(batch, vectors):
                # update() plutôt que save() : save() recalculerait l'embedding une seconde fois
                Beer.objects.filter(pk=beer.pk).update(embedding=vector)
            embedded += len(batch)

        self.stdout.write(self.style.SUCCESS(f"{embedded} bière(s) vectorisée(s)."))
        if failed:
            self.stdout.write(self.style.WARNING(f"{failed} échec(s) : relancez la commande pour les reprendre."))
