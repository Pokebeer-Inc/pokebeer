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
LAMBIC = "Lambic et fermentation spontanée"
FLAVORED = "Fruitée, épicée et aromatisée"
LOW = "Sans alcool et légère"

# Ordre d'affichage des familles (leur position en base, voir la migration 0098) : l'équipe le modifie ensuite dans l'administration.
FAMILIES = (IPA, PALE, LAGER, WHITE, AMBER, DARK, SOUR, LAMBIC, BELGIAN, FLAVORED, SPECIAL, LOW)

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
    # Styles ajoutés par la migration 0100 (référentiel élargi) : chaque nom ou alias ne désigne qu'un seul style (testé)
    ("Belgian IPA", IPA, ("IPA belge",)),
    ("Triple IPA", IPA, ("TIPA", "Triple India Pale Ale")),
    ("Red IPA", IPA, ("IPA rousse",)),
    ("White IPA", IPA, ("IPA blanche",)),
    ("Brut IPA", IPA, ()),
    ("Cold IPA", IPA, ()),
    ("Rye IPA", IPA, ("RyePA",)),
    ("Milkshake IPA", IPA, ("Smoothie IPA",)),
    ("Bitter", PALE, ("Best Bitter", "English Bitter", "English Pale Ale")),
    ("Extra Special Bitter", PALE, ("ESB",)),
    ("Cream Ale", PALE, ()),
    ("Wheat Ale", PALE, ("American Wheat", "Blé américain")),
    ("Märzen", LAGER, ("Marzen", "Oktoberfest", "Festbier")),
    ("Vienna Lager", LAGER, ("Vienna", "Vienne")),
    ("Dunkel", LAGER, ("Munich Dunkel", "Dunkles")),
    ("Schwarzbier", LAGER, ("Black Lager", "Lager noire")),
    ("Dortmunder", LAGER, ("Dortmunder Export", "Export")),
    ("Kellerbier", LAGER, ("Zwickel", "Zwickelbier", "Zwickl")),
    ("Czech Pils", LAGER, ("Bohemian Pilsner", "Pils tchèque", "Czech Pilsner")),
    ("India Pale Lager", LAGER, ("IPL",)),
    ("Dunkelweizen", WHITE, ("Dunkel Weizen", "Weizen brune")),
    ("Weizenbock", WHITE, ("Weizen Bock",)),
    ("Kristallweizen", WHITE, ("Kristall Weizen", "Crystal Weizen")),
    ("Scotch Ale", AMBER, ("Scottish Ale", "Wee Heavy", "Écossaise")),
    ("California Common", AMBER, ("Steam Beer", "Steam")),
    ("Mild", DARK, ("Dark Mild", "English Mild")),
    ("Milk Stout", DARK, ("Sweet Stout", "Stout au lait", "Cream Stout")),
    ("Oatmeal Stout", DARK, ("Stout à l'avoine",)),
    ("Pastry Stout", DARK, ("Dessert Stout", "Stout pâtissier")),
    ("Foreign Extra Stout", DARK, ("Export Stout", "Tropical Stout")),
    ("Imperial Porter", DARK, ("Porter impériale",)),
    ("Kettle Sour", SOUR, ("Sour de cuve", "Quick Sour")),
    ("Oud Bruin", SOUR, ("Flanders Brown", "Flemish Brown", "Vieille brune")),
    ("Flanders Red", SOUR, ("Flemish Red", "Rouge des Flandres", "Rodenbach")),
    ("Wild Ale", SOUR, ("Brett", "Brettanomyces", "Mixed Fermentation", "Fermentation mixte")),
    ("Lichtenhainer", SOUR, ()),
    ("Lambic", LAMBIC, ("Lambik",)),
    ("Gueuze", LAMBIC, ("Geuze", "Gueuze lambic")),
    ("Kriek", LAMBIC, ("Cerise", "Lambic kriek", "Lambic cerise")),
    ("Framboise", LAMBIC, ("Lambic framboise", "Frambozen")),
    ("Faro", LAMBIC, ()),
    ("Belgian Blonde", BELGIAN, ("Blonde belge", "Blond belge", "Belgian Blond")),
    ("Belgian Pale Ale", BELGIAN, ("Pale Ale belge", "Spéciale belge", "Belgian Ale")),
    ("Belgian Strong Golden", BELGIAN, ("Strong Golden Ale", "Golden Strong", "Belgian Golden Strong", "Blonde forte")),
    ("Belgian Dark Strong", BELGIAN, ("Dark Strong Ale", "Strong Dark Ale", "Brune forte")),
    ("Abbaye", BELGIAN, ("Abbey Ale", "Bière d'abbaye", "Abbey", "Abdij")),
    ("Trappiste", BELGIAN, ("Trappist", "Bière trappiste")),
    ("Grisette", BELGIAN, ()),
    ("Table Beer", BELGIAN, ("Bière de table", "Tafelbier")),
    ("Fruit Beer", FLAVORED, ("Bière aux fruits", "Fruited Beer", "Fruit Ale")),
    ("Spiced Beer", FLAVORED, ("Bière épicée", "Epicée", "Épicée", "Herbed Beer")),
    ("Honey Beer", FLAVORED, ("Bière au miel", "Miel")),
    ("Pumpkin Beer", FLAVORED, ("Pumpkin Ale", "Bière de citrouille")),
    ("Coffee Beer", FLAVORED, ("Bière au café", "Café")),
    ("Chestnut Beer", FLAVORED, ("Bière à la châtaigne", "Châtaigne")),
    ("Radler", FLAVORED, ("Panaché", "Shandy")),
    ("Gruit", FLAVORED, ()),
    ("Eisbock", SPECIAL, ()),
    ("Wheatwine", SPECIAL, ("Wheat Wine",)),
    ("Sahti", SPECIAL, ()),
    ("Bière de Noël", SPECIAL, ("Christmas Beer", "Winter Ale", "Winter Warmer", "Bière de Noel")),
    ("Barrel Aged", SPECIAL, ("BA", "Vieillie en fût", "Barrique", "Barrel-Aged")),
    ("Sans alcool", LOW, ("0.0", "Alcohol Free", "Non-alcoholic", "NA Beer", "Sans alcool 0.0", "Zéro")),
    ("Bière légère", LOW, ("Light Beer", "Light Lager", "Low Alcohol", "Faible en alcool")),
)
