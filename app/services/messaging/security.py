import hashlib
import hmac

from django.conf import settings


def get_secure_channel_name(user):
    """Nom du canal temps réel privé d'un membre, impossible à deviner sans la SECRET_KEY.

    128 bits, et lié au mot de passe du membre : le nom change dès que le mot de passe change (modification ou réinitialisation), ce qui
    coupe l'écoute de quiconque aurait obtenu l'ancien nom. Il ne contient pas l'identifiant et ne révèle rien sur le compte.
    """
    key = settings.SECRET_KEY.encode('utf-8')
    msg = f"{user.pk}:{user.password}".encode('utf-8')
    return f"room_{hmac.new(key, msg, hashlib.sha256).hexdigest()[:32]}"
