"""Les vues du site, une par route de app/urls.py. Chaque nom est importé explicitement depuis son module : on sait où chacune vit."""
from .core_views import index
from .load_more import load_more_generic
from .auth_views import login_view, logout_view, register_pro_view, register_view
from .onboarding_views import onboarding_birth_view, onboarding_emails_view, onboarding_gender_view, onboarding_start_view
from .account_views import account_view, delete_account_view, settings_home_view, update_username_view
from .profile_views import achievements_view, follow_user, public_profile_view, remove_follower, reorder_top_beers, update_top_beer
from .reaction_views import toggle_reaction_view, toggle_wishlist
from .avatar_views import update_profile_picture
from .moderation_views import block_user, blocked_users_list, my_reports_view, submit_report, unblock_user
from .beer_views import (
    add_beer_done_view,
    add_beer_view,
    beer_detail_view,
    delete_beer_view,
    discard_beer_draft_view,
    edit_beer_view,
    save_beer_draft_view,
)
from .tasting_views import delete_drink_view, modify_rate_beer_view, rate_beer_done_view, rate_beer_view
from .api_views import analyze_beer_label, chat_api, check_catalog, lookup_ean, postal_code_lookup, search_beer, search_brewery
from .notification_views import (
    api_seen_notifications,
    api_unread_notifications,
    delete_notification,
    mark_all_notifications_read,
    notifications_view,
    read_notification,
    update_fcm_token,
)
from .feedback_views import feedback_thread_view, team_messages_view
from .notebook_views import (
    create_custom_notebook,
    delete_custom_notebook,
    edit_custom_notebook,
    notebook_detail_view,
    notebook_drinks_fragment,
    notebook_view,
    notebook_wishlist_fragment,
)
from .search_views import all_beers_view, places_directory, search_api
from .map_views import delete_spot_view, map_view
from .suggestion_views import suggest_edit_view
from .cron_views import purge_inactive_accounts_cron
from .password_reset_views import PasswordResetCompleteView, PasswordResetConfirmView, PasswordResetDoneView, PasswordResetRequestView
from .privacy_views import PrivacyPolicyView
from .email_views import assetlinks, email_preferences, email_unsubscribe
from .place_views import BAR_VIEWS, BREWERY_VIEWS, cancel_claim, cancel_invitation, respond_invitation

# Brasseries et bars : mêmes vues, produites une fois par type (place_views.views_for)
bar_detail_view, edit_bar_view, claim_bar_view = BAR_VIEWS.detail, BAR_VIEWS.edit, BAR_VIEWS.claim
add_bar_manager, remove_bar_manager, api_search_users_for_bar_manager = BAR_VIEWS.add_manager, BAR_VIEWS.remove_manager, BAR_VIEWS.search_users
brewery_detail_view, edit_brewery_view, claim_brewery_view = BREWERY_VIEWS.detail, BREWERY_VIEWS.edit, BREWERY_VIEWS.claim
add_brewery_manager, remove_brewery_manager = BREWERY_VIEWS.add_manager, BREWERY_VIEWS.remove_manager
api_search_users_for_manager = BREWERY_VIEWS.search_users

__all__ = [
    'index',
    'load_more_generic',
    'login_view',
    'logout_view',
    'register_pro_view',
    'register_view',
    'onboarding_birth_view',
    'onboarding_gender_view',
    'onboarding_emails_view',
    'onboarding_start_view',
    'account_view',
    'achievements_view',
    'delete_account_view',
    'follow_user',
    'public_profile_view',
    'remove_follower',
    'reorder_top_beers',
    'settings_home_view',
    'toggle_reaction_view',
    'toggle_wishlist',
    'update_top_beer',
    'update_username_view',
    'update_profile_picture',
    'block_user',
    'blocked_users_list',
    'my_reports_view',
    'submit_report',
    'unblock_user',
    'add_beer_done_view',
    'add_beer_view',
    'beer_detail_view',
    'delete_beer_view',
    'discard_beer_draft_view',
    'edit_beer_view',
    'save_beer_draft_view',
    'delete_drink_view',
    'modify_rate_beer_view',
    'rate_beer_done_view',
    'rate_beer_view',
    'analyze_beer_label',
    'chat_api',
    'check_catalog',
    'lookup_ean',
    'postal_code_lookup',
    'search_beer',
    'search_brewery',
    'api_seen_notifications',
    'api_unread_notifications',
    'delete_notification',
    'mark_all_notifications_read',
    'notifications_view',
    'read_notification',
    'update_fcm_token',
    'feedback_thread_view',
    'team_messages_view',
    'create_custom_notebook',
    'delete_custom_notebook',
    'edit_custom_notebook',
    'notebook_detail_view',
    'notebook_drinks_fragment',
    'notebook_view',
    'notebook_wishlist_fragment',
    'all_beers_view',
    'places_directory',
    'search_api',
    'delete_spot_view',
    'map_view',
    'add_bar_manager',
    'api_search_users_for_bar_manager',
    'bar_detail_view',
    'claim_bar_view',
    'edit_bar_view',
    'remove_bar_manager',
    'add_brewery_manager',
    'api_search_users_for_manager',
    'brewery_detail_view',
    'claim_brewery_view',
    'edit_brewery_view',
    'remove_brewery_manager',
    'suggest_edit_view',
    'purge_inactive_accounts_cron',
    'PasswordResetCompleteView',
    'PasswordResetConfirmView',
    'PasswordResetDoneView',
    'PasswordResetRequestView',
    'PrivacyPolicyView',
    'assetlinks',
    'email_preferences',
    'email_unsubscribe',
    'cancel_claim',
    'cancel_invitation',
    'respond_invitation',
]
