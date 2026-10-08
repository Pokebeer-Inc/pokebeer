"""Contrôle d'un SIRET dans l'annuaire officiel des entreprises (recherche-entreprises.api.gouv.fr, sans clé).

Un SIRET qui n'existe pas ou dont l'établissement est fermé est refusé tout de suite. Le reste (activité qui ne ressemble pas à une
brasserie ou à un bar, commune différente, nom éloigné) n'est pas bloquant : c'est consigné pour que l'équipe décide en connaissance de cause.
Rien n'est transmis sur le membre : seul le numéro de SIRET part, depuis notre serveur (voir services/upstream.py).
"""
from dataclasses import asdict, dataclass

from . import beer_fields, match_keys, upstream

URL = 'https://recherche-entreprises.api.gouv.fr/search'
# Codes d'activité (NAF) cohérents avec chaque type de fiche
ACTIVITY_CODES = {
    match_keys.BREWERY: frozenset({'11.05Z'}),                                   # fabrication de bière
    match_keys.BAR: frozenset({'56.30Z', '56.10A', '56.10B', '56.10C'}),         # débits de boissons, restauration
}


@dataclass(frozen=True)
class SiretCheck:
    siret: str
    available: bool = True        # False : l'annuaire n'a pas répondu, rien n'a pu être contrôlé
    found: bool = False
    active: bool = False
    name: str = ''
    activity_code: str = ''
    activity_ok: bool = False
    postal_code: str = ''
    city: str = ''
    postal_match: bool = False    # le code postal de l'annuaire est celui de la fiche
    name_score: float = 0.0       # ressemblance entre le nom de la fiche et la raison sociale

    def as_dict(self):
        return asdict(self)

    @property
    def rejection(self):
        """Raison de refuser la demande sur-le-champ, ou None (y compris quand l'annuaire est indisponible)."""
        if not self.available:
            return None
        if not self.found:
            return "Ce numéro SIRET n'existe pas dans l'annuaire des entreprises."
        if not self.active:
            return "Cet établissement est fermé : son SIRET n'est plus actif."
        return None


def _establishment(results, siret):
    for company in results[:5]:
        if not isinstance(company, dict):
            continue
        candidates = [company.get('siege'), *(company.get('matching_etablissements') or [])]
        for establishment in candidates:
            if isinstance(establishment, dict) and establishment.get('siret') == siret:
                return company, establishment
    return None, None


def check(siret, kind, name='', postal_code=''):
    """Contrôle `siret` pour une fiche de type `kind` (match_keys.BREWERY ou BAR) ; `name` et `postal_code` : ceux de la fiche, pour comparer."""
    try:
        data = upstream.get_json(URL, {'q': siret, 'per_page': 5})
    except upstream.UpstreamUnavailable:
        return SiretCheck(siret=siret, available=False)
    results = data.get('results') if isinstance(data, dict) else None
    company, establishment = _establishment(results if isinstance(results, list) else [], siret)
    if establishment is None:
        return SiretCheck(siret=siret)
    activity = beer_fields.clean_text(establishment.get('activite_principale') or company.get('activite_principale'), 10) or ''
    registry_name = beer_fields.clean_text(company.get('nom_complet'), 150) or ''
    registry_postal = beer_fields.clean_text(establishment.get('code_postal'), 10) or ''
    score = match_keys.similarity(match_keys.loose_tokens(name, kind), match_keys.loose_tokens(registry_name, kind)) if name and registry_name else 0.0
    return SiretCheck(
        siret=siret, found=True, active=establishment.get('etat_administratif') == 'A', name=registry_name, activity_code=activity,
        activity_ok=activity in ACTIVITY_CODES[kind], postal_code=registry_postal, city=beer_fields.clean_text(establishment.get('libelle_commune'), 100) or '',
        postal_match=bool(postal_code) and postal_code == registry_postal, name_score=round(score, 2),
    )
