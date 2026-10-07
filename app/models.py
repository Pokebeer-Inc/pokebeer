from django.db import models, transaction
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.utils import timezone
from django.contrib.auth.models import UserManager
from datetime import date
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models.functions import Lower
from .fields import PublicSlugField
from .validators import MAX_BIO_LENGTH, MAX_TEXT_LENGTH, plain_text_validator, username_validator
from .services import notification_policy, notification_types
from .services.avatars import initials_avatar_url
from .services.images import delete_stored_file
from .services.official_images import bar_image_path, beer_image_path, brewery_image_path
from .services.tasting_photos import tasting_photo_path
from .services.profile_pictures import profile_picture_path, profile_pictures_storage
from pgvector.django import VectorField
import requests
from django.db.models.signals import post_delete, post_save, m2m_changed
from django.dispatch import receiver
from django.contrib.auth.models import Group

# Le géocodage est synchrone dans la requête web : timeout court (connexion + lecture)
GEOCODING_TIMEOUT = 2

class GeocodableMixin(models.Model):
    """
    Classe abstraite qui ajoute la logique de géocodage automatique.
    À hériter sur tout modèle possédant les champs 'address', 'latitude' et 'longitude'.
    """
    class Meta:
        abstract = True

    def _update_coordinates(self):
        """Appelle l'API OpenStreetMap pour convertir l'adresse en coordonnées."""
        if not self.address:
            self.latitude = None
            self.longitude = None
            return

        url = "https://nominatim.openstreetmap.org/search"
        params = {
            'q': self.address,
            'format': 'json',
            'limit': 1
        }
        # L'API Nominatim exige un User-Agent personnalisé
        headers = {
            'User-Agent': 'PokebeerApp/1.0' 
        }

        try:
            response = requests.get(url, params=params, headers=headers, timeout=GEOCODING_TIMEOUT)
            data = response.json() if response.status_code == 200 else None
            if data:
                self.latitude = float(data[0]['lat'])
                self.longitude = float(data[0]['lon'])
                return
            if response.status_code != 200:
                print(f"Erreur de géocodage : HTTP {response.status_code}")
        except Exception as e:
            # En cas de coupure réseau ou erreur API, on ne fait pas crasher l'enregistrement
            print(f"Erreur de géocodage : {e}")
        # Adresse introuvable ou service indisponible : mieux vaut pas de carte que les coordonnées de l'ancienne adresse
        self.latitude = None
        self.longitude = None

    def save(self, *args, **kwargs):
        # On vérifie si c'est une modification d'un objet existant
        if self.pk:
            old_instance = type(self).objects.get(pk=self.pk)
            # On appelle l'API UNIQUEMENT si l'adresse a changé
            if old_instance.address != self.address:
                self._update_coordinates()
        else:
            # C'est une création de nouvel établissement
            self._update_coordinates()

        # On appelle le comportement de sauvegarde normal de Django
        super().save(*args, **kwargs)

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

class VerifiableMixin(models.Model):
    """Coche « vérifié » posée par un admin (voir services/verification.py) ; jamais modifiable par un formulaire public."""
    is_verified = models.BooleanField(default=False, verbose_name="Vérifié")
    verified_by = models.ForeignKey('BeerUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_%(class)s_set', verbose_name="Vérifié par")
    verified_at = models.DateTimeField(null=True, blank=True, verbose_name="Date de vérification")

    class Meta:
        abstract = True

class OfficialImageMixin:
    """Image officielle d'un établissement ou d'une bière (champ `image`)."""

    @property
    def image_url(self):
        """URL de l'image, ou None : à utiliser dans les gabarits (image.url lève une erreur sans fichier)."""
        return self.image.url if self.image else None

class Brewery(OfficialImageMixin, GeocodableMixin, VerifiableMixin):
    name = models.CharField(max_length=150, blank=False, verbose_name="Nom", validators=[plain_text_validator])
    slug = PublicSlugField(source='name')
    description = models.TextField(max_length=MAX_TEXT_LENGTH, verbose_name="Description")
    image = models.ImageField(upload_to=brewery_image_path, blank=True, null=True, verbose_name="Image")
    siret = models.CharField(max_length=14, unique=True, blank=True, null=True, verbose_name="Numéro SIRET")
    managers = models.ManyToManyField('BeerUser', blank=True, related_name='managed_breweries', verbose_name="Gérants")
    
    # champs de contact
    address = models.CharField(max_length=255, blank=True, null=True, verbose_name="Adresse complète")
    phone = models.CharField(max_length=20, blank=True, null=True, verbose_name="Téléphone")
    email = models.EmailField(blank=True, null=True, verbose_name="Email")
    website = models.URLField(blank=True, null=True, verbose_name="Site web")
    instagram = models.URLField(blank=True, null=True, verbose_name="Instagram")
    facebook = models.URLField(blank=True, null=True, verbose_name="Facebook")
    
    # Géolocalisation
    latitude = models.FloatField(blank=True, null=True, verbose_name="Latitude")
    longitude = models.FloatField(blank=True, null=True, verbose_name="Longitude")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, null=True, verbose_name="Date de création")
    updated_at = models.DateTimeField(auto_now=True, null=True, verbose_name="Dernière modification")
    
    class Meta:
        verbose_name = "Brasserie"
        ordering = ['name']

    def __str__(self):
        return self.name
    
class Bar(OfficialImageMixin, GeocodableMixin, VerifiableMixin):
    name = models.CharField(max_length=150, blank=False, verbose_name="Nom", validators=[plain_text_validator])
    slug = PublicSlugField(source='name')
    description = models.TextField(max_length=MAX_TEXT_LENGTH, blank=True, null=True, verbose_name="Description")
    image = models.ImageField(upload_to=bar_image_path, blank=True, null=True, verbose_name="Image")
    siret = models.CharField(max_length=14, unique=True, blank=True, null=True, verbose_name="Numéro SIRET")
    managers = models.ManyToManyField('BeerUser', blank=True, related_name='managed_bars', verbose_name="Gérants")
    
    # Localisation et Contact
    address = models.CharField(max_length=255, blank=True, null=True, verbose_name="Adresse complète")
    phone = models.CharField(max_length=20, blank=True, null=True, verbose_name="Téléphone")
    email = models.EmailField(blank=True, null=True, verbose_name="Email")
    website = models.URLField(blank=True, null=True, verbose_name="Site web")
    instagram = models.URLField(blank=True, null=True, verbose_name="Instagram")
    facebook = models.URLField(blank=True, null=True, verbose_name="Facebook")
    
    # Géolocalisation
    latitude = models.FloatField(blank=True, null=True, verbose_name="Latitude")
    longitude = models.FloatField(blank=True, null=True, verbose_name="Longitude")
    
    # Traçabilité et Modération
    added_by = models.ForeignKey('BeerUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='added_bars', verbose_name="Ajouté par")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date de création")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Dernière modification")
    
    class Meta:
        verbose_name = "Bar"
        verbose_name_plural = "Bars"
        ordering = ['name']

    def __str__(self):
        return self.name

class Beer(OfficialImageMixin, VerifiableMixin):
    name = models.CharField(max_length=150, blank=False, verbose_name="Nom", validators=[plain_text_validator])
    image = models.ImageField(upload_to=beer_image_path, blank=True, null=True, verbose_name="Image")
    description = models.TextField(max_length=MAX_TEXT_LENGTH, blank=True, null=True, verbose_name="Description officielle")
    bitterness = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(500)], verbose_name="IBU")
    degree = models.DecimalField(max_digits=4, decimal_places=1, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)], verbose_name="Degré")
    brewery_id = models.ForeignKey(Brewery, on_delete=models.CASCADE)
    slug = PublicSlugField(source='name')
    style = models.CharField(max_length=100, blank=True, null=True, verbose_name="Style (ex: IPA, Stout...)")
    added_by = models.ForeignKey(BeerUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='added_beers')
    is_deleted = models.BooleanField(default=False, verbose_name="Supprimée du catalogue")
    
    embedding = VectorField(dimensions=3072, null=True, blank=True)

    class Meta:
        verbose_name = "Bière"
        ordering = ['name']
        constraints = [
            # Une bière retirée du catalogue libère son nom ; le slug reste unique pour garder ses anciennes URLs
            models.UniqueConstraint(
                fields=['name'],
                condition=models.Q(is_deleted=False),
                name='unique_active_beer_name',
                violation_error_message="Une bière du catalogue porte déjà ce nom.",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def embedding_text(self):
        """Texte décrivant la bière, vectorisé pour la recherche sémantique du chat IA."""
        return f"Bière {self.name} de la brasserie {self.brewery_id.name}. Style: {self.style or 'inconnu'}. Profil: {self.description}"

    # Champs dont dépend `embedding_text` : leur changement rend le vecteur obsolète
    EMBEDDING_SOURCES = ('name', 'style', 'description', 'brewery_id_id')

    def _embedding_sources(self):
        return tuple(self.__dict__.get(field) for field in self.EMBEDDING_SOURCES)

    @classmethod
    def from_db(cls, db, field_names, values):
        beer = super().from_db(db, field_names, values)
        beer._embedded_sources = beer._embedding_sources()
        return beer

    def _needs_embedding(self):
        """Vecteur absent ou obsolète ; jamais pour une bière retirée du catalogue (absente du chat IA)."""
        if self.is_deleted:
            return False
        return self.embedding is None or self._embedding_sources() != getattr(self, '_embedded_sources', None)

    def _refresh_embedding(self):
        from .services.ai import get_embedding
        vector = get_embedding(self.embedding_text)
        if vector:
            self.embedding = vector
            Beer.objects.filter(pk=self.pk).update(embedding=vector)

    def save(self, *args, **kwargs):
        update_fields = kwargs.get('update_fields')
        touches_profile = update_fields is None or bool(set(self.EMBEDDING_SOURCES) & set(update_fields))
        needs_embedding = touches_profile and self._needs_embedding()
        super().save(*args, **kwargs)
        if needs_embedding:
            self._embedded_sources = self._embedding_sources()
            # Après la validation de la transaction en cours : jamais d'appel réseau pendant qu'elle est ouverte.
            # En cas d'échec Gemini, le vecteur reste absent : `embed_beers` ou le prochain save le rattrape.
            transaction.on_commit(self._refresh_embedding)

class Drinks(models.Model):
    date = models.DateField(default=date.today, verbose_name="Date")
    slug = PublicSlugField()
    note = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(10)], null=True, blank=True, verbose_name="Note")
    comment = models.TextField(max_length=MAX_TEXT_LENGTH, verbose_name="Commentaire")
    photo = models.ImageField(upload_to=tasting_photo_path, blank=True, null=True, verbose_name="Photo")
    
    drinker_id = models.ForeignKey(BeerUser, on_delete=models.CASCADE)
    beer_id = models.ForeignKey(Beer, on_delete=models.CASCADE)
    
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    
    class Meta:
        verbose_name = "Dégustation"
        ordering = ['-date']

    def __str__(self):
        return f"{self.drinker_id.username} - {self.beer_id.name} ({self.note}/10)"

    @property
    def photo_url(self):
        """URL de la photo de la dégustation, ou None : à utiliser dans les gabarits (photo.url lève une erreur sans fichier)."""
        return self.photo.url if self.photo else None
    
class BeerSpot(models.Model):
    user = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='spots')
    slug = PublicSlugField()
    title = models.CharField(max_length=150, verbose_name="Titre du lieu")
    description = models.TextField(max_length=MAX_TEXT_LENGTH, blank=True, null=True, verbose_name="Description / Souvenirs")
    date = models.DateField(default=date.today, verbose_name="Date")
    latitude = models.FloatField()
    longitude = models.FloatField()
    
    drinks = models.ManyToManyField('Drinks', blank=True, related_name='spots', verbose_name="Dégustations associées")
    friends = models.ManyToManyField('BeerUser', blank=True, related_name='shared_spots', verbose_name="Amis associés")
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Lieu de dégustation"
        ordering = ['-date']

    def __str__(self):
        return f"{self.title} - {self.user.username}"
    
class ReverseGeocode(models.Model):
    """Cache du géocodage inverse (OpenStreetMap/Nominatim) par position arrondie à ~11 m.

    Volontairement sans lien avec un membre ni un lieu : seule la position est mise en cache, ce qui évite
    de rappeler le service externe et de lui transmettre plus de coordonnées que nécessaire.
    """
    class PlaceKind(models.TextChoices):
        HOME = 'home', 'Domicile / habitation'
        BAR = 'bar', 'Bar, pub, restaurant'
        BREWERY = 'brewery', 'Brasserie'
        OUTDOOR = 'outdoor', 'Extérieur (parc, nature)'
        STREET = 'street', 'Voie publique'
        OTHER = 'other', 'Autre'

    lat_e4 = models.IntegerField(help_text="Latitude × 10 000, arrondie")
    lon_e4 = models.IntegerField(help_text="Longitude × 10 000, arrondie")
    place_kind = models.CharField(max_length=10, choices=PlaceKind.choices, blank=True)
    settlement = models.CharField(max_length=10, blank=True, help_text="city, town, village ou hamlet")
    is_urban = models.BooleanField(null=True, blank=True)
    city = models.CharField(max_length=150, blank=True)
    postcode = models.CharField(max_length=20, blank=True)
    department = models.CharField(max_length=150, blank=True)
    region = models.CharField(max_length=150, blank=True)
    country_code = models.CharField(max_length=2, blank=True)
    osm_category = models.CharField(max_length=50, blank=True)
    osm_type = models.CharField(max_length=50, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Géocodage inverse"
        constraints = [models.UniqueConstraint(fields=['lat_e4', 'lon_e4'], name='unique_reverse_geocode_position')]

    @property
    def is_resolved(self):
        return self.resolved_at is not None

    def __str__(self):
        return f"{self.lat_e4 / 10_000:.4f}, {self.lon_e4 / 10_000:.4f} → {self.city or '?'}"

class AnalyticsLayout(models.Model):
    """Disposition personnelle d'une page d'analytics : ordre des tuiles et tuiles masquées (une ligne par membre et par page)."""
    user = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='analytics_layouts')
    page_key = models.CharField(max_length=30)
    order = models.JSONField(default=list)
    hidden = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Disposition d'analytics"
        constraints = [models.UniqueConstraint(fields=['user', 'page_key'], name='unique_analytics_layout_per_page')]

class AnalyticsView(models.Model):
    """Vue d'analytics personnalisée : un ensemble de tuiles nommé, propre à un administrateur."""
    user = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='analytics_views')
    name = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Vue d'analytics"
        ordering = ['name']
        constraints = [models.UniqueConstraint(fields=['user', 'name'], name='unique_analytics_view_name_per_user')]

    def __str__(self):
        return self.name


class AnalyticsTile(models.Model):
    """Tuile d'une vue personnalisée : titre et définition (jeu de données, regroupement, mesures, graphique)."""
    view = models.ForeignKey(AnalyticsView, on_delete=models.CASCADE, related_name='tiles')
    title = models.CharField(max_length=100)
    spec = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Tuile d'analytics"
        ordering = ['pk']

    def __str__(self):
        return self.title

class Feedback(models.Model):
    STATUS_CHOICES = [
        ('pending', 'En attente'),
        ('replied', 'Répondu'),
    ]
    
    user = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='feedbacks', verbose_name="Utilisateur")
    slug = PublicSlugField()  # jeton opaque : l'échange est privé
    message = models.TextField(verbose_name="Message / Suggestion")  # premier message du membre ; la suite est dans FeedbackMessage
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="Statut")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date")

    class Meta:
        verbose_name = "Feedback / Suggestion"
        ordering = ['-created_at']

    @property
    def last_team_message(self):
        """Dernière réponse de l'équipe, utilisée par le texte des notifications."""
        from .services.feedback import last_team_message
        return last_team_message(self)

    def __str__(self):
        return f"Feedback de {self.user.username} ({self.get_status_display()})"
    
class FeedbackMessage(models.Model):
    """Message d'un échange avec l'équipe, après le premier message du membre (stocké dans Feedback.message)."""
    class Author(models.TextChoices):
        MEMBER = 'member', 'Membre'
        TEAM = 'team', 'Équipe'

    feedback = models.ForeignKey(Feedback, on_delete=models.CASCADE, related_name='messages')
    author_kind = models.CharField(max_length=10, choices=Author.choices)
    author = models.ForeignKey('BeerUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='feedback_messages')
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']

    def __str__(self):
        return f"{self.get_author_kind_display()} : {self.body[:40]}"

class Report(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Envoyé'),
        ('review', 'En cours d\'examen'),
        ('resolved', 'Traité'),
    ]
    REASON_CHOICES = [
        ('spam', 'Spam ou publicité'),
        ('offensive', 'Contenu offensant / haineux'),
        ('fake', 'Fausse information / Faux profil'),
        ('other', 'Autre raison'),
    ]
    
    reporter = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='submitted_reports', verbose_name="Signalé par")
    slug = PublicSlugField()
    
    # Cibles possibles (une seule sera remplie par signalement)
    reported_beer = models.ForeignKey('Beer', on_delete=models.CASCADE, null=True, blank=True, verbose_name="Bière signalée")
    reported_drink = models.ForeignKey('Drinks', on_delete=models.CASCADE, null=True, blank=True, verbose_name="Dégustation signalée")
    reported_user = models.ForeignKey('BeerUser', on_delete=models.CASCADE, null=True, blank=True, related_name='reports_received', verbose_name="Membre signalé")
    reported_brewery = models.ForeignKey('Brewery', on_delete=models.CASCADE, null=True, blank=True, verbose_name="Brasserie signalée")

    reason = models.CharField(max_length=20, choices=REASON_CHOICES, verbose_name="Raison")
    description = models.TextField(max_length=1000, verbose_name="Description détaillée")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="Statut")
    admin_response = models.TextField(blank=True, null=True, verbose_name="Décision de l'administrateur")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date")

    class Meta:
        verbose_name = "Signalement"
        ordering = ['-created_at']

    def __str__(self):
        return f"Signalement #{self.id} par {self.reporter.username} - {self.get_status_display()}"
    
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

class PolicyNotice(models.Model):
    """Annonce d'une modification de la politique de confidentialité à tous les membres (notification, e-mail en option)."""
    summary = models.CharField(max_length=200, verbose_name="Ce qui a changé")
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey('BeerUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='+', verbose_name="Publiée par")
    notified_count = models.PositiveIntegerField(default=0, verbose_name="Membres notifiés")
    notify_by_email = models.BooleanField(default=False, verbose_name="Aussi par e-mail")
    # L'e-mail part par lots quotidiens (quota du compte Gmail) : le curseur est le dernier membre déjà traité
    email_cursor = models.PositiveBigIntegerField(default=0, editable=False)
    emails_sent = models.PositiveIntegerField(default=0, verbose_name="E-mails envoyés")
    email_done = models.BooleanField(default=False, editable=False)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Annonce de la politique de confidentialité"
        verbose_name_plural = "Annonces de la politique de confidentialité"


class EmailCampaign(models.Model):
    """Message rédigé dans l'administration et envoyé par lots à une audience (voir services/campaigns.py).

    Les destinataires sont figés au lancement (CampaignRecipient) : la suite de l'envoi ne dépend plus des critères.
    """

    class Kind(models.TextChoices):
        PROMOTIONAL = 'promotional', "Promotionnel (hors membres désinscrits)"
        SERVICE = 'service', "Alerte obligatoire (tous les membres actifs)"

    class Audience(models.TextChoices):
        ALL = 'all', "Tous les membres"
        ACTIVE = 'active', "Membres actifs"
        INACTIVE = 'inactive', "Membres inactifs"
        CUSTOM = 'custom', "Liste personnalisée"

    class Status(models.TextChoices):
        DRAFT = 'draft', "Brouillon"
        SENDING = 'sending', "Envoi en cours"
        DONE = 'done', "Terminée"
        CANCELLED = 'cancelled', "Annulée"

    subject = models.CharField(max_length=150, verbose_name="Objet")
    body = models.TextField(max_length=5000, verbose_name="Message")
    cta_label = models.CharField(max_length=40, blank=True, verbose_name="Texte du bouton")
    cta_url = models.URLField(max_length=300, blank=True, verbose_name="Lien du bouton")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.PROMOTIONAL, verbose_name="Type")
    audience = models.CharField(max_length=20, choices=Audience.choices, default=Audience.ACTIVE, verbose_name="Audience")
    activity_days = models.PositiveSmallIntegerField(default=90, verbose_name="Seuil d'inactivité (jours)")
    # Membres choisis pour l'audience « liste personnalisée » : vidée au lancement (les destinataires sont alors figés à part)
    custom_members = models.ManyToManyField('BeerUser', blank=True, related_name='+', verbose_name="Membres choisis")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey('BeerUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='+', verbose_name="Rédigée par")
    launched_at = models.DateTimeField(null=True, blank=True, editable=False)
    launched_by = models.ForeignKey('BeerUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='+', editable=False, verbose_name="Lancée par")
    finished_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Campagne e-mail"
        verbose_name_plural = "Campagnes e-mail"

    def __str__(self):
        return self.subject

    @property
    def is_promotional(self):
        return self.kind == self.Kind.PROMOTIONAL


class CampaignRecipient(models.Model):
    """Un membre visé par une campagne et l'état de son envoi. Supprimé avec le compte (aucune adresse n'est copiée ici)."""

    class Status(models.TextChoices):
        PENDING = 'pending', "En attente"
        SENDING = 'sending', "En cours"  # réservé : jamais renvoyé, pour qu'un incident n'envoie pas deux fois
        SENT = 'sent', "Envoyé"
        FAILED = 'failed', "Échec"
        SKIPPED = 'skipped', "Ignoré"  # désinscrit, suspendu ou campagne annulée avant l'envoi

    campaign = models.ForeignKey(EmailCampaign, on_delete=models.CASCADE, related_name='recipients')
    user = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='+')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['campaign', 'user'], name='unique_campaign_recipient')]
        indexes = [models.Index(fields=['campaign', 'status'], name='campaign_recipient_status_idx')]


class ThrottleHit(models.Model):
    """Tentative comptabilisée par la limitation de débit. La clé (IP, pseudo…) n'est conservée que hachée."""
    scope = models.CharField(max_length=40)
    key_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=['scope', 'key_hash', 'created_at'], name='throttle_lookup_idx')]


class AccountDeletion(models.Model):
    """Journal des comptes supprimés. Volontairement sans donnée personnelle (ni pseudo, ni e-mail) : RGPD, minimisation."""

    class Reason(models.TextChoices):
        INACTIVITY = 'inactivity', "Inactivité"
        SELF = 'self', "Demande du membre"

    user_id = models.PositiveBigIntegerField(verbose_name="Identifiant du compte")
    reason = models.CharField(max_length=20, choices=Reason.choices)
    last_activity_at = models.DateTimeField(verbose_name="Dernière activité")
    was_warned = models.BooleanField(default=False, verbose_name="Prévenu avant suppression")
    deleted_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-deleted_at']
        verbose_name = "Compte supprimé"
        verbose_name_plural = "Comptes supprimés"


class NotificationManager(models.Manager):
    def bulk_create(self, objs, **kwargs):
        """Intercepte les bulk_create pour retirer les notifications refusées."""
        valid_objs = notification_policy.filter_allowed(objs)
        
        # Si après filtrage la liste est vide, on arrête tout
        if not valid_objs:
            return []
            
        return super().bulk_create(valid_objs, **kwargs)
    
class Notification(models.Model):
    
    objects = NotificationManager()
    slug = PublicSlugField()
    
    NOTIFICATION_TYPES = notification_types.CHOICES

    recipient = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='notifications')
    sender = models.ForeignKey('BeerUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_notifications')
    notif_type = models.CharField(max_length=50, choices=NOTIFICATION_TYPES)
    report = models.ForeignKey('Report', on_delete=models.CASCADE, null=True, blank=True)
    feedback = models.ForeignKey('Feedback', on_delete=models.CASCADE, null=True, blank=True)
    
    beer = models.ForeignKey('Beer', on_delete=models.CASCADE, null=True, blank=True)
    brewery = models.ForeignKey('Brewery', on_delete=models.CASCADE, null=True, blank=True)
    bar = models.ForeignKey('Bar', on_delete=models.CASCADE, null=True, blank=True)
    spot = models.ForeignKey('BeerSpot', on_delete=models.CASCADE, null=True, blank=True)
    achievement_name = models.CharField(max_length=100, null=True, blank=True)
    text_content = models.CharField(max_length=255, null=True, blank=True) 
    
    is_read = models.BooleanField(default=False)
    # Instant où la notification a été montrée (pop-up ou push natif) : une même alerte ne s'affiche jamais deux fois,
    # contrairement à `is_read` qui reste faux jusqu'au clic.
    toasted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def place(self):
        """Établissement concerné (brasserie ou bar)."""
        return self.brewery or self.bar

    @property
    def image_url(self):
        """Image illustrant la notification (avatar, bière, établissement) ou None : voir NotificationType.image_for."""
        return notification_types.get(self.notif_type).image_for(self)

    @property
    def visual(self):
        return notification_types.get(self.notif_type).visual

    @property
    def time_ago(self):
        now = timezone.now()
        diff = now - self.created_at
        
        if diff.days > 0:
            return f"{diff.days} j"
        
        hours = diff.seconds // 3600
        if hours > 0:
            return f"{hours}h"
            
        minutes = (diff.seconds % 3600) // 60
        if minutes > 0:
            return f"{minutes} min"
            
        return "à l'instant"
    
    def is_allowed(self):
        """Politique d'envoi : type connu, destinataire actif, préférences, blocages (voir notification_policy)."""
        return bool(notification_policy.filter_allowed([self]))

    def save(self, *args, **kwargs):
        # On intercepte uniquement les nouvelles notifications (sans ID)
        if not self.pk and not self.is_allowed():
            return  # On annule silencieusement
        super().save(*args, **kwargs)

class UserAchievementState(models.Model):
    """Mémorise les trophées déjà débloqués par l'utilisateur pour ne pas le spammer"""
    user = models.ForeignKey('BeerUser', on_delete=models.CASCADE)
    achievement_name = models.CharField(max_length=100)
    tier_level = models.IntegerField(default=0)
    
    class Meta:
        unique_together = ('user', 'achievement_name')
        
class DrinkReaction(models.Model):
    user = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='reactions')
    drink = models.ForeignKey('Drinks', on_delete=models.CASCADE, related_name='reactions')
    is_like = models.BooleanField(default=True) # True = Pouce en l'air, False = Pouce en bas
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'drink') # Un utilisateur ne peut réagir qu'une seule fois par avis
        verbose_name = "Réaction"
        
class ChatUsage(models.Model):
    """Nombre d'appels à l'IA (chat, lecture d'étiquette) d'un utilisateur sur une journée, par usage."""
    user = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='chat_usages')
    day = models.DateField()
    scope = models.CharField(max_length=20, default='chat')
    count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('user', 'day', 'scope')
        verbose_name = "Utilisation de l'IA"

    def __str__(self):
        return f"{self.user.username} - {self.day} ({self.count})"

class CustomNotebook(models.Model):
    user = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='custom_notebooks')
    slug = PublicSlugField()
    title = models.CharField(max_length=150, verbose_name="Titre du carnet")
    description = models.TextField(max_length=MAX_TEXT_LENGTH, blank=True, null=True, verbose_name="Description")
    drinks = models.ManyToManyField('Drinks', blank=True, related_name='notebooks', verbose_name="Dégustations")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Carnet personnalisé"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.user.username}"
    
class ModerationEntryQuerySet(models.QuerySet):
    def pending(self):
        return self.filter(reviewed_at__isnull=True)

    def for_object(self, kind, object_id):
        return self.filter(kind=kind, object_id=object_id)


class ModerationEntry(models.Model):
    """Trace d'un contenu public créé ou modifié, à relire par l'équipe. N'empêche jamais la publication."""

    class Kind(models.TextChoices):
        BEER = 'beer', 'Bière'
        COMMENT = 'comment', 'Commentaire'
        BREWERY = 'brewery', 'Brasserie'
        BAR = 'bar', 'Bar'
        USER = 'user', 'Membre'

    class Action(models.TextChoices):
        CREATED = 'created', 'Création'
        MODIFIED = 'modified', 'Modification'

    kind = models.CharField(max_length=20, choices=Kind.choices)
    action = models.CharField(max_length=10, choices=Action.choices)
    object_id = models.PositiveBigIntegerField(verbose_name="Identifiant de l'objet")
    label = models.CharField(max_length=255, verbose_name="Libellé")
    context = models.CharField(max_length=255, blank=True, verbose_name="Contexte")
    # [{"field", "label", "image", "old", "new"}] : valeurs au moment de l'enregistrement
    changes = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey('BeerUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='+', verbose_name="Validé par")
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name="Validé le")

    objects = ModerationEntryQuerySet.as_manager()

    class Meta:
        verbose_name = "Contenu à valider"
        verbose_name_plural = "Contenus à valider"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['reviewed_at', 'kind', 'action'], name='moderation_queue_idx'),
            models.Index(fields=['kind', 'object_id'], name='moderation_object_idx'),
        ]

    def __str__(self):
        return f"{self.get_action_display()} - {self.get_kind_display()} - {self.label}"

# ==========================================
# Attibution des rôles
# ==========================================

@receiver(post_save, sender=BeerUser)
def assign_default_role(sender, instance, created, **kwargs):
    """
    Signal déclenché juste après la sauvegarde d'un BeerUser.
    Si c'est une création (created=True), on lui donne le rôle Contributeur par défaut.
    """
    if created:
        # get_or_create évite que le code plante si le groupe venait à être supprimé
        grp_contrib, _ = Group.objects.get_or_create(name='Contributeur')
        instance.groups.add(grp_contrib)

def delete_files_with(model, *fields):
    """Les fichiers d'un objet supprimé (par son auteur, la modération ou la suppression du compte) ne doivent pas rester dans le bucket."""
    def handler(sender, instance, **kwargs):
        for field in fields:
            stored = getattr(instance, field)
            if stored:
                storage, name = stored.storage, stored.name
                transaction.on_commit(lambda storage=storage, name=name: delete_stored_file(storage, name))
    post_delete.connect(handler, sender=model, weak=False, dispatch_uid=f'delete_files_{model.__name__}')


delete_files_with(BeerUser, 'avatar')
delete_files_with(Drinks, 'photo')
delete_files_with(Beer, 'image')
delete_files_with(Brewery, 'image')
delete_files_with(Bar, 'image')


@receiver(m2m_changed, sender=Brewery.managers.through)
def update_brewer_role(sender, instance, action, pk_set, **kwargs):
    """Ajoute ou retire automatiquement le rôle Brasseur en fonction des établissements gérés."""
    grp_brasseur, _ = Group.objects.get_or_create(name='Brasseur')
    
    if action == "post_add" and pk_set:
        users = BeerUser.objects.filter(pk__in=pk_set)
        for user in users:
            user.groups.add(grp_brasseur)
            
    elif action == "post_remove" and pk_set:
        users = BeerUser.objects.filter(pk__in=pk_set)
        for user in users:
            # S'il a été retiré et qu'il ne gère plus AUCUNE autre brasserie
            if not user.managed_breweries.exists():
                user.groups.remove(grp_brasseur)
                
    elif action == "pre_clear":
        # Si on vide complètement la liste des gérants de cette brasserie d'un coup
        for user in instance.managers.all():
            # On vérifie s'il gère d'autres brasseries que celle-ci
            if not user.managed_breweries.exclude(pk=instance.pk).exists():
                user.groups.remove(grp_brasseur)


@receiver(m2m_changed, sender=Bar.managers.through)
def update_bar_role(sender, instance, action, pk_set, **kwargs):
    """Ajoute ou retire automatiquement le rôle Bartender en fonction des établissements gérés."""
    grp_bartender, _ = Group.objects.get_or_create(name='Bartender')
    
    if action == "post_add" and pk_set:
        users = BeerUser.objects.filter(pk__in=pk_set)
        for user in users:
            user.groups.add(grp_bartender)
            
    elif action == "post_remove" and pk_set:
        users = BeerUser.objects.filter(pk__in=pk_set)
        for user in users:
            # S'il a été retiré et qu'il ne gère plus AUCUN autre bar
            if not user.managed_bars.exists():
                user.groups.remove(grp_bartender)
                
    elif action == "pre_clear":
        for user in instance.managers.all():
            if not user.managed_bars.exclude(pk=instance.pk).exists():
                user.groups.remove(grp_bartender)