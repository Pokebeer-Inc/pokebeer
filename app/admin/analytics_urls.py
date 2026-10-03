"""Routes des analytics. `admin_view` impose la connexion à l'admin ; les routes personnalisées passent avant `<slug:key>/`."""
from django.contrib import admin
from django.urls import path
from django.views.decorators.http import require_GET, require_POST

from . import analytics, analytics_custom as custom

protected = admin.site.admin_view

urlpatterns = [
    path('', protected(require_GET(analytics.analytics_index)), name='admin_analytics_index'),

    # Vues personnalisées
    path('custom/', protected(require_GET(custom.custom_home)), name='admin_analytics_custom'),
    path('custom/new/', protected(custom.view_create), name='admin_analytics_view_create'),
    path('custom/<int:view_id>/', protected(require_GET(custom.view_show)), name='admin_analytics_view'),
    path('custom/<int:view_id>/rename/', protected(custom.view_rename), name='admin_analytics_view_rename'),
    path('custom/<int:view_id>/delete/', protected(custom.view_delete), name='admin_analytics_view_delete'),
    path('custom/<int:view_id>/tiles/new/', protected(custom.tile_new), name='admin_analytics_tile_new'),
    path('custom/<int:view_id>/tiles/<int:tile_id>/edit/', protected(custom.tile_edit), name='admin_analytics_tile_edit'),
    path('custom/<int:view_id>/tiles/<int:tile_id>/delete/', protected(custom.tile_delete), name='admin_analytics_tile_delete'),

    # Pages prédéfinies (et disposition mémorisée de n'importe quelle page, y compris `custom-<id>`)
    path('<slug:key>/layout/', protected(require_POST(analytics.analytics_layout)), name='admin_analytics_layout'),
    path('<slug:key>/', protected(require_GET(analytics.analytics_page)), name='admin_analytics'),
]
