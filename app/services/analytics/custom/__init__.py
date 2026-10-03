"""Vues et tuiles personnalisées : l'administrateur compose ses propres graphiques à partir d'un catalogue fermé.

Rien de ce que saisit l'utilisateur n'atteint l'ORM autrement que comme clé de ce catalogue :
- catalog : jeux de données, dimensions et mesures autorisés (déclaratif, ouvert/fermé) ;
- spec : validation d'une définition de tuile (compatibilités, bornes) ;
- engine : exécution d'une définition, qui produit les mêmes blocs que les pages prédéfinies ;
- service : création, modification et suppression des vues et tuiles (propriété, quotas).
"""
