"""Pages qui suivent l'inscription : date de naissance (obligatoire, majorité) puis genre (facultatif), imposées à tous les nouveaux comptes."""
from datetime import date, timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from app.models import BeerUser, ThrottleHit
from app.validators import MIN_AGE, age_on, validate_adult_birth_date
from django.core.exceptions import ValidationError
from tests import factories as f

pytestmark = pytest.mark.django_db


def adult_birth(years=30):
    today = timezone.localdate()
    return (today.replace(year=today.year - years, day=1) - timedelta(days=1)).isoformat()  # une date sans ambiguïté de jour


@pytest.fixture
def newcomer(client):
    member = f.make_user(onboarding_done=False)
    client.force_login(member)
    return member


class TestAgeRules:
    @pytest.mark.parametrize("birth, today, age", [
        (date(2000, 5, 10), date(2026, 5, 10), 26), (date(2000, 5, 10), date(2026, 5, 9), 25),
        (date(2008, 10, 11), date(2026, 10, 10), 17), (date(2008, 10, 11), date(2026, 10, 11), 18),
        (date(2004, 2, 29), date(2026, 2, 28), 21), (date(2004, 2, 29), date(2026, 3, 1), 22),
    ])
    def test_age_counts_whole_years(self, birth, today, age):
        assert age_on(birth, today) == age

    def test_the_day_of_the_18th_birthday_is_enough_and_the_day_before_is_not(self):
        today = date(2026, 10, 11)
        validate_adult_birth_date(date(2008, 10, 11), today)
        with pytest.raises(ValidationError) as underage:
            validate_adult_birth_date(date(2008, 10, 12), today)
        assert underage.value.code == "underage"

    @pytest.mark.parametrize("bad", [date(2099, 1, 1), date(1899, 12, 31)])
    def test_impossible_dates_are_invalid(self, bad):
        with pytest.raises(ValidationError) as error:
            validate_adult_birth_date(bad, date(2026, 10, 11))
        assert error.value.code == "invalid_birth_date"


class TestTheGuard:
    def test_a_new_member_is_sent_to_the_onboarding_instead_of_the_home(self, client, newcomer):
        response = client.get(reverse("index"))
        assert response.status_code == 302 and response.url == reverse("onboarding")

    @pytest.mark.parametrize("name", ["map", "notebook", "account", "add_beer", "all_beers", "achievements"])
    def test_every_page_is_closed_until_the_onboarding_is_done(self, client, newcomer, name):
        assert client.get(reverse(name)).url == reverse("onboarding")

    def test_writes_and_api_calls_are_refused_not_redirected(self, client, newcomer):
        assert client.post(reverse("add_beer"), {}).status_code == 403
        assert client.get(reverse("api_places"), HTTP_ACCEPT="application/json").status_code == 403
        assert client.post(reverse("save_beer_draft"), {"step": 1}).status_code == 403

    def test_the_onboarding_logout_and_policy_stay_reachable(self, client, newcomer):
        assert client.get(reverse("onboarding_birth")).status_code == 200
        assert client.get(reverse("privacy_policy")).status_code in (301, 302)
        assert client.get(reverse("logout")).status_code in (200, 302)

    def test_existing_and_finished_members_are_not_affected(self, auth_client):
        assert auth_client.get(reverse("index")).status_code == 200

    def test_the_page_first_requested_is_opened_after_the_onboarding(self, client, newcomer):
        client.get(reverse("map"), HTTP_SEC_FETCH_DEST="document")
        client.post(reverse("onboarding_birth"), {"birth_date": adult_birth()})
        response = client.post(reverse("onboarding_gender"), {"skip": "1"})
        assert response.status_code == 302 and response.url == reverse("map")

    @pytest.mark.parametrize("probe", ["/.well-known/appspecific/com.chrome.devtools.json", "/favicon.ico", "/apple-touch-icon.png"])
    def test_automatic_browser_requests_are_never_kept_as_the_destination(self, client, newcomer, probe):
        client.get(probe)  # sans Sec-Fetch-Dest: document, comme les requêtes automatiques du navigateur
        client.post(reverse("onboarding_birth"), {"birth_date": adult_birth()})
        assert client.post(reverse("onboarding_gender"), {"skip": "1"}).url == reverse("index")

    def test_a_stored_address_that_leads_nowhere_ends_on_the_home_page(self, client, newcomer):
        session = client.session
        session["onboarding_next"] = "/.well-known/appspecific/com.chrome.devtools.json"
        session.save()
        client.post(reverse("onboarding_birth"), {"birth_date": adult_birth()})
        assert client.post(reverse("onboarding_gender"), {"skip": "1"}).url == reverse("index")

    def test_the_android_asset_links_file_is_never_intercepted(self, client, newcomer):
        assert client.get("/.well-known/assetlinks.json").status_code != 302

    def test_a_foreign_target_is_never_followed(self, client, newcomer):
        session = client.session
        session["onboarding_next"] = "https://evil.example/phish"
        session.save()
        client.post(reverse("onboarding_birth"), {"birth_date": adult_birth()})
        assert client.post(reverse("onboarding_gender"), {"skip": "1"}).url == reverse("index")

    def test_anonymous_visitors_are_asked_to_log_in(self, client):
        for name in ("onboarding", "onboarding_birth", "onboarding_gender"):
            assert client.get(reverse(name)).status_code == 302 and "login" in client.get(reverse(name)).url


class TestBirthDateStep:
    def test_the_page_explains_why_the_date_is_needed(self, client, newcomer):
        html = client.get(reverse("onboarding_birth")).content.decode()
        for needle in ("Votre date de naissance", "majeur", "18 ans révolus", "jamais affichée", "obligatoire", "Étape", 'type="date"', reverse("privacy_policy")):
            assert needle in html
        assert "Passer" not in html  # cette étape ne se passe pas
        assert 'id="chat-toggle"' not in html and "Navigation principale" not in html  # pas de menu pendant l'inscription

    def test_an_adult_date_is_saved_and_leads_to_the_gender_step(self, client, newcomer):
        response = client.post(reverse("onboarding_birth"), {"birth_date": "1990-04-12"})
        newcomer.refresh_from_db()
        assert response.status_code == 302 and response.url == reverse("onboarding_gender")
        assert newcomer.birth_date == date(1990, 4, 12) and newcomer.onboarding_done is False

    def test_the_date_is_required(self, client, newcomer):
        response = client.post(reverse("onboarding_birth"), {"birth_date": ""})
        assert response.status_code == 200 and "Indiquez votre date de naissance" in response.content.decode()
        newcomer.refresh_from_db()
        assert newcomer.birth_date is None

    def test_a_minor_is_refused_and_nothing_is_stored(self, client, newcomer):
        today = timezone.localdate()
        minor = today.replace(year=today.year - (MIN_AGE - 1)).isoformat()
        response = client.post(reverse("onboarding_birth"), {"birth_date": minor})
        newcomer.refresh_from_db()
        assert response.status_code == 200 and "réservé aux personnes majeures" in response.content.decode()
        assert newcomer.birth_date is None and newcomer.onboarding_done is False
        assert client.get(reverse("index")).url == reverse("onboarding")  # toujours enfermé dans l'inscription

    @pytest.mark.parametrize("bad", ["2099-01-01", "1800-01-01", "abc", "2020-02-30", "<script>"])
    def test_garbage_is_refused(self, client, newcomer, bad):
        assert client.post(reverse("onboarding_birth"), {"birth_date": bad}).status_code == 200
        newcomer.refresh_from_db()
        assert newcomer.birth_date is None

    def test_attempts_are_limited(self, client, newcomer):
        for _ in range(20):
            client.post(reverse("onboarding_birth"), {"birth_date": "2099-01-01"})
        response = client.post(reverse("onboarding_birth"), {"birth_date": adult_birth()})
        assert any("Trop d'essais" in str(message) for message in response.context["messages"])
        newcomer.refresh_from_db()
        assert newcomer.birth_date is None

    def test_the_form_cannot_set_other_fields(self, client, newcomer):
        client.post(reverse("onboarding_birth"), {"birth_date": adult_birth(), "onboarding_done": "on", "gender": "homme", "is_superuser": "on"})
        newcomer.refresh_from_db()
        assert (newcomer.onboarding_done, newcomer.gender, newcomer.is_superuser) == (False, "", False)

    def test_a_finished_member_is_sent_home(self, auth_client):
        assert auth_client.get(reverse("onboarding_birth")).url == reverse("index")


class TestGenderStep:
    def test_the_second_step_needs_the_birth_date(self, client, newcomer):
        assert client.get(reverse("onboarding_gender")).url == reverse("onboarding_birth")
        assert client.post(reverse("onboarding_gender"), {"skip": "1"}).url == reverse("onboarding_birth")
        newcomer.refresh_from_db()
        assert newcomer.onboarding_done is False

    def test_the_page_offers_the_four_answers_a_regular_next_and_a_small_skip(self, client, newcomer):
        newcomer.birth_date = date(1990, 1, 1)
        newcomer.save()
        html = client.get(reverse("onboarding_gender")).content.decode()
        for label in ("Femme", "Homme", "Autre", "Je préfère ne pas dire", "facultative", "Retour"):
            assert label in html
        assert html.index("Suivant") < html.index("Passer")
        assert 'class="btn btn-primary' in html[html.index("Suivant") - 200:html.index("Suivant")]
        skip = html[html.index("Passer") - 150:html.index("Passer")]
        assert "text-xs" in skip and "btn" not in skip  # discret : un petit lien, pas un bouton
        assert 'name="skip"' in html

    @pytest.mark.parametrize("choice", ["femme", "homme", "autre", "nsp"])
    def test_each_answer_is_saved_and_ends_the_onboarding(self, client, newcomer, choice):
        client.post(reverse("onboarding_birth"), {"birth_date": adult_birth()})
        response = client.post(reverse("onboarding_gender"), {"gender": choice})
        newcomer.refresh_from_db()
        assert response.status_code == 302 and response.url == reverse("index")
        assert newcomer.gender == choice and newcomer.onboarding_done is True
        assert client.get(reverse("index")).status_code == 200

    def test_skipping_saves_no_gender_but_ends_the_onboarding(self, client, newcomer):
        client.post(reverse("onboarding_birth"), {"birth_date": adult_birth()})
        client.post(reverse("onboarding_gender"), {"skip": "1", "gender": "homme"})
        newcomer.refresh_from_db()
        assert newcomer.gender == "" and newcomer.onboarding_done is True

    def test_next_without_any_choice_counts_as_skipping(self, client, newcomer):
        client.post(reverse("onboarding_birth"), {"birth_date": adult_birth()})
        client.post(reverse("onboarding_gender"), {})
        newcomer.refresh_from_db()
        assert newcomer.gender == "" and newcomer.onboarding_done is True

    def test_an_unknown_answer_is_refused_and_does_not_finish(self, client, newcomer):
        client.post(reverse("onboarding_birth"), {"birth_date": adult_birth()})
        response = client.post(reverse("onboarding_gender"), {"gender": "robot"})
        newcomer.refresh_from_db()
        assert response.status_code == 200 and newcomer.gender == "" and newcomer.onboarding_done is False

    def test_the_start_page_resumes_where_the_member_left(self, client, newcomer):
        assert client.get(reverse("onboarding")).url == reverse("onboarding_birth")
        client.post(reverse("onboarding_birth"), {"birth_date": adult_birth()})
        assert client.get(reverse("onboarding")).url == reverse("onboarding_gender")


class TestRegistrationFlows:
    def test_classic_registration_lands_on_the_onboarding_not_the_home(self, client, google_app):
        from tests.views.test_auth_views import TestRegister
        response = TestRegister().post(client)
        assert response.status_code == 302 and response.url == reverse("onboarding")
        member = BeerUser.objects.get(username="newbie")
        assert member.onboarding_done is False and member.birth_date is None
        assert client.get(reverse("index")).url == reverse("onboarding")

    def test_google_sign_in_is_covered_by_the_same_guard(self, client):
        google_member = BeerUser.objects.create_user("gmember", email="g@example.test", password=None)  # comme un compte créé par allauth
        assert google_member.onboarding_done is False
        client.force_login(google_member)
        assert client.get("/").url == reverse("onboarding")

    def test_a_login_later_still_goes_through_the_remaining_step(self, client, newcomer):
        client.post(reverse("onboarding_birth"), {"birth_date": adult_birth()})
        fresh = Client()
        fresh.force_login(newcomer)
        assert fresh.get(reverse("index")).url == reverse("onboarding")
        assert fresh.get(reverse("onboarding")).url == reverse("onboarding_gender")

    def test_superusers_created_on_the_command_line_skip_the_pages(self):
        admin = BeerUser.objects.create_superuser("rootuser", email="r@example.test", password="x" * 12)
        assert admin.onboarding_done is True

    def test_existing_accounts_were_marked_done_by_the_migration_default(self, user):
        assert user.onboarding_done is True


class TestPrivacy:
    def test_birth_date_and_gender_never_appear_on_public_pages(self, auth_client, other_user):
        other_user.birth_date, other_user.gender = date(1985, 3, 3), "femme"
        other_user.save()
        html = auth_client.get(reverse("public_profile", args=[other_user.username])).content.decode()
        assert "1985" not in html and "femme" not in html.lower().replace("famil", "")

    def test_the_data_goes_with_the_account(self, newcomer):
        newcomer.birth_date = date(1990, 1, 1)
        newcomer.save()
        pk = newcomer.pk
        newcomer.delete()
        assert not BeerUser.objects.filter(pk=pk).exists()
