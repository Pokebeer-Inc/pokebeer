import json
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from ..models import Beer, Brewery
from ..services import ask_sommelier

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

    # Appel au service métier (Business Logic)
    response_text = ask_sommelier(user_message)
    
    return JsonResponse({"response": response_text})

def search_brewery(request):
    """API pour l'autocomplétion des brasseries"""
    query = request.GET.get('term', '')
    if len(query) < 2:
        return JsonResponse([], safe=False)
    
    breweries = Brewery.objects.filter(name__icontains=query)[:10]
    results = [b.name for b in breweries]
    return JsonResponse(results, safe=False)

def search_beer(request):
    """API pour vérifier si une bière existe déjà"""
    query = request.GET.get('term', '')
    if len(query) < 2:
        return JsonResponse([], safe=False)
        
    beers = Beer.objects.filter(name__icontains=query)[:10]
    results = [b.name for b in beers]
    return JsonResponse(results, safe=False)