FROM python:3.12-slim

# Installation des outils système + Node.js + npm
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    netcat-traditional \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Création de l'utilisateur non-root (Requis par HF)
RUN useradd -m -u 1000 user

WORKDIR /app

# Installation des dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copie du code et changement de propriétaire
COPY --chown=user . .

# Droits d'exécution pour le script de démarrage
RUN chmod +x start.sh

# Passage en utilisateur non-root
USER user

# Port Hugging Face par défaut
EXPOSE 7860

# Commande de lancement
CMD ["./start.sh"]