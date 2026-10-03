"""Échanges avec l'équipe : un fil par sujet (Feedback) contenant le premier message du membre puis les messages suivants.

Règles communes au site et à l'admin : taille bornée, quota quotidien côté membre, état du fil (« en attente » = l'équipe doit
répondre, « répondu » = c'est au tour du membre), notification du membre à chaque réponse de l'équipe.
"""
from django.db import transaction
from django.utils import timezone

from ..models import Feedback, FeedbackMessage
from .notifications import notify
from .threads import Entry

MAX_BODY_LENGTH = 2000
DAILY_MEMBER_LIMIT = 10  # messages d'un membre par jour, tous fils confondus

Author = FeedbackMessage.Author


class FeedbackError(ValueError):
    """Refus explicable au membre (quota, message vide ou trop long)."""


def clean_body(value):
    body = (value or '').strip()
    if not body:
        raise FeedbackError("Écrivez un message avant d'envoyer.")
    if len(body) > MAX_BODY_LENGTH:
        raise FeedbackError(f"Le message est limité à {MAX_BODY_LENGTH} caractères.")
    return body


def _member_messages_today(user):
    today = timezone.localdate()
    opened = Feedback.objects.filter(user=user, created_at__date=today).count()
    replied = FeedbackMessage.objects.filter(author_kind=Author.MEMBER, author=user, created_at__date=today).count()
    return opened + replied


def _check_quota(user):
    if _member_messages_today(user) >= DAILY_MEMBER_LIMIT:
        raise FeedbackError("Vous avez atteint le nombre maximal de messages pour aujourd'hui. Réessayez demain.")


def open_thread(user, text):
    """Premier message d'un membre : ouvre un nouveau fil, en attente de réponse."""
    body = clean_body(text)
    _check_quota(user)
    return Feedback.objects.create(user=user, message=body)


def member_reply(feedback, user, text):
    """Message du membre dans son fil ; le fil repasse « en attente » pour que l'équipe le voie."""
    if feedback.user_id != user.pk:
        raise PermissionError("Ce fil n'appartient pas à ce membre.")
    body = clean_body(text)
    _check_quota(user)
    with transaction.atomic():
        message = FeedbackMessage.objects.create(feedback=feedback, author_kind=Author.MEMBER, author=user, body=body)
        Feedback.objects.filter(pk=feedback.pk).update(status='pending')
    return message


def team_reply(feedback, staff_user, text):
    """Réponse de l'équipe : le fil passe « répondu » et le membre est notifié (pop-up, cloche, push)."""
    body = clean_body(text)
    with transaction.atomic():
        message = FeedbackMessage.objects.create(feedback=feedback, author_kind=Author.TEAM, author=staff_user, body=body)
        Feedback.objects.filter(pk=feedback.pk).update(status='replied')
    notify('feedback_replied', [feedback.user], feedback=feedback)
    return message


def timeline(feedback):
    """Conversation complète, du plus ancien au plus récent : premier message du membre, puis tous les suivants."""
    entries = [Entry(Author.MEMBER, feedback.message, feedback.created_at)]
    entries += [Entry(m.author_kind, m.body, m.created_at) for m in feedback.messages.all()]
    return entries


def last_team_message(feedback):
    """Dernière réponse de l'équipe (None s'il n'y en a pas) ; exploite le prefetch de `messages` quand il existe."""
    team = [m for m in feedback.messages.all() if m.author_kind == Author.TEAM]
    return team[-1] if team else None
