"""
URL configuration for pokebeer project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.contrib.auth.decorators import login_not_required
from django.urls import path, include, re_path
from django.conf import settings
from django.views.decorators.http import require_GET
from django.views.static import serve

from app.admin.duplicates import duplicates_view

urlpatterns = [
    path(f'{settings.ADMIN_URL}analytics/', include('app.admin.analytics_urls')),
    path(f'{settings.ADMIN_URL}duplicates/', admin.site.admin_view(require_GET(duplicates_view)), name='admin_duplicates'),
    path(settings.ADMIN_URL, admin.site.urls),
    path('', include("app.urls"))
]

if settings.DEBUG:
    from django_browser_reload.views import events

    urlpatterns += [
        # Fichiers envoyés, servis localement en développement ; publics comme ceux du bucket en production
        re_path(rf'^{settings.MEDIA_URL.strip("/")}/(?P<path>.*)$', login_not_required(serve), {'document_root': settings.MEDIA_ROOT}),
        # Rechargement automatique (outil de développement), y compris sur les pages publiques
        path("__reload__/", include(([path("events/", login_not_required(events), name="events")], "django_browser_reload"))),
    ]

