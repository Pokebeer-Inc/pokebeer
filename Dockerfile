# Image de l'application, en deux étapes :
#   runtime : ce qu'il faut pour servir le site (gunicorn), rien d'autre ;
#   dev     : ajoute Node.js (build de Tailwind) et les outils de test, pour `docker compose`.
# La production tourne sur Vercel (api/index.py) ; cette image sert au développement et à un hébergement classique.

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Utilisateur sans privilèges (-m : avec son dossier personnel)
ARG UID=1000
ARG GID=1000
RUN groupadd --gid ${GID} appuser \
    && useradd --uid ${UID} --gid ${GID} --create-home appuser

WORKDIR /app

# Dépendances avant le code : cette couche n'est reconstruite que si requirements.txt change
# (psycopg2-binary et les autres roues n'exigent ni compilateur ni libpq-dev)
COPY requirements.txt /app/
RUN pip install -r requirements.txt

COPY --chown=appuser:appuser . /app
USER appuser
EXPOSE 8000
CMD ["gunicorn", "pokebeer.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "-"]


FROM runtime AS dev

USER root
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*
COPY requirements-dev.txt /app/
RUN pip install -r requirements-dev.txt
USER appuser
