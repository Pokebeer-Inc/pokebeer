from google import genai
from django.conf import settings
from pgvector.django import CosineDistance
from .models import Beer

# Initialisation du client avec la clé définie dans settings.py
client = genai.Client(api_key=settings.GEMINI_API_KEY)

def get_embedding(text):
    """Transforme un texte en vecteur mathématique (768 dimensions) avec Gemini."""
    if not settings.GEMINI_API_KEY:
        print("ERREUR : La clé GEMINI_API_KEY est introuvable.")
        return None
        
    try:
        # text-embedding-004 est le modèle optimal pour les vecteurs
        response = client.models.embed_content(
            model='gemini-embedding-001',
            contents=text
        )
        return response.embeddings[0].values
        
    except Exception as e:
        print(f"ERREUR Embedding Gemini : {e}")
        return None

def _format_beers_context(user_message):
    """Recherche Vectorielle (Sémantique) avec pgvector."""
    user_vector = get_embedding(user_message)
    
    if user_vector:
        # Recherche les bières les plus proches sémantiquement
        beers = Beer.objects.filter(is_deleted=False).exclude(embedding__isnull=True).select_related('brewery_id').order_by(CosineDistance('embedding', user_vector))[:10]
    else:
        # Fallback si l'API échoue
        beers = Beer.objects.filter(is_deleted=False).select_related('brewery_id').order_by('?')[:10]
    
    if not beers:
        return None
        
    context_list = []
    for b in beers:
        style = b.style if b.style else "Style inconnu"
        ibu_text = f"{b.bitterness} IBU" if b.bitterness is not None else "IBU inconnu"
        line = f"- {b.name} ({b.brewery_id.name}): {style}, {b.degree}%, {ibu_text}. Profil: {b.description}"
        context_list.append(line)
        
    return "\n".join(context_list)

def ask_sommelier(user_message):
    if not settings.GEMINI_API_KEY:
        return "Le service de sommelier est inactif (Clé Gemini manquante)."

    # On récupère le contexte vectoriel
    beers_context = _format_beers_context(user_message) or "Aucune bière en stock actuellement."

    prompt = f"""Tu es Gaétan, un sommelier bière sympathique et expert.
J'ai pré-sélectionné pour toi les bières les plus pertinentes selon la demande du client :
{beers_context}

RÈGLES STRICTES :
1. Tu ne recommandes QUE des bières de la liste ci-dessus.
2. Si la demande du client ne correspond pas du tout au stock, propose l'alternative la plus proche dans la liste.
3. Fais des réponses courtes, chaleureuses et en français.

Message du client : "{user_message}"
"""

    try:
        # gemini-2.5-flash est parfait pour des réponses rapides et précises
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        return response.text
    except Exception as e:
        print(f"Erreur IA : {str(e)}")
        return "Désolé, j'ai eu un coup de chaud en cave. Pouvez-vous répéter ?"