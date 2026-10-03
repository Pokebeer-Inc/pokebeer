"""Administration du catalogue : bières, dégustations, brasseries, bars.

La certification des bars et brasseries se fait depuis « Contenus à valider » (services/moderation).
"""
from django.contrib import admin
from unfold.admin import ModelAdmin

from ..models import Beer, Drinks, Brewery, Bar


admin.site.register(Beer)
admin.site.register(Drinks)
admin.site.register(Brewery)


@admin.register(Bar)
class BarAdmin(ModelAdmin):
    pass
