from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.utils import timezone
from django.contrib.auth.models import UserManager
from datetime import date
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.text import slugify
from pgvector.django import VectorField

class BeerUser(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True, null=False, blank=False)
    created_at = models.DateTimeField(default=timezone.now)
    username = models.CharField(max_length=150, blank=False, unique=True)
    is_staff = models.BooleanField(default=False)
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

    def __str__(self):
        return self.username
    
class UserFollow(models.Model):
    follower = models.ForeignKey(BeerUser, related_name='following', on_delete=models.CASCADE)
    followed = models.ForeignKey(BeerUser, related_name='followers', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('follower', 'followed')

class Brewery(models.Model):
    name = models.CharField(max_length=150, blank=False, unique=True, verbose_name="Nom")
    description = models.TextField(verbose_name="Description")
    city = models.CharField(max_length=150, verbose_name="Ville")
    image = models.ImageField(upload_to='breweries/', blank=True, null=True, verbose_name="Image")

    class Meta:
        verbose_name = "Brasserie"
        ordering = ['name']

    def __str__(self):
        return self.name

class Beer(models.Model):
    name = models.CharField(max_length=150, blank=False, unique=True, verbose_name="Nom")
    image = models.ImageField(upload_to='beers/', blank=True, null=True, verbose_name="Image")
    description = models.TextField(verbose_name="Description")
    bitterness = models.IntegerField(null=True, blank=True, verbose_name="Amertume (IBU)")
    degree = models.DecimalField(max_digits=4, decimal_places=1, default=0, verbose_name="Degré")
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
    note = models.IntegerField(
        default=0, 
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        verbose_name="Note /10"
    )
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
        ('wishlist_added', 'Bière ajoutée en wishlist'),
        ('feedback_replied', 'Réponse à votre feedback'),
    ]

    recipient = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='notifications')
    sender = models.ForeignKey('BeerUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_notifications')
    notif_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES)
    report = models.ForeignKey('Report', on_delete=models.CASCADE, null=True, blank=True)
    feedback = models.ForeignKey('Feedback', on_delete=models.CASCADE, null=True, blank=True)
    
    beer = models.ForeignKey('Beer', on_delete=models.CASCADE, null=True, blank=True)
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