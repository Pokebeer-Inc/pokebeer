"""Analytics réservées à l'équipe : indicateurs agrégés, jamais de données individuelles.

Organisation (une responsabilité par module) :
- periods / series / privacy / geo : outils partagés (fenêtre temporelle, séries et prévisions, anonymat, distances) ;
- blocks : description neutre de ce qu'on affiche (KPI, graphique, tableau, carte) ;
- profiles : profil d'un ensemble de dégustations (audience et contexte), partagé par les pages, les brasseries et les bars ;
- trends, forecasts, tastes, consumption, audience, habits, engagement, geography, places (+ brewery_report), bars, pros, catalogue, health,
  trophies : une fonction `build(period, params)` par page.
"""
