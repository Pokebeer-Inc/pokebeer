from django.urls import path, include
from . import views

urlpatterns = [
    # ==========================================
    # Pages Principales & Navigation
    # ==========================================
    path("", views.index, name="index"),
    path('beers/', views.all_beers_view, name='all_beers'),
    path('map/', views.map_view, name='map'),

    # ==========================================
    # Authentification & Compte Utilisateur
    # ==========================================
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('account/', views.account_view, name='account'),
    path('delete-account/', views.delete_account_view, name='delete_account'),
    path('accounts/', include('allauth.urls')),

    # ==========================================
    # Profils Publics & Social
    # ==========================================
    path('user/<str:username>/', views.public_profile_view, name='public_profile'),
    path('follow/<str:username>/', views.follow_user, name='follow_user'),
    path('remove-follower/<str:username>/', views.remove_follower, name='remove_follower'),
    
    # ==========================================
    # Signalements
    # ==========================================
    path('my-reports/', views.my_reports_view, name='my_reports'),
    path('submit-report/', views.submit_report, name='submit_report'),

    # ==========================================
    # Gestion du Catalogue de Bières
    # ==========================================
    path('beer/<slug:beer_slug>/', views.beer_detail_view, name='beer_detail'),
    path('add-beer/', views.add_beer_view, name='add_beer'),
    path('edit-beer/<slug:beer_slug>/', views.edit_beer_view, name='edit_beer'),
    path('delete-beer/<slug:beer_slug>/', views.delete_beer_view, name='delete_beer'),

    # ==========================================
    # Dégustations (Avis) & Lieux (Spots)
    # ==========================================
    path('rate-beer/<int:beer_id>/', views.rate_beer_view, name='rate_beer'),
    path('modify-rate-beer/<int:drink_id>/', views.modify_rate_beer_view, name='modify_rate_beer'),
    path('delete-drink/<int:drink_id>/', views.delete_drink_view, name='delete_drink'),
    path('delete-spot/<int:spot_id>/', views.delete_spot_view, name='delete_spot'),

    # ==========================================
    # API (Recherche, IA, etc.)
    # ==========================================
    path('api/chat/', views.chat_api, name='chat_api'),
    path('api/analyze-label/', views.analyze_beer_label, name='analyze_label'),
    path('api/search-brewery/', views.search_brewery, name='search_brewery'),
    path('api/search-beer/', views.search_beer, name='search_beer'),
]