from django.contrib import admin
from .models import BeerUser, Beer, Drinks, Brewery, Report

admin.site.register(BeerUser)
admin.site.register(Beer)
admin.site.register(Drinks)
admin.site.register(Brewery)

@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'reporter', 'get_target', 'reason', 'status', 'created_at')
    list_filter = ('status', 'reason', 'created_at')
    search_fields = ('reporter__username', 'description', 'admin_response')
    # On empêche l'admin de modifier la plainte originale, il ne peut modifier que le statut et la réponse
    readonly_fields = ('reporter', 'reported_beer', 'reported_drink', 'reported_user', 'reason', 'description', 'created_at')

    def get_target(self, obj):
        if obj.reported_beer: return f"Bière: {obj.reported_beer.name}"
        if obj.reported_drink: return f"Note de: {obj.reported_drink.drinker_id.username}"
        if obj.reported_user: return f"Profil: {obj.reported_user.username}"
        return "Inconnu"
    get_target.short_description = "Cible signalée"