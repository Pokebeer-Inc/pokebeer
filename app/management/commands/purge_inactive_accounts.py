from django.core.management.base import BaseCommand

from app.services import inactivity, policy_notice


class Command(BaseCommand):
    help = "RGPD : prévient puis supprime les comptes inactifs (INACTIVE_ACCOUNT_MONTHS). À planifier chaque jour."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Compte les comptes concernés sans rien modifier.")

    def handle(self, *args, dry_run, **options):
        if dry_run:
            self.stdout.write(f"À prévenir : {inactivity.to_warn().count()} — à supprimer : {inactivity.due_for_deletion().count()}")
            return
        warned, deleted = inactivity.purge_inactive_accounts()
        emails = policy_notice.send_pending_emails()
        self.stdout.write(self.style.SUCCESS(f"{warned} compte(s) prévenu(s), {deleted} compte(s) supprimé(s), {emails} e-mail(s) d'annonce envoyé(s)."))
