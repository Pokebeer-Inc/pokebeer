"""Liens du site et de l'application Android, tels qu'ils apparaissent dans les e-mails.

Aucune redirection côté serveur : un lien d'e-mail est une adresse https du site. Android l'ouvre dans l'application quand elle
est installée et vérifiée pour ce domaine (assetlinks.json), sinon dans le navigateur ; Gmail et consorts retirent les schémas
personnalisés (`intent://`), seuls les App Links fonctionnent partout. Le bouton Google Play couvre les membres sans l'application.
"""
from django.conf import settings
from django.urls import reverse

# Pages mises en avant dans l'e-mail de bienvenue : nom de route + libellé
HIGHLIGHTS = (
    ('all_beers', "Le catalogue de bières", "Parcourez les bières, filtrez par style, goûtez et notez."),
    ('map', "La carte des souvenirs", "Posez un lieu sur la carte pour garder le souvenir de chaque dégustation."),
    ('notebook', "Vos carnets de dégustation", "Retrouvez ce que vous avez bu, vos notes et vos photos."),
    ('achievements', "Les trophées", "Débloquez des récompenses au fil de vos découvertes."),
)


def site_url(route, *args):
    """Adresse absolue d'une page : toujours PUBLIC_BASE_URL, jamais l'en-tête Host de la requête."""
    return f'{settings.PUBLIC_BASE_URL}{reverse(route, args=args)}'


def highlights():
    return [{'url': site_url(route), 'title': title, 'text': text} for route, title, text in HIGHLIGHTS]


def assetlinks():
    """Contenu de /.well-known/assetlinks.json ; vide tant qu'aucune empreinte n'est configurée."""
    if not settings.ANDROID_CERT_FINGERPRINTS:
        return []
    return [{
        'relation': ['delegate_permission/common.handle_all_urls'],
        'target': {
            'namespace': 'android_app',
            'package_name': settings.ANDROID_PACKAGE_NAME,
            'sha256_cert_fingerprints': settings.ANDROID_CERT_FINGERPRINTS,
        },
    }]
