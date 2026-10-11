"""Actions du staff sur une entrée : valider (« vu ») ou retirer le contenu et prévenir son auteur."""
from django.contrib.admin.models import CHANGE, DELETION, LogEntry
from django.db import transaction
from django.utils import timezone

from app.models import ModerationEntry
from app.services.messaging.notifications import create_notifications
from app.services.messaging.realtime_service import broadcast_notifications
from app.services.establishments.verification import certify

from .capture import SKIP_ATTR
from .content import CONTENT_TYPES
from .editing import edit_form, plain_values, problems

NOTE_MAX_LENGTH = 150
NOTIFICATION_MAX_LENGTH = 255

# Motifs proposés au staff ; le libellé est celui montré à l'auteur
REMOVAL_REASONS = {
    'abusive': "Propos insultants ou haineux",
    'dangerous': "Contenu dangereux ou illégal",
    'spam': "Spam ou publicité",
    'false': "Informations fausses ou trompeuses",
    'inappropriate': "Contenu inapproprié",
    'other': "Non-respect des règles de la communauté",
}


class ModerationError(Exception):
    """Refus explicable à l'utilisateur de l'admin (droits, entrée déjà traitée, saisie invalide)."""


def _locked_entry(entry_id):
    entry = ModerationEntry.objects.select_for_update().filter(pk=entry_id).first()
    if not entry:
        raise ModerationError("Entrée introuvable.")
    if entry.reviewed_at:
        raise ModerationError("Cette entrée a déjà été traitée.")
    return entry, CONTENT_TYPES[entry.kind]


def _review(entry, content, user):
    """Marque l'entrée comme vue ; si le contenu est certifiable, la validation d'une création par un admin pose la coche « vérifié »."""
    entry.reviewed_by, entry.reviewed_at = user, timezone.now()
    entry.save(update_fields=['reviewed_by', 'reviewed_at'])

    if content.certifies(entry, user):
        target = content.model.objects.select_for_update().filter(pk=entry.object_id).first()
        if target and not target.is_verified:
            certify(target, user)


def validate_entry(entry_id, user):
    """Marque l'entrée comme vue. Si le contenu est certifiable, la validation d'une création par un admin pose la coche « vérifié »."""
    with transaction.atomic():
        entry, content = _locked_entry(entry_id)
        if not content.can_validate(entry, user):
            raise ModerationError("Seuls les admins peuvent valider la création de ce type de contenu.")
        _review(entry, content, user)
    return entry


def amend_and_validate(entry_id, user, data):
    """Retouche les champs publics du contenu avec le formulaire de l'équipe, puis valide l'entrée (création ou modification).

    Mêmes droits que la validation et que la retouche ; l'enregistrement de l'équipe n'est pas re-relu (pas de nouvelle entrée)."""
    with transaction.atomic():
        entry, content = _locked_entry(entry_id)
        if entry.action == ModerationEntry.Action.SUGGESTED:
            raise ModerationError("Une suggestion s'applique ou se refuse : utilisez ses boutons.")
        if not content.suggest_fields:
            raise ModerationError("Ce type de contenu ne se retouche pas ici.")
        if not (content.can_validate(entry, user) and content.can_amend(user)):
            raise ModerationError("Vous ne pouvez pas retoucher ni valider ce contenu.")
        target = content.model.objects.select_for_update().filter(pk=entry.object_id).first()
        if target is None:
            raise ModerationError("Ce contenu n'existe plus.")
        form = edit_form(content, instance=target, data=plain_values(content, data))
        errors = problems(content, form, target)
        if errors:
            raise ModerationError(" ; ".join(errors))
        setattr(target, SKIP_ATTR, True)
        form.save()
        LogEntry.objects.log_actions(
            user.pk, [target], CHANGE, single_object=True,
            change_message=f"Modération : retouché avant validation ({', '.join(form.changed_data) or 'aucun champ'})",
        )
        _review(entry, content, user)
    return entry


def removal_message(content, entry, reason_code, note):
    message = f"Votre {content.noun_for(entry)} a été retiré par l'équipe de modération. Motif : {REMOVAL_REASONS[reason_code]}."
    if note:
        message += f" {note}"
    return message[:NOTIFICATION_MAX_LENGTH]


def remove_content(entry_id, user, reason_code, note=""):
    """Retire le contenu, journalise (LogEntry Django) et notifie son auteur avec le motif."""
    if reason_code not in REMOVAL_REASONS:
        raise ModerationError("Choisissez un motif valide.")
    note = (note or "").strip()
    if len(note) > NOTE_MAX_LENGTH:
        raise ModerationError(f"La précision est limitée à {NOTE_MAX_LENGTH} caractères.")

    with transaction.atomic():
        entry, content = _locked_entry(entry_id)
        if not content.can_remove_by(entry, user):
            raise ModerationError("Vous ne pouvez pas retirer ce contenu.")
        target = content.model.objects.select_for_update().filter(pk=entry.object_id).first()
        if not target:
            ModerationEntry.objects.for_object(entry.kind, entry.object_id).delete()
            raise ModerationError("Ce contenu n'existe déjà plus.")

        recipients = content.authors(target)
        LogEntry.objects.log_actions(
            user.pk, [target], DELETION, single_object=True,
            change_message=f"Modération : {content.remove_label_for(entry)} ({REMOVAL_REASONS[reason_code]})",
        )
        content.remove(target, entry)
        # Hors suppression en base (soft-delete, bio effacée), les entrées de cet objet n'ont plus rien à relire
        ModerationEntry.objects.pending().for_object(entry.kind, entry.object_id).update(
            reviewed_by=user, reviewed_at=timezone.now(),
        )

        text = removal_message(content, entry, reason_code, note)
        notifications = create_notifications(
            'content_removed', [r for r in recipients if r.pk != user.pk], text_content=text)
        transaction.on_commit(lambda: broadcast_notifications(notifications))
    return entry
