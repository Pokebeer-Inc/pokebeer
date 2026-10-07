"""Membres, abonnements et blocages."""

from django.contrib.auth.models import AbstractBaseUser, Group, PermissionsMixin, UserManager
from django.db.models.functions import Lower
from django.db import models
from django.utils import timezone

from ..validators import MAX_BIO_LENGTH, username_validator
from ..services.avatars import initials_avatar_url
from ..services.profile_pictures import profile_picture_path, profile_pictures_storage


STAFF_GROUP = 'Staff'

class BeerUserManager(UserManager):
    """UserManager adapté aux rôles par groupes : is_staff n'est pas un champ mais l'appartenance au groupe Staff."""

    def _create_user_object(self, username, email, password, **extra_fields):
        # UserManager passe toujours is_staff au constructeur, ce que la propriété en lecture seule refuse
        extra_fields.pop('is_staff', None)
        return super()._create_user_object(username, email, password, **extra_fields)

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        # Sans le groupe Staff, is_staff vaut False et l'admin Django refuse l'accès au superuser
        user = super().create_superuser(username, email, password, **extra_fields)
        user.groups.add(Group.objects.get_or_create(name=STAFF_GROUP)[0])
        return user

    create_superuser.alters_data = True

class BeerUser(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True, null=False, blank=False)
    created_at = models.DateTimeField(default=timezone.now)
    username = models.CharField(max_length=150, blank=False, unique=True, validators=[username_validator])
    bio = models.TextField(max_length=MAX_BIO_LENGTH, verbose_name="Biographie", blank=True, null=True)
    avatar = models.ImageField(upload_to=profile_picture_path, storage=profile_pictures_storage, blank=True, null=True, verbose_name="Photo de profil")
    avatar_updated_at = models.DateTimeField(null=True, blank=True, editable=False)
    wishlist_beers = models.ManyToManyField('Beer', blank=True, related_name='wishlisted_by', verbose_name="Wishlist")
    top_beer_1 = models.ForeignKey('Beer', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    top_beer_2 = models.ForeignKey('Beer', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    top_beer_3 = models.ForeignKey('Beer', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    notif_global = models.BooleanField(default=True, verbose_name="Toutes les notifications")
    notif_follow = models.BooleanField(default=True, verbose_name="Nouveaux abonnés")
    notif_social = models.BooleanField(default=True, verbose_name="Interactions (Likes, Wishlists)")
    notif_network = models.BooleanField(default=True, verbose_name="Réseau (Ajouts de bières, Lieux)")
    notif_achievements = models.BooleanField(default=True, verbose_name="Trophées et récompenses")
    notif_establishment = models.BooleanField(default=True, verbose_name="Établissements (Équipe, mises à jour)")
    show_establishments = models.BooleanField(default=True, verbose_name="Afficher mes établissements publiquement")
    fcm_token = models.TextField(blank=True, null=True, verbose_name="Token Firebase Android")
    is_active = models.BooleanField(default=True, verbose_name="Compte actif", help_text="Décocher pour suspendre le compte : connexion refusée et profil masqué.")
    # Dernière visite (RGPD : suppression des comptes inactifs). `last_login` ne suffit pas : les sessions durent un an.
    last_activity_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="Dernière activité")
    inactivity_warned_at = models.DateTimeField(null=True, blank=True, editable=False, verbose_name="Prévenu de la suppression le")
    # E-mails promotionnels : reçus par défaut, désinscription possible à tout moment (lien de chaque e-mail, page du compte).
    # Les messages de service (mot de passe, sécurité, suppression…) ne dépendent pas de ce choix. La date et l'origine du
    # dernier choix du membre sont conservées.
    marketing_opt_in = models.BooleanField(default=True, verbose_name="Reçoit les e-mails promotionnels")
    marketing_consent_at = models.DateTimeField(null=True, blank=True, editable=False, verbose_name="Choix enregistré le")
    marketing_consent_source = models.CharField(max_length=20, blank=True, default='', editable=False, verbose_name="Origine du choix")
    welcome_sent_at = models.DateTimeField(null=True, blank=True, editable=False, verbose_name="E-mail de bienvenue envoyé le")

    USERNAME_FIELD = "username"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["email"]

    objects = BeerUserManager()
    
    class Meta:
        verbose_name = "Utilisateur"
        constraints = [
            # « Alice » et « alice » désigneraient deux comptes différents : l'unicité ignore la casse
            models.UniqueConstraint(Lower('username'), name='unique_username_ci', violation_error_message="Ce pseudo est déjà utilisé."),
            models.UniqueConstraint(Lower('email'), name='unique_email_ci', violation_error_message="Cet email est déjà utilisé par un autre membre."),
        ]
        
    @property
    def avatar_url(self):
        """Photo envoyée par le membre, sinon photo du compte Google, sinon initiale générée localement."""
        if self.avatar:
            return self.avatar.url
        for account in self.socialaccount_set.all():  # .all() : profite du prefetch_related quand il existe
            picture = account.extra_data.get('picture')
            if isinstance(picture, str) and picture.startswith('https://'):
                return picture
        return initials_avatar_url(self.username)

    @property
    def has_unread_notifications(self):
        """Vérifie si l'utilisateur a au moins une notification non lue"""
        return self.notifications.filter(is_read=False).exists()
    
    @property
    def has_public_establishments(self):
        """Renvoie True si l'utilisateur est un pro ET qu'il autorise l'affichage"""
        return self.show_establishments and (self.is_brewer or self.is_bartender)

    @property
    def my_breweries(self):
        """Renvoie la liste des brasseries gérées"""
        return self.managed_breweries.all()

    @property
    def my_bars(self):
        """Renvoie la liste des bars gérés"""
        return self.managed_bars.all()
    
    # ==========================================
    # GESTION DES RÔLES (Groupes)
    # ==========================================
    @property
    def is_brewer(self):
        """Vérifie si l'utilisateur a le rôle Brasseur."""
        return any(group.name == 'Brasseur' for group in self.groups.all())

    @property
    def is_bartender(self):
        """Vérifie si l'utilisateur a le rôle Bartender."""
        return any(group.name == 'Bartender' for group in self.groups.all())

    @property
    def is_contributor(self):
        """Vérifie si l'utilisateur a le rôle Contributeur."""
        return any(group.name == 'Contributeur' for group in self.groups.all())
    
    @property
    def is_staff(self):
        """Vérifie si l'utilisateur a le rôle Staff."""
        return any(group.name == STAFF_GROUP for group in self.groups.all())
    
    @property
    def primary_role_badge(self):
        """
        Détermine le rôle le plus élevé de l'utilisateur et renvoie
        un dictionnaire avec le nom du rôle et sa classe CSS (Tailwind/DaisyUI).
        """
        
        if self.is_staff or self.is_superuser:
            return {'name': 'Staff', 'color': 'badge-warning text-white'}
        
        # On récupère tous les noms de groupes d'un coup pour éviter les requêtes multiples
        group_names = [group.name for group in self.groups.all()]
        
        if 'Brasseur' in group_names and 'Bartender' in group_names:
            return {'name': 'Brasseur & Gérant', 'color': 'badge-primary text-white'}
        if 'Brasseur' in group_names:
            return {'name': 'Brasseur', 'color': 'badge-primary text-white'}
        if 'Bartender' in group_names:
            return {'name': 'Gérant de Bar', 'color': 'badge-primary text-white'}
        if 'Contributeur' in group_names:
            return {'name': 'Contributeur', 'color': 'badge-neutral text-white'}
            
        # Par défaut, si l'utilisateur n'a aucun groupe spécial
        return {'name': 'Membre', 'color': 'badge-ghost'}

    def __str__(self):
        return self.username
    
class UserFollow(models.Model):
    follower = models.ForeignKey(BeerUser, related_name='following', on_delete=models.CASCADE)
    followed = models.ForeignKey(BeerUser, related_name='followers', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('follower', 'followed')
    
class UserBlock(models.Model):
    blocker = models.ForeignKey(BeerUser, on_delete=models.CASCADE, related_name='blocking')
    blocked = models.ForeignKey(BeerUser, on_delete=models.CASCADE, related_name='blocked_by')
    created_at = models.DateTimeField(auto_now_add=True)
    # Date à laquelle on a invité le bloqueur à signaler le membre s'il a rencontré un problème (une seule fois)
    report_invited_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        unique_together = ('blocker', 'blocked')
        verbose_name = "Blocage"

    def __str__(self):
        return f"{self.blocker.username} a bloqué {self.blocked.username}"
