# Radar — Roadmap

> Statut : jalons 0 à 7 terminés, prochain jalon : scoring explicable
>
> Dernière mise à jour : 1er octobre 2026
>
> Horizon : MVP privé pour un utilisateur en France métropolitaine

## 1. Objet

Cette roadmap ordonne la réalisation de Radar en petites fonctionnalités
utilisables et vérifiables. Elle ne fixe pas de dates artificielles : les
jalons sont franchis dans l'ordre de leurs dépendances et de la réduction des
risques.

Le périmètre fonctionnel est défini dans `docs/product.md`. En cas d'écart,
ce document n'élargit pas implicitement le MVP.

## 2. Principes de réalisation

- Livrer une tranche verticale à la fois, avec comportement observable et
  tests associés.
- Valider tôt les hypothèses risquées sur les fournisseurs externes.
- Ne pas commencer par une plateforme technique générique.
- Garder un monolithe modulaire et une seule base PostgreSQL/PostGIS.
- Ne pas ajouter de broker, de microservice ou d'orchestrateur distribué au
  MVP.
- Construire les recherches sur les données locales ; elles ne doivent jamais
  appeler un fournisseur.
- Conserver la provenance et les corrections utilisateur dès le premier
  import, et non dans une phase de rattrapage.
- Rendre les échecs et les données inconnues visibles.
- Ne pas déclarer une fonctionnalité terminée tant que ses tests, sa
  documentation et son chemin d'erreur essentiel ne sont pas couverts.

## 3. Conditions préalables

Les prérequis de la validation réelle du jalon 1 ont été réunis localement :

- une clé publique pour l'API Sirene 3.11 ;
- une clé pour l'API DATAtourisme v1 ;
- un accès au millésime courant des contours administratifs ;
- un accès au fichier mensuel de géolocalisation Sirene conservé par la
  stratégie hybride.

Les clés sont configurées localement et ne sont jamais ajoutées au dépôt. Elles
resteront également nécessaires dans les environnements qui exécutent les
connecteurs, sous une forme secrète adaptée.

Le jalon 3 a arrêté le frontend après son prototype minimal : TypeScript,
React et Vite, avec un build statique servi sous la même origine que l'API.
Radar étant privé et sans besoin de référencement, Next.js et un processus
Node de production ne sont pas retenus.

## 4. Jalons du MVP

### Jalon 0 — Cadrage documentaire

**État : terminé.**

**But :** disposer de décisions cohérentes avant de créer l'application.

Travaux :

- valider `docs/product.md` ;
- définir les sources et leur protocole de contrôle ;
- définir les règles initiales de scoring ;
- définir l'architecture et le modèle de données ;
- vérifier la cohérence entre tous les documents ;
- consigner les décisions encore réversibles.

Critère de sortie : les invariants du produit, les responsabilités des
modules, les données persistées et les risques fournisseurs sont suffisamment
précis pour commencer une première tranche sans inventer une architecture en
cours de route.

### Jalon 1 — Validation des contrats externes

**État : terminé le 6 septembre 2026.**

**But :** éliminer les principales incertitudes avant de bâtir les imports.

Travaux :

- géocoder et vérifier la mairie de Dax ;
- sélectionner les communes qui intersectent le cercle de 50 km et sa marge
  de présélection ;
- tester la requête Sirene garantissant l'état courant ;
- vérifier les statuts administratifs et de diffusion ;
- parcourir un curseur Sirene jusqu'à son terme et contrôler les totaux ;
- comparer les coordonnées de l'API Sirene 3.11 au fichier mensuel officiel ;
- décider si ce fichier reste nécessaire au MVP ;
- tester l'endpoint événementiel DATAtourisme, ses champs, ses occurrences et
  sa pagination `next` ;
- répéter une collecte afin de vérifier la stabilité à court terme des
  identifiants ;
- examiner les événements récurrents et multiannuels afin de fixer l'identité
  source du MVP sans inventer un discriminant fragile.

Livrable : `docs/source-validation-dax-2026-09.md`, compte rendu daté selon le
protocole de `docs/data-sources.md`, sans secret ni donnée personnelle inutile.

Critère de sortie : les deux contrats d'entrée peuvent être reproduits, leurs
limites sont connues et la stratégie de géolocalisation Sirene est arrêtée.

Résultat : critère atteint. La validation a confirmé le curseur Sirene au-delà
de 10 000 résultats et des lots de 30 codes au maximum, maintenu le fichier
mensuel comme repli de l'API pour 30 402 positions, parcouru les 12 pages
DATAtourisme, retenu `(DATAtourisme, UUID)` comme identité source du MVP et
confirmé qu'une recherche ciblée retrouve un objet en diffusion partielle sans
le confondre avec une fermeture. La politique de purge correspondante a ensuite
été close et implémentée au seizième incrément du jalon 6.

### Jalon 2 — Socle applicatif minimal

**État : terminé le 8 septembre 2026.**

**But :** rendre le projet exécutable et testable sans fonctionnalité métier
superflue.

Travaux :

- structure du monolithe modulaire ;
- configuration typée et séparation des secrets ;
- connexion PostgreSQL/PostGIS ;
- première migration Alembic ;
- endpoint de santé ne révélant aucune information sensible ;
- formatage, lint, vérification de types et tests automatisés ;
- environnement local reproductible limité aux composants nécessaires.

Critère de sortie : une installation neuve peut lancer l'application et sa
base, appliquer les migrations et exécuter tous les contrôles qualité.

### Jalon 3 — Accès privé

**État : terminé le 11 septembre 2026.**

**But :** protéger l'application avant d'y introduire des données métier.

Travaux :

- création administrative du compte unique ;
- connexion et déconnexion ;
- session sécurisée et expirante ;
- protection de toutes les routes métier ;
- limitation des tentatives de connexion ;
- changement du mot de passe avec saisie du mot de passe courant ;
- invalidation des autres sessions ;
- procédure administrative de remplacement d'un mot de passe oublié ;
- écrans minimaux de connexion, déconnexion et changement de mot de passe.

Critère de sortie : les critères d'authentification de `docs/product.md` sont
testés, notamment l'absence d'accès anonyme et l'invalidation des sessions.

### Jalon 4 — Adresse de référence et recherche géographique locale

**État : terminé le 19 septembre 2026.**

**But :** établir le centre commun aux futures collectes et recherches.

Travaux :

- saisir une adresse située en France métropolitaine ;
- appeler le géocodeur de la Géoplateforme ;
- afficher le résultat et demander sa confirmation ;
- conserver la position, sa provenance et le rayon de collecte ;
- changer l'adresse sans supprimer les données existantes ;
- calculer et filtrer à vol d'oiseau sur quelques fiches de test locales ;
- distinguer rayon de collecte, rayon de recherche et couverture connue.

Critère de sortie : un rayon de recherche peut changer sans appel externe et
un dépassement de couverture produit l'avertissement prévu.

Résultat : le géocodeur officiel de la Géoplateforme est isolé derrière un
adaptateur et ne propose que des résultats d'adresse situés en France
métropolitaine. Le résultat est conservé comme candidat inactif, présenté avec
son libellé, ses coordonnées, son score et sa provenance, puis devient la
position courante uniquement après confirmation explicite. Les anciennes
positions restent historiques. Les rayons de collecte et de recherche sont
modifiables séparément de 1 mètre à 50 kilomètres sans appel externe ni
création de collecte. En l'absence de cycle réussi, l'interface indique
explicitement qu'aucune couverture Sirene ou DATAtourisme n'est encore
établie. La migration et les requêtes `ST_DWithin`/`ST_Distance` ont été
validées sur PostgreSQL/PostGIS avec des points locaux autour de Dax.

### Jalon 5 — Exécution durable des collectes

**État : terminé le 20 septembre 2026.**

**But :** disposer d'un mécanisme commun avant d'ajouter les fournisseurs.

Travaux :

- créer et suivre un cycle de collecte ;
- empêcher deux cycles identiques simultanés ;
- enregistrer étapes, compteurs, erreurs et dernier succès ;
- exécuter une tâche longue hors de la requête HTTP sans broker externe ;
- reprendre uniquement depuis un point sûr ;
- distinguer réussite, échec et réussite partielle ;
- afficher l'état d'une collecte manuelle.

Critère de sortie : une tâche factice contrôlée peut réussir, échouer puis être
relancée sans être présentée à tort comme une couverture complète.

Résultat : la file PostgreSQL conserve séparément le travail, son cycle et
chaque tentative. Les réservations utilisent un bail et `FOR UPDATE SKIP
LOCKED` ; un bail expiré conserve la tentative abandonnée et reprend depuis le
dernier point explicitement sûr. Une empreinte et un index partiel empêchent
deux demandes identiques actives, tandis que le centre et le rayon restent
figés dans chaque cycle. L'API privée et l'interface affichent l'étape, les
tentatives, l'erreur, le dernier succès et la couverture. Les scénarios
contrôlés sur PostgreSQL/PostGIS couvrent réussite, résultat partiel, erreur,
reprise différée, relance et récupération après crash. Seul un résultat
entièrement réussi crée une couverture ; les résultats partiels et échoués ne
la font jamais avancer. Le processus worker est séparé du serveur HTTP et les
adaptateurs restent injectables. Les boutons des connecteurs demeurent
désactivés tant que leurs implémentations réelles ne sont pas enregistrées aux
jalons 6 et 7, afin de ne pas créer de travaux impossibles à exécuter.

### Jalon 6 — Prospects Sirene de bout en bout

**État : terminé le 28 septembre 2026.**

**But :** livrer la première boucle métier réellement utilisable.

Travaux :

- charger le référentiel de communes retenu ;
- énumérer les communes candidates avec la marge de 1 km et les répartir en
  lots disjoints de 30 codes au maximum ;
- intégrer l'adaptateur Sirene avec quota, pages de 1 000 et curseur ;
- contrôler l'état courant, la diffusion et les totaux ;
- appliquer le traitement conforme lorsqu'un établissement ou son unité
  légale passe en diffusion partielle ;
- conserver séparément les coordonnées API et fichier, appliquer la règle
  communale versionnée, retenir l'API en priorité sans transfert de qualité,
  puis le fichier en repli et la Géoplateforme ;
- calculer leur distance exacte ;
- importer les observations avec provenance ;
- conserver les positions indéterminées dans « Localisation à vérifier » ;
- contrôler explicitement les SIRET connus absents d'un cycle réussi ;
- rendre une seconde collecte idempotente.

Interface minimale :

- liste des prospects ;
- fiche détaillée ;
- recherche par nom ou commune ;
- filtres distance, type, activité, effectif et moyens de contact ;
- tris par nom et distance ;
- état et fraîcheur de la collecte.

Critère de sortie : le connecteur satisfait ses critères de complétude autour
de Dax et une relance met à jour les mêmes SIRET sans créer de doublons.

Avancement : le premier incrément isole l'API Sirene 3.11 derrière un
adaptateur de lecture typé. Il construit le filtre courant validé, refuse les
lots de plus de 30 communes ou non disjoints, suit le curseur opaque jusqu'à
la page terminale vide et réconcilie le total annoncé, le nombre reçu et les
SIRET uniques. Les appels sont espacés pour respecter 30 requêtes par minute ;
les erreurs temporaires ont quatre tentatives HTTP bornées et les délais longs
restent destinés à la reprise durable du worker. La clé est envoyée uniquement
dans l'en-tête prévu. Les réponses sont limitées aux champs utiles, les noms
personnels d'entrepreneurs individuels ne sont pas demandés, et les statuts
courants sont revérifiés avant de produire un candidat. Les pages ne publient
qu'une empreinte du curseur suivant et une reprise après interruption devra
recommencer le lot depuis son début. Les fixtures couvrent page terminale,
comptages, doublons, boucle de curseur, fermeture concurrente, quotas, contrat
et métadonnées de fraîcheur. Un appel réel borné à une ligne a confirmé le
20 septembre 2026 que la liste explicite de champs reste acceptée et conforme
au schéma attendu, sans conserver la donnée reçue.

Le deuxième incrément charge le GeoJSON officiel de contours dans des versions
immuables `dataset_release` et `commune_boundary`. La commande d'administration
contrôle taille, SHA-256, contrat GeoJSON, unicité des codes et périmètre
métropolitain, puis PostGIS valide les contours dans une table temporaire avant
un basculement atomique. Les topologies sources invalides sont réparées et
comptabilisées ; un résultat vide ou invalide annule le chargement. Deux index
GiST permettent la sélection géodésique par `ST_DWithin` avec la marge fixe de
1 km. Le vrai fichier 2026 a chargé 34 791 communes, réparé 16 contours hors de
la zone de Dax et reproduit les 418 communes candidates attendues. Les tests
couvrent aussi l'idempotence, le remplacement de version et l'échec sans perte
de la version active.

Le troisième incrément fige, avant tout appel fournisseur, le millésime de
contours, les communes candidates et leur affectation à des lots disjoints de
30 codes maximum. Les tables `collection_source_run`, `collection_batch`,
`collection_page`, `collection_cycle_commune` et
`collection_reference_usage` séparent l'exécution, les preuves de pagination
et les référentiels employés. Le planificateur exige une réservation worker
active et est idempotent : après un crash ou l'activation d'un nouveau
référentiel, le cycle reprend ses mêmes communes et identifiants de lots. Un
scénario PostGIS avec 65 communes vérifie les lots `30 + 30 + 5`, l'absence de
recouvrement et la conservation de l'ancien millésime après remplacement.

Le quatrième incrément exécute ce plan dans le worker et conserve une preuve
non sensible après chaque page effectivement traitée. Une page n'est marquée
`PROCESSED` qu'après le retour du gestionnaire de candidats ; une interruption
entre les deux impose donc la relecture idempotente du lot au lieu de produire
un faux succès. Le curseur Sirene brut n'est jamais persisté, seulement son
empreinte, et chaque nouvelle tentative recommence le lot au curseur initial.
La page terminale vide, les totaux annoncés, reçus et uniques sont réconciliés
avant de valider le lot, puis tous les lots doivent réussir avant de valider la
source. Les métadonnées de service, compteurs, erreurs et historiques de pages
restent attachés au cycle. Deux scénarios PostgreSQL/PostGIS couvrent le chemin
nominal idempotent et une indisponibilité temporaire après la première page,
suivie d'une reprise complète qui publie finalement la couverture.

Le cinquième incrément ajoute la préparation idempotente des candidats avant
la création des fiches. Les tables `data_source`, `external_identity`,
`source_observation` et `collection_item` conservent respectivement la source
technique, l'identité SIRET, la révision normalisée et chaque occurrence par
tentative. Une relecture de lot réutilise l'identité et l'observation lorsque
leur contenu est inchangé, mais garde une occurrence distincte ; celle-ci est
rattachée à la preuve de page seulement après le succès du traitement. Les
pages de 1 000 candidats sont écrites avec des opérations SQL groupées. Dans
la même transaction, PostGIS transforme les coordonnées API Lambert-93,
contrôle leur cohérence avec la commune et sa marge versionnée, calcule la
distance au centre puis classe les positions utilisables dans ou hors du rayon.
Une coordonnée absente ou incohérente reste `LOCATION_UNKNOWN` pour le repli
géographique suivant. Un scénario de reprise confirme qu'une même révision
n'est pas dupliquée et qu'aucune fiche n'est créée avant cette résolution.

Le sixième incrément arrête le lecteur du fichier mensuel sur DuckDB embarqué,
sans ajouter de serveur ni de stockage métier. Il vérifie le fichier local, sa
taille, le SHA-1 publié et son SHA-256 calculé, ainsi que les neuf colonnes et
types documentés par l'Insee. Il place seulement les SIRET du cycle dans une
table temporaire, rejette une correspondance dupliquée et transmet les lignes
trouvées par lots bornés. Une absence reste normale pour un établissement plus
récent que le millésime du fichier. Des Parquet synthétiques couvrent la
sélection, les absences, le découpage, la dérive de schéma, les doublons et les
preuves de fichier sans télécharger le livrable de 810 Mo dans les tests.

Le septième incrément persiste chaque proposition géographique dans
`candidate_position`, séparément de l'occurrence et de l'observation brute. La
position API reste `UNKNOWN/USABLE` sans qualité empruntée au fichier. Le
fichier possède sa propre `data_source`, son `dataset_release`, son exécution et
ses compteurs ; un nouveau millésime ne devient `ACTIVE` qu'après rapprochement
des totaux demandés, trouvés et absents. PostGIS contrôle indépendamment le
point, le code commune et la marge figée. Les qualités `11`, `12`, `21` et `22`
peuvent produire un classement exact, tandis que `33` reste `TO_VERIFY`, sans
distance décisionnelle. Le scénario de reprise API importe ensuite trois
positions fichier, répète l'import sans duplication et vérifie la priorité API,
le repli fichier et le cas à géocoder.

Le huitième incrément applique la priorité versionnée aux seules occurrences
de la tentative API réussie : position API utilisable, puis position fichier
utilisable, sinon `POSITION_GEOCODING_REQUIRED`. Le classement et la distance
retenus sont reportés sur `collection_item` sans modifier les candidats ni
transférer leur qualité. Le diagnostic conserve la source et l'identifiant de
la position choisie, ainsi que l'écart lorsqu'API et fichier sont tous deux
valides mais distants de plus d'un kilomètre. L'opération exige les deux
sources réconciliées, rapproche tous ses compteurs et peut être répétée sans
créer de donnée supplémentaire.

Le neuvième incrément ajoute le géocodage de repli derrière l'adaptateur
Géoplateforme existant. Il ne sélectionne que les occurrences encore marquées
`POSITION_GEOCODING_REQUIRED`, limite l'exécution à une requête simultanée et
20 requêtes par seconde, puis persiste chaque réponse avant de poursuivre. Un
résultat `housenumber` ou `street` n'est utilisable que si son code commune est
celui attendu et si PostGIS le situe dans le contour communal ou sa marge
figée. Le score fournisseur est conservé, mais aucun seuil arbitraire n'est
inventé. Les absences et résultats insuffisants deviennent des preuves
explicites ; après réconciliation complète de la source, une seconde passe de
résolution retient le résultat utilisable ou marque `POSITION_UNRESOLVED`. Le
scénario PostgreSQL/PostGIS couvre le succès, l'adresse introuvable, la reprise
idempotente et l'absence d'appel réseau dans les tests.

Le dixième incrément matérialise les résultats définitifs, page fournisseur par
page fournisseur, sans transaction couvrant tout le cycle. Un candidat dans le
rayon ou encore sans position crée ou actualise un `organization`, un
`establishment` et une fiche `prospect` stable ; un candidat hors du rayon exact
reçoit seulement `COUNTED_ONLY`. Le SIRET rattache les collectes suivantes au
même établissement et le lien source reste distinct de la fiche. La projection
conserve aussi la présence du cycle, la filiation des champs et une
`location_assertion` source versionnée. Le nom initial suit une priorité
explicite entre enseigne locale, dénomination usuelle et dénomination légale ;
le type d'organisme demeure `UNKNOWN` tant qu'aucun mapping validé n'existe. Un
scénario PostgreSQL/PostGIS crée quatre prospects dont un à localisation
inconnue, comptabilise un cinquième établissement hors rayon et vérifie qu'une
répétition ne crée aucun doublon.

Le onzième incrément fournit la première lecture authentifiée du catalogue
local. `GET /api/v1/prospects` applique dans PostgreSQL la recherche par nom,
raison sociale, SIRET, commune ou code postal, les filtres de type, activité et
effectif, les tris par distance ou nom et une pagination bornée. Le rayon
configuré est utilisé par défaut et peut être remplacé ponctuellement jusqu'à
50 kilomètres ; `ST_DWithin` et `ST_Distance` repartent toujours de la position
de référence courante. Un mode séparé expose les localisations à vérifier sans
leur inventer de distance. `GET /api/v1/prospects/{id}` restitue l'identité du
site, l'adresse, la qualité géographique et la provenance courante. Les routes
sont privées, ne contactent aucun fournisseur et excluent des listes ordinaires
les fiches masquées, fermées, cessées ou non prospectables. Les scénarios API
et PostgreSQL/PostGIS couvrent les bornes, filtres, tris, rayons, états de
localisation et sources.

Le douzième incrément rend ces lectures utilisables dans l'interface React sans
ajouter de routeur ni de dépendance. Une navigation privée sépare le catalogue
des réglages. La liste affiche douze fiches par page, applique explicitement la
recherche et les filtres, permet les tris par nom ou distance et conserve la
pagination côté serveur. Un onglet dédié montre les localisations à vérifier
sans rayon ni distance inventée. La fiche détaillée présente l'identité Sirene,
l'activité, l'effectif, l'adresse, la précision géographique et la fraîcheur de
chaque source. Sans adresse confirmée, l'écran guide vers les réglages et ne
contacte pas l'API de catalogue. Les tests navigateur couvrent ce garde-fou,
les paramètres de filtre, la pagination et l'ouverture d'une fiche.

Le treizième incrément matérialise les contacts professionnels dans des
ensembles versionnés `SOURCE` et `USER`. La couche utilisateur courante, si elle
existe, remplace entièrement la couche source pour l'affichage et les filtres ;
une future collecte peut donc actualiser ses propres contacts sans écraser une
correction. La liste expose la présence connue d'un email, d'un téléphone et
d'un site web, applique les trois filtres sur l'ensemble effectif et la fiche
détaille la valeur, sa portée et son éventuel libellé. Une absence
reste une inconnue et ne retire jamais la fiche. Sirene ne fournit aucun de ces
contacts : son import ne crée donc pas d'ensemble fictif. Les contraintes et
tests PostgreSQL vérifient l'unicité des ensembles courants, la déduplication
des valeurs et la priorité utilisateur ; l'API et l'interface couvrent les
nouveaux filtres.

Le quatorzième incrément contrôle explicitement les SIRET connus absents de la
sélection active complète. L'adaptateur utilise la recherche multicritère exacte
par groupes de 1 000 identifiants au maximum et distingue activité, fermeture,
cessation, diffusion partielle et résultat introuvable. Une source durable
`SIRENE_KNOWN_STATUS` et la table `sirene_known_status_check` rendent les lots
idempotents. Seuls les états administratifs explicitement publiés sont
appliqués ; une réponse introuvable ne ferme rien. Les présences trouvées sont
rattachées au cycle et une réactivation respecte le masquage ainsi que les
contacts utilisateur. Le premier comportement fermé refusait une diffusion
partielle avant la validation de la politique de purge. Les tests PostgreSQL
couvrent les quatre résultats non restreints, la
sélection des seules communes comparables et une seconde exécution sans nouvel
appel fournisseur.

Le quinzième incrément valide l'actualisation complète d'une fiche déjà connue
par un second cycle Sirene réussi. Une nouvelle observation met à jour les
projections source du nom, de l'organisme, de l'activité, de l'effectif, de la
localisation et leur filiation, puis rattache une nouvelle présence au même lien
source. Le SIRET conserve le même organisme physique et la même fiche, sans
dupliquer les entités. Le scénario PostgreSQL/PostGIS vérifie aussi qu'un
masquage et un ensemble de contacts `USER` survivent à cette actualisation, que
la répétition de la projection reste idempotente et que la nouvelle couverture
n'est publiée qu'après la réussite du cycle.

Le seizième incrément ferme la politique de diffusion partielle après revue
des sources officielles Insee, Légifrance et CNIL. Une réponse `P` purge dans
la transaction la fiche concernée, ses données utilisateur, identités,
observations, liens et occurrences identifiantes ; une restriction de l'unité
légale étend la purge à tous ses établissements connus. Le MVP ne conserve
aucune liste repoussoir ou HMAC : seuls le cycle et un compteur agrégé
subsistent. Les filtres source sur les deux statuts `O` empêchent la
réimportation tant que la restriction reste publiée. Les tests PostgreSQL
couvrent la purge d'un établissement, celle de plusieurs sites d'une même unité
légale, la disparition des données utilisateur et l'idempotence.

Le dix-septième incrément compose toutes les étapes dans l'exécuteur Sirene du
worker. Le cycle impose l'ordre énumération, fichier mensuel, résolution,
géocodage de repli, résolution finale, projection puis contrôle des fiches
connues. Chaque erreur de domaine devient un échec permanent ou une reprise
temporaire explicite avec le nombre d'observations déjà préservées. Le
connecteur n'est enregistré dans le worker et proposé par l'interface qu'avec
une clé API et la provenance complète d'un Parquet mensuel local lisible. Un
test PostgreSQL/PostGIS exécute cette composition par le vrai worker jusqu'au
travail `SUCCEEDED`, à la fiche prospect et à la couverture publiée.

Le dix-huitième incrément confronte cette composition aux données réelles de
septembre autour de Dax. Il accepte un état administratif `null` uniquement
sur une période historique close, reconnaît sans ambiguïté la casse minuscule
des colonnes Parquet courantes et renouvelle le bail avec une progression tous
les 100 géocodages persistés. L'adaptateur Géoplateforme effectue cinq reprises
HTTP courtes et bornées pour les erreurs réseau, `429` et `5xx`. Le cycle réel
a réconcilié 161 506 établissements et 160 429 lignes du fichier, puis prouvé
la reprise de 9 449 résultats Géoplateforme sans relecture des sources déjà
terminées. Trois erreurs fournisseur classées temporaires ont toutefois épuisé le cycle
avec 4 745 adresses restantes : il est correctement `PARTIAL`, sans prospect
ni couverture publiée. Le diagnostic de cette réponse fournisseur reste à
terminer avant de clore le jalon.

Le dix-neuvième incrément rend le prochain diagnostic fournisseur exploitable
sans exposer de donnée métier. L'erreur Géoplateforme distingue désormais le
réseau, les limitations, les statuts HTTP temporaires, les erreurs serveur et
les requêtes fonctionnellement rejetées. L'exécution conserve uniquement le
statut HTTP, le nombre d'essais courts et l'éventuel `Retry-After`, jamais
l'adresse ni le corps fournisseur ; le compteur source additionne également
les reprises courtes consommées. Un refus fonctionnel est définitif, tandis
qu'une panne réellement temporaire reste éligible aux deux reprises durables.
Un scénario PostgreSQL vérifie que ces preuves survivent à une reprise puis à
la réussite de la source. La dernière tentative disponible clôt aussi la source
en `FAILED` si la panne persiste, afin qu'un cycle terminal ne conserve pas un
enfant faussement `RUNNING`. La transaction terminale possède le même filet de
sécurité pour toute source inachevée, y compris après une erreur interne
imprévue. Le premier appel diagnostique autorisé n'était pas exploitable : la
commande avait encodé le saut de ligne terminal de `psql` dans le paramètre de
recherche. Aucune règle n'en a été déduite.

Le vingtième incrément répète correctement ce diagnostic ciblé, après une
seconde autorisation explicite : la même adresse professionnelle sans voie
exploitable reçoit bien un HTTP 400 sans `Retry-After`. Une mesure locale montre
que 1 234 des 4 745 cibles restantes ont cette forme insuffisante, alors
qu'aucune ne manque de code postal ou de commune. Radar les conserve désormais
comme positions `MISSING`, sous une issue et un compteur explicites, sans les
envoyer à Géoplateforme. Un test PostgreSQL vérifie l'absence d'appel et
d'incrément du compteur fournisseur. Les HTTP 400 sur une adresse suffisante
restent terminaux afin de révéler une éventuelle rupture générale du contrat.

Le vingt-et-unième incrément exploite le second cycle réel. Sirene y a reçu
161 509 établissements, dont 161 504 importables, et le fichier a joint
160 426 SIRET. Le repli a persisté 12 594 décisions — 9 194 correspondances,
25 absences et 3 375 adresses localement insuffisantes — avant qu'un libellé de
voie entièrement enveloppé de guillemets doubles ne déclenche un HTTP 400. Des
requêtes synthétiques reproduisent le refus lorsque ce token ouvre `q` et
confirment que les guillemets internes rencontrés dans les autres données sont
acceptés. La requête dérivée retire désormais seulement une paire englobante,
sans modifier la valeur Sirene conservée. Le contrat adaptateur passe en `v3`
et les tests unitaires ainsi que PostgreSQL couvrent cette normalisation.

Le vingt-deuxième incrément valide ce contrat `v3` sur un troisième cycle
réel, terminé `SUCCEEDED` en une tentative. Les 161 509 établissements reçus
et uniques comprennent 161 504 candidats importables ; le Parquet en joint
160 426 et le repli prend les 14 194 décisions attendues avec 10 388 requêtes,
zéro reprise et zéro erreur fournisseur. La projection crée 139 045 prospects
dans le cercle et conserve 7 942 prospects dans « Localisation à vérifier » ;
14 517 établissements hors rayon restent seulement comptabilisés. Les
146 987 fiches correspondent à autant d'établissements et de SIRET distincts.
La couverture de 50 km n'est publiée qu'après cette réconciliation complète.

Le vingt-troisième incrément répète immédiatement cette collecte sur le
catalogue matérialisé. Le cycle termine de nouveau `SUCCEEDED` en une tentative,
avec les mêmes 161 509 établissements reçus, 160 426 jointures Parquet,
14 194 décisions de repli et 10 388 appels Géoplateforme sans erreur. Les
146 987 liens source préexistants gardent leur identité ; 146 984 candidats
projetés sont inchangés, trois absents de la sélection sont confirmés actifs
par le contrôle ciblé, et un seul nouveau SIRET crée une fiche. Le catalogue
final contient 146 988 prospects, établissements, SIRET et liens Sirene
distincts, sans groupe dupliqué. Une seconde couverture de 50 km est publiée
après succès complet.

Le score, son filtre et son tri restent volontairement au jalon 8 et ne
bloquent pas la sortie de ce jalon. Le fichier réel, sa provenance, le cycle
opérationnel complet et sa relance idempotente sont maintenant validés. La
découverte et le téléchargement automatiques du prochain millésime sont
reportés au jalon 10 : ils ne sont pas nécessaires à la boucle métier du
jalon 6.

### Jalon 7 — Événements DATAtourisme de bout en bout

**État : terminé le 1er octobre 2026.**

**But :** livrer la deuxième famille d'opportunités.

Travaux :

- intégrer l'adaptateur DATAtourisme avec clé en en-tête ;
- collecter les événements du cercle sans filtre temporel fournisseur, puis
  retenir localement les périodes valides non terminées sans horizon maximal ;
- suivre chaque lien de pagination validé jusqu'à la fin ;
- normaliser lieu, catégories, description, contacts et provenance ;
- conserver plusieurs périodes sur une fiche ;
- calculer les états à venir, en cours et passé ;
- reconnaître `(DATAtourisme, UUID)` lors d'une relance et conserver toutes
  les périodes de cet objet sur la même fiche ;
- mettre en quarantaine, sans modifier la fiche, une future réutilisation d'UUID
  qui contredit le contrat observé ;
- ne pas confondre producteur, diffuseur ou propriétaire de donnée avec
  l'organisateur, et conserver un organisateur ou statut inconnu sans
  l'inférer du texte ;
- conserver les événements passés hors de l'interface ordinaire.

Interface minimale :

- liste et fiche événement ;
- recherche textuelle par titre ou commune ;
- filtres distance, période, catégorie, organisateur, contact et statut ;
- tris par date et distance ;
- affichage des occurrences et de la fraîcheur.

Critère de sortie : des événements simples, sur plusieurs jours et récurrents
sont importés puis mis à jour sans perdre leurs périodes.

Avancement : le premier incrément isole l'API DATAtourisme v1 derrière un
adaptateur de lecture typé. Il envoie la clé uniquement dans `X-API-Key`,
demande les champs utiles en français sans aucun filtre temporel et limite le
débit à cinq requêtes par seconde dans un seul flux. La taille de page est
alignée sur le maximum courant de 100 éléments ; la réponse effective est
contrôlée au lieu de faire confiance à la valeur demandée. Chaque lien `next`
est considéré comme non fiable : seuls HTTPS, l'hôte officiel, le port attendu
et `/v1/entertainmentAndEvent` sont acceptés, `api_key` est retiré et seul le
chemin avec sa requête assainie est reconstruit. Le lien brut n'est pas exposé,
seulement son empreinte.

Les objets sont normalisés dans des contrats indépendants du fournisseur pour
les lieux, adresses, descriptions, périodes, contacts et rôles de provenance.
Producteur, diffuseur et propriétaire restent explicitement des éléments de
provenance et ne deviennent jamais un organisateur. L'adaptateur rapproche à
la fin total annoncé, objets reçus, UUID uniques, pages et dernière page, et
refuse doublons, boucles, redirections ou dérives de schéma. Seize tests couvrent
ces garanties, les quotas, reprises courtes et erreurs contrôlées. Une lecture
réelle non persistante autour de Dax a réconcilié 2 666 objets et UUID uniques
sur 27 pages ; elle a également borné la normalisation du tableau vide observé
pour une description courte absente.

Le deuxième incrément applique les décisions locales que le filtre du
fournisseur ne peut pas garantir. Il relit strictement chaque date et heure,
rejette séparément les périodes illisibles ou inversées sans perdre leurs
sœurs valides, interprète les heures sans fuseau dans `Europe/Paris` et utilise
la fin de la dernière journée connue lorsqu'une heure de fin manque. Les états
`UPCOMING`, `ONGOING` et `PAST` sont calculés à partir de toutes les périodes
valides ; une fiche nouvelle exige au moins une période non terminée, tandis
qu'un objet uniquement passé reste identifiable pour une éventuelle fiche déjà
connue. La position métropolitaine la plus proche est retenue, sa distance est
recalculée localement et le cercle exact est appliqué indépendamment de la
présélection DATAtourisme. Le contrôle d'appartenance à la France
métropolitaine est injecté explicitement afin que l'implémentation PostGIS
suivante s'appuie sur les contours officiels plutôt que sur une boîte
géographique approximative.

Le troisième incrément matérialise le schéma événementiel sans encore brancher
le worker. La source `DATATOURISME_API` est enregistrée avec sa documentation et
sa licence ; la projection `event` reste séparée de la racine `opportunity` et
n'infère ni organisateur ni statut publié. Les calendriers `SOURCE` et `USER`
sont versionnés indépendamment par ensembles complets, avec au plus un ensemble
courant de chaque couche. Les périodes imposent l'ordre des dates et des heures,
le fuseau d'interprétation `Europe/Paris`, une précision explicite et des index
pour les futurs filtres de chevauchement. Les incréments suivants assurent le
staging durable puis la projection idempotente sur ces tables.

Le quatrième incrément rend la préparation des pages durable avant toute
projection de fiche. Chaque UUID est canonisé et empreinté dans l'espace de
noms `DATATOURISME_UUID`, tandis qu'une révision de contenu identique réutilise
la même observation source. Une nouvelle tentative conserve néanmoins sa
propre occurrence légère dans `collection_item`, ce qui permet de reprendre et
de réconcilier les pages sans dupliquer la donnée métier. Les périodes valides,
les rejets détaillés et l'état temporel au moment de la collecte sont conservés
comme diagnostics de l'occurrence. PostGIS contrôle en lot les coordonnées
publiées contre le millésime actif des communes métropolitaines, choisit le
point métropolitain le plus proche, recalcule la distance géodésique depuis le
centre figé du cycle et classe explicitement les objets sans position, hors de
France métropolitaine ou hors rayon. Les objets dans le rayon restent en
attente de projection ; un objet uniquement passé reste également en attente
afin que le prochain incrément puisse mettre à jour une fiche déjà connue sans
créer de nouvelle fiche passée.

Le cinquième incrément projette ces observations par page et par transaction
dans `opportunity`, `event`, `source_binding`, `source_sighting` et les périodes
`SOURCE`. Un UUID déjà connu retrouve sa fiche, y compris lorsqu'elle est
masquée ou que toutes les nouvelles périodes sont passées ; un objet uniquement
passé encore inconnu ne crée pas de fiche. Un changement des périodes retire
l'ancien ensemble `SOURCE` avant d'en publier un nouveau, sans toucher à
l'ensemble `USER` ni à l'état de masquage. Les décisions des occurrences sont
réconciliées à la fin de la tentative et les tests PostGIS couvrent création,
reprise, mise à jour et coexistence des deux couches. À ce stade, cette
projection n'est pas encore branchée au worker ; localisation persistée,
contacts, détection des contradictions d'identité, interface et filtres
restent à réaliser avant que le jalon soit utilisable de bout en bout.

Le sixième incrément projette aussi la localisation exacte choisie pendant le
staging PostGIS. Son point, son adresse et l'index du lieu source restent liés
à l'observation DATAtourisme et à une version `SOURCE` de
`location_assertion`. Une relance sans changement ne crée pas de nouvelle
version ; un changement retire seulement l'ancienne version source. La
version `USER` éventuelle reste intacte et prioritaire pour les futures
recherches par distance. La distance au centre de collecte n'est pas stockée
sur la fiche. Cette étape ne branche toujours pas le worker et ne livre pas
encore l'interface événementielle.

Le septième incrément projette les téléphones et sites explicitement publiés
dans `hasContact` et `hasBookingContact` en ensembles de contacts `SOURCE`
versionnés. Chaque canal conserve sa valeur publique, une clé de comparaison
prudente, son chemin dans l'observation et un libellé « contact général » ou
« réservation » ; sa portée reste `UNKNOWN`. Les canaux identiques sont
dédupliqués dans l'ensemble, mais une nouvelle observation sans changement
de contacts ne crée pas de version supplémentaire. Un ensemble `USER` reste
intact et prioritaire. Les rôles producteur, diffuseur et propriétaire ne
deviennent ni organisateurs ni contacts locaux ; aucun email n'est inventé.
Le worker, le catalogue événementiel et la mise en quarantaine des conflits
d'identité restent à réaliser pour achever le jalon.

Le huitième incrément ajoute l'orchestration interne de la collecte
DATAtourisme : chaque page est normalisée et préparée avant l'enregistrement
de sa preuve dans `collection_page`. La source et son lot ne deviennent
`SUCCEEDED` qu'après rapprochement du total annoncé, des UUID, des pages et
des éléments préparés lors de la tentative courante. Une interruption reprend
la requête depuis sa première page, sans réutiliser un curseur fournisseur ;
les révisions identiques réemploient leur observation source, tandis que les
tentatives gardent leurs propres occurrences de collecte. La projection des
fiches ne commence qu'après ce succès de collecte. Des tests PostGIS couvrent
la reprise, une page vide et le refus d'une preuve incohérente. Le connecteur
n'est pas encore activé dans le worker ni dans l'interface : il reste à traiter
les contradictions d'identité avant une collecte utilisable de bout en bout.

Le neuvième incrément met en quarantaine le premier conflit d'identité
objectivement détectable : une URI de ressource DATAtourisme revendiquée par
deux UUID. Une observation jamais publiée reçoit `IDENTITY_CONFLICT` ; une
révision déjà liée à une fiche reste historiquement valide, mais sa nouvelle
occurrence est bloquée avec un diagnostic. Aucune fiche ni couche `USER` n'est
modifiée par l'objet suspect. La projection réconcilie ces décisions et rend
le cycle `PARTIAL`, sans publier une couverture complète. Un index partiel
borne le coût du contrôle. Les variations ordinaires de titre, période, lieu
ou URI non revendiquée ne sont pas considérées comme des conflits. Le worker
et l'interface événementielle restent à raccorder. Une fois un UUID mis en
quarantaine, ses collectes ultérieures restent bloquées jusqu'à une décision
explicite sur le contrat source, même si sa nouvelle URI paraît libre.

Le dixième incrément raccorde le pipeline DATAtourisme au processus worker
quand sa clé API est configurée. Il peut fonctionner sans configuration Sirene
et ferme son client fournisseur à l'arrêt. Un test PostgreSQL/PostGIS exécute
le vrai worker avec une réponse HTTP simulée, depuis la création du travail
jusqu'à la couverture, puis répète la collecte : une seule fiche et une seule
révision source subsistent, avec deux présences et deux preuves de page. Le
second parcours intégré vérifie que deux UUID revendiquant la même URI
terminent le travail `PARTIAL`, sans fiche ni couverture. Le
déclenchement DATAtourisme reste désactivé dans le serveur web tant que le
catalogue événementiel n'est pas consultable ; le branchement du worker seul
ne lance aucune collecte spontanée.

Le onzième incrément expose la lecture privée du catalogue événementiel par
`GET /api/v1/events` et `GET /api/v1/events/{id}`. La liste interroge uniquement
PostgreSQL/PostGIS, dans le rayon demandé ou celui configuré, et propose
recherche par titre ou commune, filtre de période par chevauchement, catégorie
source, organisateur, contact disponible et statut déclaré, ainsi que tris par
date et distance avec pagination. Elle écarte les fiches masquées et passées,
et les événements annulés sauf demande explicite. La fiche détail présente
toutes les périodes de la couche effective, les contacts effectifs et la
fraîcheur des observations avec leur provenance. La catégorie est encore le
type brut publié par DATAtourisme : aucune taxonomie métier ni score n'est
inventé à cette étape. Les tests HTTP et PostGIS vérifient notamment la
priorité d'une correction utilisateur et l'absence d'appel fournisseur. La
navigation événementielle et le déclenchement de sa collecte depuis le site
restent à livrer avant que ce jalon soit utilisable par l'utilisateur.

Le douzième incrément livre l'onglet « Événements » dans l'interface React et
active le déclenchement manuel DATAtourisme lorsque sa clé est configurée,
indépendamment des prérequis Sirene. La liste paginée applique les filtres et
tris de l'API locale ; le retour d'une fiche conserve la page et les filtres.
La fiche détail présente chaque période connue, ses seuls horaires publiés,
les contacts avec leur portée, ainsi que source, producteurs, diffuseurs,
licence et dates de fraîcheur. Les instants sont affichés en Europe/Paris et
les dates sans heure restent des dates civiles. Les tests de l'interface
couvrent aussi les réponses arrivant dans le désordre et les sessions expirées.
Un parcours HTTP/PostGIS avec authentification réelle et fournisseur simulé
vérifie la demande protégée par CSRF, sa mise en attente sans appel fournisseur,
le traitement par le worker, la consultation et l'ajout de périodes à la même
fiche lors d'une seconde collecte. Sans clé, le connecteur reste indisponible.

Le treizième incrément valide le parcours réel dans une base temporaire
séparée, avec les contours communaux officiels 2026 contrôlés par empreinte et
l'adresse de la mairie de Dax géocodée puis confirmée. Deux demandes HTTP
authentifiées sont traitées par le vrai worker : chaque cycle réconcilie
2 676 objets sur 27 pages. Le premier crée 2 562 événements ; le second retrouve
exactement les mêmes fiches et versions, sans création supplémentaire. Les
125 fiches à périodes multiples et les 228 périodes sur plusieurs jours
confirment la représentation attendue. Les rejets et les 16 objets hors rayon
sont comptabilisés ; aucune localisation importée ne sort du cercle exact ou
des contours métropolitains. Cent fiches sont relues par l'API à chaque cycle.
Le frontend compilé est aussi testé dans Firefox headless : connexion, liste,
pagination, détail avec périodes et provenance, retour conservant la page,
filtre à 30 km et déconnexion. Le filtre renvoie 823 événements sans créer de
cycle. Il s'agit d'un essai navigateur automatisé, pas d'une validation
ergonomique par l'utilisateur. Le rapport daté détaille les mesures et leurs
limites dans `docs/source-validation-dax-2026-09.md`, section 6.5.
Le test a aussi conduit à supprimer les valeurs d'entrée des messages d'erreur
de configuration, avec un test de non-divulgation des clés chargées.

Résultat : critère de sortie atteint. Le scoring et la planification nocturne
appartiennent aux jalons suivants ; l'essai personnel de l'interface reste
recommandé sans bloquer le prochain incrément.

### Jalon 8 — Scoring explicable

**But :** faire remonter les opportunités utiles sans en cacher.

Travaux :

- implémenter les deux moteurs de règles déterministes ;
- conserver la version des règles et les contributions ;
- afficher le score entier de 0 à 100 et chaque explication ;
- recalculer après une donnée utile modifiée ;
- ajouter les tris et filtres par plage de score ;
- vérifier que distance, date et état CRM n'affectent jamais le score ;
- qualifier manuellement l'échantillon réel prévu dans `docs/scoring.md` ;
- ajuster uniquement les pondérations justifiées par cet échantillon.

Critère de sortie : les cas clairement intéressants sont globalement classés
avant les cas clairement faibles, sans pénaliser une donnée inconnue ni
masquer automatiquement une fiche.

### Jalon 9 — Corrections, notes et masquage

**But :** permettre à l'utilisateur d'organiser durablement le catalogue.

Travaux :

- créer une fiche manuelle ;
- corriger les champs autorisés sans écraser la valeur source ;
- restaurer une valeur source ;
- recalculer les distances, filtres et scores qui dépendent des valeurs
  effectives modifiées ;
- ajouter et modifier la note libre d'une fiche ;
- masquer avec un motif facultatif ;
- relier facultativement un doublon masqué à la fiche conservée ;
- rechercher, consulter et démasquer depuis l'onglet dédié ;
- vérifier qu'une collecte actualise l'observation mais ne recrée ni ne
  démasque la fiche.

Critère de sortie : les corrections et notes survivent à une collecte et le
cycle masquer/démasquer est entièrement réversible hors obligation de
conformité.

### Jalon 10 — Planification et robustesse

**But :** rendre les mises à jour autonomes et observables.

Travaux :

- planifier Sirene une fois par mois ;
- planifier DATAtourisme chaque nuit en Europe/Paris ;
- conserver le déclenchement manuel ;
- gérer le redémarrage pendant une tâche ;
- appliquer les politiques de reprise, quotas et temporisation ;
- signaler l'échec et la date du dernier succès dans l'interface ;
- marquer l'obsolescence selon les règles propres aux sources ;
- vérifier qu'un échec n'altère pas les données précédemment utilisables.

Critère de sortie : les tâches automatiques peuvent échouer puis reprendre de
façon visible, sans doublons certains ni perte de données utilisateur.

### Jalon 11 — Mise en production privée

**But :** rendre le MVP accessible sur Internet sans exposer ses composants
internes.

Travaux :

- déploiement sur le serveur privé retenu ;
- HTTPS obligatoire ;
- PostgreSQL accessible uniquement depuis l'environnement applicatif ;
- configuration des secrets hors dépôt ;
- sauvegardes quotidiennes chiffrées sur un emplacement distinct du serveur ;
- test documenté de restauration ;
- journalisation, rotation et espace disque ;
- procédure de mise à jour et de retour arrière compatible avec les
  migrations ;
- contrôle final des critères d'acceptation du MVP.

Critère de sortie : Radar est accessible uniquement après authentification,
les sauvegardes sont restaurables et aucun secret ni port PostgreSQL n'est
exposé publiquement.

## 5. Ordre à l'intérieur d'un jalon

Chaque fonctionnalité suit autant que possible cette boucle :

1. préciser le comportement et le cas d'erreur ;
2. écrire les tests du domaine ou du contrat ;
3. implémenter la plus petite tranche backend ;
4. exposer l'API nécessaire ;
5. ajouter l'interface minimale ;
6. exécuter formatage, lint, types et tests ;
7. mettre à jour la documentation concernée ;
8. vérifier manuellement le parcours utilisateur.

Une tranche n'a pas besoin d'attendre que toute l'interface soit dessinée.
Elle doit toutefois être observable autrement que par une inspection directe
de la base.

## 6. Décisions à prendre au bon moment

Ces choix ne bloquent pas le cadrage actuel :

| Décision | Échéance maximale | Décision ou recommandation actuelle |
| --- | --- | --- |
| Frontend du MVP | Décidé le 11 septembre 2026 | TypeScript, React et Vite ; build statique sous la même origine, sans Next.js |
| Processus de tâches longues | Début du jalon 5 | Même code applicatif, file durable en PostgreSQL, sans broker |
| Diffusion partielle Sirene | Décidé le 24 septembre 2026 | Purge complète atomique, compteurs agrégés seulement, aucune HMAC |
| Serveur et mode de déploiement | Avant le jalon 11 | Un seul serveur privé, composants non publics sauf le proxy HTTPS |
| Destination et capacité des sauvegardes | Avant le jalon 11 | Valider la rétention initiale de l'architecture et tester une restauration |

Une décision prise met à jour les documents spécialisés avant son
implémentation. Une option reportée ne doit pas conduire à développer les deux
solutions « au cas où ».

Le jalon 1 a clos la stratégie de position Sirene : coordonnées API valides en
priorité, fichier mensuel conservé avec sa qualité propre et comme repli, puis
Géoplateforme. Aucune qualité n'est transférée entre les deux positions. Le
choix de la bibliothèque Parquet est une décision d'implémentation du jalon 6,
pas une remise en cause de ce contrat.

## 7. Après le MVP

L'ordre sera déterminé par l'usage réel, pas uniquement par la liste des idées.
Les candidats sont notamment :

- Annuaire officiel de l'administration française ;
- Répertoire National des Associations ;
- OpenAgenda et agendas locaux ;
- enrichissement contrôlé des sites officiels ;
- CRM et historique de contacts ;
- archives consultables des événements passés ;
- carte et éventuellement distance routière ;
- détection avancée et fusion manuelle des doublons ;
- alertes et intégrations externes ;
- classifieur IA indépendant de son fournisseur.

Une fonctionnalité future entre dans la roadmap seulement lorsqu'un problème
réel du MVP démontre sa priorité.

## 8. Hors roadmap actuelle

- microservices ;
- Kubernetes ou orchestrateur équivalent ;
- broker de messages uniquement pour anticiper une montée en charge ;
- multi-utilisateur et rôles ;
- application mobile native ;
- envoi massif d'emails ou de SMS ;
- CRM dans le MVP ;
- IA avant validation des règles déterministes ;
- collecte hors de France métropolitaine.
