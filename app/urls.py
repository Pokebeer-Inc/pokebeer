from django.urls import path, include

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path('rate-beer/<int:beer_id>/', views.rate_beer_view, name='rate_beer'),
    path('modify-rate-beer/<int:drink_id>/', views.modify_rate_beer_view, name='modify_rate_beer'),
    path('api/chat/', views.chat_api, name='chat_api'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('accounts/', include('allauth.urls')),
    path('account/', views.account_view, name='account'),
    path('add-beer/', views.add_beer_view, name='add_beer'),
    path('beers/', views.all_beers_view, name='all_beers'),
    path('api/search-brewery/', views.search_brewery, name='search_brewery'),
    path('api/search-beer/', views.search_beer, name='search_beer'),
    path('api/search-user/', views.search_user, name='search_user'),
    path('beer/<slug:beer_slug>/', views.beer_detail_view, name='beer_detail'),
    path('user/<str:username>/', views.public_profile_view, name='public_profile'),
    path('follow/<str:username>/', views.follow_user, name='follow_user'),
]