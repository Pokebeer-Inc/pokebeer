"""
Sélection de la base de données selon l'environnement.

- DEBUG=False : base de production (DATABASE_URL, ou variables DB_*).
- DEBUG=True  : base de développement (DEV_DATABASE_URL), obligatoire.

En DEBUG, le démarrage échoue si DEV_DATABASE_URL est absente ou désigne la
même base que la production : un poste de dev ne peut jamais écrire en prod.
"""
import os

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

PROD_URL_ENV = "DATABASE_URL"
DEV_URL_ENV = "DEV_DATABASE_URL"

_CONNECTION_OPTIONS = {"conn_max_age": 600, "conn_health_checks": True}
# Le pooler Supabase partage l'hôte entre projets : l'utilisateur fait partie de l'identité.
_IDENTITY_KEYS = ("HOST", "PORT", "NAME", "USER")
_DEFAULT_PORT = "5432"


def _identity(config):
    values = {key: str(config.get(key) or "").lower() for key in _IDENTITY_KEYS}
    values["PORT"] = values["PORT"] or _DEFAULT_PORT
    return tuple(values[key] for key in _IDENTITY_KEYS)


def is_same_database(config_a, config_b):
    return _identity(config_a) == _identity(config_b)


def prod_database_config(env=os.environ):
    url = env.get(PROD_URL_ENV)
    if url:
        return dj_database_url.parse(url, **_CONNECTION_OPTIONS)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env.get("DB_NAME"),
        "USER": env.get("DB_USER"),
        "PASSWORD": env.get("DB_PASSWORD"),
        "HOST": env.get("DB_HOST"),
        "PORT": env.get("DB_PORT"),
    }


def ensure_not_production(config, env=os.environ):
    if is_same_database(config, prod_database_config(env)):
        raise ImproperlyConfigured(
            f"{DEV_URL_ENV} désigne la base de production : opération refusée."
        )


def dev_database_config(env=os.environ):
    url = env.get(DEV_URL_ENV)
    if not url:
        raise ImproperlyConfigured(
            f"DEBUG=True exige {DEV_URL_ENV} (base de développement). "
            "Lancez `docker compose up -d db` et renseignez-la dans .env."
        )
    config = dj_database_url.parse(url, **_CONNECTION_OPTIONS)
    ensure_not_production(config, env)
    return config


def get_databases(debug, env=os.environ):
    config = dev_database_config(env) if debug else prod_database_config(env)
    return {"default": config}


def assert_dev_database(debug, config, env=os.environ):
    """Garde-fou pour les opérations destructrices (seed, reset)."""
    if not debug:
        raise ImproperlyConfigured("Opération réservée au mode DEBUG (base de développement).")
    ensure_not_production(config, env)
