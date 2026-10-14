import logging
import time
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import ValidationError

from ..models import Beer, Brewery
from ..domain.match_keys import MAX_NAME_LENGTH
from ..services.members.visibility import exclude_blocked
from django.template.loader import render_to_string

from ..services.catalog import catalog_matching, ean, label_scan, product_lookup, search
from ..services.establishments import postal_codes
from ..services.common import upstream
from ..services.protection.throttle import (
    AUTOCOMPLETE_BY_USER,
    CATALOG_CHECK_BY_USER,
    CHAT_BURST_BY_USER,
    CHAT_GLOBAL,
    CHAT_GLOBAL_KEY,
    POSTAL_LOOKUP_BY_IP,
)
from ..services.assistant.ai import analyze_label, ask_zythologue
from ..services.assistant.chat import ChatBusy, ChatUnavailable, payload as chat_payload
from ..services.protection.quota import CHAT, EAN_LOOKUP, LABEL_SCAN, consume_quota, refund_quota
from .utils import TOO_MANY_SEARCHES, by_user, throttle

logger = logging.getLogger(__name__)

CHAT_BUSY = "Gaétan a beaucoup de monde au comptoir : réessayez dans une minute."
CHAT_PENDING_KEY = 'chat_pending_location'
CHAT_PENDING_SECONDS = 600  # délai laissé au membre pour activer sa position
CHAT_UNAVAILABLE = "Désolé, j'ai eu un coup de chaud en cave. Pouvez-vous revenir plus tard s'il vous plaît ?"


def _chat_error(message, status):
    return JsonResponse({"response": message}, status=status)


def _take_pending_location(request, message):
    """Vrai si ce message est la reprise, avec position, d'une demande qui en manquait (déjà comptée dans le quota du membre).

    Le serveur est seul à savoir qu'une demande attend : le navigateur ne peut pas se déclarer « reprise » pour échapper au quota."""
    pending = request.session.pop(CHAT_PENDING_KEY, None)
    return bool(pending) and pending.get('message') == message and time.time() - pending.get('at', 0) < CHAT_PENDING_SECONDS and pending


def _post_chat_message(request):
    """Nouveau message : validation, limites (rafale, budget global, quota du membre), réponse, historique."""
    try:
        chat_request = chat_payload.parse(request.body)
    except chat_payload.InvalidChatRequest as error:
        return _chat_error(str(error), 400)

    # Budget global réservé d'abord (atomique), puis rendu si la demande est finalement refusée
    if not CHAT_GLOBAL.hit(CHAT_GLOBAL_KEY):
        return _chat_error("Gaétan est très sollicité aujourd'hui, revenez demain !", 503)
    if not CHAT_BURST_BY_USER.hit(request.user.pk):
        CHAT_GLOBAL.release(CHAT_GLOBAL_KEY)
        return _chat_error("Doucement, Gaétan reprend son souffle : réessayez dans une minute.", 429)
    pending = chat_request.location and _take_pending_location(request, chat_request.message)
    if not pending and not consume_quota(request.user, settings.CHAT_DAILY_LIMIT, CHAT, settings.CHAT_WEEKLY_LIMIT):
        CHAT_GLOBAL.release(CHAT_GLOBAL_KEY)
        return _chat_error("Gaétan a assez parlé pour le moment, revenez demain !", 429)

    history = request.session.get('chat_history', [])
    try:
        reply = ask_zythologue(chat_request.message, history, chat_request.location, user=request.user)
    except ChatUnavailable as error:
        # Rien n'est enregistré et le membre récupère sa question (une reprise reste possible)
        if pending:
            request.session[CHAT_PENDING_KEY] = pending
        else:
            refund_quota(request.user, CHAT)
        return _chat_error(CHAT_BUSY if isinstance(error, ChatBusy) else CHAT_UNAVAILABLE, 503)

    if reply.needs_location:
        # La demande n'est pas conservée dans l'historique : le navigateur la renverra telle quelle avec la position, sans second quota
        request.session[CHAT_PENDING_KEY] = {'message': chat_request.message, 'at': time.time()}
        return JsonResponse({"response": reply.text, "needs_location": True})

    history = [*history, {'role': 'user', 'text': chat_request.message}, {'role': 'model', 'text': reply.text}]
    # Seuls les derniers messages sont gardés : la session reste légère et la conversation courte
    request.session['chat_history'] = history[-settings.CHAT_HISTORY_LIMIT:]
    return JsonResponse({"response": reply.text, "needs_location": False})


@require_http_methods(["GET", "POST", "DELETE"])
def chat_api(request):
    """Endpoint API : historique de la discussion avec Gaétan (GET), nouveau message (POST), nouvelle conversation (DELETE)."""
    if request.method == 'GET':
        return JsonResponse({"history": request.session.get('chat_history', [])})
    if request.method == 'DELETE':
        # Repart de zéro : ni historique, ni demande en attente de position (le quota déjà utilisé n'est pas rendu)
        request.session.pop('chat_history', None)
        request.session.pop(CHAT_PENDING_KEY, None)
        return JsonResponse({"history": []})
    return _post_chat_message(request)

@require_POST
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
        reading = analyze_label(image_bytes)
        if reading is None:
            # Image sans bière identifiable : réponse normale (le scanner continue de chercher), pas une erreur
            return JsonResponse({"success": False, "not_found": True, "error": "Aucune étiquette de bière reconnue."})
        # Origine de ce qui n'était pas imprimé sur l'étiquette (catalogue, web) et de ce que le web a corrigé : à faire vérifier par le membre
        return JsonResponse({
            "success": True, "data": reading.label, "from_catalogue": reading.from_catalogue,
            "from_web": reading.from_web, "corrected_by_web": reading.corrected_by_web,
        })

    except Exception:
        # Le détail (réponse de l'IA, message du SDK) reste dans les journaux : il ne doit jamais atteindre le client
        logger.exception("Analyse d'étiquette impossible")
        refund_quota(request.user, LABEL_SCAN)  # une panne de l'IA ne coûte pas son essai au membre
        return JsonResponse({"error": "L'analyse de l'étiquette a échoué. Réessayez plus tard."}, status=500)

@require_POST
def lookup_ean(request):
    """Bière correspondant à un code-barres : d'abord le catalogue (sans service extérieur ni quota), puis Open Food Facts."""
    code = ean.normalize(request.POST.get('ean'))
    if code is None:
        return JsonResponse({"error": "Code-barres invalide."}, status=400)

    known = exclude_blocked(Beer.objects.filter(ean=code, is_deleted=False), request.user, 'added_by').select_related('brewery').first()
    if known:
        return JsonResponse({"success": True, "source": "catalog", "existing": {"name": known.name, "brewery": known.brewery.name, "slug": known.slug}})

    if not consume_quota(request.user, settings.EAN_DAILY_LIMIT, EAN_LOOKUP):
        return JsonResponse({"error": "Limite quotidienne de recherches par code-barres atteinte, revenez demain !"}, status=429)
    try:
        beer = product_lookup.fetch(code)
    except product_lookup.LookupUnavailable:
        return JsonResponse({"error": "La base de produits ne répond pas. Réessayez plus tard."}, status=503)
    if beer is None:
        return JsonResponse({"success": False, "not_found": True, "error": "Code-barres inconnu."})
    return JsonResponse({"success": True, "source": "openfoodfacts", "ean": code, "data": beer})

@require_GET
@throttle(CATALOG_CHECK_BY_USER, key=by_user, json=True, message="Trop de vérifications, réessayez dans un moment.")
def check_catalog(request):
    """Doublons possibles pendant la saisie : le panneau HTML (même gabarit que le formulaire) et la brasserie à utiliser telle quelle."""
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

@login_not_required  # l'inscription d'un gérant en a besoin
@require_GET
@throttle(POSTAL_LOOKUP_BY_IP, json=True, message=TOO_MANY_SEARCHES)
def postal_code_lookup(request):
    """Communes d'un code postal (données publiques), pour remplir la ville d'un formulaire d'établissement. Ouvert sans connexion : l'inscription
    d'un gérant en a besoin ; limité par adresse IP."""
    code = request.GET.get('code', '').strip()
    if not postal_codes.is_valid_format(code):
        return JsonResponse({"cities": [], "known": False, "available": True})
    try:
        cities = postal_codes.communes(code)
    except upstream.UpstreamUnavailable:
        return JsonResponse({"cities": [], "known": False, "available": False})  # l'annuaire ne répond pas : la saisie n'est pas bloquée
    return JsonResponse({"cities": cities, "known": bool(cities), "available": True})

@require_GET
@throttle(AUTOCOMPLETE_BY_USER, key=by_user, json=True, message=TOO_MANY_SEARCHES)
def search_brewery(request):
    """Autocomplétion des brasseries (recherche indexée : sans casse ni accents, tolérante aux fautes)."""
    query = request.GET.get('term', '')
    if len(query) < 2:
        return JsonResponse([], safe=False)
    breweries = search.breweries(Brewery.objects.only('name'), query).order_by(search.RANK_FIELD, 'name')[:10]
    return JsonResponse([brewery.name for brewery in breweries], safe=False)


@require_GET
@throttle(AUTOCOMPLETE_BY_USER, key=by_user, json=True, message=TOO_MANY_SEARCHES)
def search_beer(request):
    """Bières du catalogue au nom proche de la saisie, pour signaler un doublon possible (recherche indexée, sans accents)."""
    query = request.GET.get('term', '')
    if len(query) < 2:
        return JsonResponse([], safe=False)
    beers = exclude_blocked(Beer.objects.filter(is_deleted=False), request.user, 'added_by').select_related('brewery')
    beers = search.search(beers, query, 'name').order_by(search.RANK_FIELD, 'name')[:5]
    return JsonResponse([{'name': b.name, 'slug': b.slug, 'brewery': b.brewery.name} for b in beers], safe=False)
