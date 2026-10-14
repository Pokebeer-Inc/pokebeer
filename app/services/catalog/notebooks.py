"""Carnets personnalisés d'un membre : création (plafonnée), modification et choix des dégustations qu'ils contiennent."""
from django.db import transaction

from ...models import BeerUser, Drinks

MAX_NOTEBOOKS = 50


class NotebookLimitReached(Exception):
    """Le membre a déjà MAX_NOTEBOOKS carnets."""


def _own_drinks(user, drink_slugs):
    """Dégustations du membre désignées par leurs slugs (celles d'un autre sont ignorées)."""
    return Drinks.objects.filter(slug__in=drink_slugs, drinker=user)


def create(user, notebook_form, drink_slugs=()):
    """Crée le carnet (formulaire validé). Le compte est verrouillé le temps de compter : deux créations simultanées ne dépassent pas le plafond."""
    with transaction.atomic():
        BeerUser.objects.select_for_update().filter(pk=user.pk).first()
        if user.custom_notebooks.count() >= MAX_NOTEBOOKS:
            raise NotebookLimitReached
        notebook = notebook_form.save(commit=False)
        notebook.user = user
        notebook.save()
        if drink_slugs:
            notebook.drinks.set(_own_drinks(user, drink_slugs))
    return notebook


def update(notebook, notebook_form, drink_slugs):
    """Enregistre le titre et la description (formulaire validé) ; le carnet contient désormais exactement les dégustations choisies."""
    notebook_form.save()
    notebook.drinks.set(_own_drinks(notebook.user, drink_slugs))
    return notebook
