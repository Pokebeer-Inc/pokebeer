"""Référentiel de départ des styles de bière : (nom officiel, famille, alias). Données pures, copiées en base par la migration 0094 puis
gérées par l'équipe dans l'administration (table `Style`) ; ce fichier ne sert qu'à l'amorcer.

Les familles regroupent des styles comparables : ce sont elles qui rendent les statistiques lisibles quand les styles sont nombreux."""

IPA = "IPA"
PALE = "Pale Ale et blonde"
LAGER = "Lager et pils"
WHITE = "Blanche et weizen"
AMBER = "Ambrée et rousse"
DARK = "Brune, porter et stout"
SOUR = "Sour et gose"
BELGIAN = "Belge et abbaye"
SPECIAL = "Fumée, forte et spéciale"

STYLE_CATALOG = (
    ("IPA", IPA, ("India Pale Ale",)),
    ("NEIPA", IPA, ("New England IPA", "Hazy IPA", "Hazy", "NEIPA / Hazy")),
    ("West Coast IPA", IPA, ("WCIPA", "West Coast")),
    ("Double IPA", IPA, ("DIPA", "Imperial IPA", "Double India Pale Ale")),
    ("Session IPA", IPA, ("Sessions IPA", "Session India Pale Ale")),
    ("Black IPA", IPA, ("Cascadian Dark Ale", "India Black Ale")),
    ("Pale Ale", PALE, ("APA", "American Pale Ale")),
    ("Blonde", PALE, ("Blond", "Blonde Ale", "Golden Ale", "Dorée")),
    ("Lager", LAGER, ("Lager blonde",)),
    ("Pils", LAGER, ("Pilsner", "Pilsener", "Pilsen")),
    ("Helles", LAGER, ("Munich Helles",)),
    ("Blanche", WHITE, ("Witbier", "Wit", "Bière blanche", "White Beer")),
    ("Weizen", WHITE, ("Hefeweizen", "Weissbier", "Weiss", "Bière de blé")),
    ("Ambrée", AMBER, ("Amber Ale", "Amber", "Ambre")),
    ("Rousse", AMBER, ("Red Ale", "Irish Red", "Roux")),
    ("Brune", DARK, ("Brown Ale", "Dark Ale", "Brun")),
    ("Porter", DARK, ("Baltic Porter",)),
    ("Stout", DARK, ("Dry Stout", "Irish Stout")),
    ("Imperial Stout", DARK, ("Russian Imperial Stout", "RIS")),
    ("Sour", SOUR, ("Acide", "Sour Ale", "Bière acide")),
    ("Gose", SOUR, ()),
    ("Berliner Weisse", SOUR, ("Berliner",)),
    ("Fruited Sour", SOUR, ("Sour aux fruits", "Sour fruitée")),
    ("Saison", BELGIAN, ("Bière de saison",)),
    ("Triple", BELGIAN, ("Tripel", "Tripple")),
    ("Double", BELGIAN, ("Dubbel",)),
    ("Quadrupel", BELGIAN, ("Quad", "Quadruple")),
    ("Bière de garde", BELGIAN, ("Biere de garde",)),
    ("Rauchbier", SPECIAL, ("Bière fumée", "Smoked Beer", "Fumée")),
    ("Barley Wine", SPECIAL, ("Barleywine",)),
    ("Bock", SPECIAL, ("Doppelbock", "Maibock")),
    ("Kölsch", SPECIAL, ("Kolsch",)),
    ("Altbier", SPECIAL, ("Alt",)),
)
