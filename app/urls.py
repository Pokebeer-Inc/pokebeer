from django.urls import path, include
from django.views.generic import RedirectView
from . import views

urlpatterns = [
    # ==========================================
    # Pages Principales & Navigation
    # ==========================================
    path("", views.index, name="index"),
    path('beers/', views.all_beers_view, name='all_beers'),
    path('map/', views.map_view, name='map'),
    path('trophees/', views.achievements_view, name='achievements'),
    path('carnet/', views.notebook_view, name='notebook'),
    # Les routes fixes précèdent carnet/<slug>/ : sinon le slug les capturerait
    path('carnet/create/', views.create_custom_notebook, name='create_custom_notebook'),
    path('carnet/all/', views.notebook_detail_view, name='notebook_all'),
    path('carnet/wishlist/', views.wishlist_view, name='wishlist_view'),
    path('carnet/<slug:notebook_slug>/', views.notebook_detail_view, name='notebook_detail'),
    path('carnet/<slug:notebook_slug>/delete/', views.delete_custom_notebook, name='delete_custom_notebook'),
    path('carnet/<slug:notebook_slug>/edit/', views.edit_custom_notebook, name='edit_custom_notebook'),

    # ==========================================
    # Authentification & Compte Utilisateur
    # ==========================================
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('account/', views.account_view, name='account'),
    path('delete-account/', views.delete_account_view, name='delete_account'),
    path('cron/purge-inactive-accounts/', views.purge_inactive_accounts_cron, name='cron_purge_inactive_accounts'),
    # Les pages de connexion et d'inscription d'allauth contourneraient nos protections : on les renvoie vers les nôtres
    path('accounts/login/', RedirectView.as_view(pattern_name='login', query_string=True), name='allauth_login_redirect'),
    path('accounts/signup/', RedirectView.as_view(pattern_name='register', query_string=True), name='allauth_signup_redirect'),
    path('accounts/', include('allauth.urls')),
    path('update-top-beer/<int:slot>/', views.update_top_beer, name='update_top_beer'),
    path('swap-top-beers/', views.swap_top_beers, name='swap_top_beers'),
    path('register/pro/<str:pro_type>/', views.register_pro_view, name='register_pro'),
    
    # ==========================================
    # Notifications
    # ==========================================
    path('notifications/', views.notifications_view, name='notifications'),
    path('notifications/read/<slug:notif_slug>/', views.read_notification, name='read_notification'),
    path('notifications/delete/<slug:notif_slug>/', views.delete_notification, name='delete_notification'),
    path('notifications/read-all/', views.mark_all_notifications_read, name='mark_all_notifications_read'),

    # Échanges avec l'équipe
    path('messages/', views.team_messages_view, name='team_messages'),
    path('messages/<slug:feedback_slug>/', views.feedback_thread_view, name='feedback_thread'),

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
    path('account/avatar/', views.update_profile_picture, name='update_profile_picture'),
    path('blocked-users/', views.blocked_users_list, name='blocked_users'),

    # ==========================================
    # Gestion du Catalogue de Bières
    # ==========================================
    path('beer/<slug:beer_slug>/', views.beer_detail_view, name='beer_detail'),
    path('add-beer/', views.add_beer_view, name='add_beer'),
    path('edit-beer/<slug:beer_slug>/', views.edit_beer_view, name='edit_beer'),
    path('delete-beer/<slug:beer_slug>/', views.delete_beer_view, name='delete_beer'),
    path('beer/<slug:beer_slug>/wishlist/', views.toggle_wishlist, name='toggle_wishlist'),
    
    # ==========================================
    # Gestion des Brasseries & Bars
    # ==========================================
    path('brewery/<slug:brewery_slug>/', views.brewery_detail_view, name='brewery_detail'),
    path('bar/<slug:bar_slug>/', views.bar_detail_view, name='bar_detail'),
    path('brewery/<slug:brewery_slug>/edit/', views.edit_brewery_view, name='edit_brewery'),
    path('brewery/<slug:brewery_slug>/add-manager/', views.add_brewery_manager, name='add_brewery_manager'),
    path('brewery/<slug:brewery_slug>/remove-manager/<str:username>/', views.remove_brewery_manager, name='remove_brewery_manager'),
    path('bar/<slug:bar_slug>/edit/', views.edit_bar_view, name='edit_bar'),
    path('bar/<slug:bar_slug>/add-manager/', views.add_bar_manager, name='add_bar_manager'),
    path('bar/<slug:bar_slug>/remove-manager/<str:username>/', views.remove_bar_manager, name='remove_bar_manager'),

    # ==========================================
    # Dégustations (Avis) & Lieux (Spots)
    # ==========================================
    path('rate-beer/<slug:beer_slug>/', views.rate_beer_view, name='rate_beer'),
    path('modify-rate-beer/<slug:drink_slug>/', views.modify_rate_beer_view, name='modify_rate_beer'),
    path('delete-drink/<slug:drink_slug>/', views.delete_drink_view, name='delete_drink'),
    path('delete-spot/<slug:spot_slug>/', views.delete_spot_view, name='delete_spot'),
    path('drink/<slug:drink_slug>/react/', views.toggle_reaction_view, name='toggle_reaction'),

    # ==========================================
    # API (Recherche, IA, etc.)
    # ==========================================
    path('api/chat/', views.chat_api, name='chat_api'),
    path('api/analyze-label/', views.analyze_beer_label, name='analyze_label'),
    path('api/search-brewery/', views.search_brewery, name='search_brewery'),
    path('api/search-beer/', views.search_beer, name='search_beer'),
    path('api/notifications/unread/', views.api_unread_notifications, name='api_unread_notifications'),
    path('api/notifications/seen/', views.api_seen_notifications, name='api_seen_notifications'),
    path('api/load-more/<str:item_type>/', views.load_more_generic, name='load_more_generic'),
    path('api/brewery/<slug:brewery_slug>/search-users/', views.api_search_users_for_manager, name='api_search_users_for_manager'),
    path('api/bar/<slug:bar_slug>/search-users/', views.api_search_users_for_bar_manager, name='api_search_users_for_bar_manager'),
    path('api/update-fcm-token/', views.update_fcm_token, name="api_update_fcm_token")

]