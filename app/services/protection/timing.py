"""Temps de réponse constant pour les actions qui ne doivent pas révéler l'existence d'un compte."""
import time
from contextlib import contextmanager


@contextmanager
def minimum_duration(seconds):
    """Le bloc dure au moins `seconds` : un envoi d'e-mail (lent) et une adresse inconnue (immédiate) sont indiscernables."""
    start = time.monotonic()
    try:
        yield
    finally:
        remaining = seconds - (time.monotonic() - start)
        if remaining > 0:
            time.sleep(remaining)
