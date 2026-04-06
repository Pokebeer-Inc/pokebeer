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

    USERNAME_FIELD = "username"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["email"]

    objects = UserManager()
    
    class Meta:
        verbose_name = "Utilisateur"

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

    class Meta:
        verbose_name = "Brasserie"
        ordering = ['name']

    def __str__(self):
        return self.name

class Beer(models.Model):
    name = models.CharField(max_length=150, blank=False, unique=True, verbose_name="Nom")
    image = models.ImageField(upload_to='beers/', blank=True, null=True, verbose_name="Image")
    description = models.TextField(verbose_name="Description")
    bitterness = models.IntegerField(default=0, verbose_name="Amertume (IBU)")
    degree = models.DecimalField(max_digits=4, decimal_places=1, default=0, verbose_name="Degré")
    brewery_id = models.ForeignKey(Brewery, on_delete=models.CASCADE)
    slug = models.SlugField(max_length=150, unique=True, blank=True, null=True, verbose_name="Slug")
    style = models.CharField(max_length=100, blank=True, null=True, verbose_name="Style (ex: IPA, Stout...)")
    added_by = models.ForeignKey(BeerUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='added_beers')
    
    embedding = VectorField(dimensions=384, null=True, blank=True)

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
        
        from .services import get_embedding 
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