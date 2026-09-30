"""Constructeurs d'objets métier pour les tests.

Chaque fonction crée un objet valide avec des valeurs par défaut uniques ; tout champ
peut être surchargé par mot-clé. Les appels réseau déclenchés par les save() (Gemini,
Nominatim) sont neutralisés par les fixtures autouse de conftest.py.
"""
from decimal import Decimal
from io import BytesIO
from itertools import count

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from app.models import (
    Bar, Beer, BeerSpot, BeerUser, Brewery, CustomNotebook, DrinkReaction, Drinks,
    Feedback, Notification, Report, UserBlock, UserFollow,
)

PASSWORD = "Pokebeer-Test-2026!"
_sequence = count(1)


def unique(prefix):
    return f"{prefix}{next(_sequence)}"


def make_user(username=None, password=PASSWORD, groups=(), **fields):
    username = username or unique("member")
    fields.setdefault("email", f"{username}@example.test")
    user = BeerUser.objects.create_user(username, password=password, **fields)
    if groups:
        user.groups.add(*(Group.objects.get_or_create(name=name)[0] for name in groups))
    return user


def _make_establishment(model, name, managers, fields):
    establishment = model.objects.create(name=name or unique(f"{model.__name__} "), **fields)
    if managers:
        establishment.managers.add(*managers)
    return establishment


def make_brewery(name=None, managers=(), **fields):
    fields.setdefault("description", "Brasserie de test")
    return _make_establishment(Brewery, name, managers, fields)


def make_bar(name=None, managers=(), **fields):
    return _make_establishment(Bar, name, managers, fields)


def make_beer(name=None, brewery=None, **fields):
    fields.setdefault("degree", Decimal("5.0"))
    return Beer.objects.create(name=name or unique("Biere "), brewery_id=brewery or make_brewery(), **fields)


def make_drink(drinker, beer=None, note=7, **fields):
    fields.setdefault("comment", "Très bonne")
    return Drinks.objects.create(drinker_id=drinker, beer_id=beer or make_beer(), note=note, **fields)


def make_spot(user, friends=(), drinks=(), **fields):
    fields.setdefault("title", unique("Spot "))
    fields.setdefault("latitude", 48.85)
    fields.setdefault("longitude", 2.35)
    spot = BeerSpot.objects.create(user=user, **fields)
    spot.friends.add(*friends)
    spot.drinks.add(*drinks)
    return spot


def make_notebook(user, drinks=(), **fields):
    fields.setdefault("title", unique("Carnet "))
    notebook = CustomNotebook.objects.create(user=user, **fields)
    notebook.drinks.add(*drinks)
    return notebook


def make_notification(recipient, notif_type="follow", **fields):
    return Notification.objects.create(recipient=recipient, notif_type=notif_type, **fields)


def make_report(reporter, **fields):
    fields.setdefault("reason", "spam")
    fields.setdefault("description", "Contenu douteux")
    return Report.objects.create(reporter=reporter, **fields)


def make_feedback(user, **fields):
    fields.setdefault("message", "Une suggestion")
    return Feedback.objects.create(user=user, **fields)


def follow(follower, followed):
    return UserFollow.objects.create(follower=follower, followed=followed)


def block(blocker, blocked):
    return UserBlock.objects.create(blocker=blocker, blocked=blocked)


def react(user, drink, is_like=True):
    return DrinkReaction.objects.create(user=user, drink=drink, is_like=is_like)


def make_image_upload(name="label.png"):
    buffer = BytesIO()
    Image.new("RGB", (2, 2), "orange").save(buffer, "PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")
