"""Réactions automatiques aux changements de modèles : rôles par défaut, rôles des gérants, suppression des fichiers."""

from django.contrib.auth.models import Group
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver
from django.db import transaction

from ..services.images import delete_stored_file

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


@receiver(m2m_changed, sender=Brewery.managers.through)
def update_brewer_role(sender, instance, action, pk_set, **kwargs):
    """Ajoute ou retire automatiquement le rôle Brasseur en fonction des établissements gérés."""
    grp_brasseur, _ = Group.objects.get_or_create(name='Brasseur')
    
    if action == "post_add" and pk_set:
        users = BeerUser.objects.filter(pk__in=pk_set)
        for user in users:
            user.groups.add(grp_brasseur)
            
    elif action == "post_remove" and pk_set:
        users = BeerUser.objects.filter(pk__in=pk_set)
        for user in users:
            # S'il a été retiré et qu'il ne gère plus AUCUNE autre brasserie
            if not user.managed_breweries.exists():
                user.groups.remove(grp_brasseur)
                
    elif action == "pre_clear":
        # Si on vide complètement la liste des gérants de cette brasserie d'un coup
        for user in instance.managers.all():
            # On vérifie s'il gère d'autres brasseries que celle-ci
            if not user.managed_breweries.exclude(pk=instance.pk).exists():
                user.groups.remove(grp_brasseur)


@receiver(m2m_changed, sender=Bar.managers.through)
def update_bar_role(sender, instance, action, pk_set, **kwargs):
    """Ajoute ou retire automatiquement le rôle Bartender en fonction des établissements gérés."""
    grp_bartender, _ = Group.objects.get_or_create(name='Bartender')
    
    if action == "post_add" and pk_set:
        users = BeerUser.objects.filter(pk__in=pk_set)
        for user in users:
            user.groups.add(grp_bartender)
            
    elif action == "post_remove" and pk_set:
        users = BeerUser.objects.filter(pk__in=pk_set)
        for user in users:
            # S'il a été retiré et qu'il ne gère plus AUCUN autre bar
            if not user.managed_bars.exists():
                user.groups.remove(grp_bartender)
                
    elif action == "pre_clear":
        for user in instance.managers.all():
            if not user.managed_bars.exclude(pk=instance.pk).exists():
                user.groups.remove(grp_bartender)
