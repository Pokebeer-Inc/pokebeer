"""Les boutons d'action des fiches d'administration (accepter une demande de gestion, lancer une campagne) sont de vrais formulaires.

Un `<form>` placé à l'intérieur du formulaire de la page est ignoré par le navigateur : le bouton envoie alors le formulaire de la page, et une page en
lecture seule répond 403. Les tests qui postent directement sur l'action ne voient pas ce défaut : on contrôle donc ici le HTML affiché.
"""
from html.parser import HTMLParser

import pytest
from django.urls import reverse

from app.models import EmailCampaign
from app.services.establishments import claims
from app.services.establishments.places import BREWERY
from tests import factories as f

pytestmark = pytest.mark.django_db


class FormNesting(HTMLParser):
    """Relève les formulaires ouverts à l'intérieur d'un autre formulaire."""

    def __init__(self):
        super().__init__()
        self.depth, self.nested = 0, []

    def handle_starttag(self, tag, attrs):
        if tag == "form":
            if self.depth:
                self.nested.append(dict(attrs).get("action", ""))
            self.depth += 1

    def handle_endtag(self, tag):
        if tag == "form" and self.depth:
            self.depth -= 1


def nested_forms(html):
    parser = FormNesting()
    parser.feed(html)
    return parser.nested


def test_the_checker_detects_nesting():
    assert nested_forms('<form action="a"><form action="b"></form></form>') == ["b"]
    assert nested_forms('<form action="a"></form><form action="b"></form>') == []


def test_claim_actions_are_not_nested_in_the_page_form(client_for, superuser, geocoder):
    owner = f.make_user(username="demandeur")
    brewery = f.make_brewery(name="Brasserie à revendiquer", postal_code="75001")
    claim = claims.open_claim(owner, BREWERY, brewery, "73282932000074", "Gérant")
    html = client_for(superuser).get(reverse("admin:app_establishmentclaim_change", args=[claim.pk])).content.decode()
    assert reverse("admin:app_establishmentclaim_action", args=[claim.pk, "approve"]) in html  # les boutons sont bien affichés
    assert nested_forms(html) == []


def test_campaign_actions_are_not_nested_in_the_page_form(client_for, superuser):
    campaign = EmailCampaign.objects.create(subject="Brouillon", body="Salut {username}", audience="all")
    html = client_for(superuser).get(reverse("admin:app_emailcampaign_change", args=[campaign.pk])).content.decode()
    assert reverse("admin:app_emailcampaign_action", args=[campaign.pk, "launch"]) in html
    assert nested_forms(html) == []
