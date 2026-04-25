import json
import urllib.parse
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from ..models import Beer, Brewery, BeerUser
from ..services import ask_sommelier
from django.db.models import Q
from django.utils.text import slugify
from google import genai
from google.genai import types
from django.conf import settings
from django.contrib.auth.decorators import login_required

client = genai.Client(api_key=settings.GEMINI_API_KEY)

@require_POST
def chat_api(request):
    """
    Endpoint API : Reçoit du JSON, appelle le service, renvoie du JSON.
    Aucune logique métier ici.
    """
    try:
        data = json.loads(request.body)
        user_message = data.get('message', '')
    except json.JSONDecodeError:
        return JsonResponse({"response": "Format JSON invalide."}, status=400)

    if not user_message.strip():
        return JsonResponse({"response": "Message vide."}, status=400)

    response_text = ask_sommelier(user_message)
    
    return JsonResponse({"response": response_text})

@require_POST
@login_required
def analyze_beer_label(request):
    if 'image' not in request.FILES:
        return JsonResponse({"error": "Aucune image reçue."}, status=400)

    image_file = request.FILES['image']
    image_bytes = image_file.read()

    try:
        prompt = """
            Tu es un expert sommelier de la bière. 
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
                    mime_type=image_file.content_type,
                )
            ],
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            )
        )
        
        raw_json = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(raw_json)

        return JsonResponse({"success": True, "data": data})

    except Exception as e:
        return JsonResponse({"error": f"Erreur lors de l'analyse : {str(e)}"}, status=500)

def search_brewery(request):
    """API pour l'autocomplétion des brasseries"""
    query = request.GET.get('term', '')
    if len(query) < 2:
        return JsonResponse([], safe=False)
    
    breweries = Brewery.objects.filter(name__icontains=query)[:10]
    results = [b.name for b in breweries]
    return JsonResponse(results, safe=False)

def search_beer(request):
    """API pour vérifier si une bière existe déjà (Recherche optimisée)"""
    query = request.GET.get('term', '')
    if len(query) < 2:
        return JsonResponse([], safe=False)
        
    query_slug = slugify(query) # Permet de matcher même si l'utilisateur oublie un accent
        
    beers = Beer.objects.filter(
        Q(name__icontains=query) | Q(slug__icontains=query_slug)
    ).select_related('brewery_id')[:5]
    
    results = [
        {
            'name': b.name, 
            'slug': b.slug, 
            'brewery': b.brewery_id.name
        } for b in beers
    ]
    return JsonResponse(results, safe=False)

def search_user(request):
    """API pour l'autocomplétion des membres"""
    query = request.GET.get('term', '')
    if len(query) < 2:
        return JsonResponse([], safe=False)

    # L'ajout de prefetch_related('socialaccount_set') est très important ici 
    # pour optimiser la base de données et ne pas faire une requête par utilisateur trouvé.
    users = BeerUser.objects.filter(
        username__icontains=query,
        is_staff=False,
        is_superuser=False
    ).prefetch_related('socialaccount_set')[:10]
    
    results = []
    for u in users:
        # Vérifier si l'utilisateur s'est connecté via Google et a une photo
        social_account = u.socialaccount_set.first()
        if social_account and social_account.extra_data.get('picture'):
            avatar_url = social_account.extra_data.get('picture')
        else:
            # Sinon, on génère l'avatar avec les initiales
            safe_name = urllib.parse.quote(u.username)
            avatar_url = f"https://ui-avatars.com/api/?name={safe_name}&background=E5A022&color=fff&bold=true"

        # On renvoie un dictionnaire au lieu d'une simple chaîne de caractères
        results.append({
            'username': u.username,
            'avatar_url': avatar_url
        })
        
    return JsonResponse(results, safe=False)