import hmac
import hashlib
from django.conf import settings

def get_secure_channel_name(user_id):
    """Génère un nom de canal WebSocket impossible à deviner sans la SECRET_KEY."""
    key = settings.SECRET_KEY.encode('utf-8')
    msg = str(user_id).encode('utf-8')
    # On génère un hash sécurisé et on garde les 16 premiers caractères
    secure_hash = hmac.new(key, msg, hashlib.sha256).hexdigest()[:16]
    return f"room_{user_id}_{secure_hash}"