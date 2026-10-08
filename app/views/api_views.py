import json
import logging
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.db.models import Q
from django.db.models.functions import Greatest, Left, Length
from django.utils.text import slugify
from google import genai
from google.genai import types
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError

from ..models import Beer, Brewery
from ..services.match_keys import MAX_NAME_LENGTH
from .utils import get_blocked_users
from django.template.loader import render_to_string

from ..services import catalog_matching, ean, label_scan, postal_codes, product_lookup, upstream
from ..services.throttle import CATALOG_CHECK_BY_USER, CHAT_BURST_BY_USER, CHAT_GLOBAL, CHAT_GLOBAL_KEY, POSTAL_LOOKUP_BY_IP, client_ip
from ..services.ai import ask_zythologue, config_client
from ..services.chat import ChatBusy, ChatUnavailable, payload as chat_payload
from ..services.quota import CHAT, EAN_LOOKUP, LABEL_SCAN, consume_quota, refund_quota
from ..services.slugs import SUFFIX_LENGTH

logger = logging.getLogger(__name__)

CHAT_BUSY = "Gaétan a beaucoup de monde au comptoir : réessayez dans une minute."
CHAT_UNAVAILABLE = "Désolé, j'ai eu un coup de chaud en cave. Pouvez-vous revenir plus tard s'il vous plaît ?"


def _chat_error(message, status):
    return JsonResponse({"response": message}, status=status)


def _post_chat_message(request):
    """Nouveau message : validation, limites (rafale, budget global, quota du membre), réponse, historique."""
    try:
        chat_request = chat_payload.parse(request.body)
    except chat_payload.InvalidChatRequest as error:
        return _chat_error(str(error), 400)

    user_id = request.user.pk
    if CHAT_GLOBAL.exceeded(CHAT_GLOBAL_KEY):
        return _chat_error("Gaétan est très sollicité aujourd'hui, revenez demain !", 503)
    if CHAT_BURST_BY_USER.exceeded(user_id):
        return _chat_error("Doucement, Gaétan reprend son souffle : réessayez dans une minute.", 429)
    CHAT_BURST_BY_USER.record(user_id)
    if not consume_quota(request.user, settings.CHAT_DAILY_LIMIT, CHAT, settings.CHAT_WEEKLY_LIMIT):
        return _chat_error("Gaétan a assez parlé pour le moment, revenez demain !", 429)
    CHAT_GLOBAL.record(CHAT_GLOBAL_KEY)

    history = request.session.get('chat_history', [])
    try:
        reply = ask_zythologue(chat_request.message, history, chat_request.location)
    except ChatUnavailable as error:
        # Rien n'est enregistré et le membre récupère sa question
        refund_quota(request.user, CHAT)
        return _chat_error(CHAT_BUSY if isinstance(error, ChatBusy) else CHAT_UNAVAILABLE, 503)

    history = [*history, {'role': 'user', 'text': chat_request.message}, {'role': 'model', 'text': reply.text}]
    # Seuls les derniers messages sont gardés : la session reste légère et la conversation courte
    request.session['chat_history'] = history[-settings.CHAT_HISTORY_LIMIT:]
    return JsonResponse({"response": reply.text, "needs_location": reply.needs_location})


@require_http_methods(["GET", "POST"])
@login_required(login_url='login')
def chat_api(request):
    """Endpoint API : historique de la discussion avec Gaétan (GET) et nouveau message (POST)."""
    if request.method == 'GET':
        return JsonResponse({"history": request.session.get('chat_history', [])})
    return _post_chat_message(request)

@require_POST
@login_required(login_url='login')
def analyze_beer_label(request):
    if 'image' not in request.FILES:
        return JsonResponse({"error": "Aucune image reçue."}, status=400)

    try:
        # L'IA ne reçoit que l'image ré-encodée : le type déclaré par le navigateur n'est jamais cru, les métadonnées sont retirées
        image_bytes = label_scan.prepare_image(request.FILES['image'], settings.LABEL_MAX_UPLOAD_BYTES)
    except ValidationError as error:
        return JsonResponse({"error": error.messages[0]}, status=400)

    if not consume_quota(request.user, settings.LABEL_DAILY_LIMIT, LABEL_SCAN):
        return JsonResponse({"error": "Limite quotidienne d'analyses atteinte, revenez demain !"}, status=429)

    try:
        client = config_client()
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                label_scan.PROMPT,
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=label_scan.MIME_TYPE,
                )
            ],
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            )
        )
        
        label = label_scan.parse(response.text)
        if label is None:
            # Image sans bière identifiable : réponse normale (le scanner continue de chercher), pas une erreur
            return JsonResponse({"success": False, "not_found": True, "error": "Aucune étiquette de bière reconnue."})
        return JsonResponse({"success": True, "data": label})

    except Exception:
        # Le détail (réponse de l'IA, message du SDK) reste dans les journaux : il ne doit jamais atteindre le client
        logger.exception("Analyse d'étiquette impossible")
        refund_quota(request.user, LABEL_SCAN)  # une panne de l'IA ne coûte pas son essai au membre
        return JsonResponse({"error": "L'analyse de l'étiquette a échoué. Réessayez plus tard."}, status=500)

@login_required(login_url='login')
@require_POST
def lookup_ean(request):
    """Bière correspondant à un code-barres : d'abord le catalogue (sans service extérieur ni quota), puis Open Food Facts."""
    code = ean.normalize(request.POST.get('ean'))
    if code is None:
        return JsonResponse({"error": "Code-barres invalide."}, status=400)

    known = Beer.objects.filter(ean=code, is_deleted=False).exclude(added_by__in=get_blocked_users(request.user)).select_related('brewery_id').first()
    if known:
        return JsonResponse({"success": True, "source": "catalog", "existing": {"name": known.name, "brewery": known.brewery_id.name, "slug": known.slug}})

    if not consume_quota(request.user, settings.EAN_DAILY_LIMIT, EAN_LOOKUP):
        return JsonResponse({"error": "Limite quotidienne de recherches par code-barres atteinte, revenez demain !"}, status=429)
    try:
        beer = product_lookup.fetch(code)
    except product_lookup.LookupUnavailable:
        return JsonResponse({"error": "La base de produits ne répond pas. Réessayez plus tard."}, status=503)
    if beer is None:
        return JsonResponse({"success": False, "not_found": True, "error": "Code-barres inconnu."})
    return JsonResponse({"success": True, "source": "openfoodfacts", "ean": code, "data": beer})

@login_required(login_url='login')
@require_GET
def check_catalog(request):
    """Doublons possibles pendant la saisie : le panneau HTML (même gabarit que le formulaire) et la brasserie à utiliser telle quelle."""
    if CATALOG_CHECK_BY_USER.exceeded(request.user.pk):
        return JsonResponse({"error": "Trop de vérifications, réessayez dans un moment."}, status=429)
    CATALOG_CHECK_BY_USER.record(request.user.pk)
    name = request.GET.get('name', '').strip()[:MAX_NAME_LENGTH]
    brewery_name = request.GET.get('brewery', '').strip()[:MAX_NAME_LENGTH]
    postal_code = request.GET.get('postal', '').strip()
    postal_code = postal_code if postal_codes.is_valid_format(postal_code) else ''
    city = ' '.join(request.GET.get('city', '').split())[:100]
    if len(name) < 2 and len(brewery_name) < 2:
        return JsonResponse({"html": "", "apply_brewery": None})
    inspection = catalog_matching.inspect(name, brewery_name, postal_code=postal_code, city=city)
    same = inspection.reusable_brewery
    return JsonResponse({
        "html": render_to_string('partials/duplicate_panel.html', {
            'inspection': inspection, 'confirm_brewery_name': 'beer-confirm_brewery', 'confirm_beer_name': 'beer-confirm_beer', 'typed_postal_code': postal_code,
        }),
        # Nom exact de la brasserie déjà connue : le formulaire l'adopte, la saisie (ou l'IA) ne crée pas de variante
        "apply_brewery": same.name if same else None,
    })

@require_GET
def postal_code_lookup(request):
    """Communes d'un code postal (données publiques), pour remplir la ville d'un formulaire d'établissement. Ouvert sans connexion : l'inscription
    d'un gérant en a besoin ; limité par adresse IP."""
    ip = client_ip(request)
    if POSTAL_LOOKUP_BY_IP.exceeded(ip):
        return JsonResponse({"error": "Trop de recherches, réessayez dans un moment."}, status=429)
    POSTAL_LOOKUP_BY_IP.record(ip)
    code = request.GET.get('code', '').strip()
    if not postal_codes.is_valid_format(code):
        return JsonResponse({"cities": [], "known": False, "available": True})
    try:
        cities = postal_codes.communes(code)
    except upstream.UpstreamUnavailable:
        return JsonResponse({"cities": [], "known": False, "available": False})  # l'annuaire ne répond pas : la saisie n'est pas bloquée
    return JsonResponse({"cities": cities, "known": bool(cities), "available": True})

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
