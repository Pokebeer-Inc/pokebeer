from django.contrib import admin
from django.db import models
from django.db.models import Count
from django.contrib.postgres.fields import ArrayField
from unfold.admin import ModelAdmin
from unfold.contrib.forms.widgets import ArrayWidget, WysiwygWidget
from .models import BeerUser, Beer, Drinks, Brewery, Report
from .models import Notification, Feedback
from .services.realtime_service import broadcast_notifications


admin.site.register(BeerUser)
admin.site.register(Beer)
admin.site.register(Drinks)
admin.site.register(Brewery)


@admin.register(Report)
class ReportAdmin(ModelAdmin):
    #Configuration DjangoUnfold
    readonly_preprocess_fields = {
        "model_field_name": "html.unescape",
        "other_field_name": lambda content: content.strip(),
    }

    formfield_overrides = {
        models.TextField: {
            "widget": WysiwygWidget,
        },
        ArrayField: {
            "widget": ArrayWidget,
        }
    }

    compressed_fields = False
    warn_unsaved_form = True


    list_display = ('reporter', 'get_target', 'reason', 'status', 'created_at')
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
    
    def save_model(self, request, obj, form, change):
        # On sauvegarde d'abord l'objet
        super().save_model(request, obj, form, change)
        
        # Si c'est une modification (change=True) et que le statut ou la réponse a été modifié
        if change and ('status' in form.changed_data or 'admin_response' in form.changed_data):
            
            notif = Notification.objects.create(
                recipient=obj.reporter, # La cible est uniquement l'auteur du signalement
                sender=None,            # C'est une notification "Système"
                notif_type='report_updated',
                report=obj
            )
            broadcast_notifications([notif])

@admin.register(Feedback)
class FeedbackAdmin(ModelAdmin):
  #Configuration DjangoUnfold
    readonly_preprocess_fields = {
        "model_field_name": "html.unescape",
        "other_field_name": lambda content: content.strip(),
    }

    formfield_overrides = {
        models.TextField: {
            "widget": WysiwygWidget,
        },
        ArrayField: {
            "widget": ArrayWidget,
        }
    }

    compressed_fields = False
    warn_unsaved_form = True
   
    list_display = ('id', 'user', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('user__username', 'message', 'admin_reply')
    # L'admin ne peut pas modifier le message original de l'utilisateur
    readonly_fields = ('user', 'message', 'created_at')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        
        # Si on est en modification, que la réponse admin a été modifiée et n'est pas vide
        if change and 'admin_reply' in form.changed_data and obj.admin_reply:
            obj.status = 'replied' # On passe le statut en "Répondu"
            obj.save()
            
            # On génère la notification et on l'envoie via WebSockets
            notif = Notification.objects.create(
                recipient=obj.user,
                sender=None, 
                notif_type='feedback_replied',
                feedback=obj
            )
            broadcast_notifications([notif])

def dashboard_callback(request, context):
    beer_count_by_style = (
        Beer.objects
        .exclude(style__isnull=True)
        .exclude(style='')
        .values('style')
        .annotate(nb_bieres=Count('id'))
        .order_by('style')
    )

    kpi_users = (BeerUser.objects.count)
    kpi_beers = (Beer.objects.count)
    kpi_brewery = (Brewery.objects.count)
    kpi_report = (Report.objects.count)

    context.update({
        "beer_count_by_style": list(beer_count_by_style),
        "kpi_users":kpi_users,
        "kpi_beers":kpi_beers,
        "kpi_brewery":kpi_brewery,
        "kpi_report":kpi_report
    })

    return context