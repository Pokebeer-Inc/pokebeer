"""Compteur journalier incrémenté sans verrou : une seule règle pour toutes les mesures."""
from django.db import IntegrityError, transaction
from django.db.models import F


def increment(model, lookup, **deltas):
    """Ajoute `deltas` (ex. views=1) à la ligne désignée par `lookup`, créée au besoin. Sûr si deux requêtes arrivent ensemble.

    Un UPDATE d'abord (cas courant, atomique en base), sinon un INSERT ; si une autre requête a créé la ligne entre les deux, l'INSERT
    échoue sur la contrainte d'unicité et on retombe sur l'UPDATE."""
    updates = {name: F(name) + delta for name, delta in deltas.items()}
    if model.objects.filter(**lookup).update(**updates):
        return
    try:
        with transaction.atomic():
            model.objects.create(**lookup, **deltas)
    except IntegrityError:
        model.objects.filter(**lookup).update(**updates)
