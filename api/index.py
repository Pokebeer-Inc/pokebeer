import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pokebeer.settings")

from django.core.wsgi import get_wsgi_application

app = get_wsgi_application()