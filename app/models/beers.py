"""Bières, dégustations, réactions et carnets."""

from django.core.validators import MaxValueValidator, MinValueValidator
from pgvector.django import VectorField
from datetime import date
from django.contrib.postgres.indexes import GinIndex
from django.db import models, transaction

from ..validators import MAX_TEXT_LENGTH, plain_text_validator
from ..fields import PublicSlugField
from ..services.official_images import beer_image_path
from ..services.tasting_photos import tasting_photo_path

from .establishments import Brewery
from ..services import match_keys
from .mixins import MatchKeyMixin, OfficialImageMixin, VerifiableMixin
from .users import BeerUser


class Beer(OfficialImageMixin, VerifiableMixin, MatchKeyMixin):
    MATCH_KIND = match_keys.BEER

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
    # Code-barres EAN lu à l'ajout : une prochaine lecture retrouve la bière dans le catalogue, sans service extérieur
    ean = models.CharField(max_length=13, null=True, blank=True, editable=False, verbose_name="Code-barres EAN")

    embedding = VectorField(dimensions=3072, null=True, blank=True)

    class Meta:
        verbose_name = "Bière"
        ordering = ['name']
        indexes = [GinIndex(fields=['match_key'], name='beer_match_key_trgm', opclasses=['gin_trgm_ops'])]
        constraints = [
            # Un nom par brasserie (deux brasseries peuvent avoir chacune leur « Blonde »). Une bière retirée du catalogue libère son
            # nom ; le slug reste unique pour garder ses anciennes URLs. Les noms proches sont traités par services/catalog_matching.py.
            models.UniqueConstraint(
                fields=['brewery_id', 'name'],
                condition=models.Q(is_deleted=False),
                name='unique_active_beer_name_per_brewery',
                violation_error_message="Cette brasserie a déjà une bière de ce nom.",
            ),
            # Un code-barres désigne une seule bière du catalogue : le premier ajout le garde
            models.UniqueConstraint(
                fields=['ean'],
                condition=models.Q(is_deleted=False, ean__isnull=False),
                name='unique_active_beer_ean',
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
        from ..services.ai import get_embedding
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
