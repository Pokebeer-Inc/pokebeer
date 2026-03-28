import os
from openai import OpenAI
from .models import Beer

# Configuration du client (chargée une seule fois au démarrage)
HF_TOKEN = os.getenv("HF_TOKEN_READ")
MODEL_ID = "moonshotai/Kimi-K2-Instruct-0905"

if HF_TOKEN:
    client = OpenAI(
        base_url="https://router.huggingface.co/v1",
        api_key=HF_TOKEN
    )
else:
    client = None

def _format_beers_context():
    """
    Fonction privée pour formater le stock de bières en texte.
    Utilisée uniquement par le sommelier.
    """
    # Optimisation SQL : on charge les brasseries en même temps
    beers = Beer.objects.select_related('brewery_id').all()
    
    if not beers:
        return None
        
    context_list = []
    for b in beers:
        # Adaptation au nom de ton champ ForeignKey 'brewery_id'
        brasserie = b.brewery_id 
        line = (
            f"- {b.name} (Brasserie {brasserie.name} à {brasserie.city}) | "
            f"Alcool: {b.degree}% | "
            f"Amertume: {b.bitterness} | "
            f"Description: {b.description}"
        )
        context_list.append(line)
        
    return "\n".join(context_list)

def ask_sommelier(user_message):
    """
    Service principal : Interroge l'IA avec le contexte du stock.
    Retourne la réponse textuelle ou lève une exception.
    """
    if not client:
        return "Le service de sommelier n'est pas configuré (Token manquant)."

    beers_context = _format_beers_context() or "Aucune bière en stock actuellement."

    messages = [
        {
            "role": "system",
            "content": f"""Tu es Gaétan, un sommelier bière expert.
            Ton stock est STRICTEMENT LIMITÉ à cette liste :
            {beers_context}
            
            Consignes :
            - Ne recommande QUE des bières de cette liste.
            - Si on te demande une bière hors liste, dis poliment qu'elle n'est pas en stock.
            - Sois concis et chaleureux.
            - Réponds en français."""
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
            max_tokens=500,
            temperature=0.7,
            stream=False
        )
        return response.choices[0].message.content
    except Exception as e:
        # On log l'erreur pour le développeur, mais on ne casse pas l'app
        print(f"❌ Erreur Service Sommelier : {str(e)}")
        return "Désolé, j'ai un petit trou de mémoire. Revenez plus tard !"