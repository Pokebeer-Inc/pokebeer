from django.urls import path, include
from . import views

urlpatterns = [
    # ==========================================
    # Pages Principales & Navigation
    # ==========================================
    path("", views.index, name="index"),
    path('load-more-beers/', views.load_more_beers, name='load_more_beers'),
    path('beers/', views.all_beers_view, name='all_beers'),
    path('map/', views.map_view, name='map'),
    path('trophees/', views.achievements_view, name='achievements'),
    path('load-more-search-beers/', views.load_more_search_beers, name='load_more_search_beers'),
    path('load-more-search-users/', views.load_more_search_users, name='load_more_search_users'),
    path('carnet/', views.notebook_view, name='notebook'),
    path('load-more-notebook-drinks/', views.load_more_notebook_drinks, name='load_more_notebook_drinks'),
    path('load-more-added-beers/', views.load_more_added_beers, name='load_more_added_beers'),
    path('load-more-notebook-feedback/', views.load_more_notebook_feedback, name='load_more_notebook_feedback'),

    # ==========================================
    # Authentification & Compte Utilisateur
    # ==========================================
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('account/', views.account_view, name='account'),
    path('delete-account/', views.delete_account_view, name='delete_account'),
    path('accounts/', include('allauth.urls')),
    path('update-top-beer/<int:slot>/', views.update_top_beer, name='update_top_beer'),
    path('swap-top-beers/', views.swap_top_beers, name='swap_top_beers'),
    
    # ==========================================
    # Notifications
    # ==========================================
    path('notifications/', views.notifications_view, name='notifications'),
    path('notifications/read/<int:notif_id>/', views.read_notification, name='read_notification'),
    path('notifications/delete/<int:notif_id>/', views.delete_notification, name='delete_notification'),

    # ==========================================
    # Profils Publics & Social
    # ==========================================
    path('user/<str:username>/', views.public_profile_view, name='public_profile'),
    path('follow/<str:username>/', views.follow_user, name='follow_user'),
    path('remove-follower/<str:username>/', views.remove_follower, name='remove_follower'),
    
    # ==========================================
    # Signalements & Modération
    # ==========================================
    path('my-reports/', views.my_reports_view, name='my_reports'),
    path('submit-report/', views.submit_report, name='submit_report'),
    path('block-user/<str:username>/', views.block_user, name='block_user'),
    path('unblock-user/<str:username>/', views.unblock_user, name='unblock_user'),
    path('blocked-users/', views.blocked_users_list, name='blocked_users'),

    # ==========================================
    # Gestion du Catalogue de Bières
    # ==========================================
    path('beer/<slug:beer_slug>/', views.beer_detail_view, name='beer_detail'),
    path('add-beer/', views.add_beer_view, name='add_beer'),
    path('edit-beer/<slug:beer_slug>/', views.edit_beer_view, name='edit_beer'),
    path('delete-beer/<slug:beer_slug>/', views.delete_beer_view, name='delete_beer'),
    
    # ==========================================
    # Gestion des Brasseries
    # ==========================================
    path('brewery/<int:brewery_id>/', views.brewery_detail_view, name='brewery_detail'),

    # ==========================================
    # Dégustations (Avis) & Lieux (Spots)
    # ==========================================
    path('rate-beer/<int:beer_id>/', views.rate_beer_view, name='rate_beer'),
    path('modify-rate-beer/<int:drink_id>/', views.modify_rate_beer_view, name='modify_rate_beer'),
    path('delete-drink/<int:drink_id>/', views.delete_drink_view, name='delete_drink'),
    path('delete-spot/<int:spot_id>/', views.delete_spot_view, name='delete_spot'),
    path('drink/<int:drink_id>/react/', views.toggle_reaction_view, name='toggle_reaction'),

    # ==========================================
    # API (Recherche, IA, etc.)
    # ==========================================
    path('api/chat/', views.chat_api, name='chat_api'),
    path('api/analyze-label/', views.analyze_beer_label, name='analyze_label'),
    path('api/search-brewery/', views.search_brewery, name='search_brewery'),
    path('api/search-beer/', views.search_beer, name='search_beer'),
]