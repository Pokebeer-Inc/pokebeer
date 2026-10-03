"""Catalogue des pages d'analytics : ajouter une page = ajouter une entrée (ouvert/fermé)."""
from dataclasses import dataclass
from typing import Callable

from . import bars, habits, geography, places, tastes, trends, trophies


@dataclass(frozen=True)
class AnalyticsPage:
    key: str
    title: str
    description: str
    build: Callable
    granularity: bool = False   # la page propose le choix semaine/mois
    period: bool = True         # la page dépend de la fenêtre temporelle
    pickers: tuple = ()          # sélecteurs d'entité proposés : 'brewery', 'bar'
    is_custom: bool = False      # vue personnalisée (voir services/analytics/custom)


PAGES = (
    AnalyticsPage('trends', 'Tendances', "Évolution de l'activité dans le temps, moyennes mobiles et prévisions indicatives.", trends.build, granularity=True),
    AnalyticsPage('tastes', 'Goûts', "Styles, force, amertume, notes et demande non satisfaite : ce que les membres aiment.", tastes.build),
    AnalyticsPage('habits', 'Habitudes', "Rythme, régularité, fidélisation et adoption des fonctionnalités.", habits.build),
    AnalyticsPage('geography', 'Géographie', "Où sont les membres et les établissements, et dans quel contexte ils placent leurs lieux.", geography.build),
    AnalyticsPage('places', 'Établissements', "Classement des brasseries et pistes de mise en avant pour chacune.", places.build, pickers=('brewery',)),
    AnalyticsPage('bars', 'Bars', "Activité des membres autour de chaque bar : ce qu'ils boivent, quand, et quoi mettre en avant.", bars.build, pickers=('bar',)),
    AnalyticsPage('trophies', 'Trophées', "Difficulté réelle de chaque trophée : trop faciles, trop difficiles ?", trophies.build, period=False),
)
PAGES_BY_KEY = {page.key: page for page in PAGES}
