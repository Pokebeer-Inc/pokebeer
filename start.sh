#!/bin/bash

echo "Waiting for postgres..."
while ! nc -z $DB_HOST $DB_PORT; do
    sleep 0.1
done
echo "PostgreSQL started"


# Appliquer les migrations
echo "Applying migrations..."
python manage.py migrate --noinput

# Collecter les fichiers statiques (CSS/JS)
echo "Collecting static files..."
python manage.py tailwind install
python manage.py tailwind build
python manage.py collectstatic --noinput

# Lancer le serveur
# Sur HF, on utilise le port 7860. En local, on peut surcharger.
echo "Starting server..."
python manage.py runserver 0.0.0.0:7860