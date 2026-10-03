"""Capture des créations/modifications de contenus publics via signaux ; ne bloque jamais l'enregistrement."""
import logging

from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save

from app.models import ModerationEntry

from .content import CONTENT_TYPES

logger = logging.getLogger(__name__)
MAX_VALUE_LENGTH = 2000
BEFORE_ATTR = '_moderation_before'


def _normalize(value):
    return str(value or '').strip()


def _clip(value):
    return value if len(value) <= MAX_VALUE_LENGTH else value[:MAX_VALUE_LENGTH] + '…'


def _current(instance, spec):
    value = getattr(instance, spec.name)
    return _normalize(value.name if spec.is_image else value)


def _image_url(instance, spec):
    try:
        return getattr(instance, spec.name).url
    except ValueError:
        return ''


def build_changes(content, instance, before):
    """Champs modifiés (ou renseignés à la création). `before` vaut None pour une création."""
    changes = []
    for spec in content.fields:
        new = _current(instance, spec)
        old = _normalize((before or {}).get(spec.name))
        if new == old:
            continue
        changes.append({
            'field': spec.name,
            'label': spec.label,
            'image': spec.is_image,
            'old': None if spec.is_image else _clip(old),
            'new': (_image_url(instance, spec) if new else '') if spec.is_image else _clip(new),
        })
    return changes


def _tracked_names(content):
    return {spec.name for spec in content.fields}


def _touches_tracked(content, update_fields):
    return update_fields is None or bool(_tracked_names(content) & set(update_fields))


def _make_pre_save(content):
    def remember_previous_values(sender, instance, raw=False, update_fields=None, **kwargs):
        if raw or not instance.pk or not _touches_tracked(content, update_fields):
            return
        before = sender._default_manager.filter(pk=instance.pk).values(*_tracked_names(content)).first()
        setattr(instance, BEFORE_ATTR, before)
    return remember_previous_values


def _make_post_save(content):
    def record_change(sender, instance, created=False, raw=False, update_fields=None, **kwargs):
        before = instance.__dict__.pop(BEFORE_ATTR, None)
        if raw:
            return
        if not content.is_public(instance):
            ModerationEntry.objects.pending().for_object(content.kind, instance.pk).delete()
            return
        if not created and before is None:
            return
        changes = build_changes(content, instance, None if created else before)
        if not changes:
            return
        try:
            with transaction.atomic():  # point de sauvegarde : un échec ici ne casse pas la transaction de l'appelant
                ModerationEntry.objects.create(
                    kind=content.kind,
                    action=ModerationEntry.Action.CREATED if created else ModerationEntry.Action.MODIFIED,
                    object_id=instance.pk,
                    label=content.title(instance)[:255],
                    context=content.context(instance)[:255],
                    changes=changes,
                )
        except Exception:
            logger.exception("Enregistrement de la modération impossible (%s #%s)", content.kind, instance.pk)
    return record_change


def _make_post_delete(content):
    def forget_entries(sender, instance, **kwargs):
        ModerationEntry.objects.for_object(content.kind, instance.pk).delete()
    return forget_entries


def connect_signals():
    for content in CONTENT_TYPES.values():
        uid = f"moderation_{content.kind}"
        pre_save.connect(_make_pre_save(content), sender=content.model, weak=False, dispatch_uid=f"{uid}_pre")
        post_save.connect(_make_post_save(content), sender=content.model, weak=False, dispatch_uid=f"{uid}_post")
        post_delete.connect(_make_post_delete(content), sender=content.model, weak=False, dispatch_uid=f"{uid}_del")
