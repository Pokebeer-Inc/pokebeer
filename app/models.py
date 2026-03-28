from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.utils import timezone
from django.contrib.auth.models import UserManager
from datetime import date
from django.core.validators import MinValueValidator, MaxValueValidator

class BeerUser(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True, null=False, blank=False)
    created_at = models.DateTimeField(default=timezone.now)
    username = models.CharField(max_length=150, blank=False, unique=True)
    is_staff = models.BooleanField(default=False)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = []

    objects = UserManager()
    
    class Meta:
        verbose_name = "Utilisateur"

    def __str__(self):
        return self.username

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
    description = models.TextField(verbose_name="Description")
    bitterness = models.IntegerField(default=0, verbose_name="Amertume (IBU)")
    degree = models.DecimalField(max_digits=4, decimal_places=1, default=0, verbose_name="Degré")

    brewery_id = models.ForeignKey(Brewery, on_delete=models.CASCADE)
    
    class Meta:
        verbose_name = "Bière"
        ordering = ['name']

    def __str__(self):
        return self.name

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
    
    class Meta:
        verbose_name = "Dégustation"
        ordering = ['-date']

    def __str__(self):
        return f"{self.drinker.username} - {self.beer.name} ({self.note}/10)"