from django import template

from ..services.avatars import initials_avatar_url

register = template.Library()
register.filter('initials_avatar', initials_avatar_url)
