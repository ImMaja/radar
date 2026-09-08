# Radar — Sources de données externes

> Statut : contrats du MVP validés autour de Dax
>
> Dernière mise à jour : 8 septembre 2026
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

| Besoin | Source retenue | Fréquence | Accès | État au 6 septembre 2026 |
| --- | --- | --- | --- | --- |
| Géocoder l'adresse de référence | API de géocodage de la Géoplateforme | À la demande | Sans clé, 50 requêtes/s/IP | Appel unitaire validé ; repli des établissements à tester dans l'adaptateur |
| Trouver les communes candidates | Jeu « Contours administratifs » de data.gouv.fr | À chaque nouveau millésime utile | Téléchargement ouvert | Millésime 2026 testé et validé |
| Découvrir et actualiser les établissements | API Sirene 3.11 de l'Insee | Mensuelle et manuelle | Compte et clé publique, 30 requêtes/min | Contrat, lots et curseur validés |
| Géolocaliser les établissements Sirene | Coordonnées API puis fichier mensuel officiel de géolocalisation Sirene | Mensuelle | API et téléchargement ouvert | Stratégie hybride validée |
| Découvrir et actualiser les événements | API DATAtourisme v1 | Chaque nuit et manuelle | Clé gratuite, 1 000 requêtes/h | Contrat, champs et pagination validés |

Les limites ci-dessus sont celles publiées à la date du document. Les
adaptateurs doivent traiter les réponses de limitation et ne pas supposer que
ces valeurs resteront inchangées.

Les mesures et anomalies de cette validation sont consignées dans
`docs/source-validation-dax-2026-09.md`. Elles décrivent un essai daté, pas un
volume garanti par les fournisseurs.

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

Le contrôle finalisé le 6 septembre 2026 pour
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

Avec le millésime 2026 et le point de Dax retenu, le cercle exact de 50 km
intersecte 405 communes. La présélection élargie de 1 km en retient 418, dont
228 dans les Landes et 190 dans les Pyrénées-Atlantiques. Le connecteur
interroge ces 418 communes, puis filtre les coordonnées des établissements sur
le cercle métier exact. Ces nombres sont des résultats de validation et seront
recalculés pour tout autre centre ou millésime.

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

Les variables d'état sont historisées dans Sirene. Le contrat testé le
6 septembre 2026 utilise le paramètre logique suivant, avec un paramètre
`date` capturé au début du cycle :

```text
(
  codeCommuneEtablissement:<code-1>
  OR codeCommuneEtablissement:<code-2>
  OR ...
)
AND periode(etatAdministratifEtablissement:A)
AND etatAdministratifUniteLegale:A
AND statutDiffusionEtablissement:O
AND statutDiffusionUniteLegale:O
```

Sur l'endpoint SIRET testé, l'état historique de l'établissement exige
`periode(...)`, tandis que `etatAdministratifUniteLegale:A` doit rester hors
de cette fonction. Le cycle utilise également `nombre=1000` et un curseur
initial `*`.

Indépendamment du filtre serveur, l'adaptateur vérifie la période courante et
les statuts de chaque réponse avant de créer une fiche. Trois objets de la
validation n'étaient déjà plus actifs lors de ce contrôle postérieur. Ils sont
comptés comme reçus pour réconcilier la pagination, mais rejetés de l'import
métier. Une période historique active ne suffit jamais.

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
cohérents. Après épuisement des reprises, une différence inexpliquée, même
faible, rend le cycle `PARTIAL` si des observations exploitables ont été
conservées, sinon `FAILED`.
Comme l'API est interrogée en direct, un cycle couvrant plusieurs requêtes
n'est pas un instantané atomique. La date de chaque requête est donc conservée
et une incohérence possiblement due à une mise à jour concurrente donne lieu à
une nouvelle tentative complète du lot avant de conclure à un échec.

L'Insee limite à 1 000 le nombre d'opérateurs `AND` ou `OR` dans un même groupe
de parenthèses. En pratique, un essai avec 80 codes commune a reçu une réponse
HTTP `414`. Le MVP fixe donc un plafond opérationnel conservateur de 30 codes
par lot ; ce n'est pas une limite contractuelle annoncée par l'Insee.

Le test complet sur les 405 communes du cercle exact a utilisé 14 lots et 182
requêtes espacées de 2,55 secondes. Il a réconcilié 160 165 résultats annoncés,
160 165 lignes reçues et 160 165 SIRET uniques, sans doublon inter-lots. Le lot
le plus grand a fourni 31 122 résultats sur 32 pages non vides, suivies d'une
réponse terminale vide. Cela valide le passage au-delà des 10 000 résultats par
curseur. Ces lignes restent des candidats bruts issus de communes
sur-sélectionnées, pas autant de prospects dans le cercle.

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
- identifiant d'adresse et coordonnées publiées par l'API, pour la
  géolocalisation opérationnelle et le contrôle croisé des sources.

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

La validation a arrêté une stratégie hybride. La position courante publiée
par l'API Sirene est utilisée en priorité lorsqu'elle satisfait les contrôles
déterministes ci-dessous. Le jeu mensuel
[« Géolocalisation des établissements du répertoire SIRENE pour les études
statistiques »](https://www.data.gouv.fr/datasets/geolocalisation-des-etablissements-du-repertoire-sirene-pour-les-etudes-statistiques)
reste nécessaire comme source indépendante de qualité géographique et comme
repli lorsque la coordonnée API n'est pas utilisable.

Ce jeu contient notamment le SIRET, des coordonnées X/Y Lambert-93, des
coordonnées longitude/latitude WGS84, le code commune et des variables de
qualité. Le fichier d'août 2026 pèse `809 215 388` octets au format Parquet et
contient `37 820 296` lignes ; son volume doit être pris en compte sans être
confondu avec le volume final conservé par Radar.

Le traitement doit :

1. découvrir la ressource courante par son URL stable data.gouv.fr ;
2. télécharger dans un fichier temporaire ;
3. contrôler le format, la taille, l'empreinte et les colonnes obligatoires ;
4. conserver le millésime et la date de publication ;
5. joindre les candidats Sirene au fichier par SIRET sans charger toutes ses
   lignes dans PostgreSQL ;
6. contrôler les coordonnées WGS84 fournies et, si nécessaire, transformer les
   coordonnées Lambert-93 pour vérification ;
7. conserver séparément la provenance et la qualité de cette position ;
8. ne publier le nouveau millésime comme utilisable qu'après réussite de tous
   les contrôles.

Le fichier et l'API Sirene peuvent représenter des dates différentes. Un
établissement récent absent du fichier n'est donc pas considéré comme
inexistant.

Les codes de qualité du fichier sont normalisés ainsi :

| Code | Interprétation source | Précision Radar | Utilisabilité initiale |
| --- | --- | --- | --- |
| `11` | Voie sûre, numéro trouvé | `ADDRESS` | `USABLE` |
| `12` | Voie sûre, position aléatoire dans la voie | `STREET` | `USABLE`, approximation visible |
| `21` | Voie probable, numéro trouvé | `ADDRESS` | `USABLE`, approximation visible |
| `22` | Voie probable, position aléatoire dans la voie | `STREET` | `USABLE`, approximation visible |
| `33` | Voie inconnue, position aléatoire dans la commune | `MUNICIPALITY` | `TO_VERIFY` |

Le code et la précision du fichier restent attachés exclusivement à sa propre
coordonnée ; ils ne sont jamais transférés à la coordonnée API. Chaque position
candidate est validée séparément. Elle doit :

- contenir deux nombres finis transformables en WGS84 ;
- appartenir au contour de la France métropolitaine ;
- porter le même code commune que l'adresse Sirene courante ;
- se trouver dans le contour de cette commune ou à un kilomètre au plus de ce
  contour, marge initiale qui absorbe la généralisation géométrique et les cas
  proches d'une limite.

Une position qui échoue à l'un de ces contrôles n'est pas utilisable. Une
coordonnée API qui les satisfait reste `UNKNOWN/USABLE` en l'absence de qualité
propre : elle n'est jamais présentée comme une position au numéro de rue. La
marge de cohérence d'un kilomètre est versionnée avec la règle de résolution et
n'est pas un réglage utilisateur.

Le géocodeur de la Géoplateforme est appelé seulement lorsqu'aucune position
n'a pu être retenue par les règles ci-dessous, notamment lorsque l'API échoue
aux contrôles et que le fichier manque ou vaut `TO_VERIFY`. La requête, le
résultat, le score, la date et le fournisseur restent distincts des deux
sources Sirene. Si aucune position n'est assez fiable, la fiche va dans
« Localisation à vérifier » et sa distance reste inconnue.

### 5.7 Résultats géographiques et résolution

Sur 160 165 candidats Sirene, l'API fournissait 129 689 coordonnées et en
laissait 30 476 sans coordonnées numériques. Le fichier mensuel a joint
158 895 candidats : il fournit 30 402 positions absentes de l'API et ne laisse
que 74 candidats sans position issue des deux sources. Le fichier reste donc
dans le MVP.

Pour les 128 493 candidats présents dans les deux sources, l'écart médian
était de 20,1 m, mais 1 976 écarts dépassaient 1 km et deux dépassaient 100 km.
Radar conserve les deux provenances et ne masque pas ces divergences.

La résolution suit cet ordre :

1. conserver les coordonnées API et fichier dans deux observations distinctes,
   avec la qualité et la provenance propres à chacune ;
2. appliquer à chacune les contrôles déterministes précédents ;
3. retenir la coordonnée API valide comme position effective, avec la précision
   `UNKNOWN`, sans lui attribuer le code de qualité du fichier ;
4. si l'API n'est pas utilisable, retenir la coordonnée valide du fichier pour
   les qualités `11`, `12`, `21` ou `22` ;
5. appeler la Géoplateforme si aucune de ces positions n'est utilisable ou si
   le seul repli fichier porte la qualité `33` ;
6. conserver « Localisation à vérifier » si aucun résultat suffisant n'est
   obtenu.

Un écart supérieur à un kilomètre entre les deux sources est conservé comme
diagnostic visible, mais ne transfère aucune qualité et n'invalide pas à lui
seul une coordonnée qui satisfait ses propres contrôles : les millésimes et les
précisions peuvent différer. Un échec de cohérence avec la commune, en revanche,
écarte la position concernée de la résolution automatique.

Le classement brut avec la coordonnée API puis le fichier en repli a donné
146 166 positions dans le cercle exact, 13 925 hors cercle et 74 absences.
Une coordonnée de qualité `33` ne décide toutefois jamais seule de l'inclusion
exacte : son établissement reste à vérifier tant qu'aucun meilleur point
n'existe.

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
plus réutilisables pour la prospection. La procédure prudente est une purge de
la fiche de prospection suivie, si sa conformité est confirmée, de la seule
empreinte nécessaire pour ne pas la réimporter. Cette documentation ne
constitue pas un avis juridique.

Le statut de diffusion le plus récent doit être réconcilié pour tous les
SIRET connus : un changement de diffusion ne modifie pas nécessairement
`dateDernierTraitement`. La solution technique prudente envisagée après un
passage en `P` est de purger la fiche de prospection puis de conserver dans une
liste repoussoir dédiée uniquement une HMAC du SIRET ou du SIREN, avec une clé
hors base. Sa base légale et sa durée restent à valider avant le début du
jalon 6.

Un contrôle ciblé du 7 septembre 2026 a recherché un établissement publié en
diffusion partielle, puis l'a redemandé par son SIRET sans conserver cet
identifiant dans le rapport. Les deux appels ont répondu `200`, la recherche
ciblée a retrouvé le même objet, et l'établissement comme son unité légale
étaient administrativement actifs mais en diffusion `P`. Le chemin technique
permet donc de distinguer cette restriction d'une fermeture ; ce test ne décide
pas de la politique juridique de conservation.

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

La liste validée couvre au minimum `uuid`, `uri`, `identifier`, `label`,
`type`, `isLocatedAt`, `hasDescription`, `takesPlaceAt`, `hasContact`,
`hasBookingContact`, `hasBeenCreatedBy`, `hasBeenPublishedBy`, `isOwnedBy`,
`lastUpdate`, `lastUpdateDatatourisme` et `isObsolete`. Les autres rôles de
contact documentés peuvent être demandés, même s'ils étaient absents de
l'échantillon. Comme le paramètre `fields` remplace la sélection par défaut,
un champ omis de cette liste ne sera jamais supposé absent de la source.

Radar n'envoie aucun filtre de date au fournisseur. Le test réel a montré
qu'une borne de début peut exclure un événement déjà commencé mais toujours en
cours. Après normalisation, une nouvelle fiche n'est créée que si au moins une
période valide publiée n'est pas terminée. Les événements déjà connus restent
conservés après leur passage dans le passé.

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

Après épuisement des reprises, une différence non expliquée rend le cycle
`PARTIAL` si des observations exploitables ont été conservées, sinon `FAILED`.
Lors du test du
6 septembre 2026, les liens `next` étaient des URL HTTPS vers l'hôte et
l'endpoint attendus, sans paramètre `api_key`. Cette forme observée n'est pas
considérée comme une garantie permanente. Dans tous les cas, l'adaptateur :

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
fournisseur de rediriger la clé. Le chemin validé est
`/v1/entertainmentAndEvent` ; toute évolution est d'abord traitée comme une
rupture de contrat visible.

La collecte validée a réconcilié 2 836 objets annoncés et reçus, 2 836 UUID
uniques et 12 pages, dont une dernière page de 86 objets. Une répétition
immédiate a produit le même ensemble d'UUID. Cela prouve la stabilité de cette
exécution à court terme, pas celle de tous les objets à travers les années.

### 6.5 Identité et déduplication

Pour le MVP, le couple `(DATAtourisme, UUID)` identifie l'objet publié par
cette source et donc la fiche qu'il met à jour. Toutes les périodes publiées
par cet objet restent rattachées à cette fiche, y compris lorsqu'elles couvrent
plusieurs années. Ce choix respecte le regroupement du fournisseur sans
inventer un discriminant à partir d'une date mutable.

Deux UUID différents restent deux fiches distinctes, même si leur titre, leur
lieu et leurs dates se ressemblent. Ils peuvent être signalés ou masqués
manuellement comme doublons, mais ne sont jamais fusionnés automatiquement.
Une réutilisation future clairement contradictoire d'un UUID est signalée
comme une rupture du contrat source ; elle ne déclenche pas silencieusement
une nouvelle formule d'identité.

L'observation concernée est alors conservée en quarantaine pour le diagnostic,
sans devenir la projection courante ni créer une seconde fiche. Le cycle est
`PARTIAL` et l'objet reste bloqué jusqu'à une évolution explicite, documentée et
testée du contrat de la source.

L'URI et `identifier` sont conservés pour la provenance et le diagnostic, mais
ne se substituent pas à l'UUID comme clé de rapprochement.

### 6.6 Périodes et état temporel

Chaque élément de `takesPlaceAt` est normalisé sans perdre les valeurs source :

- date et heure de début ;
- date et heure de fin ;
- éventuels jours et semaines de récurrence publiés ;
- détails textuels d'ouverture ou de période.

Un intervalle continu devient une période. Plusieurs intervalles non
consécutifs restent plusieurs périodes de la même fiche lorsque DATAtourisme
les regroupe sous le même UUID. Radar n'invente aucune occurrence future à
partir d'un titre ou d'une habitude supposée.

Les valeurs sont interprétées dans le fuseau Europe/Paris lorsqu'aucun fuseau
explicite n'est fourni, tout en conservant la valeur source. Si une heure de
fin manque, la règle de fin de journée définie dans `docs/product.md`
s'applique.

La validation a observé 3 231 périodes sur 2 836 objets, dont 167 objets à
périodes multiples et quatre objets dont les débuts couvrent plusieurs
années. Au moment du test, 2 694 objets possédaient une période non passée et
142 seulement des périodes passées. Une période avait un début postérieur à
sa fin.

Une période illisible ou inversée est rejetée et visible dans le bilan ; elle
ne produit pas une date inventée. Les autres périodes valides du même objet
peuvent être importées. Un ensemble vide ou invalide ne remplace jamais le
dernier ensemble source valide d'une fiche connue.

### 6.7 Organisateur, contacts et statut

La propriété DATAtourisme `hasBeenCreatedBy` identifie le producteur de la
donnée. Elle ne doit pas être présentée automatiquement comme l'organisateur
de l'événement.

Le même principe s'applique à `hasBeenPublishedBy` et `isOwnedBy`, qui
décrivent respectivement des rôles de publication et de propriété. Aucun champ
du contrat observé ne fournit un organisateur fiable : l'organisateur source
reste donc inconnu, sauf preuve structurée ajoutée ultérieurement ou correction
de l'utilisateur.

De même, un contact général, administratif, de réservation ou de publication
n'est présenté comme contact confirmé de l'organisateur que si la source
l'indique explicitement. Dans les autres cas, Radar conserve sa portée comme
« inconnue » ou le présente comme relais de contact.

La validation a trouvé des structures de contact sur 2 828 objets, avec des
téléphones et pages web, mais aucune adresse email. Depuis le 26 juin 2026,
DATAtourisme ne diffuse plus les emails dans l'API. Radar enregistre donc
« aucun email connu de cette source », jamais « cet événement n'a pas
d'email ». Les contacts observés gardent une portée inconnue ou de relais et
ne prouvent pas qu'ils appartiennent à l'organisateur.

Aucun statut structuré d'annulation ou de report n'a été observé et
`isObsolete` était absent même lorsqu'il était demandé. Le statut déclaré
DATAtourisme est donc `UNKNOWN`. Il n'est pas déduit d'un mot dans le titre ou
la description. L'endpoint `POST /catalog/{uuid}/contact` peut relayer des
messages au fournisseur, mais Radar ne l'utilise pas : le MVP est strictement
en lecture.

### 6.8 Fraîcheur et disparition

La collecte DATAtourisme est exécutée chaque nuit selon le fuseau Europe/Paris
et peut être lancée manuellement.

Une absence unique ne modifie pas la fiche. Une observation peut être marquée
« potentiellement obsolète » seulement si :

1. elle était attendue dans le même périmètre ;
2. elle manque lors de trois cycles complets et comparables consécutifs ;
3. une vérification ciblée de son UUID ne retrouve plus l'objet, ou confirme
   son retrait.

Ce marquage ne signifie ni « annulé », ni « masqué », ni « supprimé ». Une
nouvelle observation portant le même UUID lève le signal d'obsolescence.

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

La validation a été achevée le 6 septembre 2026. Son compte rendu chiffré est
`docs/source-validation-dax-2026-09.md`.

### 8.1 Adresse de référence

La mairie publie l'adresse postale suivante :

```text
Mairie de Dax, rue Saint-Pierre, CS 9007
40107 Dax Cedex
```

Pour le test, le point physique de `12 rue Saint-Pierre, 40100 Dax` a été
utilisé. Dans le produit, ce résultat sera toujours présenté à l'utilisateur
avant de créer le cercle de 50 km. La zone validée rencontre les Landes et les
Pyrénées-Atlantiques ; aucune limite administrative n'a été ajoutée.

### 8.2 Prérequis utilisés

La validation a utilisé :

- une clé publique API Sirene configurée localement ;
- une clé API DATAtourisme configurée localement ;
- le millésime courant des contours administratifs ;
- le fichier courant de géolocalisation Sirene retenu comme complément et
  repli.

Les clés ne doivent pas être communiquées dans un document, un ticket, une
capture d'écran ou une conversation. Elles ont été placées directement dans
la configuration locale ignorée par Git.

### 8.3 Contrôles Sirene réalisés

Le rapport de validation consigne la requête logique et la version d'API, les
communes candidates, les lots, les totaux, les pages, les SIRET uniques, le
contrôle local de l'état courant et de la diffusion, ainsi que la comparaison
des coordonnées API et du fichier mensuel. Il distingue la répartition brute
dans le rayon, hors rayon et sans position, les qualités approximatives et les
anomalies. Le géocodeur a été validé pour l'adresse de référence ; son repli
sur les établissements devra encore être couvert par des tests d'adaptateur et
un petit échantillon, sans lancer une campagne massive pendant le cadrage.

### 8.4 Contrôles DATAtourisme réalisés

Le rapport consigne la requête et ses champs explicites, les 12 pages suivies
par `next`, les UUID uniques, les positions recalculées, les périodes simples
et multiples, les contacts et les rôles de provenance. Il documente aussi la
stabilité à court terme des UUID, l'absence de statut ou d'organisateur fiable,
le retrait des emails de l'API et la période inversée. La stabilité entre
éditions annuelles reste une limite connue ; l'identité source retenue évite
d'en faire une hypothèse cachée.

### 8.5 Critère de sortie

Un contrat d'entrée est suffisamment validé pour commencer son connecteur
lorsque son rapport démontre une pagination terminée, des comptages cohérents,
des règles de normalisation reproductibles et l'absence d'omission silencieuse
connue. Les anomalies restantes sont classées en :

- préalables au lot d'implémentation concerné ;
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

## 10. Décision à fermer avant le jalon 6

Les contrats techniques des deux sources sont suffisamment validés pour
commencer le socle et les adaptateurs indépendants de cette politique. Il reste
à faire valider avant le début du jalon 6 le
traitement minimal et licite d'un passage Sirene en diffusion partielle :
portée du blocage, purge, finalité et durée éventuelle d'une empreinte HMAC.
Cette question de conformité ne bloque pas le socle applicatif du jalon 2,
mais le connecteur Sirene ne peut pas être mis en production sans sa résolution.

## 11. Références officielles

- [API Sirene open data — data.gouv.fr](https://www.data.gouv.fr/dataservices/api-sirene-open-data)
- [Accès et téléchargement de Sirene — Insee](https://www.insee.fr/fr/information/3591226)
- [Actualités Sirene de juin 2026 — Insee](https://www.insee.fr/fr/information/9019311)
- [Diffusion partielle et droit d'opposition — Insee](https://www.insee.fr/fr/information/6790269?question=sont-informations-diffusees-lesquelles-pouvez-exercer-droit-d-opposition)
- [Liste repoussoir et opposition à la prospection — CNIL](https://www.cnil.fr/fr/comment-utiliser-une-liste-repoussoir-pour-respecter-lopposition-la-prospection)
- [Modalités de connexion à l'API Sirene](https://static.insee.fr/api-sirene/Insee_API_publique_modalites_connexion.pdf)
- [Géolocalisation des établissements Sirene](https://www.data.gouv.fr/datasets/geolocalisation-des-etablissements-du-repertoire-sirene-pour-les-etudes-statistiques)
- [API de géocodage de la Géoplateforme](https://cartes.gouv.fr/aide/fr/guides-utilisateur/utiliser-les-services-de-la-geoplateforme/geocodage/)
- [Contours administratifs — data.gouv.fr](https://www.data.gouv.fr/datasets/contours-administratifs)
- [API Découpage administratif](https://www.data.gouv.fr/dataservices/api-decoupage-administratif-api-geo)
- [Documentation de l'API DATAtourisme v1](https://api.datatourisme.fr/v1/docs)
- [Retrait des adresses email DATAtourisme](https://support.datatourisme.fr/t/protection-des-adresses-email-ce-qui-change/3133)
- [FAQ et conditions d'accès DATAtourisme](https://www.datatourisme.fr/faq/)
- [Ressources juridiques DATAtourisme](https://www.datatourisme.fr/ressources-juridiques/)
- [Adresse de la mairie de Dax](https://www.dax.fr/fiche-annuaire/mairie/)
