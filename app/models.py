from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.utils import timezone
from django.contrib.auth.models import UserManager
from datetime import date
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.text import slugify
from pgvector.django import VectorField
import requests
from django.db.models.signals import post_save, m2m_changed
from django.dispatch import receiver
from django.contrib.auth.models import Group

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
            response = requests.get(url, params=params, headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data:
                    self.latitude = float(data[0]['lat'])
                    self.longitude = float(data[0]['lon'])
                else:
                    # L'adresse n'a pas été trouvée par l'API
                    self.latitude = None
                    self.longitude = None
        except Exception as e:
            # En cas de coupure réseau ou erreur API, on ne fait pas crasher l'enregistrement
            print(f"Erreur de géocodage : {e}")

    def save(self, *args, **kwargs):
        # On vérifie si c'est une modification d'un objet existant
        if self.pk:
            old_instance = type(self).objects.get(pk=self.pk)
            # OPTIMISATION : On appelle l'API UNIQUEMENT si l'adresse a changé
            if old_instance.address != self.address:
                self._update_coordinates()
        else:
            # C'est une création de nouvel établissement
            self._update_coordinates()

        # On appelle le comportement de sauvegarde normal de Django
        super().save(*args, **kwargs)

class BeerUser(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True, null=False, blank=False)
    created_at = models.DateTimeField(default=timezone.now)
    username = models.CharField(max_length=150, blank=False, unique=True)
    bio = models.TextField(verbose_name="Biographie", blank=True, null=True)
    wishlist_beers = models.ManyToManyField('Beer', blank=True, related_name='wishlisted_by', verbose_name="Wishlist")
    top_beer_1 = models.ForeignKey('Beer', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    top_beer_2 = models.ForeignKey('Beer', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    top_beer_3 = models.ForeignKey('Beer', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    notif_global = models.BooleanField(default=True, verbose_name="Toutes les notifications")
    notif_follow = models.BooleanField(default=True, verbose_name="Nouveaux abonnés")
    notif_social = models.BooleanField(default=True, verbose_name="Interactions (Likes, Wishlists)")
    notif_network = models.BooleanField(default=True, verbose_name="Réseau (Ajouts de bières, Lieux)")
    notif_achievements = models.BooleanField(default=True, verbose_name="Trophées et récompenses")
    show_establishments = models.BooleanField(default=True, verbose_name="Afficher mes établissements publiquement")

    USERNAME_FIELD = "username"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["email"]

    objects = UserManager()
    
    class Meta:
        verbose_name = "Utilisateur"
        
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
        return any(group.name == 'Staff' for group in self.groups.all())
    
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

class Brewery(GeocodableMixin):
    name = models.CharField(max_length=150, blank=False, verbose_name="Nom")
    description = models.TextField(verbose_name="Description")
    image = models.ImageField(upload_to='breweries/', blank=True, null=True, verbose_name="Image")
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
    
    # Vérification
    is_verified = models.BooleanField(default=False, verbose_name="Brasserie vérifiée")
    verified_by = models.ForeignKey('BeerUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_breweries', verbose_name="Vérifiée par")
    verified_at = models.DateTimeField(null=True, blank=True, verbose_name="Date de vérification")

    class Meta:
        verbose_name = "Brasserie"
        ordering = ['name']

    def __str__(self):
        return self.name
    
class Bar(GeocodableMixin):
    name = models.CharField(max_length=150, blank=False, verbose_name="Nom")
    description = models.TextField(blank=True, null=True, verbose_name="Description")
    image = models.ImageField(upload_to='bars/', blank=True, null=True, verbose_name="Image")
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
    
    # Vérification
    is_verified = models.BooleanField(default=False, verbose_name="Bar vérifié")
    verified_by = models.ForeignKey('BeerUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_bars', verbose_name="Vérifié par")
    verified_at = models.DateTimeField(null=True, blank=True, verbose_name="Date de vérification")

    class Meta:
        verbose_name = "Bar"
        verbose_name_plural = "Bars"
        ordering = ['name']

    def __str__(self):
        return self.name

class Beer(models.Model):
    name = models.CharField(max_length=150, blank=False, unique=True, verbose_name="Nom")
    image = models.ImageField(upload_to='beers/', blank=True, null=True, verbose_name="Image")
    description = models.TextField(blank=True, null=True, verbose_name="Description officielle")
    bitterness = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(500)], verbose_name="IBU")
    degree = models.DecimalField(max_digits=4, decimal_places=1, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)], verbose_name="Degré")
    brewery_id = models.ForeignKey(Brewery, on_delete=models.CASCADE)
    slug = models.SlugField(max_length=150, unique=True, blank=True, null=True, verbose_name="Slug")
    style = models.CharField(max_length=100, blank=True, null=True, verbose_name="Style (ex: IPA, Stout...)")
    added_by = models.ForeignKey(BeerUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='added_beers')
    is_deleted = models.BooleanField(default=False, verbose_name="Supprimée du catalogue")
    
    embedding = VectorField(dimensions=3072, null=True, blank=True)

    class Meta:
        verbose_name = "Bière"
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            # Si le slug existe déjà (pour une autre bière), on ajoute un tiret et un chiffre
            while Beer.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
            
        text_to_embed = f"Bière {self.name} de la brasserie {self.brewery_id.name}. Style: {self.style or 'inconnu'}. Profil: {self.description}"
        
        from .services.ai import get_embedding 
        vector = get_embedding(text_to_embed)
        if vector:
            self.embedding = vector
            
        super().save(*args, **kwargs)

class Drinks(models.Model):
    date = models.DateField(default=date.today, verbose_name="Date")
    note = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(10)], null=True, blank=True, verbose_name="Note")
    comment = models.TextField(verbose_name="Commentaire")
    
    drinker_id = models.ForeignKey(BeerUser, on_delete=models.CASCADE)
    beer_id = models.ForeignKey(Beer, on_delete=models.CASCADE)
    
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    
    class Meta:
        verbose_name = "Dégustation"
        ordering = ['-date']

    def __str__(self):
        return f"{self.drinker_id.username} - {self.beer_id.name} ({self.note}/10)"
    
class BeerSpot(models.Model):
    user = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='spots')
    title = models.CharField(max_length=150, verbose_name="Titre du lieu")
    description = models.TextField(blank=True, null=True, verbose_name="Description / Souvenirs")
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
    
class Feedback(models.Model):
    STATUS_CHOICES = [
        ('pending', 'En attente'),
        ('replied', 'Répondu'),
    ]
    
    user = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='feedbacks', verbose_name="Utilisateur")
    message = models.TextField(verbose_name="Message / Suggestion")
    admin_reply = models.TextField(blank=True, null=True, verbose_name="Réponse de l'équipe")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="Statut")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date")

    class Meta:
        verbose_name = "Feedback / Suggestion"
        ordering = ['-created_at']

    def __str__(self):
        return f"Feedback de {self.user.username} ({self.get_status_display()})"
    
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
    
    # Cibles possibles (une seule sera remplie par signalement)
    reported_beer = models.ForeignKey('Beer', on_delete=models.CASCADE, null=True, blank=True, verbose_name="Bière signalée")
    reported_drink = models.ForeignKey('Drinks', on_delete=models.CASCADE, null=True, blank=True, verbose_name="Dégustation signalée")
    reported_user = models.ForeignKey('BeerUser', on_delete=models.CASCADE, null=True, blank=True, related_name='reports_received', verbose_name="Membre signalé")

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

    class Meta:
        unique_together = ('blocker', 'blocked')
        verbose_name = "Blocage"

    def __str__(self):
        return f"{self.blocker.username} a bloqué {self.blocked.username}"

class NotificationManager(models.Manager):
    def bulk_create(self, objs, **kwargs):
        """Intercepte les bulk_create pour retirer les notifications refusées."""
        # On filtre la liste avec notre nouvelle méthode is_allowed()
        valid_objs = [obj for obj in objs if obj.is_allowed()]
        
        # Si après filtrage la liste est vide, on arrête tout
        if not valid_objs:
            return []
            
        return super().bulk_create(valid_objs, **kwargs)
    
class Notification(models.Model):
    
    objects = NotificationManager()
    
    NOTIFICATION_TYPES = [
        ('follow', 'Nouvel abonné'),
        ('beer_shared', 'Bière goûtée en commun'),
        ('beer_added', 'Nouvelle bière d\'un abonnement'),
        ('achievement', 'Nouveau trophée'),
        ('spot_invite', 'Invitation à un lieu'),
        ('spot_updated', 'Lieu mis à jour'),
        ('beer_updated', 'Bière mise à jour'),
        ('drink_liked', 'Avis aimé'),
        ('report_updated', 'Signalement mis à jour'),
        ('wishlist_added', 'Bière ajoutée à la liste de souhaits'),
        ('feedback_replied', 'Réponse à votre feedback'),
    ]

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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

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
        """Vérifie si l'utilisateur accepte ce type de notification."""
        user = self.recipient
        
        # Les messages système sont toujours autorisés
        if self.notif_type in ['report_updated', 'feedback_replied']:
            return True
            
        if not user.notif_global:
            return False
        if self.notif_type == 'follow' and not user.notif_follow:
            return False
        if self.notif_type in ['drink_liked', 'wishlist_added'] and not user.notif_social:
            return False
        if self.notif_type == 'achievement' and not user.notif_achievements:
            return False
        if self.notif_type in ['beer_added', 'beer_shared', 'spot_invite', 'spot_updated', 'beer_updated'] and not user.notif_network:
            return False
            
        return True
    
    def save(self, *args, **kwargs):
        # On intercepte uniquement les nouvelles notifications (sans ID)
        if not self.pk: 
            if not self.is_allowed():
                return # On annule silencieusement
                
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
        
class CustomNotebook(models.Model):
    user = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='custom_notebooks')
    title = models.CharField(max_length=150, verbose_name="Titre du carnet")
    description = models.TextField(blank=True, null=True, verbose_name="Description")
    drinks = models.ManyToManyField('Drinks', blank=True, related_name='notebooks', verbose_name="Dégustations")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Carnet personnalisé"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.user.username}"
    
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

@receiver(m2m_changed, sender=Brewery.managers.through)
def assign_brewer_role(sender, instance, action, pk_set, **kwargs):
    """
    Écoute l'ajout d'utilisateurs dans le champ 'managers' d'une Brasserie.
    Leur donne automatiquement le rôle 'Brasseur'.
    """
    if action == "post_add":
        grp_brasseur, _ = Group.objects.get_or_create(name='Brasseur')
        # pk_set contient les IDs des utilisateurs qui viennent d'être ajoutés
        users = BeerUser.objects.filter(pk__in=pk_set)
        for user in users:
            user.groups.add(grp_brasseur)


@receiver(m2m_changed, sender=Bar.managers.through)
def assign_bar_role(sender, instance, action, pk_set, **kwargs):
    """
    Écoute l'ajout d'utilisateurs dans le champ 'managers' d'un Bar.
    Leur donne automatiquement le rôle 'Bar'.
    """
    if action == "post_add":
        grp_bar, _ = Group.objects.get_or_create(name='Bar')
        users = BeerUser.objects.filter(pk__in=pk_set)
        for user in users:
            user.groups.add(grp_bar)