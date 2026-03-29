import os
from openai import OpenAI
from .models import Beer

# Configuration du client Hugging Face (Gratuit)
HF_TOKEN_READ = os.getenv("HF_TOKEN_READ")
# Utilisation de Mistral 7B, excellent en français et très rapide sur l'API gratuite
MODEL_ID = "moonshotai/Kimi-K2-Instruct-0905"

if HF_TOKEN_READ:
    client = OpenAI(
        base_url="https://router.huggingface.co/v1",
        api_key=HF_TOKEN_READ
    )
else:
    client = None

def _format_beers_context():
    """
    Formatage ultra-condensé pour économiser les tokens.
    On limite aux 40 bières pour ne pas exploser la limite gratuite de l'API.
    """
    # Sélectionne 40 bières aléatoires (ou tu peux trier par '-degree' etc.)
    beers = Beer.objects.select_related('brewery_id').order_by('?')[:40]
    
    if not beers:
        return None
        
    context_list = []
    for b in beers:
        # Format dense pour l'IA
        style = b.style if b.style else "Style inconnu"
        line = f"- {b.name} ({b.brewery_id.name}): {style}, {b.degree}%, {b.bitterness} IBU. Profil: {b.description}"
        context_list.append(line)
        
    return "\n".join(context_list)

def ask_sommelier(user_message):
    if not client:
        return "Le service de sommelier est inactif (Token Hugging Face manquant)."

    beers_context = _format_beers_context() or "Aucune bière en stock actuellement."

    messages = [
        {
            "role": "system",
            "content": f"""Tu es Gaétan, un sommelier bière sympathique et expert.
Ton stock est LIMITÉ à cette liste :
{beers_context}

RÈGLES STRICTES :
1. Tu ne recommandes QUE des bières de la liste ci-dessus.
2. Ne propose JAMAIS une bière inventée ou hors de cette liste.
3. Si la demande du client ne correspond à rien, excuse-toi et propose l'alternative la plus proche dans la liste.
4. Fais des réponses courtes, chaleureuses et en français."""
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
            max_tokens=300, # Réponses courtes et concises
            temperature=0.6,
            stream=False
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Erreur IA : {str(e)}")
        return f"Désolé, j'ai eu un coup de chaud en cave. Pouvez-vous répéter ? {str(e)}"