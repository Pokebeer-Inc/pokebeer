from django.contrib import admin
from .models import BeerUser, Beer, Drinks, Brewery

admin.site.register(BeerUser)
admin.site.register(Beer)
admin.site.register(Drinks)
admin.site.register(Brewery)