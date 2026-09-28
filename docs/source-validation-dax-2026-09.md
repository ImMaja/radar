# Radar — Validation des sources autour de Dax

> Statut : validation technique des contrats du MVP terminée
>
> Contrôles principaux finalisés : 6 septembre 2026, fuseau Europe/Paris
>
> Contrôle ciblé de la diffusion partielle : 7 septembre 2026
>
> Politique de purge arrêtée après revue officielle : 24 septembre 2026
>
> Essai opérationnel du pipeline : 25–27 septembre 2026
>
> Diagnostic ciblé GeoPlateforme : 28 septembre 2026
>
> Périmètre : cercle de 50 km à vol d'oiseau autour de la mairie de Dax

## 1. Objet et conclusion

Ce rapport consigne l'essai réel prévu par `docs/data-sources.md`. Il sépare
les mesures ponctuelles, leur interprétation et les décisions du MVP. Les
données des fournisseurs évoluent : les nombres ci-dessous décrivent le test
du 6 septembre 2026, pas une garantie de volume futur ni une liste exhaustive
des opportunités du territoire.

Aucune clé API, aucun en-tête d'authentification et aucun contact personnel ne
figurent dans ce rapport. Les fichiers de travail et réponses détaillées ne
sont pas ajoutés au dépôt.

| Volet | Observation mesurée | Décision MVP | Statut |
| --- | --- | --- | --- |
| Zone | 405 communes intersectent le cercle exact ; 418 intersectent sa présélection élargie de 1 km | Interroger les 418 communes, puis décider sur la position de chaque établissement et le cercle exact | Validé |
| Sirene | 160 165 SIRET annoncés, reçus et uniques sur 14 lots et 182 requêtes ; curseur parcouru au-delà de 10 000 | Lots de 30 codes commune au maximum, curseur et contrôles locaux obligatoires | Validé |
| Géolocalisation Sirene | API : 129 689 coordonnées ; fichier : 158 895 correspondances ; combinaison : 160 091 positions et 74 absences | Conserver le fichier mensuel ; utiliser la coordonnée API courante en priorité et le fichier en repli, avec sa qualité | Validé avec règles conservatrices |
| DATAtourisme | 2 836 objets annoncés, reçus et UUID uniques sur 12 pages ; même ensemble lors d'une répétition immédiate | Identité `(DATAtourisme, UUID)`, périodes rattachées à l'objet, aucune fusion automatique entre UUID distincts | Contrat d'entrée validé |
| Sémantique annuelle DATAtourisme | La répétition prouve seulement une stabilité à court terme ; quatre objets couvrent plusieurs années | Respecter le regroupement de la source et ne pas inventer un discriminant annuel | Limite connue, non bloquante |

Le jalon 1 est donc suffisamment clos pour commencer le socle applicatif. La
politique technique de diffusion partielle a depuis été arrêtée : purge
complète sans conservation d'une empreinte identifiante ou pseudonymisée, avec
seuls des compteurs agrégés.

## 2. Périmètre et méthode

Le géocodeur de la Géoplateforme a retenu pour
`12 rue Saint-Pierre, 40100 Dax` :

- libellé : `12 Rue Saint Pierre 40100 Dax` ;
- code commune : `40088` ;
- identifiant BAN : `40088_1750_00012` ;
- longitude : `-1.051952` ;
- latitude : `43.70884` ;
- score de rapprochement : environ `0,9653`.

Ce résultat correspond au centre demandé pour le test. Dans le produit, un
résultat de géocodage restera présenté à l'utilisateur avant confirmation : le
premier résultat et son score ne prouvent pas seuls l'exactitude physique.

Les calculs géographiques utilisent une projection azimutale équidistante
centrée sur ce point. Un second calcul en Lambert-93 a produit la même liste de
405 communes pour le cercle exact. Le test Sirene complet a porté sur ces 405
communes. Le connecteur de production ajoutera la marge documentaire de 1 km,
soit 13 communes de bordure supplémentaires, puis appliquera toujours le
filtre ponctuel exact de 50 km.

Les API ont été interrogées en lecture seule. Sirene a été limitée à une
requête toutes les 2,55 secondes, soit environ 23,5 requêtes par minute, sous
la limite publiée de 30 requêtes par minute. DATAtourisme a été parcouru avec
une seule requête en vol, très loin des limites communiquées de 20 à 30
requêtes concurrentes, d'environ 10 requêtes par seconde en régime prolongé
et de 1 000 requêtes par heure.

## 3. Référentiel des communes

Le millésime 2026 du fichier `communes-100m.geojson.gz` des
[Contours administratifs](https://www.data.gouv.fr/datasets/contours-administratifs)
a été contrôlé :

- taille téléchargée : `8 237 354` octets ;
- empreinte SHA-256 :
  `4530cbf87a3af387c2da95935376f74b93eabd0a7595eacc5b7e0ed94a0b3778` ;
- 35 014 codes commune uniques ;
- 34 768 géométries `Polygon` et 246 `MultiPolygon` ;
- aucune géométrie invalide parmi les candidates examinées.

Le chargement PostGIS exhaustif réalisé le 20 septembre 2026 a précisé ce
dernier point : 16 contours invalides existent dans le fichier complet, mais
aucun dans la sélection autour de Dax. Radar en charge 34 791 pour la France
métropolitaine, répare ces 16 topologies avec `ST_MakeValid`, enregistre ce
compteur dans la provenance et revérifie chaque résultat. Le contrôle réel de
la requête géodésique `ST_DWithin` retrouve les 418 candidates attendues ; un
tampon polygonal approximatif n'en retrouvait que 417 et n'est donc pas utilisé.

Le cercle exact intersecte 405 communes : 224 dans les Landes et 181 dans les
Pyrénées-Atlantiques. La présélection élargie de 1 km en retient 418 : 228
dans les Landes et 190 dans les Pyrénées-Atlantiques. Ces communes sont des
candidates de requête, pas des communes entièrement situées à moins de 50 km.
Leur étendue explique que de nombreux établissements reçus soient ensuite hors
du cercle exact.

## 4. API Sirene 3.11

### 4.1 Contrat testé

L'endpoint testé est :

```text
GET https://api.insee.fr/api-sirene/3.11/siret
```

Le service annonçait la version `3.11.95` et une dernière disponibilité des
établissements au `2026-09-06T07:44:27`. La sélection logique validée est :

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

Elle a été envoyée avec la date du jour, `nombre=1000` et le curseur initial
`*`. Le champ historique de l'établissement exige `periode(...)`. Sur le
service SIRET testé, l'état de l'unité légale doit au contraire rester un
critère courant sans `periode(...)` ; cette seconde forme a été refusée comme
syntaxe invalide.

Même avec ce filtre, l'adaptateur devra relire les périodes courantes et les
statuts de chaque objet. L'API est vivante et la pagination de plusieurs lots
ne constitue pas un instantané atomique.

### 4.2 Lots, curseur et comptages

Un essai réunissant 80 codes commune dans une requête a reçu une réponse HTTP
`414`. Ce constat ne constitue pas une limite contractuelle de l'Insee : il
justifie un plafond opérationnel conservateur de 30 codes par lot pour le MVP.

| Lot | Communes | Total annoncé | Appels paginés | Lignes reçues | SIRET uniques |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 30 | 4 890 | 6 | 4 890 | 4 890 |
| 2 | 30 | 13 826 | 15 | 13 826 | 13 826 |
| 3 | 30 | 7 087 | 9 | 7 087 | 7 087 |
| 4 | 30 | 9 990 | 11 | 9 990 | 9 990 |
| 5 | 30 | 13 611 | 15 | 13 611 | 13 611 |
| 6 | 30 | 8 515 | 10 | 8 515 | 8 515 |
| 7 | 30 | 21 361 | 23 | 21 361 | 21 361 |
| 8 | 30 | 18 317 | 20 | 18 317 | 18 317 |
| 9 | 30 | 31 122 | 33 | 31 122 | 31 122 |
| 10 | 30 | 8 972 | 10 | 8 972 | 8 972 |
| 11 | 30 | 5 823 | 7 | 5 823 | 5 823 |
| 12 | 30 | 5 065 | 7 | 5 065 | 5 065 |
| 13 | 30 | 7 509 | 9 | 7 509 | 7 509 |
| 14 | 15 | 4 077 | 6 | 4 077 | 4 077 |
| **Total** | **405** | **160 165** | **181** | **160 165** | **160 165** |

Les 181 appels paginés comprennent 167 réponses contenant des lignes et une
réponse terminale vide pour chacun des 14 lots. Avec l'appel d'information du
service, le test totalise 182 requêtes. Aucun SIRET n'est apparu dans deux lots.
Le plus grand lot a parcouru 32 pages non vides, puis sa réponse terminale, pour
31 122 résultats : la pagination par curseur franchit donc bien la barrière des
10 000 résultats de la pagination classique.

Le contrôle effectué après la collecte a trouvé trois objets dont la période
courante d'établissement n'était plus active. Aucun écart n'a été observé sur
l'état de l'unité légale, les deux statuts de diffusion, le code commune ou la
présence du SIRET. Ces trois objets ne doivent pas devenir des prospects. Cette
anomalie illustre une mise à jour concurrente possible et rend obligatoire la
validation locale de chaque objet, puis la reprise du lot si ses comptages ne
se réconcilient plus.

Les 160 165 lignes sont des établissements bruts candidats issus de communes
sur-sélectionnées. Elles ne sont ni 160 165 prospects dans le rayon ni une
mesure de tous les organismes réels autour de Dax.

### 4.3 Détection ciblée de la diffusion partielle

Un contrôle complémentaire en lecture seule, le 7 septembre 2026, a recherché
un établissement publié avec le statut de diffusion `P`, puis l'a redemandé par
son SIRET. L'identifiant n'a été ni affiché ni conservé dans ce rapport.

Les deux appels ont répondu `200` et le second a retrouvé le même objet. Son
établissement et son unité légale étaient administrativement actifs, mais tous
deux en diffusion `P`. Une recherche ciblée permet donc de reconnaître cette
restriction sans l'assimiler à une fermeture. Elle ne répond pas à la question
juridique distincte des données qui peuvent ensuite être conservées.

## 5. Géolocalisation Sirene

### 5.1 Couverture observée

Les coordonnées Lambert-93 de l'API étaient numériques et plausibles pour
129 689 candidats, soit `80,97 %`. Elles manquaient ou n'étaient pas
numériques pour 30 476 candidats.

Le fichier officiel
[« Géolocalisation des établissements du répertoire SIRENE pour les études
statistiques »](https://www.data.gouv.fr/datasets/geolocalisation-des-etablissements-du-repertoire-sirene-pour-les-etudes-statistiques)
d'août 2026 a été contrôlé :

- ressource `672007af-0146-491f-835c-8314d63fa44e` ;
- `809 215 388` octets et `37 820 296` lignes ;
- aucun SIRET dupliqué dans le fichier ;
- empreinte SHA-1 vérifiée identique à celle publiée :
  `2d1426cc6ce042f80f492c184541cfd59eb08e0d` ;
- système déclaré `EPSG:2154` pour les 158 895 candidats joints ;
- colonnes Lambert-93 et longitude/latitude WGS84 présentes.

| Couverture de position | Candidats |
| --- | ---: |
| Coordonnée API | 129 689 |
| Ligne et coordonnée dans le fichier | 158 895 |
| API et fichier | 128 493 |
| API seulement | 1 196 |
| Fichier seulement | 30 402 |
| Ni API ni fichier | 74 |

L'API seule est donc insuffisante. Le fichier apporte une position à 30 402
candidats qui n'en ont pas dans l'API et laisse seulement 74 candidats sans
position issue de ces deux sources.

En choisissant la coordonnée API lorsqu'elle est valide, puis celle du fichier
en repli, le classement géométrique brut donne :

- 146 166 positions dans le cercle exact ou sur sa limite ;
- 13 925 positions hors du cercle exact ;
- 74 localisations absentes.

Ces trois comptes réconcilient les 160 165 candidats. Une position disponible
n'est toutefois pas nécessairement assez précise pour devenir une distance
exacte affichable.

### 5.1.1 Essai opérationnel du pipeline

Le premier cycle complet exécuté par le worker les 25–27 septembre 2026 a
utilisé le fichier Parquet de septembre, ressource stable
`672007af-0146-491f-835c-8314d63fa44e` :

- taille `810 724 417` octets et `37 901 783` lignes ;
- SHA-1 publié et vérifié :
  `bd2901c1ce81a862cf733e41b2b6d9046b258273` ;
- 19 colonnes publiées en minuscules, avec les neuf champs métier attendus ;
- 161 506 établissements annoncés, reçus et uniques sur 14 lots et 182 pages ;
- 161 501 candidats importables et 5 fermetures concurrentes rejetées ;
- 160 429 SIRET joints au fichier et 1 072 absences normales ;
- 14 194 adresses nécessitant le repli Géoplateforme après application des
  règles de qualité et de cohérence communale.

Cet essai a révélé deux tolérances de contrat nécessaires : certaines périodes
historiques Sirene closes ont un état administratif `null`, et la casse des
noms de colonnes du Parquet a changé sans changement sémantique. Radar accepte
désormais ces deux variations sans relâcher le contrôle de l'état courant, des
colonnes requises ni de leurs types.

Le repli a persisté 9 449 issues avant trois erreurs classées comme temporaires
par l'adaptateur. Les reprises n'ont rejoué ni les pages Sirene, ni la jointure
Parquet, ni les issues déjà conservées. Le cycle s'est terminé `PARTIAL`, avec
4 745 adresses encore en attente, zéro fiche prospect et aucune couverture
publiée. Il valide donc les frontières de reprise et d'absence de faux succès,
mais pas encore le critère de sortie opérationnel du jalon 6.

À la suite de cet essai, l'adaptateur et l'exécution persistée distinguent les
erreurs réseau, limitations `429`, autres statuts HTTP temporaires, erreurs
serveur et requêtes fonctionnellement rejetées. Le prochain diagnostic
conservera le statut, le nombre d'essais et l'éventuel `Retry-After`, sans
conserver dans l'erreur l'adresse ni le corps fournisseur. Cette amélioration
n'identifie pas rétroactivement la réponse des trois tentatives déjà terminées.
L'exécution locale historique, restée à tort `RUNNING` sous ce cycle déjà
`PARTIAL`, a été remise en cohérence en `FAILED` sans modifier ses 9 449 issues
ni ses compteurs. La clôture atomique empêche désormais cette incohérence pour
les futurs cycles.

Après autorisation explicite, un premier appel ciblé a retransmis directement
la première adresse professionnelle restante au service officiel, sans
afficher ni conserver sa valeur ou le corps de réponse. Il a reçu un HTTP 400
sans `Retry-After`, mais le contrôle de la commande a montré que le saut de
ligne terminal de `psql` avait été encodé dans le paramètre `q`. Aucune règle
n'a été déduite de cet essai invalide.

Après une seconde autorisation explicite, l'appel a été répété en supprimant
les retours de ligne avant l'encodage. Le service officiel a de nouveau répondu
`HTTP 400`, sans `Retry-After`. L'adresse n'est pas vide et ne contient aucun
caractère de contrôle, mais sa partie voie se limite à un libellé d'un seul
caractère, sans numéro, répétition ni type de voie ; seuls le code postal et la
commune complètent la recherche.

Une mesure locale, sans nouvel appel externe, a ensuite classé les 4 745 cibles
restantes :

- 1 234 ont exactement cette forme insuffisante, sans numéro, répétition ni
  type de voie et avec un libellé d'au plus un caractère ;
- aucune ne manque de code postal ou de commune ;
- les 3 511 autres conservent une voie localement suffisante et doivent encore
  suivre le contrat Géoplateforme normal.

Radar applique donc un contrôle avant appel : code postal et commune sont
requis ; le libellé doit contenir au moins deux caractères, sauf si un type de
voie est présent, ce qui conserve par exemple `RUE X`. Une cible insuffisante
reste tracée avec l'issue `SKIPPED_INSUFFICIENT_ADDRESS`, une position
`MISSING`, le diagnostic `GEOCODER_SKIPPED_INSUFFICIENT_ADDRESS` et le drapeau
`provider_requested = false`. Elle n'incrémente pas `request_count`. Cette
décision est volontairement plus étroite qu'une conversion générale des HTTP
400 : un tel statut reçu pour une adresse jugée suffisante reste terminal et
signale une éventuelle rupture du contrat fournisseur.

### 5.2 Cohérence et qualité

Pour les 128 493 candidats ayant les deux coordonnées, l'écart médian est de
20,1 m, le 95e percentile de 330,5 m et le 99e percentile de 1 364,0 m. Il
existe 1 976 écarts supérieurs à 1 km et deux anomalies supérieures à 100 km.
Les deux sources n'ont pas le même millésime ; un déménagement ou une erreur
peut donc produire un écart réel. Une divergence n'est jamais résolue en
silence.

La qualité des 30 402 positions apportées uniquement par le fichier est :

| Code | Sens du fournisseur | Nombre | Décision initiale |
| --- | --- | ---: | --- |
| `11` | Voie sûre, numéro trouvé | 8 330 | `USABLE`, précision `ADDRESS`, sauf contradiction |
| `12` | Voie sûre, point aléatoire dans la voie | 3 798 | `USABLE`, précision `STREET`, qualité visible |
| `21` | Voie probable, numéro trouvé | 1 771 | `USABLE`, précision `ADDRESS`, approximation visible |
| `22` | Voie probable, point aléatoire dans la voie | 2 692 | `USABLE`, précision `STREET`, approximation visible |
| `33` | Voie inconnue, point aléatoire dans la commune | 13 811 | `TO_VERIFY` ; ne décide jamais seul l'inclusion exacte |

La règle de résolution du MVP est donc :

1. conserver séparément les coordonnées API et fichier, chacune avec sa propre
   provenance et sa propre qualité ;
2. exiger pour chacune des nombres finis, une position en France
   métropolitaine, le code commune courant et un point dans le contour de cette
   commune ou à un kilomètre au plus de celui-ci ;
3. retenir la coordonnée API qui satisfait ces contrôles avec la précision
   `UNKNOWN/USABLE`, sans lui transférer le code de qualité du fichier ;
4. en l'absence d'API utilisable, retenir le fichier pour les codes `11`, `12`,
   `21` ou `22`, selon le tableau ci-dessus ;
5. envoyer au géocodeur les positions absentes ou invalides et les replis de
   qualité `33` ;
6. conserver dans « Localisation à vérifier » tout cas non résolu, sans
   l'écarter ni lui inventer une distance.

La marge d'un kilomètre est une règle initiale versionnée, pas un réglage
utilisateur. Un écart supérieur à un kilomètre entre deux positions valides est
conservé comme diagnostic, mais ne suffit pas à transférer une qualité ni à
invalider la coordonnée API : les dates et précisions des sources diffèrent.
Cette politique maximise la couverture tout en gardant visibles les
approximations.

## 6. API DATAtourisme v1

### 6.1 Pagination et identité

L'endpoint testé est :

```text
GET https://api.datatourisme.fr/v1/entertainmentAndEvent
```

La requête utilisait le cercle de 50 km, `page_size=250`, la langue française,
aucune borne de date et une liste explicite de champs. Les résultats étaient :

- 2 836 objets annoncés et reçus ;
- 12 pages : 11 pages de 250 objets et une page de 86 ;
- 2 836 UUID présents et uniques ;
- 2 836 URI présentes et uniques ;
- 2 836 positions recalculées dans le cercle, avec une distance maximale de
  49,8593 km ;
- même empreinte de l'ensemble des UUID lors d'une seconde collecte
  immédiate.

Les liens `next` observés utilisaient HTTPS, l'hôte officiel, le même endpoint
et aucun paramètre `api_key`. Ce constat ponctuel ne supprime pas la
canonicalisation défensive : Radar reconstruit toujours l'URL sur l'origine
autorisée, retire tout secret de la requête et refuse un hôte, un port ou un
chemin inattendu.

La stabilité mesurée est uniquement à court terme. Les UUID restent
l'identité des objets publiés par DATAtourisme ; ils ne prouvent pas une notion
universelle d'édition commerciale. Le MVP met donc à jour la même fiche pour
le même UUID, conserve toutes ses périodes et observations, et ne fusionne
jamais automatiquement deux UUID différents. Il ne coupe pas non plus un objet
multiannuel en plusieurs fiches.

### 6.2 Périodes

Les 2 836 objets contenaient 3 231 périodes :

- 167 objets avaient plusieurs périodes, avec un maximum de 78 ;
- toutes les dates de début et de fin étaient lisibles ;
- les dates de début observées allaient du 1er janvier 2025 au
  15 septembre 2029 ;
- 2 694 objets possédaient au moins une période non passée au moment du test ;
- 142 objets ne possédaient que des périodes passées ;
- quatre objets contenaient des débuts sur plusieurs années ;
- une période avait une date de début postérieure à sa date de fin.

La collecte ne doit pas envoyer de borne de date au fournisseur : le test des
paramètres a montré qu'une borne de début exclurait notamment des événements
déjà commencés mais encore en cours. Radar interprète les périodes localement,
ne crée une nouvelle fiche que si au moins une période valide n'est pas
terminée et conserve les fiches déjà connues lorsqu'elles deviennent passées.
La période incohérente est rejetée et comptée sans date inventée ; elle ne
remplace pas un ancien ensemble valide.

### 6.3 Champs, contacts et rôles

Les champs demandés explicitement couvraient notamment l'UUID, l'URI,
l'identifiant producteur, les libellés, types, descriptions, lieux, périodes,
contacts, producteurs, diffuseurs, propriétaires, dates de mise à jour et
`isObsolete`.

- 2 829 objets possédaient une description ;
- 2 828 possédaient une structure `hasContact` et une structure
  `hasBookingContact` ;
- 4 970 objets de contact contenaient un téléphone et 2 828 une page web, avec
  des doublons possibles entre rôles ;
- aucune clé email n'a été renvoyée ; DATAtourisme a retiré l'exposition des
  adresses email de son API le 26 juin 2026 ;
- `hasBeenCreatedBy`, `hasBeenPublishedBy` et `isOwnedBy` décrivent des rôles
  de production, publication ou propriété, pas un organisateur confirmé ;
- aucun statut structuré d'annulation ou de report n'a été observé ;
  `isObsolete`, bien que demandé, était absent des 2 836 objets.

L'absence d'email signifie seulement que cette source n'en expose pas. Un
contact n'est étiqueté « organisateur » que si une future source le dit
explicitement ; dans DATAtourisme, il garde une portée inconnue ou de relais.
Le statut déclaré d'un événement DATAtourisme reste `UNKNOWN`. Radar n'utilise
pas l'endpoint d'envoi de message du fournisseur : le MVP est strictement en
lecture.

## 7. Anomalies et limites

### 7.1 Décision close le 24 septembre 2026

- La revue des informations officielles de l'Insee, de l'article
  R. 123-232-1 du Code de commerce et des recommandations de la CNIL conduit à
  ne conserver aucune liste repoussoir pour le traitement source du MVP. Une
  réponse `P` provoque la purge atomique de la fiche et de toutes ses données
  identifiantes ; seuls la date du cycle et un compteur agrégé subsistent. Le
  filtre des collectes normales sur les seuls statuts `O` empêche la
  réimportation tant que la restriction est publiée.

Il n'existe aucun autre blocage identifié pour commencer le socle applicatif
du jalon 2.

### 7.2 Acceptables avec traitement explicite

- 74 candidats Sirene sans position API ni fichier restent dans
  « Localisation à vérifier » ;
- les qualités géographiques approximatives, divergences entre sources et
  points aléatoires dans une commune ne sont jamais présentés comme exacts ;
- la période DATAtourisme inversée est rejetée et visible dans le bilan ;
- l'absence d'email, d'organisateur ou de statut déclaré n'invalide pas une
  fiche ;
- la stabilité d'un UUID DATAtourisme entre éditions annuelles n'est pas
  démontrée, mais le respect strict de l'objet source évite une fausse fusion.

### 7.3 Limites des sources

- Sirene exclut de la prospection les objets en diffusion partielle et ne
  représente pas les organismes dépourvus de SIRET ;
- les appels Sirene successifs forment une lecture vivante, non un instantané
  atomique ;
- la présence d'une coordonnée ne garantit pas son exactitude ;
- DATAtourisme reflète seulement les données remises par ses producteurs et
  contient de nombreux objets sans intérêt commercial pour un food truck ;
- les volumes observés sont saisonniers et évolueront.

## 8. Décisions figées et sortie du jalon 1

Les contrats suivants peuvent guider les adaptateurs :

1. présélection de 418 communes autour de Dax avec la marge de 1 km, puis
   filtrage local exact à 50 km ;
2. lots Sirene disjoints de 30 codes au maximum, pages de 1 000, curseur suivi
   jusqu'à son terme et réconciliation des totaux et SIRET uniques ;
3. filtre Sirene courant testé et second contrôle local de chaque objet ;
4. coordonnées Sirene API et fichier contrôlées séparément, API prioritaire
   sans transfert de qualité, fichier mensuel conservé en repli, puis
   Géoplateforme et vérification manuelle ;
5. collecte DATAtourisme sans borne de date fournisseur, pagination `next`
   assainie et interprétation temporelle locale ;
6. identité `(DATAtourisme, UUID)`, périodes multiples rattachées, aucun
   discriminant annuel inventé et aucune fusion automatique de deux UUID ; une
   réutilisation future contradictoire place l'observation en quarantaine et le
   cycle en `PARTIAL` sans modifier la fiche ;
7. producteur, diffuseur, propriétaire, relais de contact et organisateur
   restent des rôles distincts ;
8. tout écart de comptage, page manquante ou étape obligatoire inachevée rend
   le cycle `PARTIAL` si au moins une observation exploitable subsiste, sinon
   `FAILED` après épuisement des reprises.

Ces décisions satisfont le critère technique du jalon 1. Les tests ont validé
les contrats d'entrée et leurs limites, pas encore les futurs adaptateurs ni
leur persistance : ceux-ci auront leurs propres tests automatisés avec des
fixtures minimales et expurgées.

## 9. Références officielles

- [API Sirene open data](https://www.data.gouv.fr/dataservices/api-sirene-open-data)
- [Modalités de connexion à l'API Sirene](https://static.insee.fr/api-sirene/Insee_API_publique_modalites_connexion.pdf)
- [Diffusion partielle dans Sirene](https://www.insee.fr/fr/information/6790269?question=sont-informations-diffusees-lesquelles-pouvez-exercer-droit-d-opposition)
- [Liste repoussoir et opposition à la prospection — CNIL](https://www.cnil.fr/fr/comment-utiliser-une-liste-repoussoir-pour-respecter-lopposition-la-prospection)
- [Statut de diffusion dans Sirene — Insee](https://www.sirene.fr/static-resources/documentation/Sirene_4-Onglet-Statut_Diffusion.pdf)
- [Droit d'opposition Sirene — Code de commerce](https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000046065401)
- [Fichier de géolocalisation Sirene](https://www.data.gouv.fr/datasets/geolocalisation-des-etablissements-du-repertoire-sirene-pour-les-etudes-statistiques)
- [Contours administratifs](https://www.data.gouv.fr/datasets/contours-administratifs)
- [API de géocodage de la Géoplateforme](https://cartes.gouv.fr/aide/fr/guides-utilisateur/utiliser-les-services-de-la-geoplateforme/geocodage/)
- [Documentation DATAtourisme v1](https://api.datatourisme.fr/v1/docs?lang=fr)
- [Retrait des adresses email de DATAtourisme](https://support.datatourisme.fr/t/protection-des-adresses-email-ce-qui-change/3133)
- [Adresse de la mairie de Dax](https://www.dax.fr/fiche-annuaire/mairie/)
