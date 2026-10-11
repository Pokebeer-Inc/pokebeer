"""Vecteur de recherche sémantique des bières (chat IA) : recalculé quand le texte qui le décrit change.

Branché sur le signal post_save de `Beer` (voir apps.py) : le modèle constate seulement que son vecteur est périmé, il n'appelle aucun service.
Le calcul attend la fin de la transaction en cours : jamais d'appel réseau pendant qu'elle est ouverte.
"""
from django.db import transaction
from django.db.models.signals import post_save

from ...models import Beer
from ..assistant import ai


def refresh(beer):
    """Calcule et enregistre le vecteur de cette bière ; ne fait rien si le service ne répond pas (rattrapé plus tard)."""
    vector = ai.get_embedding(beer.embedding_text)  # via le module : substituable dans les tests
    if vector:
        beer.embedding = vector
        Beer.objects.filter(pk=beer.pk).update(embedding=vector)


def _schedule_refresh(sender, instance, **kwargs):
    if getattr(instance, 'embedding_is_stale', False):
        transaction.on_commit(lambda: refresh(instance))


def connect_signals():
    post_save.connect(_schedule_refresh, sender=Beer, dispatch_uid='refresh_beer_embedding')
