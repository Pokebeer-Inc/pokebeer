import re
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from app.models import Beer, BeerUser, Brewery, Drinks, Notification, Report
from tests import factories as f

pytestmark = pytest.mark.django_db


class TestBeerSlug:
    def test_slug_is_ascii_lowercase_and_ends_with_a_random_token(self):
        assert re.fullmatch(r"punk-ipa-[a-z0-9]{12}", f.make_beer(name="Pünk I.P.A").slug)

    def test_same_name_gives_distinct_slugs(self):
        slugs = [f.make_beer(name=name).slug for name in ("Kölsch", "Kolsch", "KOLSCH!")]
        assert len(set(slugs)) == 3 and all(slug.startswith("kolsch-") for slug in slugs)

    def test_slug_is_stable_when_beer_is_renamed(self):
        beer = f.make_beer(name="Original")
        slug = beer.slug
        beer.name = "Renamed"
        beer.save()
        beer.refresh_from_db()
        assert beer.slug == slug


class TestBeerEmbedding:
    def test_save_succeeds_without_embedding_when_ai_is_unavailable(self):
        assert f.make_beer().embedding is None

    def test_save_stores_embedding_built_from_beer_profile(self, monkeypatch):
        received = []
        monkeypatch.setattr("app.services.ai.get_embedding", lambda text: received.append(text) or [0.5] * 3072)

        beer = f.make_beer(name="Rousse", style="Amber", description="Caramel", brewery=f.make_brewery(name="Mont"))

        beer.refresh_from_db()
        assert len(beer.embedding) == 3072
        assert all(keyword in received[0] for keyword in ("Rousse", "Mont", "Amber", "Caramel"))


class TestBeerEmbeddingRefresh:
    @pytest.fixture
    def embed_calls(self, monkeypatch):
        calls = []
        monkeypatch.setattr("app.services.ai.get_embedding", lambda text: calls.append(text) or [0.5] * 3072)
        return calls

    @pytest.fixture
    def embedded_beer(self, embed_calls):
        beer = f.make_beer(name="Rousse", style="Amber")
        embed_calls.clear()
        return type(beer).objects.get(pk=beer.pk)

    def save(self, beer, django_capture_on_commit_callbacks, **changes):
        for field, value in changes.items():
            setattr(beer, field, value)
        with django_capture_on_commit_callbacks(execute=True):
            beer.save()

    @pytest.mark.parametrize("changes", [{"is_deleted": True}, {"degree": 7}, {"bitterness": 40}])
    def test_unrelated_changes_do_not_call_gemini(self, embedded_beer, embed_calls, django_capture_on_commit_callbacks, changes):
        self.save(embedded_beer, django_capture_on_commit_callbacks, **changes)
        assert embed_calls == []

    @pytest.mark.parametrize("changes", [{"name": "Brune"}, {"style": "Stout"}, {"description": "Café"}])
    def test_profile_changes_recompute_the_vector(self, embedded_beer, embed_calls, django_capture_on_commit_callbacks, changes):
        self.save(embedded_beer, django_capture_on_commit_callbacks, **changes)
        assert len(embed_calls) == 1

    def test_beer_without_vector_is_retried_on_next_save(self, embed_calls, monkeypatch, django_capture_on_commit_callbacks):
        monkeypatch.setattr("app.services.ai.get_embedding", lambda text: None)
        beer = f.make_beer()
        monkeypatch.setattr("app.services.ai.get_embedding", lambda text: embed_calls.append(text) or [0.5] * 3072)
        self.save(beer, django_capture_on_commit_callbacks, degree=6)
        assert len(embed_calls) == 1

    def test_no_network_call_while_the_transaction_is_open(self, embed_calls, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            beer = Beer.objects.create(name="Blonde", brewery_id=f.make_brewery(), degree=5)
        assert embed_calls == [] and len(callbacks) == 1
        callbacks[0]()
        assert len(embed_calls) == 1


class TestFieldLimits:
    @pytest.mark.parametrize("note, valid", [(None, True), (0, True), (10, True), (-1, False), (11, False)])
    def test_drink_note_is_bounded_between_0_and_10(self, user, beer, note, valid):
        drink = Drinks(drinker_id=user, beer_id=beer, note=note, comment="ok")
        self._assert_validity(drink, valid)

    @pytest.mark.parametrize("degree, valid", [("0", True), ("100.0", True), ("-0.1", False), ("100.1", False)])
    def test_beer_degree_is_a_percentage(self, brewery, degree, valid):
        self._assert_validity(Beer(name=f.unique("Deg"), brewery_id=brewery, degree=Decimal(degree)), valid)

    @pytest.mark.parametrize("ibu, valid", [(None, True), (0, True), (500, True), (-1, False), (501, False)])
    def test_beer_bitterness_is_bounded(self, brewery, ibu, valid):
        self._assert_validity(Beer(name=f.unique("Ibu"), brewery_id=brewery, bitterness=ibu), valid)

    @pytest.mark.parametrize("reason, valid", [("spam", True), ("other", True), ("hack", False), ("", False)])
    def test_report_reason_must_be_a_known_choice(self, user, reason, valid):
        self._assert_validity(Report(reporter=user, reason=reason, description="desc"), valid)

    @staticmethod
    def _assert_validity(instance, valid):
        if valid:
            instance.full_clean()
        else:
            with pytest.raises(ValidationError):
                instance.full_clean()


class TestUniqueness:
    @pytest.mark.parametrize("create_twice", [
        lambda a, b, drink: (f.follow(a, b), f.follow(a, b)),
        lambda a, b, drink: (f.block(a, b), f.block(a, b)),
        lambda a, b, drink: (f.react(b, drink), f.react(b, drink, is_like=False)),
    ], ids=["follow", "block", "reaction"])
    def test_relation_cannot_be_duplicated(self, user, other_user, create_twice):
        drink = f.make_drink(user)
        with pytest.raises(IntegrityError), transaction.atomic():
            create_twice(user, other_user, drink)

    def test_user_email_is_unique(self, user):
        with pytest.raises(IntegrityError), transaction.atomic():
            f.make_user(email=user.email)

    def test_two_active_beers_of_a_brewery_cannot_share_a_name(self, beer):
        with pytest.raises(IntegrityError), transaction.atomic():
            f.make_beer(name=beer.name, brewery=beer.brewery_id)

    def test_two_breweries_can_each_have_their_own_beer_of_the_same_name(self, beer):
        other = f.make_beer(name=beer.name, brewery=f.make_brewery(name="Autre Brasserie"))
        assert other.pk != beer.pk and Beer.objects.filter(name=beer.name, is_deleted=False).count() == 2

    def test_soft_deleted_beer_frees_its_name_but_keeps_its_slug(self, beer):
        Beer.objects.filter(pk=beer.pk).update(is_deleted=True)
        again = f.make_beer(name=beer.name)
        assert again.slug != beer.slug and Beer.objects.get(pk=beer.pk).slug == beer.slug

    def test_restoring_a_beer_whose_name_was_reused_is_refused(self, beer):
        Beer.objects.filter(pk=beer.pk).update(is_deleted=True)
        f.make_beer(name=beer.name, brewery=beer.brewery_id)
        beer.refresh_from_db()
        beer.is_deleted = False
        with pytest.raises(ValidationError):
            beer.validate_constraints()


class TestRoles:
    def test_new_user_is_contributor_by_default(self, user):
        assert user.is_contributor
        assert not (user.is_brewer or user.is_bartender or user.is_staff)

    @pytest.mark.parametrize("factory, role", [(f.make_brewery, "is_brewer"), (f.make_bar, "is_bartender")])
    def test_managing_an_establishment_grants_the_role(self, user, factory, role):
        factory(managers=[user])
        assert getattr(BeerUser.objects.get(pk=user.pk), role)

    @pytest.mark.parametrize("factory, role", [(f.make_brewery, "is_brewer"), (f.make_bar, "is_bartender")])
    def test_role_is_kept_while_user_still_manages_another_establishment(self, user, factory, role):
        first, _ = factory(managers=[user]), factory(managers=[user])
        first.managers.remove(user)
        assert getattr(BeerUser.objects.get(pk=user.pk), role)

    @pytest.mark.parametrize("factory, role", [(f.make_brewery, "is_brewer"), (f.make_bar, "is_bartender")])
    @pytest.mark.parametrize("revoke", [lambda place, u: place.managers.remove(u), lambda place, u: place.managers.clear()],
                             ids=["remove", "clear"])
    def test_role_is_revoked_with_the_last_establishment(self, user, factory, role, revoke):
        place = factory(managers=[user])
        revoke(place, user)
        assert not getattr(BeerUser.objects.get(pk=user.pk), role)

    @pytest.mark.parametrize("groups, superuser, expected", [
        ((), True, "Staff"),
        (("Staff",), False, "Staff"),
        (("Brasseur", "Bartender"), False, "Brasseur & Gérant"),
        (("Brasseur",), False, "Brasseur"),
        (("Bartender",), False, "Gérant de Bar"),
        ((), False, "Contributeur"),
    ])
    def test_primary_role_badge_picks_highest_role(self, groups, superuser, expected):
        member = f.make_user(groups=groups, is_superuser=superuser)
        assert member.primary_role_badge["name"] == expected

    def test_member_without_any_group_gets_default_badge(self, user):
        user.groups.clear()
        assert user.primary_role_badge["name"] == "Membre"

    @pytest.mark.parametrize("is_pro, show, expected", [(True, True, True), (True, False, False), (False, True, False)])
    def test_public_establishments_require_pro_role_and_consent(self, is_pro, show, expected):
        member = f.make_user(show_establishments=show, groups=("Brasseur",) if is_pro else ())
        assert member.has_public_establishments is expected


class TestNotificationPreferences:
    PREFERENCE_BY_TYPE = {
        "follow": "notif_follow",
        "drink_liked": "notif_social",
        "wishlist_added": "notif_social",
        "achievement": "notif_achievements",
        "beer_added": "notif_network",
        "beer_shared": "notif_network",
        "spot_invite": "notif_network",
        "spot_updated": "notif_network",
        "beer_updated": "notif_network",
        "manager_added": "notif_establishment",
        "manager_removed": "notif_establishment",
        "place_updated": "notif_establishment",
        "beer_added_to_brewery": "notif_establishment",
        "beer_updated_by_manager": "notif_establishment",
        "beer_deleted_by_manager": "notif_establishment",
    }
    SYSTEM_TYPES = ["report_updated", "feedback_replied", "content_removed"]

    @pytest.mark.parametrize("notif_type, preference", PREFERENCE_BY_TYPE.items())
    def test_disabled_category_blocks_only_its_notifications(self, notif_type, preference):
        recipient = f.make_user(**{preference: False})
        assert f.make_notification(recipient, notif_type).pk is None
        untouched = next(t for t, p in self.PREFERENCE_BY_TYPE.items() if p != preference)
        assert f.make_notification(recipient, untouched).pk is not None

    @pytest.mark.parametrize("notif_type", PREFERENCE_BY_TYPE)
    def test_global_switch_blocks_every_user_notification(self, notif_type):
        recipient = f.make_user(notif_global=False)
        f.make_notification(recipient, notif_type)
        assert not Notification.objects.exists()

    @pytest.mark.parametrize("notif_type", SYSTEM_TYPES)
    def test_system_messages_ignore_preferences(self, notif_type):
        recipient = f.make_user(notif_global=False)
        assert f.make_notification(recipient, notif_type).pk is not None

    def test_bulk_create_drops_refused_notifications(self, user):
        muted = f.make_user(notif_follow=False)
        created = Notification.objects.bulk_create([
            Notification(recipient=user, notif_type="follow"),
            Notification(recipient=muted, notif_type="follow"),
        ])
        assert [n.recipient for n in created] == [user]

    def test_bulk_create_with_only_refused_notifications_returns_empty_list(self):
        muted = f.make_user(notif_global=False)
        assert Notification.objects.bulk_create([Notification(recipient=muted, notif_type="follow")]) == []

    def test_existing_notification_can_still_be_updated_after_opt_out(self, user):
        notification = f.make_notification(user)
        BeerUser.objects.filter(pk=user.pk).update(notif_global=False)
        notification.recipient.refresh_from_db()
        notification.is_read = True
        notification.save()
        assert Notification.objects.get(pk=notification.pk).is_read

    def test_unread_flag_reflects_unread_notifications(self, user):
        assert not user.has_unread_notifications
        notification = f.make_notification(user)
        assert user.has_unread_notifications
        notification.is_read = True
        notification.save()
        assert not user.has_unread_notifications


class TestNotificationTimeAgo:
    @pytest.mark.parametrize("delta, expected", [
        (timedelta(seconds=0), "à l'instant"),
        (timedelta(seconds=59), "à l'instant"),
        (timedelta(minutes=1), "1 min"),
        (timedelta(minutes=59, seconds=59), "59 min"),
        (timedelta(hours=1), "1h"),
        (timedelta(hours=23, minutes=59), "23h"),
        (timedelta(days=1), "1 j"),
        (timedelta(days=400), "400 j"),
    ])
    def test_time_ago_boundaries(self, delta, expected):
        assert Notification(created_at=timezone.now() - delta).time_ago == expected


class TestGeocoding:
    def test_creation_geocodes_the_address(self, geocoder):
        brewery = f.make_brewery(address="1 rue de la Soif, Paris")
        assert (brewery.latitude, brewery.longitude) == (48.8566, 2.3522)
        assert geocoder.call_args.kwargs["params"]["q"] == "1 rue de la Soif, Paris"
        assert geocoder.call_args.kwargs["timeout"] > 0

    def test_unchanged_address_is_not_geocoded_again(self, geocoder):
        brewery = f.make_brewery(address="Lille")
        brewery.name = "Nouveau nom"
        brewery.save()
        assert geocoder.call_count == 1

    def test_changed_address_is_geocoded_again(self, geocoder):
        bar = f.make_bar(address="Lille")
        bar.address = "Lyon"
        bar.save()
        assert geocoder.call_count == 2

    def test_empty_address_clears_coordinates_without_api_call(self, geocoder):
        brewery = f.make_brewery(address=None, latitude=1.0, longitude=1.0)
        assert (brewery.latitude, brewery.longitude) == (None, None)
        geocoder.assert_not_called()

    def test_unknown_address_clears_coordinates(self, geocoder):
        geocoder.return_value.json.return_value = []
        assert f.make_bar(address="Nulle part").latitude is None

    @pytest.mark.parametrize("failure", [
        {"side_effect": ConnectionError("down")},
        {"return_value": type("Response", (), {"status_code": 503})()},
    ], ids=["network-error", "http-error"])
    def test_geocoding_failure_never_blocks_the_save(self, geocoder, failure):
        geocoder.configure_mock(**failure)
        brewery = f.make_brewery(address="Paris")
        assert Brewery.objects.filter(pk=brewery.pk).exists()
        assert brewery.latitude is None

    @pytest.mark.parametrize("failure", [
        {"side_effect": ConnectionError("down")},
        {"return_value": type("Response", (), {"status_code": 503})()},
    ], ids=["network-error", "http-error"])
    def test_failure_after_an_address_change_drops_the_old_coordinates(self, geocoder, failure):
        bar = f.make_bar(address="Paris")
        assert bar.latitude is not None
        geocoder.configure_mock(**failure)
        bar.address = "Lyon"
        bar.save()
        bar.refresh_from_db()
        assert (bar.latitude, bar.longitude) == (None, None)

    def test_geocoding_timeout_is_short(self, geocoder):
        f.make_bar(address="Paris")
        assert geocoder.call_args.kwargs["timeout"] <= 2


class TestStringRepresentations:
    def test_str_is_human_readable(self, user, beer):
        drink = f.make_drink(user, beer, note=8)
        assert str(drink) == "alice - Test IPA (8/10)"
        assert str(beer) == "Test IPA"
        assert str(f.block(user, beer.added_by)) == "alice a bloqué bobby"
        assert "alice" in str(f.make_report(user))
