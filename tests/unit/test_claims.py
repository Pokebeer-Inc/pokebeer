"""Revendication d'un établissement : dépôt, inscription d'un gérant, acceptation, refus, annulation ; rien n'est accordé sans l'équipe."""
import pytest
from django.core import mail
from django.db import IntegrityError, transaction

from app.models import Bar, Brewery, EstablishmentClaim, Notification, ThrottleHit
from app.services import claims, siret_registry
from app.services.places import BAR, BREWERY
from app.services.throttle import CLAIM_BY_USER, Rule
from app.validators import validate_siret
from tests import factories as f

pytestmark = pytest.mark.django_db

SIRET = "73282932000074"
Status = EstablishmentClaim.Status


def make_siret(seed):
    """SIRET de test à clé de Luhn valide."""
    body = f"{seed:013d}"
    for check in range(10):
        try:
            validate_siret(body + str(check))
            return body + str(check)
        except Exception:
            continue


OTHER_SIRET = make_siret(5522813176652)


@pytest.fixture
def coin():
    return f.make_brewery(name="Brasserie du Coin", postal_code="44000", city="Nantes")


class TestOpenClaim:
    def test_a_claim_is_recorded_pending_with_the_registry_snapshot(self, user, coin):
        claim = claims.open_claim(user, BREWERY, coin, SIRET, "Je suis la gérante")
        assert (claim.claimant, claim.brewery, claim.siret, claim.status, claim.message) == (user, coin, SIRET, Status.PENDING, "Je suis la gérante")
        assert claim.registry["found"] and claim.registry["siret"] == SIRET

    def test_no_right_is_given_by_the_request_itself(self, user, coin):
        claims.open_claim(user, BREWERY, coin, SIRET)
        coin.refresh_from_db()
        assert not coin.managers.exists() and coin.siret is None and not user.is_brewer

    def test_bars_work_the_same_way(self, user):
        bar = f.make_bar(name="Le Zinc")
        assert claims.open_claim(user, BAR, bar, SIRET).bar == bar

    def test_the_claimant_is_told_and_current_managers_are_warned(self, user, other_user, coin):
        coin.managers.add(other_user)
        claims.open_claim(user, BREWERY, coin, SIRET)
        assert [m.to[0] for m in mail.outbox] == [user.email] and "bien reçue" in mail.outbox[0].subject
        assert list(Notification.objects.values_list("recipient", "notif_type", "sender")) == [(other_user.id, "claim_received", user.id)]

    @pytest.mark.parametrize("siret", ["", "123", "12345678901234", "7328293200007X", "٧٣٢٨٢٩٣٢٠٠٠٠٧٤", " 73 282 932 000 074 ".replace(" ", "x")])
    def test_a_badly_formed_siret_is_refused(self, user, coin, siret):
        with pytest.raises(claims.ClaimError) as raised:
            claims.open_claim(user, BREWERY, coin, siret)
        assert raised.value.field == "siret" and not EstablishmentClaim.objects.exists()

    def test_spaces_inside_the_siret_are_tolerated(self, user, coin):
        assert claims.open_claim(user, BREWERY, coin, " 732 829 320 00074 ").siret == SIRET

    def test_the_registry_can_refuse_it(self, user, coin, siret_directory):
        siret_directory[SIRET] = siret_registry.SiretCheck(siret=SIRET)
        with pytest.raises(claims.ClaimError, match="n'existe pas") as raised:
            claims.open_claim(user, BREWERY, coin, SIRET)
        assert raised.value.field == "siret" and not EstablishmentClaim.objects.exists() and mail.outbox == []

    def test_a_closed_establishment_is_refused(self, user, coin, siret_directory):
        siret_directory[SIRET] = siret_registry.SiretCheck(siret=SIRET, found=True, active=False)
        with pytest.raises(claims.ClaimError, match="fermé"):
            claims.open_claim(user, BREWERY, coin, SIRET)

    def test_an_outage_of_the_registry_does_not_block_the_claim(self, user, coin, siret_directory):
        siret_directory[SIRET] = siret_registry.SiretCheck(siret=SIRET, available=False)
        claim = claims.open_claim(user, BREWERY, coin, SIRET)
        assert claim.registry["available"] is False and claim.status == Status.PENDING

    def test_a_manager_cannot_claim_what_they_manage(self, user, coin):
        coin.managers.add(user)
        with pytest.raises(claims.ClaimError, match="gérez déjà"):
            claims.open_claim(user, BREWERY, coin, SIRET)

    def test_one_pending_claim_per_member_and_fiche(self, user, coin):
        claims.open_claim(user, BREWERY, coin, SIRET)
        with pytest.raises(claims.ClaimError, match="déjà une demande"):
            claims.open_claim(user, BREWERY, coin, SIRET)
        assert EstablishmentClaim.objects.count() == 1

    def test_the_database_also_refuses_two_pending_claims(self, user, coin):
        claims.open_claim(user, BREWERY, coin, SIRET)
        with pytest.raises(IntegrityError), transaction.atomic():
            EstablishmentClaim.objects.create(claimant=user, brewery=coin, siret=SIRET)

    def test_a_claim_is_either_about_a_brewery_or_a_bar(self, user, coin):
        bar = f.make_bar(name="Le Zinc")
        for kwargs in ({}, {"brewery": coin, "bar": bar}):
            with pytest.raises(IntegrityError), transaction.atomic():
                EstablishmentClaim.objects.create(claimant=user, siret=SIRET, **kwargs)

    def test_a_new_claim_is_possible_after_a_refusal(self, user, coin, superuser):
        first = claims.open_claim(user, BREWERY, coin, SIRET)
        claims.reject(first, superuser, "SIRET sans rapport")
        assert claims.open_claim(user, BREWERY, coin, SIRET).status == Status.PENDING

    def test_a_fiche_tied_to_another_siret_cannot_be_claimed_with_a_different_one(self, user):
        owned = f.make_brewery(name="Déjà liée", siret=SIRET)
        with pytest.raises(claims.ClaimError, match="autre SIRET"):
            claims.open_claim(user, BREWERY, owned, OTHER_SIRET)

    def test_a_siret_already_held_by_another_fiche_points_to_it(self, user, coin):
        f.make_brewery(name="Autre fiche", siret=SIRET)
        with pytest.raises(claims.ClaimError, match="Erreur de SIRET"):
            claims.open_claim(user, BREWERY, coin, SIRET)

    def test_claims_are_limited_per_member_per_day(self, user, coin, monkeypatch):
        monkeypatch.setattr(claims, "CLAIM_BY_USER", Rule("claim-user", 1, CLAIM_BY_USER.window))
        claims.open_claim(user, BREWERY, coin, SIRET)
        other = f.make_brewery(name="Autre brasserie")
        with pytest.raises(claims.ClaimError, match="Trop de demandes"):
            claims.open_claim(user, BREWERY, other, SIRET)
        assert ThrottleHit.objects.filter(scope="claim-user").count() == 1

    def test_the_message_is_cleaned_and_bounded(self, user, coin):
        claim = claims.open_claim(user, BREWERY, coin, SIRET, "<b>Bonjour</b>\n" + "x" * 900)
        assert "<" not in claim.message and len(claim.message) <= 500


class TestPlanRegistration:
    def plan(self, kind=BREWERY, name="Nouvelle Brasserie", postal="44000", city="Nantes", siret=SIRET, choice=""):
        return claims.plan_registration(kind, name, postal, city, siret, choice)

    def test_a_new_fiche_when_nothing_looks_like_it(self, coin):
        plan = self.plan()
        assert plan.place is None and plan.check.found

    def test_the_siret_is_checked_first(self, siret_directory):
        siret_directory[SIRET] = siret_registry.SiretCheck(siret=SIRET)
        with pytest.raises(claims.ClaimError) as raised:
            self.plan()
        assert raised.value.field == "siret"

    def test_a_fiche_that_already_has_this_siret_is_the_one_claimed(self):
        holder = f.make_brewery(name="Titulaire", siret=SIRET)
        assert self.plan(name="Tout autre nom").place == holder

    def test_a_lookalike_in_the_same_place_requires_a_choice(self, coin):
        with pytest.raises(claims.ChoiceRequired) as raised:
            self.plan(name="Microbrasserie du Coin")
        assert [c.obj for c in raised.value.report.candidates] == [coin]

    def test_choosing_the_existing_fiche(self, coin):
        assert self.plan(name="Microbrasserie du Coin", choice=f"existing:{coin.slug}").place == coin

    def test_choosing_a_fiche_that_was_not_proposed_is_refused(self, coin):
        elsewhere = f.make_brewery(name="Rien à voir")
        with pytest.raises(claims.ChoiceRequired):
            self.plan(name="Microbrasserie du Coin", choice=f"existing:{elsewhere.slug}")

    def test_confirming_that_the_fiche_does_not_exist_yet(self, coin):
        from app.services import catalog_matching as cm
        token = cm.find_brewery("Microbrasserie du Coin", "44000", "Nantes").token
        assert self.plan(name="Microbrasserie du Coin", choice=f"new:{token}").place is None

    @pytest.mark.parametrize("choice", ["new:forged", "new:", "new", "existing:", "garbage", ":", "existing"])
    def test_forged_choices_are_refused(self, coin, choice):
        with pytest.raises(claims.ChoiceRequired):
            self.plan(name="Microbrasserie du Coin", choice=choice)

    def test_the_same_name_in_another_city_is_another_establishment(self, coin):
        assert self.plan(name="Brasserie du Coin", postal="69001", city="Lyon").place is None

    def test_an_identical_name_in_the_same_city_can_only_be_claimed(self, coin):
        with pytest.raises(claims.ChoiceRequired) as raised:
            self.plan(name="Brasserie du Coin")
        assert raised.value.report.token == ""  # pas d'option « elle n'existe pas » : c'est bien la même

    def test_bars_follow_the_same_rules(self):
        bar = f.make_bar(name="Le Zinc", postal_code="44000", city="Nantes")
        with pytest.raises(claims.ChoiceRequired):
            self.plan(kind=BAR, name="Zinc")
        assert self.plan(kind=BAR, name="Le Zinc", choice=f"existing:{bar.slug}").place == bar


class TestDecisions:
    @pytest.fixture
    def claim(self, user, coin):
        return claims.open_claim(user, BREWERY, coin, SIRET)

    def test_approving_makes_the_member_a_manager_with_the_role_and_ties_the_siret(self, claim, user, coin, superuser):
        claims.approve(claim, superuser)
        coin.refresh_from_db()
        claim.refresh_from_db()
        assert list(coin.managers.all()) == [user] and coin.siret == SIRET and user.is_brewer
        assert (claim.status, claim.decided_by) == (Status.APPROVED, superuser) and claim.decided_at

    def test_a_bar_claimant_gets_the_bartender_role(self, user, superuser):
        bar = f.make_bar(name="Le Zinc")
        claims.approve(claims.open_claim(user, BAR, bar, SIRET), superuser)
        assert user.is_bartender

    def test_the_claimant_is_notified_and_emailed_after_the_commit(self, claim, user, superuser, django_capture_on_commit_callbacks):
        mail.outbox.clear()
        with django_capture_on_commit_callbacks(execute=True):
            claims.approve(claim, superuser)
        assert Notification.objects.filter(recipient=user, notif_type="claim_approved").exists()
        assert [m.to[0] for m in mail.outbox] == [user.email] and "à vous" in mail.outbox[0].subject

    def test_nothing_is_announced_if_the_decision_is_rolled_back(self, claim, superuser, django_capture_on_commit_callbacks):
        mail.outbox.clear()
        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            with pytest.raises(RuntimeError), transaction.atomic():
                claims.approve(claim, superuser)
                raise RuntimeError
        assert callbacks == [] and mail.outbox == []

    def test_a_decided_claim_cannot_be_decided_again(self, claim, superuser):
        claims.approve(claim, superuser)
        for action in (lambda: claims.approve(claim, superuser), lambda: claims.reject(claim, superuser, "tard"), lambda: claims.cancel(claim, claim.claimant)):
            with pytest.raises(claims.ClaimError, match="déjà été traitée"):
                action()

    def test_a_suspended_claimant_is_not_made_a_manager(self, claim, user, superuser):
        type(user).objects.filter(pk=user.pk).update(is_active=False)
        with pytest.raises(claims.ClaimError, match="suspendu"):
            claims.approve(claim, superuser)
        assert Brewery.objects.get(pk=claim.brewery_id).managers.count() == 0

    def test_approval_is_refused_if_the_siret_was_taken_meanwhile(self, claim, superuser):
        f.make_brewery(name="Arrivée entre-temps", siret=SIRET)
        with pytest.raises(claims.ClaimError, match="autre fiche"):
            claims.approve(claim, superuser)
        assert not claim.brewery.managers.exists()

    def test_approval_is_refused_if_the_fiche_got_another_siret(self, claim, superuser):
        Brewery.objects.filter(pk=claim.brewery_id).update(siret=OTHER_SIRET)
        with pytest.raises(claims.ClaimError, match="autre SIRET"):
            claims.approve(claim, superuser)

    def test_rejecting_needs_a_reason_and_tells_the_claimant(self, claim, user, superuser, django_capture_on_commit_callbacks):
        with pytest.raises(claims.ClaimError, match="motif"):
            claims.reject(claim, superuser, "  ")
        mail.outbox.clear()
        with django_capture_on_commit_callbacks(execute=True):
            claims.reject(claim, superuser, "Le SIRET est celui d'une autre société")
        claim.refresh_from_db()
        assert (claim.status, claim.reason) == (Status.REJECTED, "Le SIRET est celui d'une autre société") and not claim.brewery.managers.exists()
        assert "autre société" in mail.outbox[0].body and Notification.objects.get(notif_type="claim_rejected").text_content == claim.reason

    def test_the_reason_is_cleaned(self, claim, superuser):
        assert "<" not in claims.reject(claim, superuser, "<script>x</script>" + "y" * 900).reason

    def test_only_the_claimant_can_withdraw_their_claim(self, claim, other_user):
        with pytest.raises(claims.ClaimError, match="pas la vôtre"):
            claims.cancel(claim, other_user)
        assert claims.cancel(claim, claim.claimant).status == Status.CANCELLED

    def test_the_pending_count(self, claim, other_user, coin):
        claims.open_claim(other_user, BREWERY, coin, SIRET)
        assert claims.pending_count() == 2

    def test_can_claim(self, user, other_user, coin):
        assert claims.can_claim(user, BREWERY, coin)
        claims.open_claim(user, BREWERY, coin, SIRET)
        assert not claims.can_claim(user, BREWERY, coin) and claims.can_claim(other_user, BREWERY, coin)
        coin.managers.add(other_user)
        assert not claims.can_claim(other_user, BREWERY, coin)
