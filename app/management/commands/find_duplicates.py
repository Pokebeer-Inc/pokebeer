from django.core.management.base import BaseCommand

from app.models import Bar, Beer, Brewery
from app.services import catalog_matching


class Command(BaseCommand):
    help = "Liste les brasseries et les bières du catalogue qui se ressemblent (détection seulement). --rebuild-keys recalcule d'abord les clés de comparaison."

    def add_arguments(self, parser):
        parser.add_argument("--rebuild-keys", action="store_true", help="Recalcule les clés de comparaison de toutes les fiches (après un import ou un changement de règle).")

    def handle(self, *args, rebuild_keys, **options):
        if rebuild_keys:
            for model in (Brewery, Bar, Beer):
                rows = list(model.objects.only("pk", "name"))
                for row in rows:
                    row.refresh_match_keys()
                model.objects.bulk_update(rows, ["name_key", "match_key"], batch_size=500)
                self.stdout.write(f"Clés recalculées : {len(rows)} {model._meta.verbose_name_plural}")
        for label, pairs in (("Brasseries", catalog_matching.duplicate_breweries()), ("Bars", catalog_matching.duplicate_bars()), ("Bières", catalog_matching.duplicate_beers())):
            self.stdout.write(self.style.MIGRATE_HEADING(f"{label} : {len(pairs)} paire(s)"))
            for pair in pairs:
                verdict = "identiques" if pair.level == catalog_matching.Level.SAME else "proches"
                self.stdout.write(f"  [{verdict} {pair.score:.2f}] {pair.first.name}  <->  {pair.second.name}")
