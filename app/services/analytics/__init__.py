"""Analytics réservées à l'équipe : indicateurs agrégés, jamais de données individuelles.

Organisation (une responsabilité par module) :
- periods / series / privacy / geo : outils partagés (fenêtre temporelle, séries et prévisions, anonymat, distances) ;
- blocks : description neutre de ce qu'on affiche (KPI, graphique, tableau, carte) ;
- trends, tastes, habits, geography, places, trophies : une fonction `build(period, params)` par page.
"""
