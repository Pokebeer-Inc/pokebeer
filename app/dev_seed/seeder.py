import random
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal

from allauth.socialaccount.models import SocialApp
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group
from django.contrib.sites.models import Site
from django.db import transaction
from django.utils import timezone

from app.models import (
    Bar, Beer, BeerSpot, BeerUser, Brewery, CustomNotebook, DrinkReaction, Drinks,
    Feedback, FeedbackMessage, Notification, Report, UserBlock, UserFollow,
)

from . import data

CONTRIBUTOR, BREWER, BARTENDER, STAFF = "Contributeur", "Brasseur", "Bartender", "Staff"
MANAGED_ESTABLISHMENTS = 2


class DevDatabaseSeeder:
    """Remplit une base vide avec un jeu de données cohérent et reproductible.

    Tout passe par bulk_create : les save() des modèles appellent Gemini (embeddings)
    et Nominatim (géocodage), et les signaux d'attribution des rôles ne sont pas
    déclenchés. Leur effet (groupes) est donc reproduit explicitement ici.
    """

    def __init__(self, password, seed=42):
        self.password_hash = make_password(password)
        self.rng = random.Random(seed)
        self.counts = Counter()

    @transaction.atomic
    def run(self):
        self._seed_site()
        self.groups = {name: Group.objects.get_or_create(name=name)[0] for name in (CONTRIBUTOR, BREWER, BARTENDER, STAFF)}
        self._seed_users()
        self._seed_breweries_and_beers()
        self._seed_bars()
        self._seed_drinks()
        self._seed_social()
        self._seed_moderation()
        return dict(self.counts)

    # ------------------------------------------------------------------ helpers

    def _bulk(self, model, objs):
        created = model.objects.bulk_create(objs)
        self.counts[model.__name__] += len(created)
        return created

    def _grant(self, group_name, users):
        through = BeerUser.groups.through
        group_id = self.groups[group_name].pk
        self._bulk(through, [through(beeruser_id=user.pk, group_id=group_id) for user in users])

    def _others(self, user):
        return [member for member in self.members if member.pk != user.pk]

    # ------------------------------------------------------------------ seeders

    def _seed_site(self):
        site, _ = Site.objects.update_or_create(
            pk=settings.SITE_ID, defaults={"domain": data.SITE_DOMAIN, "name": "Pokebeer (dev)"}
        )
        # Requis par {% provider_login_url 'google' %} ; le bouton Google n'est pas fonctionnel en dev.
        google, _ = SocialApp.objects.get_or_create(
            provider="google", defaults={"name": "Google (dev)", "client_id": "dev-placeholder"}
        )
        google.sites.add(site)

    def _seed_users(self):
        users = self._bulk(BeerUser, [
            BeerUser(
                username=spec["username"],
                email=f"{spec['username']}@{data.EMAIL_DOMAIN}",
                bio=spec["bio"],
                is_superuser=spec.get("is_superuser", False),
                password=self.password_hash,
            )
            for spec in data.USERS
        ])
        self.users = {user.username: user for user in users}
        self.admin = self.users[data.ADMIN_USERNAME]
        pro_accounts = {data.ADMIN_USERNAME, data.BREWER_USERNAME, data.BARTENDER_USERNAME}
        self.members = [user for user in users if user.username not in pro_accounts]

        self._grant(CONTRIBUTOR, users)
        for spec in data.USERS:
            for role in spec.get("roles", ()):
                self._grant(role, [self.users[spec["username"]]])

    def _seed_breweries_and_beers(self):
        brewer = self.users[data.BREWER_USERNAME]
        now = timezone.now()
        breweries = self._bulk(Brewery, [
            Brewery(
                **{key: value for key, value in spec.items() if key != "beers"},
                is_verified=index < MANAGED_ESTABLISHMENTS,
                verified_by=self.admin if index < MANAGED_ESTABLISHMENTS else None,
                verified_at=now if index < MANAGED_ESTABLISHMENTS else None,
            )
            for index, spec in enumerate(data.BREWERIES)
        ])
        managed = breweries[:MANAGED_ESTABLISHMENTS]
        through = Brewery.managers.through
        self._bulk(through, [through(brewery_id=brewery.pk, beeruser_id=brewer.pk) for brewery in managed])
        self._grant(BREWER, [brewer])

        self.beers = self._bulk(Beer, [
            Beer(
                name=name,
                style=style,
                degree=Decimal(str(degree)),
                bitterness=ibu,
                description=description,
                brewery_id=brewery,
                added_by=brewer if brewery in managed else self.admin,
            )
            for brewery, spec in zip(breweries, data.BREWERIES)
            for name, style, degree, ibu, description in spec["beers"]
        ])

    def _seed_bars(self):
        bartender = self.users[data.BARTENDER_USERNAME]
        bars = self._bulk(Bar, [
            Bar(**spec, added_by=self.rng.choice(self.members), is_verified=index < MANAGED_ESTABLISHMENTS)
            for index, spec in enumerate(data.BARS)
        ])
        through = Bar.managers.through
        self._bulk(through, [through(bar_id=bar.pk, beeruser_id=bartender.pk) for bar in bars[:MANAGED_ESTABLISHMENTS]])
        self._grant(BARTENDER, [bartender])

    def _seed_drinks(self):
        today = date.today()
        self.drinks = self._bulk(Drinks, [
            Drinks(
                drinker_id=user,
                beer_id=beer,
                note=self.rng.randint(3, 10),
                comment=self.rng.choice(data.DRINK_COMMENTS),
                date=today - timedelta(days=self.rng.randint(0, 365)),
            )
            for user in self.members
            for beer in self.rng.sample(self.beers, self.rng.randint(5, 12))
        ])
        self.drinks_by_user = defaultdict(list)
        for drink in self.drinks:
            self.drinks_by_user[drink.drinker_id.pk].append(drink)

    def _seed_social(self):
        self._seed_follows()
        self._seed_reactions()
        self._seed_wishlists_and_tops()
        self._seed_spots()
        self._seed_notebooks()

    def _seed_follows(self):
        pairs = [(follower, followed) for follower in self.members for followed in self.rng.sample(self._others(follower), 3)]
        self._bulk(UserFollow, [UserFollow(follower=follower, followed=followed) for follower, followed in pairs])
        self._bulk(Notification, [Notification(recipient=followed, sender=follower, notif_type="follow") for follower, followed in pairs])

    def _seed_reactions(self):
        self._bulk(DrinkReaction, [
            DrinkReaction(user=self.rng.choice(self._others(drink.drinker_id)), drink=drink, is_like=self.rng.random() < 0.8)
            for drink in self.drinks
            if self.rng.random() < 0.3
        ])

    def _seed_wishlists_and_tops(self):
        through = BeerUser.wishlist_beers.through
        wishlist = []
        for user in self.members:
            tasted = self.drinks_by_user[user.pk]
            tasted_ids = {drink.beer_id.pk for drink in tasted}
            untasted = [beer for beer in self.beers if beer.pk not in tasted_ids]
            wishlist += [through(beeruser_id=user.pk, beer_id=beer.pk) for beer in self.rng.sample(untasted, 3)]
            best = sorted(tasted, key=lambda drink: drink.note, reverse=True)[:3]
            user.top_beer_1, user.top_beer_2, user.top_beer_3 = (drink.beer_id for drink in best)
        self._bulk(through, wishlist)
        BeerUser.objects.bulk_update(self.members, ["top_beer_1", "top_beer_2", "top_beer_3"])

    def _seed_spots(self):
        spots = self._bulk(BeerSpot, [self._build_spot(user) for user in self.members[::2]])
        drinks_through, friends_through = BeerSpot.drinks.through, BeerSpot.friends.through
        self._bulk(drinks_through, [
            drinks_through(beerspot_id=spot.pk, drinks_id=drink.pk)
            for spot in spots
            for drink in self.drinks_by_user[spot.user.pk][:2]
        ])
        invitations = [(spot, friend) for spot in spots for friend in self.rng.sample(self._others(spot.user), 2)]
        self._bulk(friends_through, [friends_through(beerspot_id=spot.pk, beeruser_id=friend.pk) for spot, friend in invitations])
        self._bulk(Notification, [
            Notification(recipient=friend, sender=spot.user, notif_type="spot_invite", spot=spot)
            for spot, friend in invitations
        ])

    def _build_spot(self, user):
        brewery = self.drinks_by_user[user.pk][0].beer_id.brewery_id
        return BeerSpot(
            user=user,
            title=self.rng.choice(data.SPOT_TITLES),
            description="Super moment partagé autour de quelques bières.",
            latitude=brewery.latitude + self.rng.uniform(-0.01, 0.01),
            longitude=brewery.longitude + self.rng.uniform(-0.01, 0.01),
        )

    def _seed_notebooks(self):
        notebooks = self._bulk(CustomNotebook, [
            CustomNotebook(user=user, title="Mes coups de cœur", description="Les bières à refaire goûter.")
            for user in self.members[1::2]
        ])
        through = CustomNotebook.drinks.through
        self._bulk(through, [
            through(customnotebook_id=notebook.pk, drinks_id=drink.pk)
            for notebook in notebooks
            for drink in sorted(self.drinks_by_user[notebook.user.pk], key=lambda d: d.note, reverse=True)[:3]
        ])

    def _seed_moderation(self):
        first, second, third = self.members[:3]
        feedbacks = self._bulk(Feedback, [
            Feedback(user=first, message="Pourrait-on filtrer les bières par degré d'alcool ?"),
            Feedback(user=second, message="Super appli, bravo !", status="replied"),
        ])
        self._bulk(FeedbackMessage, [FeedbackMessage(feedback=feedbacks[1], author_kind="team", body="Merci beaucoup !")])
        self._bulk(Notification, [Notification(recipient=second, notif_type="feedback_replied", feedback=feedbacks[1])])
        self._bulk(Report, [
            Report(reporter=third, reported_beer=self.beers[0], reason="fake", description="Le degré indiqué semble faux."),
            Report(reporter=first, reported_drink=self.drinks[-1], reason="offensive", description="Commentaire déplacé.", status="review"),
        ])
        self._bulk(UserBlock, [UserBlock(blocker=third, blocked=self.members[-1])])
