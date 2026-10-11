"""Suggestions de modification d'une fiche : proposées par les membres sans droit d'édition, relues et appliquées par l'équipe."""
import pytest
from django.contrib.admin.models import CHANGE, LogEntry
from django.urls import reverse

from app.models import Beer, Brewery, ModerationEntry
from app.services.protection import throttle
from app.services.moderation import suggestions
from tests import factories as f
from tests.helpers import messages_of

pytestmark = pytest.mark.django_db

Action = ModerationEntry.Action


def url(kind, obj):
    return reverse("suggest_edit", args=[kind, obj.slug])


def beer_data(beer, **changes):
    return {"name": beer.name, "description": beer.description or "", "style": beer.style or "", "degree": str(beer.degree), "bitterness": "", **changes}


def place_data(place, **changes):
    fields = ("name", "description", "street", "postal_code", "city", "phone", "email", "website", "instagram", "facebook")
    return {name: getattr(place, name) or "" for name in fields} | changes


def pending_suggestions():
    return ModerationEntry.objects.pending().suggestions()


class TestMenu:
    def test_a_member_without_edit_rights_is_offered_the_suggestion(self, auth_client, beer):
        html = auth_client.get(reverse("beer_detail", args=[beer.slug])).content.decode()
        assert "Suggérer une modification" in html and 'id="modal_suggest"' in html and "Signaler" in html

    def test_the_form_is_prefilled_with_the_current_values(self, auth_client, other_user):
        beer = f.make_beer(name="Punk IPA", style="IPA", description="Houblonnée", added_by=other_user)
        html = auth_client.get(reverse("beer_detail", args=[beer.slug])).content.decode()
        modal = html[html.index('id="modal_suggest"'):]
        assert 'value="Punk IPA"' in modal and 'value="IPA"' in modal and "Houblonnée" in modal and 'aria-label="Fermer"' in modal

    def test_the_unverified_creator_edits_directly_and_gets_no_suggestion(self, auth_client, user):
        beer = f.make_beer(added_by=user)
        assert "Suggérer une modification" not in auth_client.get(reverse("beer_detail", args=[beer.slug])).content.decode()

    def test_the_creator_of_a_verified_beer_can_suggest(self, auth_client, user):
        beer = f.make_beer(added_by=user, is_verified=True)
        assert "Suggérer une modification" in auth_client.get(reverse("beer_detail", args=[beer.slug])).content.decode()

    def test_a_brewery_manager_edits_directly(self, auth_client, user):
        brewery = f.make_brewery(managers=[user])
        beer = f.make_beer(brewery=brewery)
        assert "Suggérer une modification" not in auth_client.get(reverse("beer_detail", args=[beer.slug])).content.decode()
        assert "Suggérer une modification" not in auth_client.get(reverse("brewery_detail", args=[brewery.slug])).content.decode()

    @pytest.mark.parametrize("maker, route", [(f.make_brewery, "brewery_detail"), (f.make_bar, "bar_detail")])
    def test_other_members_can_suggest_for_places(self, auth_client, maker, route):
        place = maker()
        assert "Suggérer une modification" in auth_client.get(reverse(route, args=[place.slug])).content.decode()

    def test_anonymous_visitors_are_not_offered_anything(self, client, beer):
        assert client.get(url("beer", beer)).status_code in (302, 405)


class TestPropose:
    def test_only_the_changed_fields_are_kept_and_nothing_is_applied(self, auth_client, user, beer):
        response = auth_client.post(url("beer", beer), beer_data(beer, description="Nouvelle description"))
        assert response.status_code == 302
        entry = pending_suggestions().get()
        assert (entry.kind, entry.action, entry.object_id, entry.suggested_by) == ("beer", Action.SUGGESTED, beer.pk, user)
        assert [(c["field"], c["new"]) for c in entry.changes] == [("description", "Nouvelle description")]
        beer.refresh_from_db()
        assert beer.description != "Nouvelle description"

    def test_a_confirmation_is_shown(self, auth_client, beer):
        response = auth_client.post(url("beer", beer), beer_data(beer, style="Stout"), follow=True)
        assert any("transmise" in message for message in messages_of(response))

    @pytest.mark.parametrize("maker, kind", [(f.make_brewery, "brewery"), (f.make_bar, "bar")])
    def test_places_work_the_same_way(self, auth_client, maker, kind):
        place = maker(name="Le Comptoir")
        auth_client.post(url(kind, place), place_data(place, city="Lille", phone="0320000000"))
        entry = pending_suggestions().get()
        assert entry.kind == kind and {c["field"] for c in entry.changes} == {"city", "phone"}

    def test_a_suggestion_without_any_change_is_refused(self, auth_client, beer):
        response = auth_client.post(url("beer", beer), beer_data(beer), follow=True)
        assert not pending_suggestions().exists() and any("Aucune modification" in m for m in messages_of(response))

    def test_a_second_pending_suggestion_on_the_same_fiche_is_refused(self, auth_client, beer):
        auth_client.post(url("beer", beer), beer_data(beer, style="Stout"))
        auth_client.post(url("beer", beer), beer_data(beer, style="Porter"))
        assert pending_suggestions().count() == 1

    def test_two_members_can_each_suggest(self, auth_client, client_for, beer):
        auth_client.post(url("beer", beer), beer_data(beer, style="Stout"))
        client_for(f.make_user()).post(url("beer", beer), beer_data(beer, style="Porter"))
        assert pending_suggestions().count() == 2

    def test_invalid_values_are_refused_with_the_models_rules(self, auth_client, other_user):
        place = f.make_brewery()
        response = auth_client.post(url("brewery", place), place_data(place, email="pas-un-email"), follow=True)
        assert not pending_suggestions().exists() and any("mail" in m.lower() for m in messages_of(response))

    def test_a_rename_that_collides_with_another_beer_of_the_brewery_is_refused(self, auth_client):
        brewery = f.make_brewery()
        f.make_beer(name="Blonde", brewery=brewery)
        other = f.make_beer(name="Brune", brewery=brewery)
        auth_client.post(url("beer", other), beer_data(other, name="Blonde"))
        assert not pending_suggestions().exists()

    def test_members_who_can_edit_are_refused(self, auth_client, user):
        brewery = f.make_brewery(managers=[user])
        auth_client.post(url("brewery", brewery), place_data(brewery, city="Lille"))
        assert not pending_suggestions().exists()

    def test_a_removed_beer_cannot_receive_suggestions(self, auth_client):
        beer = f.make_beer(is_deleted=True)
        auth_client.post(url("beer", beer), beer_data(beer, style="Stout"))
        assert not pending_suggestions().exists()

    @pytest.mark.parametrize("kind", ["user", "comment", "nonsense"])
    def test_other_types_of_content_are_not_suggestible(self, auth_client, beer, kind):
        auth_client.post(reverse("suggest_edit", args=[kind, beer.slug]), {"name": "x"})
        assert not pending_suggestions().exists()

    def test_only_post_is_accepted(self, auth_client, beer):
        assert auth_client.get(url("beer", beer)).status_code == 405

    def test_the_daily_limit_protects_the_team_from_floods(self, auth_client, monkeypatch):
        from datetime import timedelta
        monkeypatch.setattr(suggestions, "SUGGESTION_BY_USER", throttle.Rule("suggestion-test", 2, timedelta(days=1)))
        for _ in range(3):
            beer = f.make_beer()
            auth_client.post(url("beer", beer), beer_data(beer, style="Stout"))
        assert pending_suggestions().count() == 2

    def test_html_in_a_suggestion_is_stored_as_plain_text(self, auth_client, beer):
        auth_client.post(url("beer", beer), beer_data(beer, description="<script>alert(1)</script>Bonne"))
        entry = pending_suggestions().get()
        assert "<" not in entry.changes[0]["new"] and ">" not in entry.changes[0]["new"]

    def test_a_description_keeps_its_line_breaks(self, auth_client, beer):
        auth_client.post(url("beer", beer), beer_data(beer, description="Ligne 1\nLigne 2"))
        assert pending_suggestions().get().changes[0]["new"] == "Ligne 1\nLigne 2"

    def test_a_suggestion_never_creates_a_modification_entry_by_itself(self, auth_client, beer):
        before = ModerationEntry.objects.filter(action=Action.MODIFIED).count()
        auth_client.post(url("beer", beer), beer_data(beer, style="Stout"))
        assert ModerationEntry.objects.filter(action=Action.MODIFIED).count() == before


class TestReview:
    @pytest.fixture
    def suggestion(self, other_client, other_user):
        beer = f.make_beer(name="Punk IPA", style="IPA", description="Ancienne")
        other_client.post(url("beer", beer), beer_data(beer, description="Nouvelle description", style="Session IPA"))
        return pending_suggestions().get()

    def apply_url(self, entry):
        return reverse("admin:app_moderationentry_apply", args=[entry.pk])

    def dismiss_url(self, entry):
        return reverse("admin:app_moderationentry_dismiss", args=[entry.pk])

    def form_of(self, entry, **changes):
        beer = Beer.objects.get(pk=entry.object_id)
        return beer_data(beer, **suggestions.proposed_values(entry)) | changes

    def test_the_team_page_lists_the_suggestion_with_a_prefilled_form(self, client_for, staff, suggestion):
        html = client_for(staff).get(reverse("admin:app_moderationentry_changelist")).content.decode()
        assert "Suggestion" in html and "suggéré par" in html and "bobby" in html and "Nouvelle description" in html
        assert "Appliquer" in html and "Refuser" in html and 'name="description"' in html

    def test_applying_the_suggestion_updates_the_fiche(self, client_for, staff, suggestion):
        client_for(staff).post(self.apply_url(suggestion), self.form_of(suggestion))
        beer = Beer.objects.get(pk=suggestion.object_id)
        assert (beer.description, beer.style) == ("Nouvelle description", "Session IPA")
        suggestion.refresh_from_db()
        assert suggestion.reviewed_by == staff and suggestion.outcome == "applied"

    def test_the_team_can_adjust_the_values_before_applying(self, client_for, staff, suggestion):
        client_for(staff).post(self.apply_url(suggestion), self.form_of(suggestion, description="Version ajustée par l'équipe"))
        assert Beer.objects.get(pk=suggestion.object_id).description == "Version ajustée par l'équipe"

    def test_applying_does_not_create_a_new_entry_to_review(self, client_for, staff, suggestion):
        client_for(staff).post(self.apply_url(suggestion), self.form_of(suggestion))
        assert not ModerationEntry.objects.pending().filter(action=Action.MODIFIED).exists()

    def test_applying_leaves_an_audit_trail(self, client_for, staff, suggestion):
        client_for(staff).post(self.apply_url(suggestion), self.form_of(suggestion))
        log = LogEntry.objects.get(action_flag=CHANGE)
        assert log.user_id == staff.pk and "suggestion" in log.change_message

    def test_an_invalid_adjustment_is_refused_and_the_suggestion_stays_pending(self, client_for, staff, suggestion):
        client_for(staff).post(self.apply_url(suggestion), self.form_of(suggestion, degree="999"))
        suggestion.refresh_from_db()
        assert suggestion.reviewed_at is None and Beer.objects.get(pk=suggestion.object_id).description == "Ancienne"

    def test_dismissing_changes_nothing_and_needs_no_justification(self, client_for, staff, suggestion):
        client_for(staff).post(self.dismiss_url(suggestion))
        suggestion.refresh_from_db()
        assert suggestion.outcome == "dismissed" and suggestion.reviewed_by == staff
        assert Beer.objects.get(pk=suggestion.object_id).description == "Ancienne"

    def test_a_suggestion_is_decided_only_once(self, client_for, staff, suggestion):
        client = client_for(staff)
        client.post(self.dismiss_url(suggestion))
        client.post(self.apply_url(suggestion), self.form_of(suggestion))
        assert Beer.objects.get(pk=suggestion.object_id).description == "Ancienne"

    def test_members_cannot_decide(self, auth_client, suggestion):
        auth_client.post(self.apply_url(suggestion), self.form_of(suggestion))
        suggestion.refresh_from_db()
        assert suggestion.reviewed_at is None and Beer.objects.get(pk=suggestion.object_id).description == "Ancienne"

    def test_other_kinds_of_entries_cannot_be_applied_as_suggestions(self, client_for, staff):
        beer = f.make_beer()
        entry = ModerationEntry.objects.pending().get(object_id=beer.pk, kind="beer")
        client_for(staff).post(self.apply_url(entry), beer_data(beer, style="Hack"))
        assert Beer.objects.get(pk=beer.pk).style != "Hack" and ModerationEntry.objects.get(pk=entry.pk).reviewed_at is None

    def test_places_are_decided_by_superusers_only_like_their_removal(self, client_for, staff, superuser, other_client):
        brewery = f.make_brewery(name="Le Comptoir")
        other_client.post(url("brewery", brewery), place_data(brewery, city="Lille"))
        entry = pending_suggestions().get()
        data = place_data(brewery, city="Lille")
        client_for(staff).post(self.apply_url(entry), data)
        assert Brewery.objects.get(pk=brewery.pk).city != "Lille"
        client_for(superuser).post(self.apply_url(entry), data)
        assert Brewery.objects.get(pk=brewery.pk).city == "Lille"

    def test_a_suggestion_whose_fiche_disappeared_is_refused_cleanly(self, client_for, staff, suggestion):
        Beer.objects.filter(pk=suggestion.object_id).delete()
        assert client_for(staff).post(self.apply_url(suggestion), {}).status_code == 302

    def test_decided_suggestions_move_to_the_validated_list_with_their_outcome(self, client_for, staff, suggestion):
        client = client_for(staff)
        client.post(self.dismiss_url(suggestion))
        html = client.get(reverse("admin:app_moderationentry_changelist"), {"state": "done"}).content.decode()
        assert "Refusée" in html

    def test_the_suggestions_tab_counts_pending_ones(self, client_for, staff, suggestion):
        html = client_for(staff).get(reverse("admin:app_moderationentry_changelist"), {"action": "suggested"}).content.decode()
        assert "Suggestions (1)" in html


class TestAmendDuringValidation:
    """L'équipe peut retoucher les champs d'une création ou d'une modification au moment de la valider."""

    def amend_url(self, entry):
        return reverse("admin:app_moderationentry_amend", args=[entry.pk])

    def entry_of(self, kind, obj, action=Action.CREATED):
        return ModerationEntry.objects.pending().filter(action=action).get(kind=kind, object_id=obj.pk)

    def test_the_page_offers_the_form_on_a_creation(self, client_for, staff):
        f.make_beer(name="Punk IPA")
        html = client_for(staff).get(reverse("admin:app_moderationentry_changelist")).content.decode()
        assert "Modifier avant de valider" in html and "Enregistrer &amp; valider" in html and 'name="degree"' in html

    def test_amending_a_creation_updates_the_fiche_and_validates_the_entry(self, client_for, staff):
        beer = f.make_beer(name="Punk IPAA", description="avant")
        entry = self.entry_of("beer", beer)
        client_for(staff).post(self.amend_url(entry), beer_data(beer, name="Punk IPA", description="corrigée"))
        beer.refresh_from_db()
        assert (beer.name, beer.description) == ("Punk IPA", "corrigée")
        entry.refresh_from_db()
        assert entry.reviewed_by == staff and entry.reviewed_at

    def test_the_team_edit_does_not_create_another_entry_to_review(self, client_for, staff):
        beer = f.make_beer(name="Punk IPAA")
        client_for(staff).post(self.amend_url(self.entry_of("beer", beer)), beer_data(beer, name="Punk IPA"))
        assert not ModerationEntry.objects.pending().filter(kind="beer").exists()

    def test_a_modification_can_be_amended_too(self, client_for, staff):
        beer = f.make_beer(description="a")
        ModerationEntry.objects.pending().filter(object_id=beer.pk).update(reviewed_at="2026-01-01T00:00:00Z")
        beer.description = "texte douteux"
        beer.save()
        entry = self.entry_of("beer", beer, Action.MODIFIED)
        client_for(staff).post(self.amend_url(entry), beer_data(beer, description="texte nettoyé"))
        beer.refresh_from_db()
        assert beer.description == "texte nettoyé" and ModerationEntry.objects.get(pk=entry.pk).reviewed_at

    def test_a_superuser_amending_a_creation_also_certifies_it(self, client_for, superuser, staff):
        beer = f.make_beer(name="Punk IPA")
        client_for(superuser).post(self.amend_url(self.entry_of("beer", beer)), beer_data(beer, style="IPA"))
        beer.refresh_from_db()
        assert beer.is_verified and beer.style == "IPA"

    def test_a_staff_member_validates_without_certifying(self, client_for, staff):
        beer = f.make_beer(name="Punk IPA")
        client_for(staff).post(self.amend_url(self.entry_of("beer", beer)), beer_data(beer, style="IPA"))
        beer.refresh_from_db()
        assert not beer.is_verified and beer.style == "IPA"

    def test_places_need_a_superuser_like_their_validation(self, client_for, staff, superuser):
        brewery = f.make_brewery(name="Le Comptoir")
        entry = self.entry_of("brewery", brewery)
        data = place_data(brewery, city="Lille")
        client_for(staff).post(self.amend_url(entry), data)
        assert Brewery.objects.get(pk=brewery.pk).city != "Lille"
        client_for(superuser).post(self.amend_url(entry), data)
        assert Brewery.objects.get(pk=brewery.pk).city == "Lille"

    def test_an_invalid_retouch_keeps_the_entry_pending(self, client_for, staff):
        beer = f.make_beer(name="Punk IPA")
        entry = self.entry_of("beer", beer)
        client_for(staff).post(self.amend_url(entry), beer_data(beer, degree="999"))
        assert ModerationEntry.objects.get(pk=entry.pk).reviewed_at is None

    def test_html_is_stripped_from_the_retouched_values(self, client_for, staff):
        beer = f.make_beer(name="Punk IPA")
        client_for(staff).post(self.amend_url(self.entry_of("beer", beer)), beer_data(beer, description="<b>gras</b>"))
        assert Beer.objects.get(pk=beer.pk).description == "bgras/b"

    def test_comments_have_no_form_and_cannot_be_amended(self, client_for, staff, user):
        drink = f.make_drink(user)
        entry = ModerationEntry.objects.pending().get(kind="comment", object_id=drink.pk)
        client_for(staff).post(self.amend_url(entry), {"comment": "x"})
        assert ModerationEntry.objects.get(pk=entry.pk).reviewed_at is None

    def test_a_suggestion_cannot_be_amended_through_this_door(self, client_for, staff, other_client):
        beer = f.make_beer(added_by=None)
        other_client.post(url("beer", beer), beer_data(beer, style="Stout"))
        entry = pending_suggestions().get()
        client_for(staff).post(self.amend_url(entry), beer_data(beer, style="Hack"))
        assert Beer.objects.get(pk=beer.pk).style != "Hack" and ModerationEntry.objects.get(pk=entry.pk).reviewed_at is None

    def test_an_entry_is_amended_only_once(self, client_for, staff):
        beer = f.make_beer(name="Punk IPAA")
        entry = self.entry_of("beer", beer)
        client = client_for(staff)
        client.post(self.amend_url(entry), beer_data(beer, name="Punk IPA"))
        client.post(self.amend_url(entry), beer_data(beer, name="Autre"))
        assert Beer.objects.get(pk=beer.pk).name == "Punk IPA"

    def test_members_cannot_amend(self, auth_client, staff):
        beer = f.make_beer(name="Punk IPAA")
        auth_client.post(self.amend_url(self.entry_of("beer", beer)), beer_data(beer, name="Hack"))
        assert Beer.objects.get(pk=beer.pk).name == "Punk IPAA"

    def test_the_retouch_leaves_an_audit_trail(self, client_for, staff):
        beer = f.make_beer(name="Punk IPAA")
        client_for(staff).post(self.amend_url(self.entry_of("beer", beer)), beer_data(beer, name="Punk IPA"))
        log = LogEntry.objects.get(action_flag=CHANGE)
        assert log.user_id == staff.pk and "retouché" in log.change_message and "name" in log.change_message
