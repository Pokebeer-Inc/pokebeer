# Audit des analytics Pokebeer

Date : 19/10/2026. Périmètre : tout `app/services/analytics/`, les pages d'administration associées et les modèles de données.
Objectif : préparer la vente de données et de prévisions aux brasseurs et aux bars.

## 1. En bref

- **Beaucoup de données collectées n'étaient pas exploitées.** Le plus gros gisement : le contexte des dégustations (lieu, compagnie, format, **prix payé**), l'âge et le genre des membres, les pouces sur les avis, les revendications d'établissements, les usages IA, les notifications. Rien de cela n'apparaissait dans les analytics.
- **Sur 57 blocs existants, 23 ont une vraie valeur commerciale (A), 14 servent au pilotage (B) et 20 sont faibles ou redondants (C).** Rien n'a été supprimé : c'est à toi de trancher (section 4).
- **J'ai ajouté 7 pages et ~129 blocs**, plus un rapport complet par brasserie et un profil enrichi par bar (section 5).
- **Trois trous de collecte bloquent le modèle économique** : pas de lien dégustation → bar, pas de mesure des vues de fiches, pas d'historique d'activité (section 6). Ils pèsent plus lourd que n'importe quel graphique.
- **Un biais de calcul existant** fausse les variations (« vs période précédente ») : section 7.

## 2. Ce qu'on collecte, et ce qu'on en faisait

| Donnée | Champs | Exploitée avant | Exploitée maintenant |
|---|---|---|---|
| Dégustation | note, commentaire, date, photo | oui (note, date) | + richesse des avis dans le temps |
| **Contexte de dégustation** | lieu, compagnie, format, **prix** | **non** | Consommation, rapport brasserie, profil bar |
| Bière | style, degré, IBU, EAN, vérifiée, description, image | style, degré, IBU | + offre/demande, complétude, longue traîne |
| **Âge et genre du membre** | date de naissance, genre | **non** | Audience, rapport brasserie, profil bar, vues custom |
| Activité du membre | `last_activity_at` | non | Engagement (actifs 7/30/90 j, ancienneté) |
| Réseau social | abonnements, pouces sur les avis | adoption seulement | Engagement (courbes, densité, pouces) |
| Liste « À goûter » | souhaits | top 10 des bières souhaitées | + conversion souhait → dégustation |
| Lieux de la carte | position, amis, dégustations liées, géocodage inverse | oui (géographie, bars) | + taille du groupe, bières par visite |
| **Établissements** | contacts, SIRET, vérifié, gérants, adresse | positions seulement | Professionnels (couverture, complétude) |
| **Revendications et invitations** | statut, dates, SIRET | **non** | Professionnels (entonnoir, délai, prospects) |
| **Quotas IA / scan** | appels par service et par jour | **non** | Engagement (usage et adoption) |
| **Notifications** | type, lue ou non, préférences, jeton push | **non** | Engagement (taux de lecture, désactivations) |
| Brouillons d'ajout de bière | étape atteinte | **non** | Engagement (abandons par étape) |
| Signalements, modération, échanges avec l'équipe, blocages | motif, cible, statut, délais | **non** | Communauté |
| Campagnes e-mail | destinataires, statut d'envoi | **non** | Communauté |
| Comptes supprimés | motif, prévenu ou non | non (hors tableau de bord) | Communauté |
| Trophées | paliers | oui | inchangé |

**Données qui n'existent pas** (et dont l'absence limite ce qu'on peut vendre) : voir section 6.

## 3. Légende de classement

- **A** : vendable ou argument commercial direct (un brasseur ou un bar paierait pour ça).
- **B** : utile pour piloter Pokebeer, pas vendable en l'état.
- **C** : faible valeur, redondant ou purement technique.

## 4. Classement des graphiques existants

### Tendances (13 blocs : 3 A, 2 B, 8 C)

| Bloc | Classe | Verdict |
|---|---|---|
| KPI Dégustations + courbe | A | Garder |
| Courbe Membres actifs | A | Garder |
| KPI + courbe Nouveaux membres | B | Garder |
| KPI Lieux placés + courbe | C | Fusionner ou masquer |
| KPI Nouvelles bières + courbe | C | À supprimer : « date de première dégustation » n'est qu'un substitut, `Beer` n'a pas de date de création |
| KPI + courbe Nouvelles brasseries / Nouveaux bars | C | Fusionner en une courbe « Établissements référencés » |

Les 6 KPI répètent la somme des courbes : n'en garder que 3 avec variation.

### Goûts (9 blocs : 6 A, 2 B, 1 C)

| Bloc | Classe | Verdict |
|---|---|---|
| Styles les plus bus | A | Garder |
| Styles les mieux notés | A | Garder, lisser la note (moyenne bayésienne) |
| Styles en hausse / baisse | A | Garder |
| Bières les mieux notées | A | Garder, même lissage : une bière à 10/10 notée 3 fois passe devant une à 9,2 notée 80 fois |
| **Bières les plus souhaitées** | A | Garder, c'est le meilleur argument pour un brasseur |
| Saisonnalité des styles (heatmap) | A | Garder |
| Force (ABV) / Amertume (IBU) | B | Remplacés par « offre et demande » du Catalogue : à supprimer ici |
| Répartition des notes | C | Diagnostic de calibrage, pas une donnée à vendre |

### Habitudes (6 blocs : 2 A, 3 B, 1 C)

| Bloc | Classe | Verdict |
|---|---|---|
| Fidélisation par cohorte | A | Garder (argument investisseurs) |
| Dégustations par jour de la semaine | A | Garder |
| KPI par membre actif, Régularité, Adoption | B | Garder |
| Dégustations par mois de l'année | C | Triple emploi avec la saisonnalité des Goûts et l'indice saisonnier des Prévisions : à supprimer |

### Géographie (11 blocs : 3 A, 3 B, 5 C)

| Bloc | Classe | Verdict |
|---|---|---|
| Carte, Villes les plus actives, Lieux par région | A | Garder |
| Type de lieu, Urbain ou rural, KPI Lieux | B | Garder |
| KPI « Lieux géocodés », « Zones publiées », « Lieux dans des zones masquées » | C | Indicateurs techniques : à passer en note |
| Contexte des lieux (estimation par proximité) | C | Redondant avec « Type de lieu » issu d'OpenStreetMap, moins fiable |
| Zones les plus actives (lat, lon) | C | Coordonnées illisibles, couvertes par la carte et les villes |

### Établissements (7 blocs : 5 A, 1 B, 1 C)

| Bloc | Classe | Verdict |
|---|---|---|
| Brasseries les plus bues | A | Garder |
| **Styles demandés que la brasserie ne propose pas** | A | Garder, très fort |
| Styles du catalogue en hausse | A | Garder |
| Où les bières sont bues | A | Garder |
| **Zones à potentiel** | A | Garder, très fort |
| Dégustations par mois | B | Remplacé par la courbe avec prévision du rapport : à supprimer |
| KPI Établissements géolocalisés | C | Masquer |

### Bars (8 blocs : 4 A, 3 B, 1 C)

| Bloc | Classe | Verdict |
|---|---|---|
| Activité autour de chaque bar | A | Garder |
| **Styles bus autour du bar (indice)** | A | Garder, très fort |
| Bières les plus bues autour du bar | A | Garder |
| Fréquentation par jour de la semaine | A | Garder |
| Fréquentation par mois, KPI Lieux, KPI Membres | B | Garder |
| KPI Bars géolocalisés | C | Masquer |

### Trophées (3 blocs : 3 C)

Réglage interne du jeu, aucune valeur commerciale. À garder, mais à sortir du menu principal (le déplacer sous Communauté).

### Vues custom

Précieux pour toi, pas un produit à vendre tel quel. Étendu cette session (section 5).

### Tableau de bord d'accueil de l'admin

Compteurs et répartition des bières par style : B. Redondant avec les pages Catalogue et Professionnels.

## 5. Ce que j'ai ajouté

Rien n'est retiré, aucune migration, aucune nouvelle collecte. Tout vient de données déjà en base. Les groupes de moins de 3 dégustateurs restent masqués partout (règle existante `MIN_GROUP_SIZE`).

### Nouvelles pages (menu Analytics)

| Page | Contenu | Classe |
|---|---|---|
| **Consommation** | Taux de remplissage de chaque info, où on boit, avec qui, format, prix moyen et médian, répartition des prix, prix par format / par style / par ville, **prix au litre selon le lieu**, note selon le prix, évolution du prix, mix de formats dans le temps, styles selon lieu / compagnie / format, quand on boit selon le lieu, note selon lieu et compagnie, heure d'enregistrement | A |
| **Audience** | Âge et genre des dégustateurs (donuts), styles préférés par tranche d'âge et par genre, intensité d'usage et note moyenne par segment | A |
| **Prévisions** | Prévision avec **fourchette à 80 %** pour dégustations, membres actifs, nouveaux membres, lieux ; indicateur de fiabilité selon l'historique ; tableau « styles : tendance, prévision 3 mois, fiabilité R², verdict » ; styles à suivre ; **indice saisonnier** | A |
| **Professionnels** | Revendications (en attente, taux d'acceptation, délai médian, tendance), invitations, couverture et complétude des fiches, **brasseries et bars à démarcher** (activité sans gérant), part des dégustations déjà couverte par des gérants | A (c'est ton entonnoir de vente) |
| **Catalogue** | **Offre et demande par style, force et amertume**, indice demande / offre, longue traîne, concentration, complétude, brasseries par département, styles à normaliser | A / B |
| **Engagement** | Actifs 7 / 30 / 90 jours, ancienneté de la dernière visite, **parcours d'activation**, délai avant la première dégustation, richesse des avis dans le temps, réseau social, pouces, usage IA et coût, taux de lecture des notifications, désactivations, push, souhait → dégustation, abandons d'ajout de bière | B (A pour investisseurs) |
| **Communauté** | Signalements, modération, relecture, échanges avec l'équipe, blocages, campagnes e-mail, départs | B |

### Rapport complet par brasserie (page Établissements, après choix d'une brasserie)

C'est le **prototype du produit payant** : dégustations, rang et part de marché, dégustateurs et **fidélité**, note vs communauté, tendance avec **prévision et fourchette**, répartition des notes vs communauté, **tableau par bière** (écart au style, prix, souhaits, souhaits goûtés), **part de marché par style**, audience (âge, genre), contexte (lieu, compagnie, format), prix vs communauté. Les calculs prennent un simple ensemble de dégustations : ils se brancheront tels quels sur un tableau de bord réservé aux gérants.

### Profil enrichi par bar (page Bars, après choix d'un bar)

Taille moyenne du groupe, bières par visite, lieu / compagnie / format, prix vs communauté, audience.

### Vues custom étendues

Dégustations : mesures *prix moyen* et *prix renseignés* ; regroupements *lieu, compagnie, format, tranche de prix, tranche d'âge, genre, heure*. Nouveaux membres : *tranche d'âge, genre*. Nouveaux jeux de données : *pouces, abonnements, notifications, services IA, revendications, signalements, catalogue de bières*. L'anonymat s'applique à tous les regroupements.

## 6. Ce qui manque pour vendre : recommandations de collecte

Classées par priorité. Aucune n'est faite : chacune demande ton accord (modèle de données, vie privée).

**Priorité 1 : bloquant pour le produit bar**
1. **Lier la dégustation à un établissement.** Aujourd'hui un bar n'« existe » dans les données que si un membre pose un lieu à moins de 150 m *et* y rattache sa dégustation. Ajouter un champ `bar` facultatif sur la dégustation (« Où ? » avec les bars proches). Les chiffres par bar passent de quelques dizaines à toutes les dégustations déclarées au bar. Les brasseries n'ont pas ce problème (la bière connaît sa brasserie).
2. **Mesurer les vues des fiches** (bière, brasserie, bar) par compteur journalier, **sans identifiant de membre** (compatible RGPD). C'est le premier chiffre qu'un professionnel demandera : « combien de personnes ont vu ma bière ? ».
3. **Historique d'activité** : une ligne (membre, jour) à chaque jour actif. Sans elle, impossible d'afficher des actifs quotidiens / hebdomadaires dans le passé ou une vraie rétention (aujourd'hui seule la *dernière* visite existe, mise à jour au plus toutes les 12 h).

**Priorité 2 : qualité des données vendues**
4. **Faire monter le remplissage** de lieu, compagnie, format et prix (champs facultatifs). La page Consommation affiche ce taux en premier. Idées : proposer la dernière valeur par défaut, saisie en un geste, trophée dédié.
5. **Normaliser les styles.** `Beer.style` est un texte libre découpé sur les virgules : « IPA », « Ipa » et « NEIPA » sont trois styles. Une table de styles (avec famille) rend tous les benchmarks comparables. La page Catalogue liste les styles à fusionner.
6. **Dates manquantes** : `Beer.created_at`, `Report.resolved_at`, `Notification.read_at`. Sans elles : pas de rythme d'enrichissement du catalogue, pas de délai de traitement des signalements, pas de délai de lecture.
7. **Recherches sans résultat** (terme normalisé, compteur journalier) et **codes-barres introuvables** : mesure la demande non satisfaite du catalogue.
8. **Ouverture et clic des e-mails** : absents, donc aucune mesure d'efficacité des campagnes.

**Priorité 3 : mise en vente**
9. **Vie privée** : l'âge et le genre sont « jamais montrés aux autres membres » dans le formulaire. Les revendre agrégés aux pros doit figurer dans la politique de confidentialité (finalité statistique). À valider avec ton conseil juridique, je ne peux pas le trancher.
10. **Seuil d'anonymat** : 3 membres distincts est un minimum. Pour des données *sorties* de Pokebeer, viser 10 et ajouter une règle de dominance (un seul membre ne doit pas représenter plus de la moitié d'un groupe).
11. **Accès par établissement** : aujourd'hui tout est réservé au staff. Un gérant ne devra voir que sa fiche plus les repères de comparaison.
12. **Seed de développement** : le jeu de données local ne remplit ni prix, ni lieu, ni âge, ni genre. Les nouvelles pages y apparaissent presque vides.

## 7. Problèmes de méthode relevés dans l'existant

| Problème | Effet | Correction proposée |
|---|---|---|
| **Période courante plus courte que la précédente.** « 12 derniers mois » = 11 mois pleins + mois en cours partiel, comparé à 12 mois pleins | Les variations « vs période précédente » sont biaisées à la baisse (≈ -8 % à 12 mois, jusqu'à -33 % à 3 mois en début de mois) | Comparer à durée égale ou exclure le mois en cours |
| Notes moyennes non lissées | Classements dominés par les petits effectifs | Moyenne bayésienne |
| `Drinks.date` est déclarée par le membre | L'activité par date reflète la date saisie, pas l'usage réel | Utiliser `created_at` pour l'activité, `date` pour la consommation |
| Calculs en Python sur tous les lieux | `classify_spot` (lieux × établissements), vue d'ensemble des bars, nouveautés, segments : acceptable jusqu'à quelques milliers de membres | Passer en agrégats SQL ou tables précalculées au-delà |
| Prix sans devise | Supposé en euros | À documenter |
| Heure d'enregistrement ≠ heure de consommation | Graphique indicatif seulement | Signalé dans le sous-titre |

## 8. Vérifications effectuées

- Les 3379 tests passent (dont 61 nouveaux dans `tests/admin/test_analytics_business.py`), `ruff` est propre.
- Chaque nouvelle page s'ouvre avec une base vide, avec des données riches et pour les périodes extrêmes (3 et 24 mois, par semaine).
- Anonymat testé : un segment de moins de 3 dégustateurs n'est jamais affiché, ni date de naissance, ni pseudo dans le HTML.
- Calculs vérifiés sur des valeurs connues (prix moyen / médian, tranches d'âge, fourchette de prévision, souhaits convertis).
- Toutes les combinaisons jeu de données × regroupement × mesure des vues custom s'exécutent.
- **Non vérifié** : rendu visuel dans le navigateur (la base de développement compte 14 membres et 79 dégustations, presque aucune donnée de contexte), comportement sur les volumes de production.

## 9. Décisions à prendre

1. Quels blocs C supprimer (section 4) ?
2. Quels trous de collecte lancer en premier (section 6) ? Je recommande 1, 2 et 3.
3. Corriger le biais de période (section 7) maintenant ?
4. Valider l'usage commercial de l'âge et du genre avec ton conseil.

## 10. Décisions sur les blocs de classe C (20/10/2026)

| Bloc | Décision |
|---|---|
| Tendances · Nouvelles bières (KPI + courbe) | Gardé, en attendant `Beer.created_at` |
| Tendances · Lieux placés (KPI + courbe) | Supprimé |
| Tendances · Nouvelles brasseries / Nouveaux bars (2 KPI + 2 courbes) | Supprimés |
| Habitudes · Dégustations par mois de l'année | Supprimé |
| Géographie · KPI Lieux géocodés / Zones publiées / Lieux en zones masquées | Remplacés par une note « Couverture et anonymat » |
| Géographie · Contexte des lieux placés | Supprimé (avec `classify_spot` et son test) |
| Géographie · Zones les plus actives | Supprimé |
| Établissements · KPI Établissements géolocalisés | Supprimé |
| Bars · KPI Bars géolocalisés | Supprimé |
| Goûts · Répartition des notes | Supprimé |
| Trophées (page de 3 blocs) | Gardée, sortie de la barre de navigation des analytics ; entrée « Difficulté des trophées » sous Membres |

## 11. Collecte ajoutée le 20/10/2026

Points de la section 6 traités : 2 (vues des fiches), 3 (historique d'activité), 4 (remplissage du contexte), 5 (styles), 7 (demandes sans résultat), 9 (âge et genre), 12 (jeu de données de développement). Le point 1 (lier la dégustation à un bar) reste à faire.

| Point | Ce qui a été fait |
|---|---|
| Vues des fiches | Compteurs par fiche et par jour (vues et visiteurs distincts). Empreinte du visiteur non réversible sans la clé du site, propre à chaque fiche, supprimée le lendemain. Équipe et gérants exclus. Visible dans Professionnels, rapport brasserie et profil bar |
| Historique d'activité | Une ligne (membre, jour), écrite une fois par jour et par session. Donne DAU, WAU, MAU, stickiness, courbe des actifs avec prévision et rétention par visites (page Engagement) |
| Contexte des dégustations | Trophée « Chroniqueur » (lieu, format et prix) et rappel discret (un à la fois, au plus tous les 14 jours, dégustation de plus d'un jour, catégorie « Trophées ») |
| Styles | Table `Style` (nom, famille, alias) gérée dans l'administration ; tout enregistrement de bière est ramené au nom officiel, avec sa famille. 33 styles de départ, bières existantes migrées. Nouvelle dimension « Famille de style » |
| Demandes sans résultat | Compteurs par jour de termes cherchés sans résultat (bières, brasseries, bars), codes-barres inconnus, étiquettes non reconnues. Aucun lien avec un membre ; e-mails et suites de chiffres écartés. Page Catalogue |
| Âge et genre | Case « Compter mon âge et mon genre dans les statistiques anonymes » (cochée par défaut, dans Compte, Confidentialité). Les opposés sont exclus de tout calcul d'âge ou de genre. Mention ajoutée dans les deux pages d'inscription. Seuil d'anonymat réglable (`ANALYTICS_MIN_GROUP_SIZE`) |
| Jeu de développement | Le seeder remplit contexte, prix, âge, genre, opposants, visites, vues et demandes sans résultat |

### Durées de conservation (à indiquer dans la politique de confidentialité)

| Donnée | Durée |
|---|---|
| Jours d'activité | 800 jours (≈ 26 mois), supprimés avec le compte |
| Compteurs de vues | 800 jours, sans lien avec un membre |
| Empreintes de visiteurs | jusqu'au lendemain |
| Demandes sans résultat | 180 jours, sans lien avec un membre |

La purge se fait dans la tâche quotidienne existante (`/cron/purge-inactive-accounts/`).

### Âge et genre : cadre juridique

Je ne suis pas juriste : ce qui suit est une lecture des pages de la CNIL, à faire valider avant de vendre quoi que ce soit.

- La date de naissance et le genre sont des données personnelles ordinaires, pas des données sensibles (article 9). Aucune interdiction de principe de les exploiter.
- **Réutilisation pour une nouvelle finalité.** Les membres ont donné leur date de naissance pour vérifier leur majorité. Produire des statistiques est une finalité nouvelle. D'après la CNIL, une finalité statistique bénéficie d'une présomption de compatibilité (article 6.4 du RGPD), mais il faut quand même une base légale, informer les personnes, et la possibilité de s'opposer est citée comme garantie. D'où le choix de l'information et de l'opposition.
- **Base légale envisageable : l'intérêt légitime** (article 6.1.f), avec droit d'opposition. À documenter par une courte analyse de mise en balance (intérêt de Pokebeer, attentes raisonnables des membres, garanties). Le consentement est la voie la plus sûre mais réduirait fortement les volumes.
- **Sortie anonyme ?** La CNIL retient trois critères : individualisation, corrélation, inférence. Un agrégat de 3 personnes résiste mal à l'inférence (tout le groupe aime la même bière : on le sait de chacun). Tant que le résultat n'est pas démontrablement anonyme, il reste une donnée personnelle et sa transmission à un tiers est encadrée. Avant tout envoi hors de l'équipe : seuil à 10 (`ANALYTICS_MIN_GROUP_SIZE=10`), pas de croisement fin (âge × genre × style × ville), pas de petites cellules.
- **À faire de votre côté** : mettre à jour la politique de confidentialité (finalité, base légale, destinataires « brasseries et bars sous forme de statistiques anonymes », droit d'opposition dans Compte, Confidentialité, durées ci-dessus), mettre à jour le registre des traitements, puis publier l'annonce de modification dans l'administration (Annonces de politique) pour prévenir les membres.

Sources : [CNIL, anonymisation](https://www.cnil.fr/lanonymisation-de-donnees-personnelles), [CNIL, réutilisation des données](https://cnil.fr/fr/assurer-que-le-traitement-est-licite-reutilisation-des-donnees).

## 12. Analytics pour les gérants (20/10/2026)

Les gérants lisent les analytics de leurs établissements dans l'application (site et appli Android) à l'adresse `/pro/analytics/`. Rien n'ouvre l'administration à un non-staff : un gérant n'y a pas accès et ne voit donc aucun autre onglet.

| Rôle | Accès | Sections |
|---|---|---|
| Équipe (staff, super-utilisateur) | Tout, dans l'administration comme dans l'application | Pages complètes de l'administration |
| Gérant d'une brasserie | Uniquement les brasseries qu'il gère | Vue d'ensemble, Mes bières, Mes clients, Visibilité, Marché |
| Gérant d'un bar | Uniquement les bars qu'il gère | Vue d'ensemble, Ce qu'on boit, Clientèle, Visibilité, Marché |
| Autre membre | Aucun (la page l'explique) | |

- **Droit d'accès** : la relation « gérants » de l'établissement, pas le seul groupe Brasseur ou Bartender. Un établissement hors de portée répond 404, comme un établissement inexistant. Un seul endroit décide (`services/analytics/access.py`) : c'est là que se branchera un abonnement payant.
- **Ce que voit un gérant** : ses propres chiffres, et des moyennes anonymes de la communauté pour se comparer (note, prix, part de marché, styles qui montent). Jamais le nom ni le chiffre d'un autre établissement, jamais un membre. Les groupes de moins de 3 dégustateurs restent masqués.
- **Export CSV** de chaque bloc et ZIP de la section, limité à son établissement, neutralisé contre les formules de tableur.
- **Sécurité** : connexion obligatoire, lecture seule, période validée par liste blanche, limite de 120 consultations par heure et par membre, réponses jamais mises en cache.
- **Code** : un rapport est une suite de sections qui partagent un contexte (`services/analytics/reports.py`). Les pages de l'administration (Établissements, Bars) affichent toutes les sections à la suite, la page des gérants une seule : aucun calcul n'est écrit deux fois. Le rendu des graphiques est partagé (`static/script/analytics_charts.js`).
- **Entrées dans l'application** : fiche de la brasserie ou du bar (menu du gérant), et le profil (« Statistiques de mes établissements »).
