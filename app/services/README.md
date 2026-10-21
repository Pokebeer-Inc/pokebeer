# Services

La logique métier du site, rangée par domaine ; chacun des modules a son objectif décrit en tête de fichier.

Sens des dépendances : `app/domain/` (règles pures : slugs, clés de comparaison des noms, adresses, styles, avatars, chemins d'upload,
registre des types de notifications) <- `app/models/` <- `app/services/` <- `app/views/`. Les vues valident les formulaires et répondent ;
enregistrements, notifications et trophées qui en découlent sont décidés ici. Les signaux qui appellent un service sont déclarés par le
service lui-même (`connect_signals()`, voir `app/apps.py`). Toute page exige d'être connecté sauf celles marquées `@login_not_required`.

## `members/` — Membres : comptes, rôles, relations, confidentialité, trophées

| Module | Rôle |
|---|---|
| `achievements.py` | Trophées des membres : calcul des paliers et notifications de progression. |
| `account.py` | Profil du membre connecté : enregistrement et ce qui en découle (avis de sécurité, trophées). |
| `blocks.py` | Blocages entre membres : invitation à signaler quand un même membre est bloqué par plusieurs personnes. |
| `follows.py` | Abonnés et abonnements d'un membre : comptés en base, affichés par pages (une fenêtre de profil ne charge pas des milliers de lignes). |
| `identity.py` | Confirmation d'identité (mot de passe, ou pseudo pour un compte Google) avant une action sensible, et avis de sécurité. |
| `inactivity.py` | RGPD : suppression des comptes inactifs. |
| `inactivity_mail.py` | E-mails liés à la suppression des comptes inactifs (adresse d'envoi : celle du service, comme la réinitialisation du mot de passe). |
| `password_reset.py` | Réinitialisation du mot de passe par e-mail. |
| `profile_pictures.py` | Photos de profil : validation stricte puis ré-encodage, stockage dans un bucket dédié. |
| `profile_stats.py` | Statistiques du profil (moyennes, style préféré, bières du Top 3) calculées par la base. |
| `roles.py` | Rôles utilisateur : groupes Django cumulatifs (Contributeur toujours conservé) + drapeau superuser pour Admin. |
| `social.py` | Abonnements et blocages entre membres (règles, notifications). |
| `visibility.py` | Qui peut voir quoi : blocages entre membres et comptes suspendus, appliqués à une requête par sous-requête SQL (aucun identifiant chargé en mémoire). |
| `welcome.py` | E-mail de bienvenue envoyé à la création d'un compte (formulaire, établissement pro ou connexion Google). |

## `support/` — Échanges avec l'équipe (fils de messages, signalements)

| Module | Rôle |
|---|---|
| `feedback.py` | Échanges avec l'équipe : un fil par sujet (Feedback) contenant le premier message du membre puis les messages suivants. |
| `threads.py` | Éléments d'affichage communs aux pages de type « échange » : messages d'un fil avec l'équipe, signalement et sa décision. |

## `catalog/` — Catalogue : bières, dégustations, recherche, recommandations, ajout en plusieurs étapes, IA de lecture d'étiquette

| Module | Rôle |
|---|---|
| `beer_drafts.py` | Ajout d'une bière en plusieurs étapes : étapes, brouillon enregistré en base et validation étape par étape. |
| `beer_fields.py` | Champs d'une bière reçus d'une source extérieure (IA, base de produits) : réduits aux champs connus, convertis et bornés. |
| `beers.py` | Cycle de vie d'une bière : ajout avec la première dégustation, modification, retrait (notifications, trophées). |
| `context_reminders.py` | Rappel discret aux membres dont une dégustation récente n'a ni lieu, ni format, ni prix. |
| `catalog_matching.py` | Détection des doublons du catalogue : une seule règle, partagée par le formulaire d'ajout, la vérification en direct (API) et |
| `drinks.py` | Dégustations : notation d'une bière, modification, suppression (règle partagée avec la modération). |
| `ean.py` | Codes-barres EAN : validation (longueur et clé de contrôle) et forme normalisée. |
| `embeddings.py` | Vecteur de recherche sémantique des bières (chat IA) : recalculé quand le texte qui le décrit change. |
| `label_scan.py` | Analyse d'une étiquette de bière : consigne envoyée à l'IA et validation stricte de sa réponse. |
| `notebooks.py` | Carnets personnalisés : création (plafonnée), modification, dégustations qu'ils contiennent. |
| `official_images.py` | Images officielles (bières, brasseries, bars) : mêmes garanties que les photos de dégustation (voir images.reencode_as_webp). |
| `permissions.py` | Droits sur une bière : qui peut la modifier ou la retirer, qui voit une bière retirée. |
| `product_lookup.py` | Recherche d'une bière par son code-barres dans Open Food Facts (base de produits collaborative, accès libre). |
| `reactions.py` | Pouces sur les avis et liste « À goûter ». |
| `recommendations.py` | Recommandations de bières de l'accueil, d'après ce que le membre a aimé. |
| `search.py` | Recherche unique : bières, brasseries, bars et membres. |
| `selectors.py` | Requêtes de l'application : bières, membres, brasseries, bars, carnet, fil d'activité, liste « À goûter ». |
| `style_registry.py` | Référentiel des styles (table `Style`) : noms officiels, alias, famille de chaque bière ; branché sur l'enregistrement d'une bière. |
| `styles.py` | Styles du catalogue pour les filtres, en cache vidé à chaque changement de bière. |
| `tasting_photos.py` | Photos de dégustation : validation stricte puis ré-encodage, stockées dans media/tastings/ (Supabase en production). |

## `establishments/` — Brasseries et bars : adresse, géolocalisation, annuaire, revendication, certification, lieux de la carte

| Module | Rôle |
|---|---|
| `claims.py` | Revendication d'un établissement : qui peut gérer une brasserie ou un bar, et comment on s'en assure. |
| `nominatim.py` | Nominatim (OpenStreetMap) : le seul endroit qui l'interroge, pour la recherche d'une adresse et pour le géocodage inverse. |
| `place_directory.py` | Annuaire des bars et brasseries localisés, pour classer les lieux par distance « Près de moi ». |
| `place_filters.py` | Filtres et tri des brasseries et des bars : ville, vérifiés, style de bière brassé ; tri par nom ou par date d'ajout. |
| `place_geocoding.py` | Coordonnées des brasseries et des bars : calculées à partir de leur adresse (Nominatim) quand elle change. |
| `places.py` | Ce qui distingue une brasserie d'un bar ; tout le reste (édition, équipe, carte admin) est partagé. |
| `places_map.py` | Données de la carte admin : toutes les brasseries et tous les bars géolocalisés, sous une forme unique. |
| `removal.py` | Suppression d'une brasserie qui a des bières : transfert vers une autre, ou suppression explicite. |
| `postal_codes.py` | Code postal -> commune(s), pour que la ville d'un établissement vienne du code postal et non d'une saisie libre. |
| `reverse_geocoding.py` | Géocodage inverse des lieux (OpenStreetMap/Nominatim) avec cache : type de lieu, ville, région, urbain ou rural. |
| `siret_registry.py` | Contrôle d'un SIRET dans l'annuaire officiel des entreprises (recherche-entreprises.api.gouv.fr, sans clé). |
| `spots.py` | Lieux posés sur la carte par les membres : création, modification, qui est invité et qui est prévenu. |
| `team.py` | Équipe d'un établissement : gérants, invitations (le rôle n'est donné qu'à l'acceptation), retraits. |
| `verification.py` | Certification (coche « vérifié ») d'un bar, d'une brasserie ou d'une bière : règle unique partagée par l'admin. |

## `messaging/` — Notifications (liste, push, temps réel) et e-mails (transactionnels, promotionnels, campagnes)

| Module | Rôle |
|---|---|
| `app_links.py` | Liens du site et de l'application Android, tels qu'ils apparaissent dans les e-mails. |
| `campaigns.py` | Campagnes e-mail rédigées dans l'administration : audience, lancement, envoi par lots. |
| `mailer.py` | Envoi des e-mails transactionnels : un gabarit texte et un gabarit HTML par message (templates/emails/). |
| `marketing.py` | Choix des e-mails promotionnels et liens signés pour le gérer sans se connecter. |
| `notification_policy.py` | Qui a le droit de recevoir quoi : appliqué à toute notification créée, quel que soit l'appelant. |
| `notification_presenter.py` | Représentation d'une notification pour le navigateur et les appareils : une seule construction, utilisée par l'API |
| `notifications.py` | Point d'entrée unique pour créer et envoyer des notifications ; la politique d'envoi s'applique ici. |
| `policy_notice.py` | Annonce d'une modification de la politique de confidentialité. |
| `realtime_service.py` | Diffusion des notifications : temps réel (Supabase) et push Android (Firebase), plafond de 3 alertes par jour et par membre. |
| `security.py` | Nom du canal temps réel privé d'un membre (dérivé de la SECRET_KEY et du mot de passe). |

## `assistant/` — Gaétan, l'assistant IA : appels à Mistral, dialogue avec outils (dossier chat/)

| Module | Rôle |
|---|---|
| `ai.py` | Point d'entrée de Gaétan : réponse du chat (avec les bières les plus proches), lecture d'étiquette, vecteur d'un texte. |
| `llm.py` | Accès à Mistral AI (hébergé dans l'Union européenne) : client, budget d'appels par minute et embeddings. |
| `chat/engine.py` | Dialogue avec Mistral : appel du modèle, exécution des outils demandés, réponse finale. |
| `chat/geo.py` | Position du membre : validée, arrondie (~1 km) et jamais enregistrée. Calculs de distance pour classer les lieux. |
| `chat/geocoding.py` | Du nom d'un lieu (« Dublin », « Lille centre ») à ses coordonnées, via Nominatim (OpenStreetMap, gratuit). |
| `chat/payload.py` | Lecture et validation de la requête du chat (JSON du navigateur) : un seul endroit, un seul type d'erreur. |
| `chat/places.py` | Bars et brasseries proches d'une position, depuis des sources gratuites : la base Pokebeer, puis OpenStreetMap. |
| `chat/prompt.py` | Consignes de Gaétan. Seul ce texte fait foi : tout le reste (message, catalogue, résultats d'outils) est une donnée. |
| `chat/sanitize.py` | Tout texte qui entre dans le modèle ou en sort passe ici. |
| `chat/tools.py` | Ce que le modèle a le droit d'appeler. Un outil = une déclaration pour le modèle + une exécution côté serveur. |

## `protection/` — Protection et limites : CSP, limitation de débit, quotas, temps de réponse constant

| Module | Rôle |
|---|---|
| `csp.py` | Politique de sécurité du contenu (CSP) : seules les origines utilisées par le site sont autorisées. |
| `quota.py` | Quotas quotidiens et hebdomadaires par membre pour les services à coût (chat, étiquette, code-barres, photo). |
| `throttle.py` | Limitation de débit des actions sensibles (connexion, inscription), partagée entre toutes les instances. |
| `timing.py` | Temps de réponse constant pour les actions qui ne doivent pas révéler l'existence d'un compte. |

## `common/` — Briques partagées : contrôle des images, appels aux API extérieures

| Module | Rôle |
|---|---|
| `images.py` | Contrôle commun des images envoyées par les membres : taille, format réel (jamais le type déclaré) et dimensions. |
| `upstream.py` | Appel d'une API publique extérieure (Open Food Facts, annuaire des entreprises, communes) : un seul chemin, prudent. |

## `analytics/` — Statistiques de l'administration (pages prédéfinies et tuiles personnalisées)

| Module | Rôle |
|---|---|
| `access.py` | Qui peut lire les analytics d'un établissement (équipe : tout ; gérant : ses établissements) et registre des rapports. |
| `audience.py` | Audience : âge et genre des dégustateurs (tranches agrégées, anonymes) et ce que chaque segment aime. |
| `bar_report.py` | Rapport d'un bar en cinq sections (vue d'ensemble, ce qu'on boit, clientèle, visibilité, marché), pour l'équipe et pour son gérant. |
| `bars.py` | Bars : vue d'ensemble de l'activité autour de chaque bar ; le détail d'un bar est son rapport. |
| `blocks.py` | Blocs d'affichage indépendants du rendu : chaque page d'analytics renvoie une liste de blocs. |
| `page_views.py` | Vues des fiches pour les analytics : totaux, courbes et classements, visiteurs masqués sous le seuil d'anonymat. |
| `brewery_report.py` | Rapport d'une brasserie en cinq sections (vue d'ensemble, bières, clients, visibilité, marché), comparé à la communauté. |
| `catalogue.py` | Catalogue : offre et demande par style, force et amertume ; qualité des fiches bière. |
| `consumption.py` | Consommation : lieu, compagnie, format, prix et moment des dégustations. |
| `date.py` | Filtres par date calendaire. |
| `engagement.py` | Engagement : activation des nouveaux membres, notifications, services IA, réseau social, richesse des avis. |
| `export.py` | Export CSV des blocs d'une page d'analytics, avec les filtres courants. |
| `forecasts.py` | Prévisions : tendance avec fourchette à 80 %, styles en hausse, indice saisonnier, avec la fiabilité de chacune. |
| `geo.py` | Géométrie : distances et regroupement en cases. Pas de géocodage inverse (aucun appel réseau). |
| `geography.py` | Géographie : où les membres placent leurs lieux, et dans quel contexte (près d'un bar, d'une brasserie, ailleurs). |
| `habits.py` | Habitudes : quand et comment les membres utilisent Pokebeer (rythme, régularité, fidélisation, adoption). |
| `health.py` | Communauté : signalements, modération, échanges avec l'équipe, campagnes e-mail et départs (pilotage interne). |
| `layout.py` | Disposition personnelle des tuiles (ordre, masquage) : stockée en base, par membre et par page. |
| `periods.py` | Fenêtre temporelle des analyses : valeurs validées contre une liste blanche (jamais de saisie libre). |
| `places.py` | Établissements et aide à la décision : classement, et pistes de mise en avant pour une brasserie donnée. |
| `profiles.py` | Profil d'un ensemble de dégustations (âge, genre, lieu, compagnie, format, prix) : brique commune aux pages, aux brasseries et aux bars. |
| `privacy.py` | Anonymat : on n'affiche jamais un groupe assez petit pour identifier un membre (k-anonymat). |
| `pros.py` | Professionnels : revendications, couverture et complétude des fiches, prospects à démarcher. |
| `reports.py` | Base des rapports d'établissement : sections qui partagent un contexte de calcul, lisibles une à une (gérant) ou toutes (équipe). |
| `registry.py` | Catalogue des pages d'analytics : ajouter une page = ajouter une entrée (ouvert/fermé). |
| `series.py` | Séries temporelles : agrégation alignée sur la période, moyenne mobile, tendance et prévision indicative. |
| `spots.py` | Lieux des membres enrichis du géocodage inverse mis en cache (quand il existe) : base commune à la géographie, |
| `tastes.py` | Goûts : ce que les membres boivent et apprécient (styles, force, amertume, notes, demande non satisfaite). |
| `trends.py` | Tendances : évolution de l'activité dans le temps, avec moyenne mobile et prévision indicative. |
| `trophies.py` | Trophées : difficulté réelle de chaque trophée d'après la progression des membres. |
| `custom/catalog.py` | Catalogue fermé des données interrogeables : jeux de données, dimensions (regrouper par) et mesures (calculer). |
| `custom/engine.py` | Exécution d'une tuile personnalisée : même sortie (blocs Kpi/Chart/Table) que les pages prédéfinies. |
| `custom/forms.py` | Formulaires de création/édition d'une vue et d'une tuile : la validation métier est celle de `spec.validate`. |
| `custom/service.py` | Vues et tuiles personnalisées : création, modification, suppression, quotas. La propriété est vérifiée par l'appelant |
| `custom/spec.py` | Définition d'une tuile personnalisée et sa validation : seule porte d'entrée des données saisies par l'utilisateur. |

## `tracking/` — Mesures d'usage minimales : vues des fiches, jours d'activité, demandes sans résultat, purge

| Module | Rôle |
|---|---|
| `__init__.py` | `safely` : une mesure en échec ne casse jamais la page qui la déclenche. |
| `counters.py` | Compteur journalier incrémenté sans verrou (UPDATE, sinon INSERT). |
| `page_views.py` | Vues et visiteurs distincts par fiche et par jour ; empreinte HMAC supprimée le lendemain ; équipe et gérants exclus. |
| `activity.py` | Un jour d'activité par membre et par jour, retenu dans la session (une écriture par jour). |
| `misses.py` | Recherches sans résultat, codes-barres inconnus, étiquettes non reconnues, sans lien avec un membre. |
| `retention.py` | Durée de conservation de chaque mesure et purge quotidienne (tâche planifiée). |

## `moderation/` — Modération des contenus : file de validation, suggestions, suppression

| Module | Rôle |
|---|---|
| `actions.py` | Actions du staff sur une entrée : valider (« vu ») ou retirer le contenu et prévenir son auteur. |
| `capture.py` | Capture des créations/modifications de contenus publics via signaux ; ne bloque jamais l'enregistrement. |
| `content.py` | Types de contenus modérés. Ajouter un type = ajouter une classe et l'enregistrer dans CONTENT_TYPES (ouvert/fermé). |
| `editing.py` | Formulaire d'édition des champs publics d'une fiche (bière, brasserie, bar), partagé par les suggestions des membres et par les retouches |
| `suggestions.py` | Suggestions de modification : un membre sans droit d'édition propose de nouvelles valeurs, l'équipe les accepte (en les ajustant au |

