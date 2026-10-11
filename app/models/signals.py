"""Réactions automatiques aux changements de modèles : rôles par défaut, rôles des gérants, suppression des fichiers."""

from django.contrib.auth.models import Group
from django.core.cache import cache
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver
from django.db import transaction

from ..services.common.images import delete_stored_file

from .beers import Beer, Drinks
from .establishments import Bar, Brewery
from .users import BeerUser


# ==========================================
# Attibution des rôles
# ==========================================

@receiver(post_save, sender=BeerUser)
def assign_default_role(sender, instance, created, **kwargs):
    """
    Signal déclenché juste après la sauvegarde d'un BeerUser.
    Si c'est une création (created=True), on lui donne le rôle Contributeur par défaut.
    """
    if created:
        # get_or_create évite que le code plante si le groupe venait à être supprimé
        grp_contrib, _ = Group.objects.get_or_create(name='Contributeur')
        instance.groups.add(grp_contrib)

def delete_files_with(model, *fields):
    """Les fichiers d'un objet supprimé (par son auteur, la modération ou la suppression du compte) ne doivent pas rester dans le bucket."""
    def handler(sender, instance, **kwargs):
        for field in fields:
            stored = getattr(instance, field)
            if stored:
                storage, name = stored.storage, stored.name
                transaction.on_commit(lambda storage=storage, name=name: delete_stored_file(storage, name))
    post_delete.connect(handler, sender=model, weak=False, dispatch_uid=f'delete_files_{model.__name__}')


delete_files_with(BeerUser, 'avatar')
delete_files_with(Drinks, 'photo')
delete_files_with(Beer, 'image')
delete_files_with(Brewery, 'image')
delete_files_with(Bar, 'image')


def sync_manager_role(place_model, group_name, managed_related_name):
    """Donne ou retire automatiquement le rôle (groupe) selon les établissements gérés : un membre l'a tant qu'il en gère au moins un.

    Un seul comportement pour les brasseries (rôle Brasseur) et les bars (rôle Bartender)."""
    def handler(sender, instance, action, pk_set, **kwargs):
        group, _ = Group.objects.get_or_create(name=group_name)

        if action == "post_add" and pk_set:
            for user in BeerUser.objects.filter(pk__in=pk_set):
                user.groups.add(group)

        elif action == "post_remove" and pk_set:
            for user in BeerUser.objects.filter(pk__in=pk_set):
                # S'il a été retiré et qu'il ne gère plus AUCUN autre établissement de ce type
                if not getattr(user, managed_related_name).exists():
                    user.groups.remove(group)

        elif action == "pre_clear":
            # Si on vide complètement la liste des gérants de cet établissement d'un coup
            for user in instance.managers.all():
                # On vérifie s'il gère d'autres établissements de ce type que celui-ci
                if not getattr(user, managed_related_name).exclude(pk=instance.pk).exists():
                    user.groups.remove(group)

    m2m_changed.connect(handler, sender=place_model.managers.through, weak=False, dispatch_uid=f'sync_manager_role_{place_model.__name__}')


sync_manager_role(Brewery, 'Brasseur', 'managed_breweries')
sync_manager_role(Bar, 'Bartender', 'managed_bars')


@receiver(m2m_changed, sender=BeerUser.groups.through)
def forget_cached_group_names(sender, instance, action, **kwargs):
    """Les rôles lus pour un membre (BeerUser.group_names) ne doivent pas survivre à un changement de ses groupes."""
    if isinstance(instance, BeerUser):
        instance._group_names_cache = None


@receiver(post_save, sender=Beer)
@receiver(post_delete, sender=Beer)
def forget_cached_beer_styles(sender, **kwargs):
    """La liste des styles du filtre de recherche (mise en cache) suit le catalogue."""
    cache.delete('beer_styles')


@receiver(post_save, sender=Bar)
@receiver(post_save, sender=Brewery)
@receiver(post_delete, sender=Bar)
@receiver(post_delete, sender=Brewery)
def forget_cached_place_lists(sender, **kwargs):
    """L'annuaire « Près de moi » et les repères de la carte (mis en cache) suivent les fiches."""
    from ..services.establishments import place_directory
    place_directory.forget()
