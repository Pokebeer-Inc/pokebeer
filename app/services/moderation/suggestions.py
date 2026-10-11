"""Suggestions de modification : un membre sans droit d'édition propose de nouvelles valeurs, l'équipe les accepte (en les ajustant au
besoin) ou les refuse, sans justification. Rien n'est appliqué avant la décision de l'équipe.

Une suggestion est une entrée de la file « Contenus à valider » (ModerationEntry, action « suggestion ») : les valeurs proposées y sont
conservées, et le formulaire de l'équipe est le formulaire du modèle, pré-rempli avec elles. Les champs suggérables sont déclarés par
type de contenu (ModeratedContent.suggest_fields) : ajouter un champ ou un type ne modifie pas ce module.
"""
import copy

from django.contrib.admin.models import CHANGE, LogEntry
from django.db import transaction
from django.utils import timezone

from app.models import ModerationEntry

from ..protection.throttle import SUGGESTION_BY_USER
from .actions import ModerationError, _locked_entry
from .capture import SKIP_ATTR, _clip, _normalize
from .content import CONTENT_TYPES
from .editing import edit_form, plain_values, problems

Action, Outcome = ModerationEntry.Action, ModerationEntry.Outcome


class SuggestionError(ModerationError):
    """Suggestion refusée, avec un message explicable au membre ou à l'équipe."""


def menu_context(content, obj, user):
    """Ce qu'une page de fiche doit savoir pour proposer (ou non) « Suggérer une modification »."""
    allowed = content.can_suggest(obj, user)
    return {
        'can_suggest': allowed,
        'suggest_kind': content.kind,
        'suggest_form': edit_form(content, instance=obj) if allowed else None,
    }


def _changes(content, form, target):
    """Champs réellement modifiés par la suggestion, au format des entrées de modération."""
    changes = []
    for name in content.suggest_fields:
        old, new = _normalize(getattr(target, name)), _normalize(form.cleaned_data.get(name))
        if old != new:
            changes.append({'field': name, 'label': str(form.fields[name].label or name), 'image': False, 'old': _clip(old), 'new': _clip(new)})
    return changes


def propose(kind, slug, user, data):
    """Enregistre la suggestion d'un membre. Lève SuggestionError (message affichable) si elle n'est pas recevable."""
    content = CONTENT_TYPES.get(kind)
    target = content.find(slug) if content and content.suggest_fields else None
    if target is None:
        raise SuggestionError("Cette fiche n'existe plus.")
    if not content.can_suggest(target, user):
        raise SuggestionError("Vous pouvez modifier cette fiche directement.")
    if SUGGESTION_BY_USER.exceeded(user.pk):
        raise SuggestionError("Vous avez déjà beaucoup suggéré aujourd'hui : merci, réessayez demain.")
    if ModerationEntry.objects.pending().suggestions().filter(kind=kind, object_id=target.pk, suggested_by=user).exists():
        raise SuggestionError("Votre suggestion pour cette fiche est déjà en attente : merci de patienter.")

    form = edit_form(content, instance=copy.copy(target), data=plain_values(content, data))  # copie : valider ne touche jamais la vraie fiche
    errors = problems(content, form, target)
    if errors:
        raise SuggestionError(" ; ".join(errors))
    changes = _changes(content, form, target)
    if not changes:
        raise SuggestionError("Aucune modification : changez au moins un champ.")

    SUGGESTION_BY_USER.record(user.pk)
    return ModerationEntry.objects.create(
        kind=kind, action=Action.SUGGESTED, object_id=target.pk, suggested_by=user,
        label=content.title(target)[:255], context=content.context(target)[:255], changes=changes,
    )


def proposed_values(entry):
    """Valeurs proposées par un membre, champ par champ (pour pré-remplir le formulaire de l'équipe)."""
    return {change['field']: change['new'] for change in entry.changes}


def _locked_suggestion(entry_id, user):
    entry, content = _locked_entry(entry_id)
    if entry.action != Action.SUGGESTED:
        raise SuggestionError("Cette entrée n'est pas une suggestion.")
    if not content.can_amend(user):
        raise SuggestionError("Vous ne pouvez pas traiter les suggestions de ce type de contenu.")
    return entry, content


def apply_suggestion(entry_id, user, data):
    """Applique la suggestion avec les valeurs du formulaire de l'équipe (ajustées ou non) ; l'enregistrement n'est pas re-relu."""
    with transaction.atomic():
        entry, content = _locked_suggestion(entry_id, user)
        target = content.model.objects.select_for_update().filter(pk=entry.object_id).first()
        if target is None:
            raise SuggestionError("Cette fiche n'existe plus.")
        form = edit_form(content, instance=target, data=plain_values(content, data))
        errors = problems(content, form, target)
        if errors:
            raise SuggestionError(" ; ".join(errors))
        setattr(target, SKIP_ATTR, True)  # la modification vient de l'équipe : pas de nouvelle entrée « à relire »
        form.save()
        LogEntry.objects.log_actions(
            user.pk, [target], CHANGE, single_object=True,
            change_message=f"Modération : suggestion de {entry.suggested_by or 'un membre'} appliquée ({', '.join(c['label'] for c in entry.changes)})",
        )
        _close(entry, user, Outcome.APPLIED)
    return entry


def dismiss_suggestion(entry_id, user):
    """Refuse la suggestion, sans justification."""
    with transaction.atomic():
        entry, _ = _locked_suggestion(entry_id, user)
        _close(entry, user, Outcome.DISMISSED)
    return entry


def _close(entry, user, outcome):
    entry.reviewed_by, entry.reviewed_at, entry.outcome = user, timezone.now(), outcome
    entry.save(update_fields=['reviewed_by', 'reviewed_at', 'outcome'])
