"""Règles du domaine sans base de données, réseau ni service extérieur : utilisables par les modèles comme par les services.

Le sens des dépendances est toujours domain <- models <- services <- views : un module de ce paquet n'importe jamais `app.models`
ni `app.services`.
"""
