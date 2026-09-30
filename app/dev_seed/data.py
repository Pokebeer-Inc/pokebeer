"""Jeu de données fictif pour la base de développement (aucune donnée réelle)."""

SITE_DOMAIN = "localhost:8000"
EMAIL_DOMAIN = "example.com"

ADMIN_USERNAME = "admin_dev"
BREWER_USERNAME = "brasseur_dev"
BARTENDER_USERNAME = "barman_dev"

USERS = [
    {"username": ADMIN_USERNAME, "bio": "Compte administrateur de développement.", "is_superuser": True, "roles": ("Staff",)},
    {"username": BREWER_USERNAME, "bio": "Brasseur passionné, gère deux brasseries."},
    {"username": BARTENDER_USERNAME, "bio": "Gérant de bars à bières."},
    {"username": "alice", "bio": "Fan d'IPA et de houblons fruités."},
    {"username": "bruno", "bio": "Les stouts, sinon rien."},
    {"username": "chloe", "bio": "Toujours à la recherche de la sour parfaite."},
    {"username": "damien", "bio": "Amateur de trappistes."},
    {"username": "emma_b", "bio": "Je note tout, même l'eau."},
    {"username": "felix", "bio": "Blondes légères en terrasse."},
    {"username": "gaelle", "bio": "Zythologue en herbe."},
    {"username": "hugo_l", "bio": "Découvreur de micro-brasseries."},
]

# Les deux premières brasseries et les deux premiers bars sont gérés par les comptes pro.
BREWERIES = [
    {
        "name": "Brasserie du Vieux Port", "address": "12 Quai du Port, 13002 Marseille",
        "latitude": 43.2951, "longitude": 5.3740,
        "description": "Brasserie artisanale face à la Méditerranée.",
        "beers": [
            ("Mistral Blonde", "Blonde, Pale Ale", 5.2, 22, "Légère, notes de céréales et d'agrumes."),
            ("Calanque IPA", "IPA", 6.5, 55, "Houblons citronnés, amertume franche."),
            ("Bouillabaisse Stout", "Stout", 7.0, 40, "Café torréfié et chocolat noir."),
        ],
    },
    {
        "name": "Les Brasseurs du Rhône", "address": "8 Quai Saint-Antoine, 69002 Lyon",
        "latitude": 45.7640, "longitude": 4.8357,
        "description": "Bières de caractère brassées entre Rhône et Saône.",
        "beers": [
            ("Traboule Ambrée", "Ambrée", 6.0, 28, "Caramel, biscuit et fruits secs."),
            ("Fourvière Triple", "Triple", 8.5, 30, "Ronde, épicée, finale sèche."),
            ("Confluence NEIPA", "NEIPA, IPA", 6.8, 35, "Trouble, jus de mangue et fruit de la passion."),
        ],
    },
    {
        "name": "Brasserie des Flandres", "address": "3 Grand Place, 59000 Lille",
        "latitude": 50.6365, "longitude": 3.0635,
        "description": "Tradition flamande et levures belges.",
        "beers": [
            ("Beffroi Blanche", "Blanche", 4.8, 12, "Coriandre et écorce d'orange."),
            ("Vieux Lille Brune", "Brune", 7.5, 25, "Fruits rouges confits et réglisse."),
            ("Braderie Saison", "Saison", 6.2, 30, "Poivrée, sèche et très rafraîchissante."),
        ],
    },
    {
        "name": "Atelier Brassicole Breton", "address": "5 Rue du Port, 29900 Concarneau",
        "latitude": 47.8730, "longitude": -3.9180,
        "description": "Micro-brasserie iodée du Finistère.",
        "beers": [
            ("Embruns Gose", "Gose, Sour", 4.5, 8, "Acidulée, pointe de sel de Guérande."),
            ("Korrigan Rousse", "Rousse", 5.8, 24, "Malt toasté, notes de pain d'épices."),
            ("Phare Porter", "Porter", 6.4, 34, "Cacao, vanille et fumée légère."),
        ],
    },
    {
        "name": "Brasserie des Alpes", "address": "20 Rue de la République, 38000 Grenoble",
        "latitude": 45.1885, "longitude": 5.7245,
        "description": "Eau de montagne et houblons locaux.",
        "beers": [
            ("Chartreuse Pils", "Pils, Lager", 4.9, 32, "Nette, herbacée, très désaltérante."),
            ("Sommet Imperial Stout", "Imperial Stout", 10.5, 65, "Puissante, café, bourbon et mélasse."),
            ("Glacier Session IPA", "Session IPA, IPA", 4.2, 40, "Légère et très aromatique."),
        ],
    },
    {
        "name": "La Garonne Brassée", "address": "15 Quai de la Garonne, 31000 Toulouse",
        "latitude": 43.6045, "longitude": 1.4440,
        "description": "Bières ensoleillées du Sud-Ouest.",
        "beers": [
            ("Violette Blonde", "Blonde", 5.0, 18, "Florale, légère touche de violette."),
            ("Capitole Double IPA", "Double IPA, IPA", 8.2, 80, "Résineuse, pin et pamplemousse."),
            ("Cassoulet Smoked Ale", "Rauchbier", 6.0, 26, "Fumée de hêtre et malt grillé."),
        ],
    },
    {
        "name": "Brasserie de l'Estuaire", "address": "2 Quai de la Fosse, 44000 Nantes",
        "latitude": 47.2120, "longitude": -1.5620,
        "description": "Brasserie expérimentale en bord de Loire.",
        "beers": [
            ("Machine Sour Framboise", "Fruited Sour, Sour", 5.5, 6, "Framboise éclatante, acidité vive."),
            ("Loire Lager", "Lager", 4.6, 20, "Simple, fraîche et équilibrée."),
            ("Petit Beurre Brown Ale", "Brown Ale", 5.6, 22, "Biscuit, noisette et caramel au beurre salé."),
        ],
    },
    {
        "name": "Brasserie Parisienne du Canal", "address": "40 Quai de Valmy, 75010 Paris",
        "latitude": 48.8716, "longitude": 2.3640,
        "description": "Micro-brasserie urbaine au bord du canal Saint-Martin.",
        "beers": [
            ("Canal West Coast IPA", "West Coast IPA, IPA", 6.9, 70, "Sèche, amère, pin et résine."),
            ("Zinc Witbier", "Blanche", 4.7, 14, "Légère, épicée, notes de citron."),
            ("Montmartre Quadrupel", "Quadrupel", 10.0, 28, "Figue, datte et sucre candi."),
        ],
    },
]

BARS = [
    {"name": "Le Houblon Doré", "address": "18 Rue Oberkampf, 75011 Paris", "latitude": 48.8650, "longitude": 2.3780,
     "description": "Vingt tireuses et une terrasse ensoleillée."},
    {"name": "La Mousse Lyonnaise", "address": "4 Place des Terreaux, 69001 Lyon", "latitude": 45.7675, "longitude": 4.8335,
     "description": "Bar à bières craft au cœur des pentes."},
    {"name": "Le Comptoir Flamand", "address": "22 Rue de la Monnaie, 59000 Lille", "latitude": 50.6400, "longitude": 3.0630,
     "description": "Spécialités belges et flamandes."},
    {"name": "Au Fût Marin", "address": "7 Cours Julien, 13006 Marseille", "latitude": 43.2940, "longitude": 5.3830,
     "description": "Bières locales et planches de la mer."},
    {"name": "Le Refuge des Brasseurs", "address": "11 Place Grenette, 38000 Grenoble", "latitude": 45.1905, "longitude": 5.7270,
     "description": "Chalet urbain dédié aux bières de montagne."},
]

DRINK_COMMENTS = [
    "Très bonne surprise, je recommande !",
    "Un peu trop amère à mon goût.",
    "Parfaite pour l'apéro.",
    "Belle complexité, à redéguster.",
    "Correcte sans plus.",
    "Ma nouvelle préférée.",
    "Très rafraîchissante en terrasse.",
    "Arômes superbes, bouche un peu légère.",
]

SPOT_TITLES = [
    "Soirée entre amis",
    "Dégustation au bord de l'eau",
    "Festival de la bière",
    "Terrasse d'été",
    "Visite de brasserie",
]
