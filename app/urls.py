from django.urls import path, include

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path('rate-beer/<int:beer_id>/', views.rate_beer_view, name='rate_beer'),
    path('api/chat/', views.chat_api, name='chat_api'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('accounts/', include('allauth.urls')),
    path('add-beer/', views.add_beer_view, name='add_beer'),
    path('beers/', views.all_beers_view, name='all_beers'),
    path('api/search-brewery/', views.search_brewery, name='search_brewery'),
    path('api/search-beer/', views.search_beer, name='search_beer'),
    path('beer/<slug:beer_slug>/', views.beer_detail_view, name='beer_detail'),
]