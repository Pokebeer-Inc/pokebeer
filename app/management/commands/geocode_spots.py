from django.core.management.base import BaseCommand

from app.services.reverse_geocoding import REQUEST_DELAY, pending_keys, resolve_pending


class Command(BaseCommand):
    help = "Rattrapage manuel : géocode les lieux antérieurs au géocodage automatique (les nouveaux lieux le sont à leur enregistrement)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100, help="Nombre maximal de positions résolues par exécution.")

    def handle(self, *args, limit, **options):
        waiting = len(pending_keys())
        self.stdout.write(f"{waiting} position(s) à résoudre ; traitement de {min(waiting, limit)} (~{REQUEST_DELAY}s chacune).")
        stats = resolve_pending(limit=limit)
        self.stdout.write(self.style.SUCCESS(f"{stats['resolved']} résolue(s)."))
        if stats['failed']:
            self.stdout.write(self.style.WARNING(f"{stats['failed']} échec(s) : elles seront retentées au prochain passage."))
