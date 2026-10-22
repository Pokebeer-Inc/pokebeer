"""Les trois formulaires de dégustation (notation, première réaction, modification) : ce que le navigateur envoie est accepté ou refusé
pour une raison que le membre peut lire, jamais pour un champ que l'écran annonce comme facultatif."""
import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from app.models import Drinks
from tests import factories as f

pytestmark = pytest.mark.django_db

# Ce qu'envoie la fenêtre de notation quand le membre n'a rien rempli d'autre que la date
BLANK = {"date": "2026-02-01", "note": "", "comment": "", "price": ""}


def messages_of(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


class TestWizardRating:
    """Fenêtre « Ajouter mon avis » de la fiche, ouverte aussi depuis le tirage du jour."""

    def rate(self, client, beer, **data):
        return client.post(reverse("rate_beer", args=[beer.slug]), {**BLANK, **data}, HTTP_REFERER="/beers/")

    @pytest.mark.parametrize("data", [
        {},                                                       # rien que la date : tout le reste est annoncé « facultatif »
        {"note": "8"},                                            # une note seule
        {"comment": "Très bonne"},                                # un avis seul
        {"note": "0", "comment": "Décevante", "price": "4.50", "venue_type": "bar", "company": "friends", "serving_format": "pint"},
    ])
    def test_every_optional_field_may_be_left_empty(self, auth_client, user, beer, data):
        self.rate(auth_client, beer, **data)
        assert Drinks.objects.filter(drinker=user, beer=beer).exists()

    def test_an_empty_review_is_stored_as_an_empty_text_not_a_missing_one(self, auth_client, user, beer):
        self.rate(auth_client, beer)
        assert Drinks.objects.get(drinker=user).comment == ""

    @pytest.mark.parametrize("data, reason", [
        ({"note": "11"}, "Note"),
        ({"date": "2999-01-01"}, "futur"),
        ({"date": ""}, "Date"),
        ({"price": "5000"}, "Prix"),
        ({"venue_type": "spaceship"}, "Lieu"),
    ])
    def test_a_refused_form_says_which_field_and_why(self, auth_client, beer, data, reason):
        response = self.rate(auth_client, beer, **data)
        assert not Drinks.objects.exists()
        assert any(reason in text for text in messages_of(response)), messages_of(response)


class TestQuickRating:
    """Première réaction juste après l'ajout d'une bière : une note ou quelques mots."""

    def rate(self, client, beer, **data):
        return client.post(reverse("quick_rate_beer", args=[beer.slug]), {"note": "", "comment": "", **data})

    @pytest.mark.parametrize("data", [{"note": "7"}, {"comment": "Top"}, {"note": "0"}])
    def test_a_note_or_a_few_words_are_enough(self, auth_client, user, beer, data):
        self.rate(auth_client, beer, **data)
        assert Drinks.objects.filter(drinker=user).exists()

    def test_nothing_at_all_is_refused_with_a_readable_reason(self, auth_client, beer):
        response = self.rate(auth_client, beer)
        assert not Drinks.objects.exists()
        assert any("Donnez une note ou écrivez quelques mots" in text for text in messages_of(response))


class TestEditingARating:
    def modify(self, client, drink, **data):
        return client.post(reverse("modify_rate_beer", args=[drink.slug]), {**BLANK, "date": drink.date.isoformat(), **data})

    def test_the_review_can_be_cleared_while_editing(self, auth_client, user, beer):
        drink = f.make_drink(user, beer, note=6, comment="Avant")
        self.modify(auth_client, drink, note="6", comment="")
        drink.refresh_from_db()
        assert drink.comment == "" and drink.note == 6

    def test_a_refused_edit_keeps_the_rating_and_says_why(self, auth_client, user, beer):
        drink = f.make_drink(user, beer, note=6, comment="Avant")
        response = self.modify(auth_client, drink, note="42")
        drink.refresh_from_db()
        assert drink.note == 6 and any("Note" in text for text in messages_of(response))


class TestFromTheDailyDraw:
    def test_the_whole_path_from_the_card_to_the_saved_rating(self, auth_client, user, beer):
        """Lien de la carte -> fenêtre de la fiche -> envoi du formulaire avec tout ce qui est facultatif laissé vide."""
        f.make_beer()
        card = auth_client.post(reverse("open_daily_draw")).json()["cards"][0]
        page = auth_client.get(card["beer_url"]).content.decode()
        assert card["rate_url"].endswith(f"#modalRate-{card['slug']}") and f'id="modalRate-{card["slug"]}"' in page
        response = auth_client.post(reverse("rate_beer", args=[card["slug"]]), {**BLANK, "note": "9"}, HTTP_REFERER=card["beer_url"])
        assert response.status_code == 302 and Drinks.objects.filter(drinker=user, beer__slug=card["slug"], note=9).exists()
