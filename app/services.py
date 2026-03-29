import os
import requests
from huggingface_hub import InferenceClient
from openai import OpenAI
from pgvector.django import CosineDistance
from .models import Beer

# Configuration du client Hugging Face (Gratuit)
HF_TOKEN_READ = os.getenv("HF_TOKEN_READ")
# Utilisation de Mistral 7B, excellent en français et très rapide sur l'API gratuite
MODEL_ID = "moonshotai/Kimi-K2-Instruct-0905"

if HF_TOKEN_READ:
    # Client pour discuter avec Gaétan
    client = OpenAI(base_url="https://router.huggingface.co/v1", api_key=HF_TOKEN_READ)
    # NOUVEAU : Client officiel HF pour créer les vecteurs mathématiques
    hf_client = InferenceClient(token=HF_TOKEN_READ)
else:
    client = None
    hf_client = None
    
def get_embedding(text):
    """Transforme un texte en vecteur mathématique avec le client officiel Hugging Face."""
    if not hf_client:
        print("ERREUR : Le Token HF_TOKEN_READ est introuvable.")
        return None
        
    try:
        # On utilise feature_extraction pour obtenir le vecteur (l'embedding)
        embedding = hf_client.feature_extraction(
            text,
            model="sentence-transformers/all-MiniLM-L6-v2"
        )
        
        # La librairie renvoie un objet numpy, on le convertit en liste Python classique pour Neon
        return embedding.tolist() if hasattr(embedding, 'tolist') else list(embedding)
        
    except Exception as e:
        print(f"ERREUR Embedding HF : {e}")
        return None

def _format_beers_context(user_message):
    """Recherche Vectorielle (Sémantique) avec pgvector."""
    user_vector = get_embedding(user_message)
    
    if user_vector:
        beers = Beer.objects.exclude(embedding__isnull=True).select_related('brewery_id').order_by(CosineDistance('embedding', user_vector))[:10]
    else:
        beers = Beer.objects.select_related('brewery_id').order_by('?')[:10]
    
    if not beers:
        return None
        
    context_list = []
    for b in beers:
        style = b.style if b.style else "Style inconnu"
        line = f"- {b.name} ({b.brewery_id.name}): {style}, {b.degree}%, {b.bitterness} IBU. Profil: {b.description}"
        context_list.append(line)
        
    return "\n".join(context_list)

def ask_sommelier(user_message):
    if not client:
        return "Le service de sommelier est inactif (Token Hugging Face manquant)."

    # On passe le message pour la recherche vectorielle
    beers_context = _format_beers_context(user_message) or "Aucune bière en stock actuellement."

    messages = [
        {
            "role": "system",
            "content": f"""Tu es Gaétan, un sommelier bière sympathique et expert.
J'ai pré-sélectionné pour toi les bières les plus pertinentes selon la demande du client :
{beers_context}

RÈGLES STRICTES :
1. Tu ne recommandes QUE des bières de la liste ci-dessus.
2. Si la demande du client ne correspond pas du tout au stock, propose l'alternative la plus proche dans la liste.
3. Fais des réponses courtes, chaleureuses et en français."""
        },
        {
            "role": "user", 
            "content": user_message
        }
    ]

    try:
        response = client.chat.completions.create(
            model=MODEL_ID,
            messages=messages,
            max_tokens=300,
            temperature=0.6,
            stream=False
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Erreur IA : {str(e)}")
        return f"Désolé, j'ai eu un coup de chaud en cave. Pouvez-vous répéter ? {str(e)}"