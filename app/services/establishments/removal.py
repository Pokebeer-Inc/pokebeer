"""Suppression d'une brasserie qui a des bières : la base l'interdit (Beer.brewery en PROTECT), l'équipe choisit explicitement.

- transférer : ses bières (et donc toutes leurs dégustations) passent à une autre brasserie, puis la fiche est supprimée ;
- tout supprimer : ses bières et leurs dégustations sont supprimées avec elle (choix explicite, jamais par défaut).
"""
from django.db import transaction
from django.db.models import Count

from ...models import Beer


class RemovalError(Exception):
    """Suppression impossible telle que demandée : le message est affichable tel quel."""


def impact(brewery):
    """Ce que la brasserie emporterait : nombre de bières et de dégustations."""
    totals = Beer.objects.filter(brewery=brewery).aggregate(beers=Count('id', distinct=True), tastings=Count('drinks', distinct=True))
    return {'beers': totals['beers'], 'tastings': totals['tastings']}


def name_conflicts(brewery, target):
    """Bières du catalogue qui existent déjà sous le même nom chez `target` (une brasserie n'a qu'une bière active d'un nom donné)."""
    taken = Beer.objects.filter(brewery=target, is_deleted=False).values('name')
    return sorted(Beer.objects.filter(brewery=brewery, is_deleted=False, name__in=taken).values_list('name', flat=True))


def transfer_beers(brewery, target):
    """Rattache toutes les bières de `brewery` à `target`. Leur vecteur de recherche (qui cite la brasserie) est recalculé plus tard
    (commande embed_beers). Lève RemovalError en cas de bières homonymes chez `target`."""
    if target.pk == brewery.pk:
        raise RemovalError("Choisissez une autre brasserie que celle à supprimer.")
    conflicts = name_conflicts(brewery, target)
    if conflicts:
        raise RemovalError(f"{target.name} a déjà une bière du même nom : {', '.join(conflicts)}. Renommez ou retirez-les d'abord.")
    return Beer.objects.filter(brewery=brewery).update(brewery=target, embedding=None)


def delete_brewery(brewery, transfer_to=None, delete_beers=False):
    """Supprime la brasserie après avoir transféré (`transfer_to`) ou explicitement supprimé (`delete_beers`) ses bières."""
    with transaction.atomic():
        if transfer_to is not None:
            transfer_beers(brewery, transfer_to)
        elif delete_beers:
            for beer in Beer.objects.filter(brewery=brewery):
                beer.delete()  # une à une : les signaux (fichiers, caches) suivent
        brewery.delete()
