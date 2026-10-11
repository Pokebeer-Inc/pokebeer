"""Administration du catalogue : bières, dégustations, brasseries, bars.

La certification des bars et brasseries se fait depuis « Contenus à valider » (services/moderation).
"""
from django.contrib import admin
from unfold.admin import ModelAdmin

from ..models import Beer, Drinks, Brewery, Bar
from ..services.catalog.official_images import process_official_image
from ..services.catalog.tasting_photos import process_tasting_photo
from .images import ProcessedImageAdminMixin


class OfficialImageAdmin(ProcessedImageAdminMixin, ModelAdmin):
    image_processors = {'image': process_official_image}




@admin.register(Beer)
class BeerAdmin(OfficialImageAdmin):
    # Le vecteur de recherche du chat IA est calculé par le site (services/catalog/embeddings.py) : l'afficher comme un champ de texte de
    # 1024 nombres invitait à le casser (un envoi vide faisait planter l'enregistrement)
    exclude = ('embedding',)


admin.site.register(Brewery, OfficialImageAdmin)
admin.site.register(Bar, OfficialImageAdmin)


@admin.register(Drinks)
class DrinksAdmin(ProcessedImageAdminMixin, ModelAdmin):
    image_processors = {'photo': process_tasting_photo}
