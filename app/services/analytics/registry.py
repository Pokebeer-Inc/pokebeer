"""Catalogue des pages d'analytics : ajouter une page = ajouter une entrée (ouvert/fermé)."""
from dataclasses import dataclass
from collections.abc import Callable

from . import audience, bars, catalogue, consumption, engagement, forecasts, habits, geography, health, places, pros, tastes, trends, trophies


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
    listed: bool = True          # présente dans la barre de navigation des analytics (sinon : page technique, atteinte depuis un autre menu)


PAGES = (
    AnalyticsPage('trends', 'Tendances', "Évolution de l'activité dans le temps, moyennes mobiles et prévisions indicatives.", trends.build, granularity=True),
    AnalyticsPage('forecasts', 'Prévisions', "Où va l'activité, quels styles montent, quels mois sont porteurs : prévisions avec fourchette et fiabilité.", forecasts.build, granularity=True),
    AnalyticsPage('tastes', 'Goûts', "Styles, force, amertume, notes et demande non satisfaite : ce que les membres aiment.", tastes.build),
    AnalyticsPage('consumption', 'Consommation', "Lieu, compagnie, format, prix et moment : dans quel contexte on boit et ce que cela coûte.", consumption.build),
    AnalyticsPage('audience', 'Audience', "Âge et genre des dégustateurs, et ce que chaque segment aime (agrégats anonymes).", audience.build),
    AnalyticsPage('habits', 'Habitudes', "Rythme, régularité, fidélisation et adoption des fonctionnalités.", habits.build),
    AnalyticsPage('engagement', 'Engagement', "Activation des nouveaux membres, notifications, services IA, réseau social et qualité des avis.", engagement.build),
    AnalyticsPage('geography', 'Géographie', "Où sont les membres et les établissements, et dans quel contexte ils placent leurs lieux.", geography.build),
    AnalyticsPage('places', 'Établissements', "Classement des brasseries et rapport complet pour chacune : audience, contexte, prix, fidélité, prévision.", places.build, pickers=('brewery',)),
    AnalyticsPage('bars', 'Bars', "Activité des membres autour de chaque bar : ce qu'ils boivent, quand, à quel prix, et quoi mettre en avant.", bars.build, pickers=('bar',)),
    AnalyticsPage('pros', 'Professionnels', "Revendications, couverture et complétude des fiches, prospects à démarcher : le vivier de clients.", pros.build),
    AnalyticsPage('catalogue', 'Catalogue', "Offre et demande par style, force et amertume ; qualité des fiches bière.", catalogue.build),
    AnalyticsPage('health', 'Communauté', "Signalements, modération, échanges avec l'équipe, campagnes e-mail et départs.", health.build),
    AnalyticsPage('trophies', 'Trophées', "Difficulté réelle de chaque trophée : trop faciles, trop difficiles ?", trophies.build, period=False, listed=False),
)
PAGES_BY_KEY = {page.key: page for page in PAGES}
