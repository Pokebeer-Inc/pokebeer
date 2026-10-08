"""Analyse d'une étiquette de bière : consigne envoyée à l'IA et validation stricte de sa réponse.

La réponse de l'IA est une donnée non fiable : elle remplit des champs de formulaire. Elle est donc réduite aux cinq champs connus par
beer_fields.clean (texte court sans balise, degré 0-100, amertume 0-500), et ignorée si aucune bière n'est identifiée.
"""
import json
import re

from . import beer_fields

PROMPT = """
Tu es un expert zythologue de la bière.
1. Regarde l'image : une étiquette, une bouteille, une canette ou un sous-bock de bière est-il clairement visible, avec un nom lisible ?
   Sinon (mur, table, visage, texte sans rapport, image floue), réponds found = false.
2. Si oui, identifie la bière. Si des informations (brasserie, style, degré d'alcool, IBU) ne sont pas visibles, UTILISE TES CONNAISSANCES
   INTERNES d'expert pour les déduire et les compléter à partir du nom trouvé.
3. Ne renvoie AUCUN autre texte que le JSON strict.

Les clés doivent être exactement :
- "found" : true si une bière est identifiée, false sinon (les autres clés valent alors null).
- "name" : Le nom de la bière.
- "brewery" : Le nom de la brasserie (déduis-le si non écrit).
- "style" : Le style de bière (ex: IPA, Stout, Triple...).
- "degree" : Le degré d'alcool en format numérique (ex: 5.5).
- "bitterness" : L'amertume IBU en nombre entier (déduis-le si possible, sinon null).
"""

_FENCE = re.compile(r'```(?:json)?', re.IGNORECASE)


def parse(raw):
    """Étiquette identifiée sous forme de dict {name, brewery, style, degree, bitterness}, ou None si aucune bière n'est reconnue.

    Lève ValueError si la réponse n'est pas du JSON : c'est une panne de l'IA, pas une étiquette illisible.
    """
    data = json.loads(_FENCE.sub('', raw or '').strip())
    if not isinstance(data, dict):
        raise ValueError("Réponse de l'IA inattendue")
    label = beer_fields.clean(data)
    if data.get('found') is not True or not label['name']:
        return None
    return label
