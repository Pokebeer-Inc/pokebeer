"""Types de contenus modérés. Ajouter un type = ajouter une classe et l'enregistrer dans CONTENT_TYPES (ouvert/fermé)."""
from dataclasses import dataclass

from django.db import transaction
from django.urls import reverse

from app.models import Bar, Beer, BeerUser, Brewery, Drinks, ModerationEntry, Notification
from app.services.achievements import check_and_notify_achievements
from app.services.drinks import delete_drink
from app.services.profile_pictures import delete_stored_picture

Kind = ModerationEntry.Kind


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    is_image: bool = False


class ModeratedContent:
    """Comportement par défaut ; chaque sous-classe décrit un type de contenu."""

    kind = None
    model = None
    noun = "contenu"                  # « Votre {noun} a été retiré… »
    fields = ()
    certifiable = False               # la validation d'une création par un admin pose la coche « vérifié »
    staff_reviews_creation = False    # si certifiable : le staff peut quand même marquer la création comme vue (sans certifier)
    superuser_only = False            # actions réservées aux superusers (impact fort)
    remove_label = "Supprimer"

    def title(self, obj):
        return str(obj)

    def context(self, obj):
        return ""

    def url(self, obj):
        raise NotImplementedError

    def authors(self, obj):
        """Membres notifiés en cas de retrait."""
        return []

    def is_public(self, obj):
        return True

    def can_remove(self, entry):
        return True

    def cascade_warning(self, obj):
        return ""

    def remove(self, obj, entry):
        raise NotImplementedError

    # Libellés propres à l'entrée (un même type peut retirer des éléments différents)
    def remove_label_for(self, entry):
        return self.remove_label

    def noun_for(self, entry):
        return self.noun

    # --- droits : source unique pour l'interface et les actions POST ---
    def _staff_allowed(self, user):
        return user.is_superuser or (user.is_active and user.is_staff and not self.superuser_only)

    def certifies(self, entry, user):
        """Valider cette entrée pose-t-il la coche « vérifié » ? Réservé aux superusers."""
        return self.certifiable and entry.action == ModerationEntry.Action.CREATED and user.is_superuser

    def can_validate(self, entry, user):
        needs_superuser = (
            self.certifiable and not self.staff_reviews_creation and entry.action == ModerationEntry.Action.CREATED
        )
        return user.is_superuser if needs_superuser else user.is_active and user.is_staff

    def can_remove_by(self, entry, user):
        return self.can_remove(entry) and self._staff_allowed(user)


def _joined(*parts):
    return " · ".join(part for part in parts if part)


class BeerContent(ModeratedContent):
    kind = Kind.BEER
    model = Beer
    noun = "bière"
    certifiable = True
    staff_reviews_creation = True
    fields = (
        FieldSpec('name', 'Nom'), FieldSpec('description', 'Description'),
        FieldSpec('style', 'Style'), FieldSpec('image', 'Image', is_image=True),
    )

    def context(self, obj):
        return f"Brasserie : {obj.brewery_id.name}"

    def url(self, obj):
        return reverse('beer_detail', args=[obj.slug])

    def authors(self, obj):
        return [obj.added_by] if obj.added_by else []

    def is_public(self, obj):
        return not obj.is_deleted

    def remove(self, obj, entry):
        # Même règle que le retrait par le créateur : soft-delete, les notes des membres sont conservées
        Beer.objects.filter(pk=obj.pk).update(is_deleted=True)
        Notification.objects.filter(beer=obj).delete()
        if obj.added_by:
            check_and_notify_achievements(obj.added_by)


class CommentContent(ModeratedContent):
    kind = Kind.COMMENT
    model = Drinks
    noun = "avis"
    fields = (FieldSpec('comment', 'Commentaire'), FieldSpec('photo', 'Photo', is_image=True))

    def title(self, obj):
        return f"Avis de {obj.drinker_id.username} sur {obj.beer_id.name}"

    def context(self, obj):
        return _joined(f"Bière : {obj.beer_id.name}", f"Note : {obj.note}/10" if obj.note is not None else "")

    def url(self, obj):
        return reverse('beer_detail', args=[obj.beer_id.slug])

    def authors(self, obj):
        return [obj.drinker_id]

    def remove(self, obj, entry):
        drinker = obj.drinker_id
        delete_drink(obj)
        check_and_notify_achievements(drinker)


class EstablishmentContent(ModeratedContent):
    """Brasserie et bar : mêmes champs publics, même certification ; suppression en cascade selon le modèle."""

    certifiable = True
    superuser_only = True
    fields = (
        FieldSpec('name', 'Nom'), FieldSpec('description', 'Description'), FieldSpec('street', 'Adresse'), FieldSpec('postal_code', 'Code postal'), FieldSpec('city', 'Ville'),
        FieldSpec('phone', 'Téléphone'), FieldSpec('email', 'Email'), FieldSpec('website', 'Site web'),
        FieldSpec('instagram', 'Instagram'), FieldSpec('facebook', 'Facebook'),
        FieldSpec('image', 'Image', is_image=True),
    )

    def authors(self, obj):
        return list(obj.managers.all())

    def remove(self, obj, entry):
        obj.delete()


class BreweryContent(EstablishmentContent):
    kind = Kind.BREWERY
    model = Brewery
    noun = "brasserie"

    def url(self, obj):
        return reverse('brewery_detail', args=[obj.slug])

    def cascade_warning(self, obj):
        count = obj.beer_set.count()
        return f"{count} bière(s) de cette brasserie et leurs avis seront aussi supprimés." if count else ""


class BarContent(EstablishmentContent):
    kind = Kind.BAR
    model = Bar
    noun = "bar"

    def url(self, obj):
        return reverse('bar_detail', args=[obj.slug])

    def authors(self, obj):
        people = {user.pk: user for user in super().authors(obj)}
        if obj.added_by:
            people[obj.added_by.pk] = obj.added_by
        return list(people.values())


class UserContent(ModeratedContent):
    """Infos de profil : on efface la bio ou la photo signalée ; le pseudo se traite depuis la fiche utilisateur (suspension)."""

    kind = Kind.USER
    model = BeerUser
    noun = "bio"
    fields = (FieldSpec('username', 'Pseudo'), FieldSpec('bio', 'Bio'), FieldSpec('avatar', 'Photo de profil', is_image=True))
    remove_label = "Effacer la bio"

    # Champ modifiable par le membre -> (libellé de l'action, nom employé dans la notification)
    REMOVABLE = {'bio': ("la bio", "bio"), 'avatar': ("la photo", "photo de profil")}

    def url(self, obj):
        return reverse('public_profile', args=[obj.username])

    def authors(self, obj):
        return [obj]

    def is_public(self, obj):
        return obj.is_active

    def _flagged(self, entry):
        """Champs retirables effectivement renseignés par cette modification."""
        return [c['field'] for c in entry.changes if c['field'] in self.REMOVABLE and c['new']]

    def can_remove(self, entry):
        return bool(self._flagged(entry))

    def remove_label_for(self, entry):
        return "Effacer " + " et ".join(self.REMOVABLE[f][0] for f in self._flagged(entry))

    def noun_for(self, entry):
        return " et ".join(self.REMOVABLE[f][1] for f in self._flagged(entry))

    def remove(self, obj, entry):
        flagged = self._flagged(entry)
        previous_picture = obj.avatar.name if 'avatar' in flagged and obj.avatar else None
        # update() : pas de signal, l'effacement ne génère pas une nouvelle entrée à relire
        updates = {'bio': ''} if 'bio' in flagged else {}
        if 'avatar' in flagged:
            updates['avatar'] = None
        BeerUser.objects.filter(pk=obj.pk).update(**updates)
        # Le fichier n'est supprimé qu'une fois la modération validée en base
        transaction.on_commit(lambda: delete_stored_picture(previous_picture))


CONTENT_TYPES = {content.kind: content for content in (
    BeerContent(), CommentContent(), BreweryContent(), BarContent(), UserContent(),
)}
