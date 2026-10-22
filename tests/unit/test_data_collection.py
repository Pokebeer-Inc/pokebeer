"""Référentiel des styles, opposition aux statistiques d'âge et de genre, rappel de contexte et trophée associé."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from app.domain import styles as style_rules
from app.models import Beer, Drinks, Notification, Style, StyleFamily
from app.services.analytics import profiles
from app.services.analytics.custom import engine
from app.services.analytics.periods import Period
from app.services.catalog import context_reminders, style_registry
from app.services.members.achievements import get_user_achievements
from tests import factories as f

pytestmark = pytest.mark.django_db


class TestStyleRules:
    CATALOG = {"ipa": "IPA", "india pale ale": "IPA", "ambree": "Ambrée", "amber ale": "Ambrée"}

    @pytest.mark.parametrize("raw, expected", [
        ("ipa", "IPA"), ("India Pale Ale", "IPA"), ("AMBREE, amber ale", "Ambrée"), ("inconnu, IPA", "Inconnu, IPA"), ("", ""), (",,", ""),
    ])
    def test_known_styles_get_their_official_name_and_unknown_ones_are_only_formatted(self, raw, expected):
        assert style_rules.canonicalize(raw, self.CATALOG) == expected

    def test_family_comes_from_the_first_recognised_style(self):
        families = {"IPA": "IPA", "Stout": "Brune"}
        assert style_rules.family_of("Inconnu, Stout, IPA", families) == "Brune"
        assert style_rules.family_of("Inconnu", families) == ""

    def test_keys_ignore_case_accents_and_spaces(self):
        assert style_rules.style_key("  Ambrée   Ale ") == "ambree ale"


class TestStyleRegistry:
    def test_a_beer_is_normalised_whatever_the_way_it_is_saved(self):
        beer = f.make_beer(style="west coast ipa, india pale ale")
        beer.refresh_from_db()
        assert (beer.style, beer.style_family_name) == ("West Coast IPA, IPA", "IPA")
        assert list(beer.styles.order_by("beer_styles__position").values_list("name", flat=True)) == ["West Coast IPA", "IPA"]

    def test_unknown_style_is_kept_as_a_style_to_validate_without_family(self):
        beer = f.make_beer(style="Zythos exotique")
        beer.refresh_from_db()
        assert (beer.style, beer.style_family_name) == ("Zythos exotique", "")
        pending = Style.objects.get(name="Zythos exotique")
        assert not pending.is_official and pending.family is None and beer.primary_style == pending

    def test_editing_the_registry_applies_to_new_saves_immediately(self):
        family = StyleFamily.objects.create(name="Fermière")
        Style.objects.create(name="Fermette", family=family, aliases="Farmhouse\nRustique")
        beer = f.make_beer(style="farmhouse")
        beer.refresh_from_db()
        assert (beer.style, beer.style_family_name) == ("Fermette", "Fermière")

    def test_partial_save_of_the_style_keeps_the_family_in_step(self):
        beer = f.make_beer(style="Stout")
        beer.style = "IPA"
        beer.save(update_fields=["style"])
        beer.refresh_from_db()
        assert (beer.style, beer.style_family_name, beer.primary_style.name) == ("IPA", "IPA", "IPA")

    def test_renormalize_updates_only_what_changed(self):
        beer = f.make_beer(style="Stout")
        Beer.objects.filter(pk=beer.pk).update(style="stout")  # écriture qui contourne le référentiel
        Style.objects.filter(name="Stout").update(aliases="Dry Stout")
        assert style_registry.renormalize_all() == 1 and style_registry.renormalize_all() == 0
        beer.refresh_from_db()
        assert (beer.style, beer.style_family_name) == ("Stout", "Brune, porter et stout")

    def test_command_reports_the_count(self, capsys):
        call_command("normalize_styles")
        assert "bière(s) mise(s) à jour" in capsys.readouterr().out

    def test_recognised(self):
        assert style_registry.recognized("IPA, Stout") and not style_registry.recognized("IPA, Zythos")


class TestOptOut:
    def test_the_setting_is_saved_from_the_account_page(self, auth_client, user):
        assert user.demographic_stats is True
        response = auth_client.post(reverse("account_settings", args=["privacy"]), {"btn_stats": ""})
        assert response.status_code == 302
        user.refresh_from_db()
        assert user.demographic_stats is False
        auth_client.post(reverse("account_settings", args=["privacy"]), {"btn_stats": "", "demographic_stats": "on"})
        user.refresh_from_db()
        assert user.demographic_stats is True

    def test_opposed_members_are_left_out_of_every_segment(self, superuser):
        beer = f.make_beer(style="IPA")
        today = timezone.localdate()
        for index in range(4):
            member = f.make_user(username=f.unique("m_"), birth_date=today.replace(year=today.year - 25 - index), gender="homme",
                                 demographic_stats=index != 0)
            f.make_drink(member, beer)
        segments = profiles.segments(Drinks.objects.all(), today)
        assert len(segments) == 3

    def test_custom_age_and_gender_groupings_ignore_opposed_members(self, superuser):
        beer = f.make_beer(style="IPA")
        today = timezone.localdate()
        for index in range(4):
            member = f.make_user(username=f.unique("m_"), birth_date=today.replace(year=today.year - 30), gender="femme", demographic_stats=index > 0)
            f.make_drink(member, beer)
        for dimension in ("age", "gender"):
            spec = {"dataset": "drinks", "dimension": dimension, "measures": ["count"], "chart": "table", "limit": 10, "sort": "value_desc"}
            assert engine.build_block(1, "T", spec, Period(12, "month")).rows[0][1] == 3
        members = {"dataset": "members", "dimension": "gender", "measures": ["count"], "chart": "table", "limit": 10, "sort": "value_desc"}
        assert engine.build_block(1, "T", members, Period(12, "month")).rows[0][1] == 3

    def test_default_threshold_is_never_below_three(self, settings):
        assert settings.ANALYTICS_MIN_GROUP_SIZE >= 3


class TestContextTrophy:
    def test_only_complete_tastings_count(self, user):
        beer_args = {"venue_type": "bar", "serving_format": "pint", "price": Decimal("5.0")}
        for _ in range(5):
            f.make_drink(user, **beer_args)
        f.make_drink(user, venue_type="bar")  # incomplet
        achievements, _ = get_user_achievements(user)
        trophy = next(a for a in achievements if a["slug"] == "chroniqueur")
        assert trophy["tier_level"] == 1


class TestContextReminders:
    def old_drink(self, user, hours=30, **fields):
        drink = f.make_drink(user, **fields)
        Drinks.objects.filter(pk=drink.pk).update(created_at=timezone.now() - timedelta(hours=hours))
        return drink

    def test_a_member_with_an_old_bare_tasting_gets_one_reminder_for_the_latest(self, user):
        self.old_drink(user, hours=100)
        latest = self.old_drink(user, hours=30)
        assert context_reminders.send_pending() == 1
        reminder = Notification.objects.get(notif_type="context_reminder")
        assert reminder.recipient == user and reminder.beer == latest.beer

    def test_nothing_for_recent_complete_or_already_reminded_tastings(self, user, other_user):
        self.old_drink(user, hours=2)  # trop récente : le membre est peut-être encore en train de la saisir
        self.old_drink(other_user, venue_type="home")  # un contexte partiel suffit
        assert context_reminders.send_pending() == 0

    def test_cooldown_between_two_reminders(self, user):
        self.old_drink(user)
        assert context_reminders.send_pending() == 1
        self.old_drink(user, hours=40)
        assert context_reminders.send_pending() == 0

    def test_preferences_are_respected(self, user):
        user.notif_achievements = False
        user.save(update_fields=["notif_achievements"])
        self.old_drink(user)
        assert context_reminders.send_pending() == 0 and not Notification.objects.exists()
