# Pokebeer

Explorez, dégustez et notez des bières ! Soyez conseillé par Gaétan, notre zythologue IA

Télécharger l'application ici : [Google Play](https://play.google.com/store/apps/details?id=com.scarone.pokebeer)


## Développement

```bash
cp .env.example .env            # puis renseigner SECRET_KEY, DEV_DB_PASSWORD…
docker compose up -d db web     # site sur http://localhost:8000 (image « dev » : Node + outils de test)
docker compose exec web python -m pytest
```

### Dépendances

- `requirements.in` : les dépendances **directes** du site (versions fixées). C'est le seul fichier à éditer.
- `requirements.txt` : sa version figée avec toutes les dépendances indirectes (installée par Vercel, la CI et l'image Docker).
  Pour la régénérer : `python -m venv /tmp/v && /tmp/v/bin/pip install -r requirements.in && /tmp/v/bin/pip freeze > requirements.txt`,
  puis remettre l'en-tête de commentaire.
- `requirements-dev.txt` : tests, `ruff`, `pip-audit`, rechargement automatique (jamais installé en production).

La CI lance `ruff`, `pip-audit`, `manage.py check --deploy` et la suite de tests (couverture minimale 90 %).

### Organisation du code

- `app/models/` : un module par domaine ; les modèles ne contiennent ni appel réseau ni règle d'envoi (voir `app/apps.py` pour les branchements).
- `app/services/` : la logique métier, rangée par domaine (`members`, `catalog`, `establishments`, `messaging`, `assistant`, `protection`, `common`, `support`, `analytics`, `moderation`) ; voir `app/services/README.md` pour le rôle de chaque module.
- `app/views/` : les vues, une par route de `app/urls.py`, importées explicitement dans `app/views/__init__.py`.
- `app/templates/partials/notifications/<type>.html` : le texte de chaque type de notification (voir `app/services/messaging/notification_types.py`).

### Mise en production

Un push sur `main` déclenche, dans l'ordre : la CI (`Django CI`), puis `Deploy production` qui applique les migrations à la base de production et
met seulement ensuite le code en ligne sur Vercel (le déploiement automatique de Vercel est coupé pour `main` dans `vercel.json`).
Secrets GitHub requis (environnement `production`) : `PRODUCTION_DATABASE_URL`, `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`.
Une migration doit rester compatible avec le code encore en ligne pendant la mise en ligne : ajouter d'abord, supprimer dans une version suivante.
