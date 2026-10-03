"""Définition d'une tuile personnalisée et sa validation : seule porte d'entrée des données saisies par l'utilisateur."""
from dataclasses import asdict, dataclass

from .catalog import CATALOG

CHART_TYPES = {
    'kpi': 'Valeur unique (KPI)',
    'table': 'Tableau',
    'bar': 'Barres verticales',
    'hbar': 'Barres horizontales',
    'line': 'Courbe dans le temps',
    'donut': 'Anneau (répartition)',
}
SORTS = {'value_desc': 'Plus grandes valeurs d\'abord', 'label_asc': 'Ordre alphabétique'}
MAX_MEASURES = 4
MAX_LIMIT = 25
DEFAULT_LIMIT = 10
TITLE_MAX = 100


class SpecError(ValueError):
    """Définition refusée ; le message est affichable à l'utilisateur."""


@dataclass(frozen=True)
class TileSpec:
    dataset: str
    measures: tuple
    chart: str
    dimension: str = ''
    limit: int = DEFAULT_LIMIT
    sort: str = 'value_desc'
    trend: bool = False

    def to_json(self):
        data = asdict(self)
        data['measures'] = list(self.measures)
        return data


def _as_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def validate(raw):
    """Construit une TileSpec à partir de données brutes ou lève SpecError. Tout est contrôlé contre le catalogue."""
    if not isinstance(raw, dict):
        raise SpecError("Définition de tuile invalide.")
    dataset_key = raw.get('dataset')
    if dataset_key not in CATALOG:
        raise SpecError("Choisissez un jeu de données valide.")
    dataset = CATALOG[dataset_key]

    chart = raw.get('chart')
    if chart not in CHART_TYPES:
        raise SpecError("Choisissez un type de graphique valide.")

    measures = raw.get('measures') or []
    if not isinstance(measures, (list, tuple)) or not all(isinstance(m, str) for m in measures):
        raise SpecError("Mesures invalides.")
    measures = tuple(dict.fromkeys(measures))
    if not 1 <= len(measures) <= MAX_MEASURES:
        raise SpecError(f"Choisissez entre 1 et {MAX_MEASURES} mesures.")
    if any(m not in dataset.measures for m in measures):
        raise SpecError("Une des mesures n'existe pas pour ce jeu de données.")

    dimension = raw.get('dimension') or ''
    if chart == 'kpi':
        if dimension:
            raise SpecError("Une valeur unique n'a pas de regroupement : laissez « Regrouper par » vide.")
        if len(measures) != 1:
            raise SpecError("Une valeur unique affiche une seule mesure.")
    else:
        if dimension not in dataset.dimensions:
            raise SpecError("Choisissez un regroupement valide pour ce jeu de données.")
        if chart == 'line' and dataset.dimensions[dimension].kind != 'time':
            raise SpecError("La courbe nécessite le regroupement « Période ».")
        if chart == 'donut' and len(measures) != 1:
            raise SpecError("L'anneau affiche une seule mesure.")

    sort = raw.get('sort') or 'value_desc'
    if sort not in SORTS:
        raise SpecError("Tri invalide.")
    limit = _as_int(raw.get('limit'), DEFAULT_LIMIT)
    if not 1 <= limit <= MAX_LIMIT:
        raise SpecError(f"Le nombre de lignes doit être compris entre 1 et {MAX_LIMIT}.")

    trend = bool(raw.get('trend'))
    if trend and not (chart == 'line' and len(measures) == 1):
        raise SpecError("La tendance (moyenne mobile et prévision) s'applique à une courbe à une seule mesure.")

    return TileSpec(dataset_key, measures, chart, dimension, limit, sort, trend)


def normalize_text(value):
    """Texte sans caractères de contrôle et aux espaces normalisés (le rendu l'échappe de toute façon)."""
    return ' '.join(''.join(c for c in str(value or '') if c.isprintable()).split())


def clean_title(value):
    title = normalize_text(value)
    if not title:
        raise SpecError("Donnez un titre à la tuile.")
    if len(title) > TITLE_MAX:
        raise SpecError(f"Le titre est limité à {TITLE_MAX} caractères.")
    return title
