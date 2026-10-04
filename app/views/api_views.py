import json
import logging
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_http_methods
from django.db.models import Q
from django.db.models.functions import Greatest, Left, Length
from django.utils.text import slugify
from google import genai
from google.genai import types
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError

from ..models import Beer, Brewery
from ..services.ai import ask_zythologue, config_client
from ..services.images import MIME_TYPES, open_image
from ..services.quota import CHAT, LABEL_SCAN, consume_quota
from ..services.slugs import SUFFIX_LENGTH

logger = logging.getLogger(__name__)

@require_http_methods(["GET", "POST"])
@login_required(login_url='login')
def chat_api(request):
    """Endpoint API : Gère l'historique et la discussion avec l'IA."""
    
    # 1. Requête GET : Le frontend demande l'historique au chargement de la page
    if request.method == 'GET':
        history = request.session.get('chat_history', [])
        return JsonResponse({"history": history})

    # 2. Requête POST : Nouveau message de l'utilisateur
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            user_message = data.get('message', '')
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({"response": "Format JSON invalide."}, status=400)

        if not isinstance(user_message, str) or not user_message.strip():
            return JsonResponse({"response": "Message vide."}, status=400)

        if len(user_message) > settings.CHAT_MESSAGE_MAX_LENGTH:
            return JsonResponse({"response": f"Message trop long ({settings.CHAT_MESSAGE_MAX_LENGTH} caractères maximum)."}, status=400)

        if not consume_quota(request.user, settings.CHAT_DAILY_LIMIT, CHAT):
            return JsonResponse({"response": "Gaétan a assez parlé pour aujourd'hui, revenez demain !"}, status=429)

        # On récupère l'historique existant
        history = request.session.get('chat_history', [])
        
        # On passe le message et l'historique au service IA
        response_text = ask_zythologue(user_message, history)
        
        # On sauvegarde le nouvel échange dans la session
        history.append({'role': 'user', 'text': user_message})
        history.append({'role': 'model', 'text': response_text})
        
        # On ne garde que les 10 derniers messages (5 échanges) pour ne pas surcharger la session
        request.session['chat_history'] = history[-10:]
        
        return JsonResponse({"response": response_text})

@require_POST
@login_required(login_url='login')
def analyze_beer_label(request):
    if 'image' not in request.FILES:
        return JsonResponse({"error": "Aucune image reçue."}, status=400)

    image_file = request.FILES['image']
    try:
        # Le format réel est lu dans le fichier : le type déclaré par le navigateur n'est jamais cru
        mime_type = MIME_TYPES[open_image(image_file, settings.LABEL_MAX_UPLOAD_BYTES).format]
    except ValidationError as error:
        return JsonResponse({"error": error.messages[0]}, status=400)

    if not consume_quota(request.user, settings.LABEL_DAILY_LIMIT, LABEL_SCAN):
        return JsonResponse({"error": "Limite quotidienne d'analyses atteinte, revenez demain !"}, status=429)

    image_file.seek(0)
    image_bytes = image_file.read()

    try:
        client = config_client()
        prompt = """
            Tu es un expert zythologue de la bière. 
            1. Analyse l'image de cette étiquette pour identifier la bière.
            2. Si des informations (comme la brasserie, le style, le degré d'alcool ou l'IBU) ne sont pas visibles ou lisibles sur l'image, UTILISE TES CONNAISSANCES INTERNES d'expert pour déduire et compléter ces champs manquants à partir du nom trouvé.
            3. Ne renvoie AUCUN autre texte que le JSON strict.

            Les clés doivent être exactement :
            - "name" : Le nom de la bière.
            - "brewery" : Le nom de la brasserie (déduis-le si non écrit).
            - "style" : Le style de bière (ex: IPA, Stout, Triple...).
            - "degree" : Le degré d'alcool en format numérique (ex: 5.5).
            - "bitterness" : L'amertume IBU en nombre entier (déduis-le si possible, sinon null).
            """

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                prompt,
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=mime_type,
                )
            ],
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            )
        )
        
        raw_json = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(raw_json)

        return JsonResponse({"success": True, "data": data})

    except Exception:
        # Le détail (réponse de l'IA, message du SDK) reste dans les journaux : il ne doit jamais atteindre le client
        logger.exception("Analyse d'étiquette impossible")
        return JsonResponse({"error": "L'analyse de l'étiquette a échoué. Réessayez plus tard."}, status=500)

@login_required(login_url='login')
def search_brewery(request):
    """API pour l'autocomplétion des brasseries"""
    query = request.GET.get('term', '')
    if len(query) < 2:
        return JsonResponse([], safe=False)
    
    breweries = Brewery.objects.filter(name__icontains=query)[:10]
    results = [b.name for b in breweries]
    return JsonResponse(results, safe=False)

@login_required(login_url='login')
def search_beer(request):
    """API pour vérifier si une bière existe déjà (Recherche optimisée)"""
    query = request.GET.get('term', '')
    if len(query) < 2:
        return JsonResponse([], safe=False)
        
    query_slug = slugify(query) # Permet de matcher même si l'utilisateur oublie un accent
        
    # Le slug se termine par un jeton aléatoire : on ne compare que sa partie lisible
    beers = Beer.objects.annotate(
        readable_slug=Left('slug', Greatest(Length('slug') - SUFFIX_LENGTH, 0))
    ).filter(
        (Q(name__icontains=query) | Q(readable_slug__icontains=query_slug)),
        is_deleted=False
    ).select_related('brewery_id')[:5]
    
    results = [
        {
            'name': b.name, 
            'slug': b.slug, 
            'brewery': b.brewery_id.name
        } for b in beers
    ]
    return JsonResponse(results, safe=False)
