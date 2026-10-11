"""Rôles utilisateur : groupes Django cumulatifs (Contributeur toujours conservé) + drapeau superuser pour Admin."""
from django.contrib.auth.models import Group
from django.db.models import Count, Q

from app.models import STAFF_GROUP

CONTRIBUTOR_GROUP = 'Contributeur'
ADMIN = 'admin'

# clé -> (libellé, groupe Django ou None pour Admin, description)
ROLES = {
    'contributor': ('Contributeur', CONTRIBUTOR_GROUP, "Attribué à l'inscription, toujours conservé."),
    'brewer': ('Brasseur', 'Brasseur', "Gère une brasserie (attribué automatiquement via les gérants)."),
    'bartender': ('Bartender', 'Bartender', "Gère un bar (attribué automatiquement via les gérants)."),
    'staff': ('Staff', STAFF_GROUP, "Accès à l'administration (modération)."),
    ADMIN: ('Admin', None, "Superuser : tous les droits, y compris la gestion des rôles."),
}
LOCKED_ROLES = {'contributor'}


def user_roles(user):
    """Clés des rôles détenus par l'utilisateur (utilise les groupes préchargés si disponibles)."""
    group_names = {group.name for group in user.groups.all()}
    return [
        key for key, (_, group, _) in ROLES.items()
        if (user.is_superuser if key == ADMIN else group in group_names)
    ]


def grant_role(user, key):
    if key == ADMIN:
        user.is_superuser = True
        user.save(update_fields=['is_superuser'])
        # Sans le groupe Staff, l'admin Django refuse l'accès au superuser
        key = 'staff'
    user.groups.add(Group.objects.get_or_create(name=ROLES[key][1])[0])


def revoke_role(user, key):
    if key in LOCKED_ROLES:
        raise ValueError("Le rôle Contributeur ne peut pas être retiré.")
    if key == ADMIN:
        user.is_superuser = False
        user.save(update_fields=['is_superuser'])
    else:
        user.groups.remove(*Group.objects.filter(name=ROLES[key][1]))


def role_q(key):
    """Filtre ORM des membres détenant le rôle."""
    return Q(is_superuser=True) if key == ADMIN else Q(groups__name=ROLES[key][1])


def role_counts(queryset):
    """Effectif par rôle en une seule requête : {clé: nombre}."""
    return queryset.aggregate(**{key: Count('pk', filter=role_q(key), distinct=True) for key in ROLES})
