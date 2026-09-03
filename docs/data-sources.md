# Radar — Sources de données externes

> Statut : cadrage technique initial, validation réelle à terminer
>
> Dernière mise à jour : 3 septembre 2026
>
> Périmètre : France métropolitaine, MVP Sirene et DATAtourisme

## 1. Objet du document

Ce document définit les fournisseurs externes de Radar, leur rôle, les données
utilisées, les règles de collecte et les vérifications nécessaires avant leur
mise en production.

Il complète `docs/product.md`, qui reste la référence pour le besoin produit.
Il ne décrit ni le schéma physique de la base, ni l'ordonnancement technique
des tâches, qui relèvent respectivement de `docs/database.md` et de
`docs/architecture.md`.

Une source est considérée comme :

- **documentée** lorsque son fonctionnement est confirmé par sa documentation
  officielle actuelle ;
- **testée** lorsqu'un appel réel a été exécuté et contrôlé ;
- **validée pour le MVP** seulement après un essai complet dans un rayon de
  50 km autour de la mairie de Dax.

La lecture de la documentation ne remplace donc pas la validation sur des
données réelles.

## 2. Principes communs

### 2.1 Périmètre géographique

Radar couvre uniquement la France métropolitaine, Corse comprise. Les DROM,
les COM et les territoires étrangers sont hors scope.

Une zone peut traverser un département ou une région sans traitement spécial.
Si son cercle déborde sur un pays voisin, seule sa partie située en France
métropolitaine est couverte. Une donnée étrangère éventuellement renvoyée par
un fournisseur est rejetée lors de la normalisation.

### 2.2 Responsabilité des adaptateurs

Chaque fournisseur est isolé derrière un adaptateur. Un adaptateur :

1. appelle ou télécharge sa source ;
2. vérifie la réponse, le schéma, la pagination et les totaux disponibles ;
3. transforme les données reçues en observations normalisées ;
4. transmet ces observations au service d'import de Radar ;
5. ne modifie jamais directement les modèles de persistance.

Les règles propres à un fournisseur restent dans son adaptateur. Le domaine ne
doit pas dépendre des noms de champs ou des formats de Sirene, de
DATAtourisme ou d'un futur fournisseur.

### 2.3 Provenance minimale

Toute observation externe conservée doit permettre d'identifier :

- le fournisseur et, lorsqu'il est distinct, le producteur initial ;
- l'identifiant externe stable, ou la clé technique documentée ;
- l'URL de la ressource d'origine lorsqu'elle existe ;
- la date et l'heure de récupération ;
- la date de mise à jour annoncée par la source lorsqu'elle existe ;
- le cycle de collecte et la version de l'adaptateur ;
- la licence ou les conditions de réutilisation applicables ;
- les valeurs externes utiles dont dérive la fiche normalisée.

Un identifiant n'est unique qu'à l'intérieur de son fournisseur. Radar ne
rapproche jamais deux sources différentes sur la seule ressemblance de leurs
identifiants.

Les corrections et notes utilisateur restent séparées des observations
externes. Une synchronisation peut remplacer une ancienne valeur source par
une nouvelle valeur source, mais pas une correction utilisateur, sauf
traitement de conformité obligatoire défini dans `docs/product.md`.

### 2.4 Données inconnues et données absentes

L'absence d'un champ dans une réponse signifie « inconnu dans cette source ».
Elle ne prouve pas que l'information n'existe pas dans le monde réel.

En particulier :

- une fiche sans email, téléphone ou site reste valide ;
- une absence dans une collecte ne prouve ni une fermeture, ni une annulation ;
- une position manquante ne permet pas d'écarter silencieusement un prospect
  Sirene candidat ;
- une donnée obtenue d'un autre fournisseur conserve sa propre provenance.

### 2.5 Succès et échec d'une collecte

Un cycle n'est déclaré réussi que si toutes les requêtes, pages, jointures et
vérifications obligatoires du connecteur ont abouti. Un quota dépassé, une
page manquante, un curseur non terminé, un total incohérent ou une ressource
de référence indisponible rend le cycle partiel ou échoué.

Les observations correctement reçues peuvent être conservées avec le cycle
partiel qui les a produites, mais elles ne permettent pas d'affirmer que la
zone est complètement couverte. Un échec ne supprime, ne masque et ne rend
jamais inactives les données du dernier cycle réussi.

## 3. Sources du MVP

| Besoin | Source retenue | Fréquence | Accès | État au 3 septembre 2026 |
| --- | --- | --- | --- | --- |
| Géocoder l'adresse de référence | API de géocodage de la Géoplateforme | À la demande | Sans clé, 50 requêtes/s/IP | Documentation vérifiée ; adresse de Dax testée |
| Trouver les communes candidates | Jeu « Contours administratifs » de data.gouv.fr | À chaque nouveau millésime utile | Téléchargement ouvert | Documentation vérifiée ; intégration non testée |
| Découvrir et actualiser les établissements | API Sirene 3.11 de l'Insee | Mensuelle et manuelle | Compte et clé publique, 30 requêtes/min | Documentation vérifiée ; appels métier bloqués sans clé |
| Géolocaliser les établissements Sirene | Fichier mensuel officiel de géolocalisation Sirene | Mensuelle | Téléchargement ouvert | Source produit actuelle ; échantillon réel non testé |
| Découvrir et actualiser les événements | API DATAtourisme v1 | Chaque nuit et manuelle | Clé gratuite, 1 000 requêtes/h | Documentation vérifiée ; appels métier bloqués sans clé |

Les limites ci-dessus sont celles publiées à la date du document. Les
adaptateurs doivent traiter les réponses de limitation et ne pas supposer que
ces valeurs resteront inchangées.

## 4. Référentiels géographiques

### 4.1 Géocodage de l'adresse de référence

Radar utilise l'[API de géocodage de la
Géoplateforme](https://cartes.gouv.fr/aide/fr/guides-utilisateur/utiliser-les-services-de-la-geoplateforme/geocodage/),
opérée par l'IGN, via :

```text
GET https://data.geopf.fr/geocodage/search
```

Le service s'appuie notamment sur la Base Adresse Nationale et renvoie des
coordonnées géographiques. L'ancienne API `api-adresse.data.gouv.fr` ne doit
pas être intégrée : elle a été remplacée par le service de la Géoplateforme.

Radar conserve pour le résultat choisi :

- l'adresse saisie ;
- le libellé normalisé renvoyé ;
- les coordonnées WGS84 ;
- le code commune et l'identifiant BAN lorsqu'ils existent ;
- le type de résultat et son score de rapprochement lorsqu'ils existent ;
- le fournisseur et la date du géocodage.

Le meilleur résultat automatique n'est jamais considéré comme exact sans
présentation à l'utilisateur. L'utilisateur vérifie la position avant la
première collecte. Une correction ultérieure crée un nouveau résultat de
géocodage sans réécrire la provenance de l'ancien.

Le contrôle préliminaire du 3 septembre 2026 pour
`12 rue Saint-Pierre, 40100 Dax` a renvoyé comme premier résultat
`12 Rue Saint Pierre 40100 Dax`, code commune `40088`, identifiant BAN
`40088_1750_00012`, aux coordonnées WGS84 longitude `-1.051952`, latitude
`43.70884`, avec un score d'environ `0,9653`. Ce contrôle confirme seulement
le fonctionnement du géocodeur ; l'utilisateur devra toujours valider le
point affiché dans Radar.

### 4.2 Contours des communes

L'API Sirene ne prend pas directement un cercle métier comme entrée. Radar
commence donc par déterminer les communes françaises susceptibles de contenir
un établissement situé dans le cercle.

Le référentiel retenu est le jeu officiel
[« Contours administratifs »](https://www.data.gouv.fr/datasets/contours-administratifs),
construit notamment à partir d'Admin Express de l'IGN et également utilisé par
l'[API Découpage
administratif](https://www.data.gouv.fr/dataservices/api-decoupage-administratif-api-geo).

Pour ne pas rendre chaque collecte dépendante d'une série d'appels externes,
Radar utilise un fichier GeoJSON de communes téléchargé et versionné
localement. Le niveau de généralisation `100m` est retenu pour le MVP : il est
nettement plus léger que le fichier `5m` et suffit à une présélection
conservative. Seules les communes métropolitaines sont chargées.

Pour chaque version, Radar conserve :

- l'URL stable ou l'identifiant de la ressource ;
- la date de récupération et la date de publication disponible ;
- la taille et une empreinte du fichier téléchargé ;
- la licence ;
- les codes commune et géométries effectivement chargés.

Une commune devient candidate lorsque son contour intersecte le cercle de
collecte élargi de 1 km pour cette seule présélection. Cette marge, nettement
supérieure à la généralisation du fichier, privilégie une légère
sur-sélection plutôt qu'un oubli en bordure. Elle ne modifie pas le rayon
métier : les coordonnées de chaque établissement sont ensuite comparées au
cercle exact. Interroger quelques établissements hors rayon est acceptable ;
omettre une commune intersectée ne l'est pas.

Le référentiel est remplacé lorsqu'un nouveau millésime modifie le Code
officiel géographique ou les contours utiles. Une collecte conserve la version
qu'elle a utilisée afin de rester explicable.

## 5. API Sirene 3.11

### 5.1 Rôle et limites fonctionnelles

L'[API Sirene open data](https://www.data.gouv.fr/dataservices/api-sirene-open-data)
est la première source des prospects réguliers. Elle identifie des entreprises,
associations immatriculées, organismes publics et autres unités légales ainsi
que leurs établissements.

Dans Radar, l'opportunité locale est l'établissement identifié par son SIRET.
Le SIREN identifie son unité légale et ne suffit pas à distinguer plusieurs
sites physiques.

Sirene ne garantit pas la présence d'un email, d'un téléphone ou d'un site
web. Ces champs ne doivent pas être inventés ou déduits. Sirene ne couvre pas
non plus toutes les associations : celles sans SIRET nécessiteront une source
complémentaire après le MVP.

### 5.2 Accès et secret

L'accès open data nécessite un compte sur le catalogue des API de l'Insee et
une souscription gratuite. La clé publique est transmise uniquement dans
l'en-tête :

```text
X-INSEE-Api-Key-Integration: <clé>
```

Elle n'apparaît jamais dans une URL, un journal, un message d'erreur affiché ou
une observation conservée. La limite publiée est de 30 requêtes par minute.
L'adaptateur doit donc limiter son débit et respecter un éventuel délai
`Retry-After`.

La version ciblée est `V3.11` et la ressource principale est la recherche
multicritère des établissements :

```text
GET https://api.insee.fr/api-sirene/3.11/siret
```

Le service `informations` est consulté au début du cycle afin de conserver la
date de dernière mise à disposition annoncée par l'Insee. Cette date ne doit
pas être confondue avec la date du fichier mensuel de géolocalisation.

### 5.3 Sélection logique

Pour chaque lot disjoint de communes candidates, la requête doit sélectionner
l'état courant et respecter simultanément les conditions suivantes :

- le code commune de l'établissement appartient au lot ;
- l'établissement est administrativement actif ;
- son unité légale est administrativement active ;
- `statutDiffusionEtablissement` vaut `O` ;
- `statutDiffusionUniteLegale` vaut `O`.

Aucun code d'activité, type d'organisme, effectif ou score n'est utilisé pour
réduire cette découverte. Ces critères sont appliqués seulement dans Radar.

Les variables d'état sont historisées dans Sirene. Une condition qui signifie
seulement « a été actif à un moment » pourrait donc ramener un établissement
désormais fermé. L'expression exacte de la requête courante doit être figée par
un test de contrat avec une clé réelle. Indépendamment du filtre serveur,
l'adaptateur vérifie la période courante de chaque réponse avant de créer une
fiche. Une période historique active ne suffit jamais.

Tant que ce test n'est pas réalisé, aucun exemple d'URL complète n'est déclaré
comme contrat définitif dans ce document.

### 5.4 Lots, curseurs et complétude

La limite des 10 000 résultats de la pagination classique n'impose pas de
limite de 10 000 établissements à Radar. La collecte utilise la pagination par
curseur, documentée par l'Insee pour charger jusqu'à 1 000 résultats par page.

Le déroulement logique est le suivant :

1. répartir les codes commune en lots disjoints suffisamment petits pour
   respecter les limites de longueur et d'opérateurs de la requête ;
2. lancer la première page d'un lot avec un curseur initial et une taille de
   page de 1 000 ;
3. conserver le total annoncé par l'en-tête de réponse ;
4. réutiliser exactement le curseur renvoyé pour demander la page suivante ;
5. continuer jusqu'à la fin annoncée, même après le 10 000e résultat ;
6. compter les lignes reçues et les SIRET uniques du lot ;
7. vérifier le total, puis réunir les lots en dédupliquant par SIRET.

Un lot n'est terminé que lorsque son curseur l'est et que ses comptages sont
cohérents. Une différence inexpliquée, même faible, rend le cycle partiel.
Comme l'API est interrogée en direct, un cycle couvrant plusieurs requêtes
n'est pas un instantané atomique. La date de chaque requête est donc conservée
et une incohérence possiblement due à une mise à jour concurrente donne lieu à
une nouvelle tentative complète du lot avant de conclure à un échec.

L'Insee limite à 1 000 le nombre d'opérateurs `AND` ou `OR` dans un même groupe
de parenthèses. Le nombre exact de communes par lot sera choisi par un test de
contrat, avec une marge suffisante pour la longueur d'URL ; il ne constitue
pas un réglage produit.

### 5.5 Champs utiles

L'adaptateur ne demande et ne conserve que les champs nécessaires au produit :

- SIRET, SIREN et caractère siège ;
- enseignes, dénomination usuelle et dénomination de l'unité légale utiles à
  l'affichage ;
- catégorie juridique ;
- activité principale de l'établissement et nomenclature associée ;
- tranche et année d'effectif de l'établissement ;
- adresse publique et code commune ;
- états administratifs courants de l'établissement et de l'unité légale ;
- statuts de diffusion de l'établissement et de l'unité légale ;
- dates de création, de début de période et de dernier traitement utiles à la
  fraîcheur ;
- identifiant d'adresse et coordonnées publiées par l'API, à des fins de
  comparaison pendant la validation géographique.

Les dates de naissance, le sexe, les données financières et les informations
sur les dirigeants n'ont aucune utilité pour Radar et ne sont pas collectés.
Pour un entrepreneur individuel, l'utilisation éventuelle du nom de la
personne comme solution de dernier recours doit être justifiée par le besoin
d'identification, limitée aux données en diffusion totale et revue avant la
mise en production.

Le passage annoncé à la NAF 2025 en janvier 2027 impose de conserver avec tout
code d'activité sa nomenclature. Les règles métier ne doivent jamais supposer
qu'un même code conserve sa signification entre la NAF 2008 et la NAF 2025.

### 5.6 Géolocalisation officielle

Conformément à la décision actuelle de `docs/product.md`, la position de
référence d'un établissement provient d'abord du jeu mensuel
[« Géolocalisation des établissements du répertoire SIRENE pour les études
statistiques »](https://www.data.gouv.fr/datasets/geolocalisation-des-etablissements-du-repertoire-sirene-pour-les-etudes-statistiques).

Ce jeu contient notamment le SIRET, des coordonnées X/Y, le code commune et
des variables de qualité. En métropole, les coordonnées utilisent le système
RGF93 / Lambert-93. Le fichier publié en août 2026 représente environ 772 Mo au
format Parquet ; son volume doit donc être pris en compte sans être confondu
avec le volume final conservé par Radar.

Le traitement doit :

1. découvrir la ressource courante par son URL stable data.gouv.fr ;
2. télécharger dans un fichier temporaire ;
3. contrôler le format, la taille, l'empreinte et les colonnes obligatoires ;
4. conserver le millésime et la date de publication ;
5. joindre les candidats Sirene au fichier par SIRET ;
6. transformer les coordonnées Lambert-93 en WGS84 ou dans le type géographique
   retenu par PostGIS ;
7. conserver séparément la provenance et la qualité de cette position ;
8. ne publier le nouveau millésime comme utilisable qu'après réussite de tous
   les contrôles.

Le fichier et l'API Sirene peuvent représenter des dates différentes. Un
établissement récent absent du fichier n'est donc pas considéré comme
inexistant.

Les codes de qualité acceptés sans vérification et ceux qui déclenchent le
géocodage de repli seront définis après lecture du fichier réel et comparaison
sur l'échantillon de Dax. Avant cette validation, Radar ne doit pas inventer un
seuil arbitraire.

Si la jointure échoue ou si la qualité est insuffisante, l'adresse publique de
l'établissement est envoyée au géocodeur de la Géoplateforme. La requête, le
résultat, le score, la date et le fournisseur restent distincts du fichier
Sirene. Si aucune position n'est assez fiable, la fiche va dans
« Localisation à vérifier » et sa distance reste inconnue.

### 5.7 Simplification géographique à évaluer

La documentation officielle de l'API Sirene 3.11 indique désormais directement
les champs `coordonneeLambertAbscisseEtablissement`,
`coordonneeLambertOrdonneeEtablissement` et
`identifiantAdresseEtablissement`. Cette évolution peut rendre le fichier
mensuel de 772 Mo inutile pour le MVP.

Avant de modifier la décision produit, un test réel doit comparer, sur tous les
candidats du cercle de Dax :

- le taux de coordonnées présentes dans l'API ;
- leur cohérence avec le fichier mensuel ;
- la précision apportée par les variables de qualité du fichier ;
- le nombre de géocodages de repli nécessaires ;
- le coût opérationnel des deux solutions.

Si la couverture de l'API est suffisante, la recommandation est d'utiliser ses
coordonnées en premier, puis le géocodeur de la Géoplateforme en repli, et de
retirer le gros fichier mensuel du MVP. Ce serait plus simple et plus frais.
Jusqu'à validation explicite de ce changement, le fichier mensuel reste la
source de référence définie par `docs/product.md`.

### 5.8 Prospects déjà connus

Après une collecte active entièrement réussie, les SIRET déjà connus qui ne
figurent plus dans la sélection sont contrôlés dans leur état courant. Une
interrogation unitaire peut demander la période courante en passant la date du
jour au service SIRET.

Les résultats sont interprétés ainsi :

- fermeture explicite de l'établissement : prospect administrativement
  inactif ;
- cessation explicite de l'unité légale : prospect administrativement inactif ;
- établissement et unité légale de nouveau actifs : réactivation, sous réserve
  des règles de diffusion ;
- diffusion partielle `P` : fiche non prospectable, jamais « fermée » pour ce
  seul motif ;
- absence, erreur, quota ou réponse ambiguë : aucun changement d'état.

Un passage en diffusion partielle déclenche le retrait des données qui ne sont
plus réutilisables pour la prospection. Avant l'implémentation, la liste exacte
des éléments minimaux pouvant être conservés pour reconnaître le SIRET et ne
pas le réimporter doit faire l'objet d'une vérification de conformité. Cette
documentation ne constitue pas un avis juridique.

### 5.9 Fraîcheur et obsolescence

La collecte Sirene est mensuelle et peut être lancée manuellement. Une valeur
Sirene devient remplacée lorsqu'une réponse courante plus récente fournit une
nouvelle valeur. La simple absence d'un établissement dans un cycle ne rend
pas ses données obsolètes et ne change jamais son état administratif.

## 6. API DATAtourisme v1

### 6.1 Rôle et couverture

L'[API DATAtourisme](https://api.datatourisme.fr/v1/docs) est la première
source d'événements du MVP. Elle agrège et normalise les données de nombreux
systèmes d'information touristique territoriaux.

Elle fournit des événements culturels, commerciaux, sociaux et sportifs, mais
ne garantit pas que tous les organisateurs ou territoires publient tout leur
agenda. Elle ne fournit pas de statistiques générales de fréquentation. Sa
couverture doit donc être mesurée dans la zone réelle et ne doit jamais être
présentée comme exhaustive du monde réel.

### 6.2 Accès et limites

L'API v1 nécessite une clé gratuite obtenue après inscription. Radar l'envoie
dans l'en-tête recommandé :

```text
X-API-Key: <clé>
```

La clé n'est ni placée dans l'URL, ni journalisée. Les limites publiées sont de
1 000 requêtes par heure, environ 10 requêtes par seconde en usage prolongé et
20 à 30 requêtes simultanées. Radar n'a pas besoin d'approcher ces limites et
utilise une concurrence faible.

Les données sont placées sous Licence Ouverte 2.0. La source, le producteur
initial disponible et la date de mise à jour doivent être conservés et
affichables.

### 6.3 Requête de découverte

La collecte utilise l'endpoint préfiltré :

```text
GET https://api.datatourisme.fr/v1/entertainmentAndEvent
```

La requête fournit :

- `geo_distance` avec latitude, longitude et rayon de collecte ;
- `page_size=250`, maximum publié ;
- `lang=fr` ;
- une liste explicite de champs nécessaires.

La liste des champs doit au minimum couvrir l'UUID, l'URI, le titre, les types,
la description, la position, l'adresse, les périodes `takesPlaceAt`, les
contacts, le producteur de la donnée et les dates de mise à jour. Comme le
paramètre `fields` remplace la sélection par défaut, un champ omis de cette
liste ne sera pas supposé absent de la source.

Radar ne limite pas la date future dans la requête. Après normalisation, une
nouvelle fiche n'est créée que si au moins une période publiée n'est pas
terminée. Les événements déjà connus restent conservés après leur passage dans
le passé.

La position renvoyée par DATAtourisme est contrôlée et la distance est
recalculée localement. Une donnée hors du cercle exact ou hors de France
métropolitaine est écartée de la découverte, même si le filtre du fournisseur
l'a renvoyée.

### 6.4 Pagination et complétude

L'API renvoie `meta.total`, `meta.page`, `meta.page_size`, `meta.total_pages`
et un lien `meta.next`. Radar utilise l'information de navigation `next`
jusqu'à ce qu'elle soit nulle, mais ne transmet jamais cette chaîne telle
quelle à `httpx`.

L'accès direct par numéro de page est limité aux 10 000 premières ressources,
mais la documentation autorise de dépasser cette limite en suivant les liens
`next`. Radar ne calcule donc pas lui-même le numéro ou le curseur de la page
suivante ; il normalise de manière sûre l'information `next` fournie comme
décrit ci-dessous.

À la fin du cycle, il compare :

- le total annoncé ;
- le nombre d'objets reçus ;
- le nombre d'UUID uniques ;
- le nombre de pages et la dernière page annoncés.

Une différence non expliquée rend le cycle partiel. La documentation officielle
montre actuellement des formes de `next` hétérogènes : URL relative ou URL
absolue en `http`, parfois avec un paramètre `api_key`. Le test réel doit en
confirmer la forme. Dans tous les cas, l'adaptateur :

1. accepte uniquement une URL relative ou une URL absolue dont l'hôte est
   exactement `api.datatourisme.fr`, sans port inattendu ;
2. extrait le chemin et la requête nécessaires à la pagination, puis reconstruit
   la requête sur l'origine HTTPS configurée ; il n'effectue jamais de requête
   HTTP en clair ;
3. retire tout paramètre `api_key` reçu et transmet exclusivement sa propre clé
   configurée dans l'en-tête `X-API-Key` ;
4. refuse un chemin non prévu et toute redirection vers un autre hôte ;
5. ne journalise et ne persiste qu'une forme assainie, sans secret.

Cette canonicalisation conserve le curseur opaque fourni sans permettre au
fournisseur de rediriger la clé. Les chemins exacts acceptés seront figés par
le test de contrat afin de ne pas casser une transition documentée entre
l'endpoint préfiltré et `/catalog`.

### 6.5 Identité et déduplication

L'UUID DATAtourisme identifie d'abord l'objet publié par cette source. Il ne
devient l'identité d'une édition commerciale qu'après validation de son usage
sur des événements récurrents et sur plusieurs éditions annuelles.

Tant que le fournisseur conserve le même UUID pour la même édition, une
nouvelle observation met à jour la même fiche. Deux UUID différents restent
deux fiches distinctes dans le MVP, même si leur titre, leur lieu et leurs dates
se ressemblent. Ils peuvent être signalés ou masqués manuellement comme
doublons, mais ne sont jamais fusionnés automatiquement.

Si le test montre qu'un UUID est réutilisé pour des éditions commercialement
distinctes, l'adaptateur devra produire une identité d'édition documentée, par
exemple à partir d'un identifiant d'édition réellement stable fourni par la
source. Une simple date mutable ne sera pas choisie sans preuve de stabilité.
Le modèle générique accepte cette identité composée tout en conservant l'UUID
brut dans la provenance.

L'URI est conservée lorsqu'elle existe, mais n'est pas substituée à l'UUID sans
validation spécifique.

### 6.6 Périodes et état temporel

Chaque élément de `takesPlaceAt` est normalisé sans perdre les valeurs source :

- date et heure de début ;
- date et heure de fin ;
- éventuels jours et semaines de récurrence publiés ;
- détails textuels d'ouverture ou de période.

Un intervalle continu devient une période. Plusieurs intervalles non
consécutifs restent plusieurs périodes de la même fiche si DATAtourisme les
regroupe sous une même identité d'édition validée. La seule réutilisation d'un
UUID ne suffit pas si elle désigne en réalité plusieurs éditions commerciales.
Radar n'invente aucune occurrence future à partir d'un titre ou d'une habitude
supposée.

Les valeurs sont interprétées dans le fuseau Europe/Paris lorsqu'aucun fuseau
explicite n'est fourni, tout en conservant la valeur source. Si une heure de
fin manque, la règle de fin de journée définie dans `docs/product.md`
s'applique.

Les cas récurrents, les heures manquantes et les changements de dates doivent
faire partie de l'échantillon de validation. Une période illisible rend
l'observation invalide et visible dans le bilan ; elle ne produit pas une date
inventée.

### 6.7 Organisateur, contacts et statut

La propriété DATAtourisme `hasBeenCreatedBy` identifie le producteur de la
donnée. Elle ne doit pas être présentée automatiquement comme l'organisateur
de l'événement.

De même, un contact général, administratif, de réservation ou de publication
n'est présenté comme contact confirmé de l'organisateur que si la source
l'indique explicitement. Dans les autres cas, Radar conserve sa portée comme
« inconnue » ou le présente comme relais de contact.

Un statut « annulé » ou « reporté » n'est appliqué que depuis une propriété
structurée dont le sens a été validé. Il n'est pas déduit automatiquement d'un
mot dans le titre ou la description. L'endpoint `POST /catalog/{uuid}/contact`
permet au fournisseur de relayer certains messages, mais Radar ne l'utilise
pas dans le MVP, qui n'envoie aucun email.

### 6.8 Fraîcheur et disparition

La collecte DATAtourisme est exécutée chaque nuit selon le fuseau Europe/Paris
et peut être lancée manuellement.

Une absence unique ne modifie pas la fiche. Une observation peut être marquée
« potentiellement obsolète » seulement si :

1. elle était attendue dans le même périmètre ;
2. elle manque lors de trois cycles complets et comparables consécutifs ;
3. une vérification ciblée de son UUID et de son identité d'édition ne retrouve
   plus cette édition, ou confirme son retrait.

Ce marquage ne signifie ni « annulé », ni « masqué », ni « supprimé ». Une
nouvelle observation reconnue comme la même identité d'édition lève le signal
d'obsolescence.

## 7. Reprises, quotas et erreurs

Tous les adaptateurs HTTP suivent les règles communes suivantes :

- délai de connexion et de lecture borné ;
- nouvelle tentative avec attente progressive pour les erreurs réseau, `429`
  et erreurs serveur temporaires ;
- respect de `Retry-After` lorsqu'il est fourni ;
- aucune répétition aveugle des erreurs fonctionnelles `4xx` ;
- nombre maximal de tentatives par page ;
- reprise depuis le dernier point sûr uniquement si le protocole du
  fournisseur le garantit ;
- sinon, reprise complète de la requête logique ;
- journal sans clé, mot de passe, contact personnel inutile ou corps brut
  sensible.

Les valeurs exactes de temporisation et les horaires des tâches seront définis
dans `docs/architecture.md`.

## 8. Validation réelle autour de Dax

### 8.1 Adresse de référence

La mairie publie l'adresse postale suivante :

```text
Mairie de Dax, rue Saint-Pierre, CS 9007
40107 Dax Cedex
```

Pour rechercher le point physique, le contrôle préliminaire utilise
`12 rue Saint-Pierre, 40100 Dax`. Le point géocodé est présenté à l'utilisateur
avant de créer le cercle de 50 km. Le test doit inclure des communes de
plusieurs départements si le cercle les rencontre ; aucune limite
administrative n'est ajoutée.

### 8.2 Prérequis

La validation complète nécessite :

- une clé publique API Sirene configurée localement ;
- une clé API DATAtourisme configurée localement ;
- le millésime courant des contours administratifs ;
- le fichier courant de géolocalisation Sirene tant que cette source reste
  dans le MVP.

Les clés ne doivent pas être communiquées dans un document, un ticket, une
capture d'écran ou une conversation. Elles seront placées directement dans la
configuration secrète de l'environnement de test.

### 8.3 Contrôles Sirene

Le rapport de validation doit consigner :

- la requête logique et la version d'API ;
- les communes candidates et la version de leurs contours ;
- les lots, totaux annoncés, pages, SIRET reçus et SIRET uniques ;
- des exemples d'établissements actifs, fermés, sièges et non-sièges ;
- le comportement des périodes historiques et de la période courante ;
- les statuts de diffusion `O` et `P`, sans exploiter les données protégées ;
- la concordance entre API, fichier géographique et géocodage de repli ;
- la répartition dans le rayon, hors rayon et « Localisation à vérifier » ;
- les champs réellement disponibles et les anomalies observées ;
- la durée, le nombre d'appels et tout incident de quota.

### 8.4 Contrôles DATAtourisme

Le rapport doit consigner :

- la requête, les champs demandés et la version d'API ;
- le total, toutes les pages suivies par `next` et les UUID uniques ;
- des événements simples, continus, récurrents et publiés longtemps à
  l'avance ;
- les événements sans contact ou organisateur ;
- les positions, adresses et distances recalculées ;
- la stabilité des UUID entre deux collectes ;
- le comportement des UUID entre deux éditions annuelles distinctes et pour
  les événements récurrents ;
- les producteurs de données et les contacts sans les confondre avec les
  organisateurs ;
- les statuts explicites disponibles et les changements de dates ;
- les champs manquants, valeurs inattendues et objets rejetés.

### 8.5 Critère de sortie

Un connecteur n'est validé pour le MVP que lorsque son rapport démontre une
pagination terminée, des comptages cohérents, une normalisation reproductible
et l'absence d'omission silencieuse connue. Les anomalies restantes sont
classées en :

- bloquantes avant implémentation ;
- acceptables avec affichage explicite ;
- limites connues de la source.

## 9. Sources postérieures au MVP

L'ordre envisagé reste :

1. Annuaire officiel de l'administration française ;
2. Répertoire National des Associations ;
3. OpenAgenda ;
4. agendas locaux dont l'apport est démontré ;
5. enrichissement contrôlé depuis les sites officiels.

Une nouvelle source n'est ajoutée qu'après avoir vérifié :

- sa couverture supplémentaire réelle ;
- sa licence, ses CGU et ses règles de réutilisation ;
- sa stabilité et sa fréquence de mise à jour ;
- ses identifiants, sa pagination et ses quotas ;
- les champs utiles qu'elle apporte ;
- le coût de normalisation et les risques de doublons ;
- sa capacité à conserver une provenance claire.

Le futur enrichissement web n'est pas un crawler généraliste. Il partira
uniquement d'un site officiel déjà associé à une fiche, respectera les règles
d'accès applicables et limitera profondeur, fréquence et domaines. Chaque
email, téléphone ou rôle trouvé conservera l'URL exacte et la date de lecture.
Les coordonnées privées ou sans rapport professionnel ne seront pas
collectées.

## 10. Points à résoudre avant de valider les connecteurs

La rédaction peut continuer, mais les points suivants doivent être résolus
avant de considérer les connecteurs concernés comme terminés :

1. obtenir et configurer localement une clé publique Sirene et une clé
   DATAtourisme ;
2. tester l'expression exacte garantissant l'état courant dans la recherche
   multicritère Sirene ;
3. comparer les coordonnées intégrées à l'API Sirene 3.11 au fichier mensuel
   et décider si ce dernier reste nécessaire au MVP ;
4. fixer les niveaux de qualité géographique après examen du fichier réel ;
5. déterminer si l'UUID DATAtourisme identifie durablement une édition ou s'il
   faut une règle d'identité spécifique aux éditions récurrentes ;
6. valider le mapping complet des périodes, contacts, organisateurs et statuts,
   ainsi que les formes et chemins de pagination `next`, sur des réponses
   DATAtourisme réelles ;
7. valider le traitement minimal et licite d'un passage Sirene en diffusion
   partielle avant une mise en production.

## 11. Références officielles

- [API Sirene open data — data.gouv.fr](https://www.data.gouv.fr/dataservices/api-sirene-open-data)
- [Accès et téléchargement de Sirene — Insee](https://www.insee.fr/fr/information/3591226)
- [Actualités Sirene de juin 2026 — Insee](https://www.insee.fr/fr/information/9019311)
- [Modalités de connexion à l'API Sirene](https://static.insee.fr/api-sirene/Insee_API_publique_modalites_connexion.pdf)
- [Géolocalisation des établissements Sirene](https://www.data.gouv.fr/datasets/geolocalisation-des-etablissements-du-repertoire-sirene-pour-les-etudes-statistiques)
- [API de géocodage de la Géoplateforme](https://cartes.gouv.fr/aide/fr/guides-utilisateur/utiliser-les-services-de-la-geoplateforme/geocodage/)
- [Contours administratifs — data.gouv.fr](https://www.data.gouv.fr/datasets/contours-administratifs)
- [API Découpage administratif](https://www.data.gouv.fr/dataservices/api-decoupage-administratif-api-geo)
- [Documentation de l'API DATAtourisme v1](https://api.datatourisme.fr/v1/docs)
- [FAQ et conditions d'accès DATAtourisme](https://www.datatourisme.fr/faq/)
- [Ressources juridiques DATAtourisme](https://www.datatourisme.fr/ressources-juridiques/)
- [Adresse de la mairie de Dax](https://www.dax.fr/fiche-annuaire/mairie/)
