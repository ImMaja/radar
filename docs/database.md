# Radar — Modèle de données

> Statut : conception logique du MVP
>
> Dernière mise à jour : 3 septembre 2026
>
> SGBD cible : PostgreSQL avec PostGIS

## 1. Objet du document

Ce document décrit le modèle de persistance du MVP de Radar. Il précise les
entités, leurs relations, les invariants et les index nécessaires pour pouvoir
implémenter les migrations sans figer prématurément chaque nom de colonne.

Il complète :

- `docs/product.md`, qui définit le comportement attendu ;
- `docs/data-sources.md`, qui définit les contrats des fournisseurs ;
- `docs/architecture.md`, qui définit les composants et les transactions ;
- `docs/scoring.md`, qui définit le contenu des scores.

Ce document ne contient ni SQL, ni migration Alembic. Les noms de tables
proposés sont normatifs pour la conception, mais peuvent être ajustés lors de
la première migration à condition de conserver les invariants décrits ici.

## 2. Principes structurants

### 2.1 Une fiche n'est pas une réponse fournisseur

Une fiche affichée est une entité métier stable. Elle peut survivre :

- à une modification ou à la disparition temporaire de sa source ;
- à une fermeture administrative ;
- au passage d'un événement dans le passé ;
- à son masquage par l'utilisateur ;
- à une nouvelle collecte dans une autre zone.

Les réponses externes sont donc conservées séparément des fiches. Un
adaptateur produit une observation normalisée ; seul le service d'import du
domaine peut la rapprocher d'une fiche et mettre à jour la projection source.
Un adaptateur ne manipule jamais directement les tables métier.

### 2.2 Trois couches de valeurs

Les valeurs d'une fiche sont séparées en trois couches :

1. **observation source** : représentation datée et minimisée de ce que le
   fournisseur a publié ;
2. **projection source courante** : valeur normalisée actuellement retenue par
   Radar parmi les observations autorisées ;
3. **correction utilisateur** : valeur prioritaire, conservée indépendamment
   des collectes.

La valeur effective affichée est la correction utilisateur lorsqu'elle est
explicitement active ; sinon, c'est la projection source courante. Une
correction peut explicitement remplacer une valeur par « vide ». L'absence de
correction ne doit donc pas être déduite d'une simple colonne `NULL` : chaque
champ corrigeable possède un indicateur `is_overridden` distinct.

Une nouvelle observation peut modifier la projection source et sa provenance,
mais jamais l'indicateur ni la valeur de correction. Restaurer une valeur
source consiste à désactiver la correction correspondante, pas à recopier la
valeur source dans la couche utilisateur.

### 2.3 États orthogonaux

Les états suivants ne sont pas regroupés dans un unique statut de fiche :

- masquage volontaire ;
- état administratif d'un établissement et de son unité légale ;
- droit de diffusion et de réutilisation pour la prospection ;
- qualité ou absence de localisation ;
- statut déclaré d'un événement ;
- état temporel calculé d'un événement ;
- obsolescence éventuelle d'une observation.

Une fiche peut, par exemple, être à la fois masquée, administrativement active
et dépourvue de position. Cette séparation évite les transitions implicites et
les pertes de données.

### 2.4 Identité interne et identité externe

Toutes les entités métier utilisent un identifiant interne non signifiant,
de préférence un UUID. Les identifiants externes restent des données :

- SIREN : unité légale ou organisme ;
- SIRET : établissement physique ;
- UUID DATAtourisme : objet événementiel de cette source, éventuellement
  complété par un discriminant d'édition validé par l'adaptateur ;
- identifiant technique documenté : objet d'une future source dépourvue
  d'identifiant publié fiable.

Un identifiant externe n'est globalement unique qu'avec son autorité émettrice
et son espace de noms. Un SIREN ne sert jamais à fusionner deux établissements
et deux UUID DATAtourisme différents ne sont jamais fusionnés automatiquement
dans le MVP. Si DATAtourisme réutilise un UUID entre éditions distinctes,
l'espace de noms de l'identité métier inclut le discriminant documenté par
l'adaptateur ; l'UUID brut reste conservé dans l'observation source.

### 2.5 Données minimisées

Radar ne conserve pas par défaut le corps HTTP brut complet. Une observation
contient uniquement les champs source utiles, autorisés et nécessaires à la
provenance, à la reproduction de la normalisation et à la détection d'un
changement. Les en-têtes d'authentification, clés API, cookies et autres secrets
ne sont jamais persistés.

## 3. Conventions communes

### 3.1 Types et dates

- Les identifiants internes sont des UUID.
- Les instants techniques utilisent `timestamptz`, qui représente un instant
  normalisé mais ne conserve pas à lui seul le fuseau ou l'offset écrit par la
  source. Ce fuseau, cet offset ou la valeur textuelle source sont conservés
  séparément lorsqu'ils sont nécessaires à l'interprétation.
- Les dates et heures métier incomplètes d'une source sont conservées dans des
  colonnes distinctes `date` et `time`, accompagnées du fuseau supposé et de la
  précision connue.
- Les traitements temporels du produit utilisent `Europe/Paris` lorsque la
  source ne fournit pas de fuseau.
- Les empreintes de contenu et de fichiers sont conservées sous une forme
  binaire ou hexadécimale, avec l'algorithme identifié.
- Les montants de distance et de rayon sont exprimés en mètres entiers.

Tous les enregistrements modifiables possèdent au minimum `created_at` et
`updated_at`. Une date annoncée par une source, une date de récupération et une
date de traitement par Radar restent toujours trois notions distinctes.

### 3.2 Géographie

Les positions ponctuelles utilisent `geography(Point, 4326)`. Ce choix permet
d'utiliser [`ST_DWithin`](https://postgis.net/docs/ST_DWithin.html) avec un
rayon en mètres et [`ST_Distance`](https://postgis.net/docs/ST_Distance.html)
pour une distance géodésique en mètres, avec l'index spatial PostGIS.

Les contours de communes utilisent des `geometry(MultiPolygon, 4326)`
versionnées.
Ils servent seulement à présélectionner les communes ; la décision finale
d'inclusion utilise le point de l'opportunité et le cercle exact.

Une position inconnue vaut `NULL`. Le point `(0, 0)` n'est jamais une valeur de
remplacement. Longitude et latitude ne sont pas dupliquées comme vérité métier
si elles peuvent être obtenues depuis le point PostGIS.

### 3.3 `NULL`, vide et inconnu

- Une chaîne vide reçue est normalisée en `NULL`, sauf si la source lui donne
  un sens documenté.
- `NULL` signifie « non connu ou non applicable dans ce contexte » ; il ne
  signifie jamais « non ».
- Les états dont l'inconnu a un effet métier utilisent une valeur explicite
  `UNKNOWN`, et non `NULL` : diffusion, état administratif, éligibilité à la
  prospection et qualité de localisation notamment.
- Une liste de contacts vide signifie « aucun contact connu de Radar », pas
  « cet organisme ne possède aucun contact ».
- Une tranche d'effectif inconnue ne vaut ni zéro salarié ni la tranche la plus
  faible.
- La présence d'une ligne de correction et de son indicateur
  `is_overridden=true` permet de distinguer une correction volontairement vide
  d'une absence de correction.

### 3.4 Codes contrôlés

Les codes métier stables utilisent soit une table de référence, soit une
chaîne contrainte par la base. Les types PostgreSQL `ENUM` ne sont pas retenus
par défaut, car l'ajout ou la transition d'une valeur est plus lourd à faire
évoluer. Les libellés destinés à l'interface ne servent jamais de clé.

## 4. Vue d'ensemble des relations

```text
account ──< auth_session
   │
application_setting ──> reference_position

opportunity
   ├── prospect ──> establishment ──> organization
   ├── event ────────────────> organization (organisateur fiable, facultatif)
   ├── opportunity_note
   ├── location_assertion
   ├── contact_set ──< contact_point
   ├── source_binding ──< source_observation
   └── score_evaluation ──< score_contribution

event ──< event_period_set ──< event_period

collection_job ── collection_cycle
   └── collection_attempt

collection_cycle
   ├── collection_source_run
   ├── collection_batch ──< collection_page
   ├── collection_item
   ├── collection_cycle_commune
   └── collection_reference_usage ──> dataset_release

dataset_release ──< commune_boundary
collection_cycle réussi ──> connector_coverage
```

## 5. Compte unique et sessions

### 5.1 `account`

Le MVP possède exactement un compte. La table contient :

- `id` ;
- une clé constante de singleton, unique et contrainte à une valeur connue ;
- un nom d'affichage facultatif ;
- `password_hash`, produit par l'algorithme de hachage choisi dans
  `docs/architecture.md` ;
- `password_changed_at` ;
- `session_generation`, entier monotone utilisé pour invalider des sessions ;
- `created_at` et `updated_at`.

Il n'existe ni mot de passe en clair, ni mot de passe chiffré réversible, ni
question secrète. L'adresse email n'est pas nécessaire au MVP. La contrainte
sur la clé singleton empêche de créer un deuxième compte même si une route est
appelée par erreur.

### 5.2 `auth_session`

Une session contient :

- `id` ;
- `account_id` ;
- uniquement le condensat cryptographique du jeton, unique ;
- le condensat ou nonce du jeton CSRF lié à cette session, jamais sa valeur
  brute lorsqu'elle est persistée ;
- la génération du compte au moment de l'émission ;
- `created_at`, `last_seen_at`, `idle_expires_at` et `absolute_expires_at` ;
- `revoked_at` et un motif de révocation facultatifs.

Le jeton brut n'est jamais écrit en base ni dans les journaux. Une session est
valide seulement si ses deux échéances ne sont pas dépassées, si elle n'est pas
révoquée et si elle appartient à la génération attendue. La mise à jour de
l'activité ne repousse jamais `absolute_expires_at`.

Le changement de mot de passe est une transaction qui vérifie le mot de passe
actuel, remplace le condensat du mot de passe, incrémente
`session_generation` et révoque toutes les autres sessions. La session ayant
initié le changement peut être renouvelée dans la même transaction ; ce choix
ne doit jamais laisser une ancienne session valide.

Un index unique porte sur le condensat du jeton et des index sur les deux
échéances facilitent le refus et le nettoyage administratif des sessions
expirées.

## 6. Réglage géographique

### 6.1 `reference_position`

Chaque géocodage ou correction de l'adresse de référence crée une ligne
historique :

- adresse saisie ;
- libellé normalisé retenu ;
- adresse structurée disponible ;
- point `geography(Point, 4326)` obligatoire ;
- code commune, identifiant BAN et type de résultat lorsqu'ils existent ;
- score du géocodeur lorsqu'il existe ;
- fournisseur et observation de géocodage ;
- date de géocodage et date de validation par l'utilisateur ;
- code pays, contraint à `FR` dans le MVP ;
- indicateur confirmant que le point est en France métropolitaine.

Une ligne validée est immuable. Une nouvelle correction crée une nouvelle
ligne afin de ne pas réécrire la provenance de la précédente.

### 6.2 `application_setting`

Cette table singleton contient :

- la référence vers la `reference_position` courante, nulle jusqu'à la
  première adresse confirmée ;
- le rayon de collecte, par défaut `50 000` et contraint à
  `1..50 000` mètres ;
- le rayon de recherche courant, contraint à `1..50 000` mètres ;
- la date de modification.

Changer cette ligne ne supprime aucune fiche et ne crée aucun cycle de
collecte. Les distances sont recalculées à la lecture depuis la position
courante ; elles ne sont pas enregistrées comme attribut durable d'une fiche.
Tant qu'aucune position n'est confirmée, Radar refuse simplement de lancer une
collecte ou une recherche par distance.

## 7. Racine des fiches

### 7.1 `opportunity`

Toutes les fiches partagent une racine contenant :

- `id` ;
- `kind`, égal à `PROSPECT` ou `EVENT` ;
- `creation_origin`, égal à `SOURCE` ou `MANUAL` ;
- `hidden_at`, nul lorsque la fiche n'est pas masquée ;
- `hidden_reason`, facultatif parmi `NOT_RELEVANT`, `DUPLICATE`,
  `INCORRECT_INFORMATION` et `OTHER` ;
- `duplicate_of_opportunity_id`, facultatif ;
- `created_at` et `updated_at`.

Une fiche n'a aucun `deleted_at` fonctionnel : le MVP ne propose pas de
suppression utilisateur. Le masquage est déterminé uniquement par
`hidden_at`. Une synchronisation ne possède jamais le droit d'écrire les
colonnes de masquage.

Lorsque `duplicate_of_opportunity_id` est renseigné :

- la fiche doit être masquée pour le motif `DUPLICATE` ;
- la cible doit être différente de la fiche elle-même ;
- les deux fiches doivent appartenir à la même famille ;
- la cible reste une simple référence, sans transfert ni fusion de contenu.

La base peut contraindre les trois premiers points simples ; la concordance de
famille est contrôlée dans le service métier et ses tests. La relation utilise
une suppression restreinte, jamais une cascade.

Une transaction de création insère la racine et exactement une ligne de
sous-type cohérente avec `kind`. Les clés primaires partagées garantissent au
moins une relation un-à-un ; l'invariant « exactement un sous-type » est aussi
vérifié par le service et par un test de contrainte, car il n'est pas exprimé
simplement avec des clés étrangères ordinaires.

### 7.2 `opportunity_note`

La note libre est séparée de la donnée fournisseur :

- `opportunity_id`, clé primaire et étrangère ;
- `content` ;
- `created_at` et `updated_at`.

Seul l'utilisateur écrit cette table. Une collecte ne l'insère, ne la modifie
et ne la supprime jamais. Une ligne absente et une note vide sont équivalentes
pour l'affichage. Il n'existe pas d'historique de contacts ou de statut CRM
dans le MVP.

## 8. Organismes, établissements et prospects

### 8.1 Pourquoi séparer organisme et établissement

Le prospect local correspond au site physique, pas à l'entité juridique dans
son ensemble. La séparation minimale suivante évite de confondre un SIREN et
un SIRET tout en permettant :

- plusieurs établissements pour une même unité légale ;
- le rattachement futur d'un événement à un organisateur identifié ;
- un établissement manuel sans identifiant officiel ;
- un organisateur textuel qui n'est pas fusionné abusivement.

Ni `organization` ni `establishment` n'est une seconde fiche visible. Seule la
ligne `prospect` associée constitue l'opportunité de prospection.

### 8.2 `organization`

Cette table représente une unité légale ou un organisme identifié :

- `id` ;
- `siren`, facultatif, unique et contraint à neuf chiffres lorsqu'il existe ;
- dénomination légale et dénomination usuelle issues de la source ;
- type d'organisme et catégorie juridique issus de la source ;
- état administratif parmi `ACTIVE`, `CEASED`, `UNKNOWN` ;
- statut de diffusion parmi `FULL`, `PARTIAL`, `UNKNOWN` ;
- observation ayant établi chacun des états courants ;
- dates de première et dernière observation.

Deux organismes ne sont rapprochés automatiquement que par un identifiant
fiable compatible, tel qu'un SIREN. Un nom ressemblant ne suffit pas.

### 8.3 `establishment`

Cette table représente un site physique :

- `id` ;
- `organization_id`, facultatif pour une fiche entièrement manuelle ;
- `siret`, facultatif, unique et contraint à quatorze chiffres lorsqu'il
  existe ;
- caractère siège lorsqu'il est connu ;
- enseigne et nom usuel issus de la source ;
- activité principale, avec son code, sa nomenclature et son libellé ;
- tranche et année d'effectif ;
- portée de l'effectif parmi `LOCAL`, `GENERAL`, `UNKNOWN` ;
- état administratif parmi `ACTIVE`, `CLOSED`, `UNKNOWN` ;
- statut de diffusion parmi `FULL`, `PARTIAL`, `UNKNOWN` ;
- dates de création, de début de période et de traitement source lorsqu'elles
  existent ;
- observations ayant établi les états et valeurs courants ;
- dates de première et dernière observation.

Le code et la nomenclature d'activité forment une paire indivisible. Aucun code
NAF n'est interprété sans sa version. Le passage à la NAF 2025 ne nécessite
ainsi ni réécriture des anciennes observations, ni changement d'identité de
l'établissement.

L'état de l'établissement et celui de son organisme restent séparés. Une
absence lors d'une collecte n'écrit jamais `CLOSED` ou `CEASED`.

### 8.4 `prospect`

La ligne utilise le même identifiant primaire que son `opportunity` et
référence un `establishment` unique. Elle contient la projection source de la
fiche :

- nom d'affichage résolu ;
- description ;
- type d'organisme destiné aux filtres ;
- éventuels signaux métier normalisés utiles au score ;
- éligibilité à la prospection parmi `ELIGIBLE`, `RESTRICTED`, `UNKNOWN` ;
- date et motif du dernier changement d'éligibilité ;
- dates de première et dernière observation.

L'activité et l'effectif source sont lus sur l'établissement. Le nom
d'affichage peut être résolu depuis l'enseigne, le nom usuel ou la dénomination
de l'organisme, sans perdre le champ source choisi grâce à la filiation décrite
plus bas.

Une contrainte unique sur `establishment_id` empêche la création de deux
prospects pour le même établissement. Lorsqu'un SIRET masqué revient dans une
collecte, l'identité ramène donc à ce même établissement et à cette même fiche.

Une fiche créée manuellement sans restriction externe connue reçoit
`ELIGIBLE` afin d'être visible immédiatement. Si elle est ensuite rapprochée
d'une identité soumise à une restriction de diffusion, la règle de conformité
prévaut : son origine manuelle ne permet jamais de contourner cette
restriction.

### 8.5 `prospect_user_override`

Cette table un-à-un avec `prospect` contient les corrections scalaires :

- nom d'affichage ;
- description ;
- type d'organisme ;
- activité, modifiée comme un triplet nomenclature/code/libellé ;
- tranche, année et portée de l'effectif.

Chaque groupe possède son indicateur `is_overridden`. Une valeur corrigée peut
être nulle lorsque l'utilisateur souhaite effacer une information affichée.
La contrainte exige qu'une valeur soit nulle lorsque son indicateur est faux.

La localisation et les contacts ne sont pas placés dans cette table : leurs
corrections utilisent les ensembles versionnés décrits aux sections 10 et 11.
Le SIRET, le SIREN, les états administratifs, les statuts de diffusion et
l'éligibilité réglementaire ne sont pas corrigeables par cette couche. Une
anomalie sur ces valeurs reste signalée avec sa provenance ; l'utilisateur ne
peut pas rendre prospectable une donnée restreinte.

### 8.6 Visibilité ordinaire d'un prospect

Un prospect apparaît dans les listes ordinaires seulement si toutes les
conditions suivantes sont satisfaites :

- la fiche n'est pas masquée ;
- l'établissement n'est pas `CLOSED` ;
- l'organisme n'est pas `CEASED` ;
- l'éligibilité vaut `ELIGIBLE` ;
- les règles de diffusion permettent encore la prospection.

Une localisation inconnue ne retire pas le prospect de la base. Elle le place
dans « Localisation à vérifier » et l'exclut uniquement des filtres exigeant
une distance connue.

## 9. Événements et organisateurs

### 9.1 `event`

La ligne utilise le même identifiant primaire que son `opportunity` et
contient la projection source courante :

- titre ;
- description ;
- catégorie et format principal normalisés ;
- fréquentation ou capacité propre à l'édition lorsqu'elle est publiée, avec
  sa valeur, sa nature `EXPECTED_ATTENDANCE` ou `EVENT_CAPACITY` et sa portée
  temporelle connue ;
- statut déclaré parmi `SCHEDULED`, `POSTPONED`, `CANCELLED`, `UNKNOWN` ;
- nom ou description textuelle de l'organisateur ;
- `organizer_organization_id`, facultatif ;
- URI et liens métier qui ne sont pas des contacts ;
- dates de première et dernière observation.

`organizer_organization_id` n'est renseigné que lorsqu'une identité fiable de
l'organisateur est fournie ou confirmée. Une ressemblance de nom, le producteur
DATAtourisme et le champ `hasBeenCreatedBy` ne suffisent pas. Le texte source
reste disponible lorsque l'organisateur ne peut pas être relié.

Une fréquentation numérique est un entier strictement positif et n'est
renseignée que si son contexte la rattache à cette édition. La capacité
générale d'un lieu et un nombre sans unité certaine restent dans l'observation
source, mais pas dans cette projection structurée.

Le statut temporel `UPCOMING`, `ONGOING` ou `PAST` n'est pas stocké : il dépend
de l'heure courante et des périodes effectives. Il est calculé à la requête
dans le fuseau `Europe/Paris`. La disparition d'un événement d'une source ne
change jamais son statut déclaré.

### 9.2 `event_user_override`

Cette table un-à-un contient les corrections scalaires du titre, de la
description, de la catégorie ou du format principal, de la fréquentation ou
capacité, du statut déclaré et de l'organisateur. Chaque groupe possède un
indicateur `is_overridden` distinct.

Une correction d'organisateur peut contenir soit une référence vers un
`organization` confirmé, soit un texte libre, jamais une fusion implicite.
Les dates utilisent le mécanisme d'ensemble de périodes ci-dessous.
L'identifiant DATAtourisme, la provenance, le score et le masquage ne sont pas
des champs corrigés dans cette table.

### 9.3 `event_period_set`

Les périodes sont corrigées comme un ensemble cohérent plutôt que ligne par
ligne. La table contient :

- `id` et `event_id` ;
- `layer`, égal à `SOURCE` ou `USER` ;
- l'observation source lorsque `layer=SOURCE` ;
- `is_current` ;
- `created_at` et `retired_at`.

Il existe au maximum un ensemble source courant et un ensemble utilisateur
courant par événement. L'ensemble effectif est l'ensemble utilisateur courant
s'il existe, sinon l'ensemble source courant. Une première correction copie
les périodes effectives dans un nouvel ensemble utilisateur ; les éditions
suivantes modifient une nouvelle version de cet ensemble. Restaurer les dates
source retire l'ensemble utilisateur courant sans supprimer l'historique.

Une collecte crée une nouvelle version de l'ensemble source et retire
uniquement l'ancienne version source. Elle ne touche jamais l'ensemble
utilisateur. Ce choix simple évite qu'une nouvelle occurrence fournisseur soit
mélangée silencieusement à un calendrier corrigé manuellement ; l'interface
peut signaler qu'une source sous-jacente a changé.

### 9.4 `event_period`

Une période contient :

- `period_set_id` et un ordre stable d'affichage ;
- date de début obligatoire et heure de début facultative ;
- date de fin et heure de fin facultatives ;
- fuseau explicite ou fuseau d'interprétation ;
- précision parmi `DATE_ONLY`, `DATE_AND_TIME`, `MIXED` ;
- détails textuels et structure de récurrence source minimisée lorsqu'ils sont
  utiles ;
- chemin du champ source pour la provenance.

La date de fin ne peut pas précéder la date de début. Lorsque les deux heures
sont connues le même jour, l'heure de fin ne peut pas précéder l'heure de
début, sauf anomalie conservée comme observation rejetée et non comme période
effective.

Pour les recherches, une fin absente utilise la fin de la date de début ; une
heure de fin absente utilise la fin de sa dernière date connue. Une colonne
`daterange` dérivée ou maintenue à partir de ces dates peut être indexée en
GiST pour le test de chevauchement.

Les métadonnées de récurrence ne servent jamais à inventer des occurrences.
Seules les périodes effectivement publiées et normalisées déterminent la
visibilité.

Une nouvelle fiche événementielle importée possède au moins une période
valide et non terminée. Une fiche manuelle ne peut être enregistrée comme
événement exploitable sans au moins une période utilisateur valide. Une mise à
jour illisible ou accidentellement vide ne remplace pas silencieusement le
dernier ensemble source valide : elle reste une observation rejetée visible
dans le bilan de collecte.

### 9.5 Visibilité ordinaire d'un événement

Une fiche événementielle apparaît dans les listes ordinaires si elle n'est pas
masquée et possède au moins une période effective en cours ou future. Un
événement à venir déclaré `CANCELLED` est exclu par défaut, mais peut être
inclus par le filtre prévu. Une nouvelle période non terminée reçue pour une
fiche passée la rend à nouveau visible.

La requête de l'onglet « Fiches masquées » repose sur `hidden_at` et ignore les
conditions temporelles, administratives et géographiques. Elle permet donc de
retrouver un événement masqué devenu passé. La même règle vaut pour un prospect
masqué devenu inactif ou non prospectable. Démasquer ne modifie aucun de ces
autres états.

## 10. Localisations

### 10.1 `location_assertion`

Une localisation est une version attribuée à une fiche. Elle contient :

- `id` et `opportunity_id` ;
- `layer`, égal à `SOURCE` ou `USER` ;
- adresse complète et composants normalisés disponibles ;
- code commune, code postal et code pays ;
- point `geography(Point, 4326)`, facultatif ;
- origine de la position parmi `SIRENE_DATASET`, `SIRENE_API`,
  `GEOPLATFORM_GEOCODER`, `DATATOURISME`, `USER_CONFIRMED` et `OTHER` ;
- code de qualité brut, score de rapprochement et précision normalisée parmi
  `ROOFTOP`, `ADDRESS`, `STREET`, `MUNICIPALITY`, `UNKNOWN` ;
- utilisabilité parmi `USABLE`, `TO_VERIFY`, `MISSING` ;
- observation source, version de jeu de données et résultat de géocodage
  associés lorsqu'ils existent ;
- `is_current`, `created_at` et `retired_at`.

Le code de qualité brut n'est jamais interprété sans son fournisseur. Les
seuils qui conduisent à `USABLE` ou `TO_VERIFY` seront fixés après le test réel
de Dax décrit dans `docs/data-sources.md`.

Il existe au maximum une localisation source courante et une localisation
utilisateur courante par fiche. La localisation effective est la version
utilisateur lorsqu'elle existe, sinon la version source. Une correction
d'adresse crée une version utilisateur ; son éventuel résultat de géocodage
reste une observation distincte. Restaurer l'adresse source retire la version
utilisateur courante.

Une collecte peut remplacer la localisation source courante d'une fiche, y
compris d'une fiche masquée. Elle ne peut ni retirer ni modifier la version
utilisateur. Le choix entre fichier Sirene, coordonnées de l'API Sirene et
géocodage de repli est ainsi une règle de résolution, pas une dépendance du
schéma. Si le gros fichier mensuel sort du MVP, aucune table métier ni clé
étrangère ne change.

Une fiche sans point conserve son adresse et une utilisabilité `MISSING` ou
`TO_VERIFY`. La distance effective vaut alors `NULL` et elle ne satisfait
jamais un filtre de rayon.

### 10.2 Calcul de distance

La distance n'est pas persistée sur la fiche. Une requête :

1. choisit la localisation utilisateur courante, sinon la source courante ;
2. exige un point utilisable ;
3. applique `ST_DWithin` entre ce point et la `reference_position` courante ;
4. calcule `ST_Distance` seulement pour les lignes retenues et l'affichage.

Une distance ponctuellement mise en cache reste une optimisation invalidable,
jamais une vérité. Modifier l'adresse de référence ne déclenche donc aucune
mise à jour massive des fiches.

## 11. Contacts et liens

### 11.1 `contact_set`

Comme les périodes, les contacts d'une fiche forment deux ensembles
versionnés : source et utilisateur. La table contient `opportunity_id`,
`layer`, l'observation source, `is_current`, `created_at` et `retired_at`.

L'ensemble utilisateur courant, lorsqu'il existe, remplace l'ensemble source
pour l'affichage et les filtres. À la première correction, il est initialisé
avec les contacts effectifs afin que l'utilisateur puisse ajouter, modifier ou
retirer un élément. Une collecte continue à mettre à jour son propre ensemble
source sans toucher l'ensemble utilisateur. Restaurer les contacts source
retire l'ensemble utilisateur courant.

Cette granularité par ensemble est volontairement simple pour le MVP. Elle
évite de devoir inventer des identifiants stables pour chaque contact dans des
sources qui n'en fournissent pas.

### 11.2 `contact_point`

Chaque élément d'un ensemble contient :

- type parmi `EMAIL`, `PHONE`, `WEBSITE`, `BOOKING_URL` et `CONTACT_RELAY` ;
- valeur telle qu'affichée et valeur normalisée pour les comparaisons ;
- portée parmi `LOCAL`, `CENTRAL`, `UNKNOWN` ;
- libellé ou rôle facultatif ;
- URL source exacte ou chemin du champ source lorsqu'il existe ;
- ordre d'affichage.

Les emails sont comparés sous une forme normalisée prudente, les téléphones
sous une forme internationale lorsqu'elle peut être établie et les URL après
normalisation de leur schéma et de leur hôte. La valeur d'origine reste
affichable. Une contrainte empêche les doublons exacts de type, valeur
normalisée et portée dans un même ensemble.

Les filtres « possède un email », « possède un téléphone » et « possède un
site » utilisent `EXISTS` sur l'ensemble effectif. L'absence de ligne ne crée
aucune affirmation d'absence réelle. Un contact central ou inconnu n'est
jamais présenté comme local ; sa portée reste visible.

## 12. Valeurs source, filiation et corrections

### 12.1 `field_lineage`

Pour chaque valeur scalaire de projection affichable, cette table indique :

- `opportunity_id` et un code de champ contrôlé ;
- l'observation source retenue ;
- le chemin ou nom du champ fournisseur ;
- la date de résolution ;
- éventuellement la règle de priorité appliquée entre plusieurs sources.

Les codes couvrent au minimum les noms, descriptions, types, activités,
effectifs, catégories, statuts déclarés et organisateurs. Les localisations,
contacts et périodes portent leur filiation directement sur leurs lignes.

Une contrainte unique garantit une seule filiation courante par entité et code
de champ. L'historique complet reste accessible dans les observations
précédentes ; cette table représente seulement la valeur source actuellement
retenue.

### 12.2 Projection effective

Les lectures passent par des requêtes ou vues logiques `prospect_effective` et
`event_effective` qui appliquent toujours les mêmes règles :

- correction scalaire active, sinon projection source ;
- localisation utilisateur courante, sinon source courante ;
- ensemble de contacts utilisateur courant, sinon source courant ;
- ensemble de périodes utilisateur courant, sinon source courant.

Les filtres, le scoring et les pages de détail utilisent cette projection. Il
est interdit qu'un écran lise directement les colonnes source lorsqu'une
correction peut exister.

Les valeurs effectives peuvent être matérialisées plus tard si une mesure de
performance le justifie. Dans le MVP, la taille locale attendue ne justifie pas
de mécanisme de cache ou de synchronisation supplémentaire.

## 13. Provenance et identités externes

### 13.1 `data_source`

Cette table de référence décrit une source technique, par exemple
`SIRENE_API`, `SIRENE_GEOLOCATION`, `GEOPLATFORM_GEOCODER`,
`DATATOURISME_API` ou `COMMUNE_BOUNDARIES` :

- code stable et nom ;
- fournisseur ou autorité ;
- URL documentaire ;
- licence ou référence des conditions ;
- statut actif ;
- métadonnées non secrètes utiles.

Les secrets de connexion n'y figurent pas.

### 13.2 `external_identity`

Cette table centralise les identifiants fiables :

- autorité émettrice ;
- espace de noms, par exemple `SIREN`, `SIRET`, `DATATOURISME_UUID` ou une
  identité d'édition DATAtourisme validée ;
- valeur canonique, nullable uniquement après un traitement de conformité ;
- empreinte technique et version de son algorithme ;
- référence facultative vers l'organisme, l'établissement ou l'opportunité
  identifiés ;
- dates de première et dernière observation ;
- date de restriction ou de retrait éventuel.

Au plus une des trois références de cible est renseignée. La paire
`(autorité, espace de noms, empreinte)` est unique. Tant que la donnée est
autorisée, cette empreinte sert surtout de clé technique et la valeur canonique
reste disponible pour les requêtes métier.

Après une restriction, conserver uniquement un HMAC calculé avec un secret
applicatif serait techniquement plus résistant qu'un simple hachage devinable
pour un identifiant à faible entropie comme un SIRET. Il ne s'agit toutefois
que d'une option : sa conservation, sa finalité et sa durée doivent être
validées au titre de la conformité avant implémentation. Le modèle autorise
aussi le retrait complet de l'empreinte et de l'identité si cette validation
l'exige.

Les colonnes structurées `siren` et `siret` peuvent dupliquer ces deux
identifiants sur leur entité pour les contraintes métier et les requêtes. Elles
doivent être mises à jour dans la même transaction et ne peuvent diverger de
l'identité active correspondante.

### 13.3 `source_binding`

Un lien source représente l'objet stable d'une source attaché à une fiche :

- `data_source_id` et `external_identity_id` ;
- `opportunity_id` ;
- URL d'origine lorsqu'elle existe ;
- producteur initial lorsqu'il est distinct du fournisseur ;
- première et dernière dates d'observation ;
- observation courante ;
- état parmi `CURRENT`, `POTENTIALLY_STALE`, `RESTRICTED` ;
- compteur d'absences comparables consécutives ;
- date du dernier contrôle ciblé.

La paire source-identité est unique. Elle constitue la première clé de
reconnaissance d'une nouvelle collecte et reste attachée à une fiche masquée.
Un lien `RESTRICTED` empêche une réimportation incorrecte tant que la
conservation de l'identité minimale nécessaire est autorisée. Une obligation
de retrait complet prévaut sur cette protection technique.

### 13.4 `source_observation`

Une observation est une révision normalement immuable contenant :

- `data_source_id` obligatoire et `source_binding_id` facultatif ;
- cycle, lot et page ayant produit la valeur lorsqu'ils existent ;
- version éventuelle du jeu de données ;
- instant de récupération ;
- date de mise à jour annoncée par la source ;
- version de l'adaptateur et du schéma normalisé ;
- empreinte du contenu normalisé ;
- charge `jsonb` minimisée avec les valeurs source autorisées ;
- URL ou référence source propre à cette révision ;
- statut de validation et éventuelle erreur de normalisation non sensible.

La charge est validée par le modèle typé de l'adaptateur avant insertion. Le
`jsonb` n'est pas utilisé comme substitut aux colonnes relationnelles servant
aux filtres ; il conserve la preuve normalisée et les champs source
nécessaires.

Un résultat ponctuel sans objet externe stable, tel qu'un géocodage de
l'adresse de référence, possède une source mais aucun lien source. Il peut
néanmoins être référencé par la position ou la localisation qui en dérive.

Dans le fonctionnement ordinaire, une observation n'est jamais modifiée. Si
le contenu change, une nouvelle révision est créée et devient l'observation
courante du lien. Si le contenu est identique, Radar peut réutiliser la
révision existante et ne créer qu'une observation de présence. Une unicité sur
le lien et l'empreinte évite les copies quotidiennes strictement identiques.
Le retrait ou l'anonymisation de champs imposé par la conformité constitue la
seule exception : la charge peut alors être caviardée et reçoit `redacted_at`
sans conserver ailleurs la valeur retirée.

### 13.5 `source_sighting`

Cette table enregistre qu'un objet a été vu lors d'un cycle :

- `source_binding_id` ;
- `collection_cycle_id` ;
- observation courante correspondante ;
- instant de présence.

La paire lien-cycle est unique. Elle permet de distinguer « contenu inchangé »
de « objet absent » sans recopier la charge complète et de calculer les trois
absences comparables prévues pour DATAtourisme.

## 14. Référentiels versionnés

### 14.1 `dataset_release`

Une version téléchargée d'un jeu de référence contient :

- source et code du jeu ;
- identifiant de ressource ou millésime ;
- URL de ressource ;
- dates de publication et de récupération ;
- taille, algorithme et empreinte du fichier ;
- schéma ou liste de colonnes attendu ;
- état parmi `STAGED`, `VALIDATED`, `ACTIVE`, `REJECTED`, `RETIRED` ;
- licence et métadonnées non secrètes.

Une version n'est `ACTIVE` qu'après tous les contrôles. Il ne peut exister
qu'une version active par jeu, sans supprimer les métadonnées des versions
utilisées par d'anciens cycles.

Le fichier mensuel de géolocalisation Sirene n'est pas chargé intégralement
dans une table permanente. Il est contrôlé dans un espace de travail, joint
aux candidats, puis seules les localisations utiles et la provenance de la
version sont conservées. Cette règle évite de transformer un fichier de près
de 772 Mo en dépendance structurelle de Radar.

### 14.2 `commune_boundary`

Chaque ligne contient :

- `dataset_release_id` ;
- code commune ;
- nom officiel utile au diagnostic ;
- contour `geometry(MultiPolygon, 4326)` ;
- indicateur France métropolitaine.

La clé est la paire version-code commune. Un index GiST porte sur le contour.
Les changements de code ou de contour créent de nouvelles lignes dans une
nouvelle version ; ils ne réécrivent pas les cycles passés.

### 14.3 Référentiels métier

Les référentiels suivants sont petits et versionnés ou historisés lorsque leur
signification change :

- nomenclature d'activité, avec version, code et libellé ;
- tranches d'effectif, avec code fournisseur, libellé et bornes lorsqu'elles
  sont connues ;
- catégories d'événements et types d'organismes normalisés ;
- règles de correspondance entre codes source et codes Radar.

La clé d'une activité est `(nomenclature, code)`. Les catégories Radar ont un
code stable et un libellé modifiable. Les mappings fournisseur sont versionnés
avec l'adaptateur ou dans une table dédiée ; une modification de mapping doit
permettre le recalcul des projections et des scores.

Une migration de schéma ne télécharge jamais un référentiel externe. Le
chargement et la validation d'un millésime sont des traitements applicatifs
traçables.

## 15. Collectes, lots, pages et couverture

### 15.1 `collection_job`

Cette table constitue la file durable PostgreSQL. Elle contient :

- le connecteur et le déclencheur `MANUAL` ou `SCHEDULED` ;
- le créneau planifié logique lorsqu'il existe ;
- la référence unique au cycle créé dans la même transaction ;
- l'état `WAITING`, `RUNNING`, `WAITING_RETRY`, `SUCCEEDED`, `PARTIAL` ou
  `FAILED` ;
- l'instant de création et `available_at`, avant lequel le travail n'est pas
  réservable ;
- nombre de tentatives et maximum autorisé ;
- propriétaire, expiration du bail et dernier battement de vie ;
- progression publique et dernière erreur non sensible ;
- copie de l'empreinte de la demande logique utilisée pour l'unicité des
  travaux actifs.

Le worker réserve un travail disponible dans une transaction courte. Le bail
est libéré avant tout appel réseau et renouvelé pendant le traitement. Un bail
expiré rend le travail réservable de nouveau, ce qui impose l'idempotence des
imports.

Un index unique partiel sur l'empreinte de demande pour `WAITING`, `RUNNING`
et `WAITING_RETRY` empêche deux travaux actifs identiques. Un second index
unique sur `(connecteur, créneau planifié)` lorsqu'un créneau existe rend le
rattrapage de l'ordonnanceur idempotent. L'index de réservation commence par
`state` et `available_at`.

Un travail finit `FAILED` seulement si aucune observation exploitable n'a été
conservée après épuisement des reprises. S'il en a conservé au moins une sans
terminer la couverture, son état final est `PARTIAL`.

L'état du travail est l'autorité pour la réservation, le bail et les reprises.
Le cycle n'a pas un second automate concurrent : il porte seulement le résultat
métier final décrit en section 15.3. La relation est unidirectionnelle et
un-à-un de `collection_job` vers `collection_cycle` ; le cycle ne référence pas
le travail en retour.

### 15.2 `collection_attempt`

Chaque réservation effective du travail crée une tentative :

- `collection_job_id` et numéro de tentative ;
- identifiant du worker ;
- début, dernier battement et fin ;
- résultat `SUCCEEDED`, `RETRYABLE_FAILURE`, `PARTIAL` ou `FAILED` ;
- dernier point sûr et erreur structurée non sensible.

La paire travail-numéro est unique. Une tentative abandonnée par expiration du
bail reste visible et n'est pas réécrite par la suivante. Les lots et pages
peuvent référencer la tentative qui les a produits afin de distinguer une
reprise d'une première lecture.

### 15.3 `collection_cycle`

Un cycle contient :

- connecteur, par exemple `SIRENE` ou `DATATOURISME` ;
- déclencheur `MANUAL` ou `SCHEDULED` ;
- résultat final nullable parmi `SUCCEEDED`, `PARTIAL` ou `FAILED` ;
- version de l'adaptateur et empreinte de configuration non secrète ;
- copie du centre `geography(Point, 4326)`, du rayon et référence à la
  `reference_position` utilisée ;
- fuseau de planification ;
- instants de demande, début et fin ;
- résumé des compteurs et des erreurs non sensibles ;
- `request_fingerprint` représentant connecteur, centre, rayon et paramètres
  logiques de la collecte.

Le centre et le rayon sont copiés : un changement ultérieur des réglages ne
réécrit pas le périmètre historique. L'empreinte est copiée dans le travail
associé uniquement parce que l'index d'unicité ne peut pas traverser une clé
étrangère ; le service garantit leur égalité à la création. L'unicité des
travaux actifs empêche deux collectes identiques de s'exécuter simultanément.

Le résultat reste nul tant que le travail est en attente, en cours ou en
attente de reprise. Seul un cycle dont toutes les étapes obligatoires sont
terminées et dont les comptages sont cohérents reçoit `SUCCEEDED`. La
transaction terminale écrit simultanément le résultat du cycle et l'état final
identique du travail. Un résultat final n'est jamais requalifié
silencieusement.

### 15.4 `collection_source_run`

Un connecteur peut combiner plusieurs sources. Cette table associe au cycle :

- la source ;
- l'éventuelle version de jeu ;
- la date de dernière mise à disposition annoncée ;
- les instants de début et fin ;
- le statut et les compteurs propres à cette source ;
- le nombre d'appels, de reprises et d'erreurs ;
- la version de contrat utilisée.

Elle distingue ainsi la fraîcheur de l'API Sirene, du fichier géographique et
d'un géocodage de repli.

### 15.5 `collection_batch`

Un lot représente une unité logique relançable : lot disjoint de communes,
requête événementielle, jointure géographique ou contrôle de SIRET connu. Il
contient :

- cycle et source ;
- type et clé stable du lot ;
- numéro d'ordre ;
- état et nombre de tentatives ;
- instants de début et fin ;
- total annoncé, nombre reçu et nombre d'identifiants uniques ;
- état de reprise `jsonb` strictement dépourvu de secret ;
- erreur structurée et non sensible.

La paire cycle-clé de lot est unique. Un curseur ou lien `next` n'est conservé
que si la source en autorise la reprise et après retrait de tout secret. Son
hôte, son schéma et son empreinte peuvent être conservés sans stocker une clé
API.

### 15.6 `collection_page`

Une page contient :

- lot et numéro ou clé de page ;
- instants de requête et de réponse ;
- statut HTTP utile, sans en-têtes secrets ;
- nombre d'objets reçus et uniques ;
- total et nombre de pages annoncés lorsqu'ils existent ;
- empreintes du curseur reçu et du lien suivant ;
- état de traitement et erreur non sensible.

La clé de page est unique dans son lot. Cette table permet de démontrer qu'un
curseur ou un lien `next` a été parcouru jusqu'à son terme sans conserver les
réponses brutes.

### 15.7 `collection_cycle_commune`

Pour Sirene, cette table conserve toutes les communes candidates :

- cycle ;
- version du contour et code commune ;
- motif de sélection et marge de présélection ;
- lot auquel la commune a été affectée ;
- état de traitement.

La paire cycle-code commune est unique. Une commune n'appartient qu'à un lot
d'énumération afin que les totaux des lots soient additionnables sans
recouvrement attendu.

### 15.8 `collection_item`

Chaque occurrence d'un objet reçu utile au contrôle de complétude possède une
ligne légère :

- cycle, lot, page et rang dans la page ;
- autorité, espace de noms et empreinte de l'identifiant externe ;
- valeur de l'identifiant seulement si sa conservation est autorisée ;
- éventuel lien source, observation et fiche créés ;
- résultat de normalisation ;
- classement géographique parmi `IN_RADIUS`, `OUTSIDE_RADIUS`,
  `LOCATION_UNKNOWN`, `OUTSIDE_METROPOLITAN_FRANCE` et `NOT_APPLICABLE` ;
- distance au centre du cycle lorsqu'elle est calculable ;
- décision parmi `CREATED`, `UPDATED`, `UNCHANGED`, `COUNTED_ONLY`,
  `REJECTED` et `ERROR` ;
- motif structuré d'un rejet ou d'une erreur.

La paire page-rang est unique. Plusieurs occurrences du même identifiant sont
donc conservées et détectables si un fournisseur le renvoie sur plusieurs
pages. Un index cycle-identité permet de compter les identifiants distincts.
Cette table sert aux totaux et au diagnostic, y compris pour un établissement
hors du cercle exact qui ne crée pas de fiche. Elle ne doit pas devenir une
copie supplémentaire du contenu source.

### 15.9 `collection_reference_usage`

Cette association relie un cycle à chaque `dataset_release` utilisé, avec son
rôle : contours de communes, géolocalisation Sirene ou autre référentiel. Elle
permet de reproduire le contexte d'une collecte sans imposer un jeu
géographique précis au schéma métier.

### 15.10 `connector_coverage`

Une couverture est créée uniquement à la réussite complète d'un cycle :

- connecteur et cycle unique ;
- centre `geography(Point, 4326)` et rayon ;
- instant d'établissement de la couverture ;
- dates de fraîcheur des sources concernées ;
- éventuelles limites explicites qui ne remettent pas en cause le statut de
  succès défini pour ce connecteur.

Un cycle partiel ou échoué ne crée ni ne remplace une couverture. La couverture
active d'un connecteur est son dernier enregistrement réussi pertinent autour
de la position courante.

Un cercle de recherche est couvert lorsque la distance entre son centre et le
centre de couverture, augmentée de son rayon, ne dépasse pas le rayon couvert.
Le calcul reste géographique et ne dépend pas d'un département. La couverture
ne signifie jamais que la source représente tout ce qui existe dans le monde
réel.

## 16. Scores

### 16.1 `score_ruleset`

Chaque version exécutable de scoring possède :

- une famille `PROSPECT` ou `EVENT` ;
- un code de version unique, par exemple `prospect-v1` ;
- l'empreinte du code, des dictionnaires et des mappings qui influencent le
  résultat ;
- son état `CANDIDATE`, `ACTIVE` ou `RETIRED` ;
- dates de création et d'activation.

Il existe exactement une version active par famille dès que le scoring de
cette famille est exposé. L'activation d'une candidate et le remplacement de
l'ancienne version sont atomiques, après réussite du recalcul complet. Les
dictionnaires ne sont pas édités dans cette table : ils restent du code
versionné et testé.

### 16.2 `score_evaluation`

Une évaluation contient :

- `opportunity_id` ;
- type de score `PROSPECT` ou `EVENT` cohérent avec la fiche ;
- entier `value` contraint à `0..100` ;
- référence au `score_ruleset` ;
- valeur du socle de départ ;
- empreinte des données effectives ayant servi au calcul ;
- instant de calcul ;
- indicateur d'évaluation courante.

Il existe au maximum une évaluation courante par fiche. Une nouvelle
évaluation est produite lorsque les données effectives ou la version des règles
changent. Les anciennes évaluations peuvent être conservées dans le MVP car
elles sont petites et rendent les évolutions explicables ; elles ne sont pas
utilisées pour les tris.

### 16.3 `score_contribution`

Chaque règle ayant contribué contient :

- l'évaluation ;
- code stable et version de règle ;
- libellé figé au moment du calcul ;
- sens `POSITIVE` ou `NEGATIVE` ;
- variation signée ;
- explication et valeurs d'entrée minimisées.

Le socle et la somme des contributions doivent produire directement une valeur
entre `0` et `100`, comme l'impose `docs/scoring.md` ; aucun écrêtage silencieux
n'est appliqué. L'empreinte d'entrée ne contient que les caractéristiques
explicitement autorisées par cette version. Elle exclut notamment la distance,
la position de référence, la date courante, le statut temporel ou déclaré de
l'événement, le masquage, l'état administratif, la diffusion, la provenance,
la fraîcheur, la note et tout futur état CRM.

### 16.4 Qualification initiale

La qualification de Dax est un travail de validation du produit, pas une
fonction récurrente proposée dans l'interface. Le schéma initial n'ajoute donc
pas de tables de campagne ou d'appréciation. Le petit échantillon est conservé
comme un artefact de validation daté et associé à la version évaluée, avec au
minimum le cycle source, la version du score, les identifiants internes des
fiches, leur rang, l'appréciation aveugle et la justification. Il ne contient
ni coordonnées de contact, ni notes utilisateur, ni corps source bruts. Il
n'est ajouté au dépôt que sous une forme anonymisée ; sinon, il reste dans
l'espace privé prévu pour les données de test.

Si Radar doit plus tard réaliser plusieurs campagnes depuis l'interface, une
migration introduira alors des tables de campagne et d'éléments qualifiés. Une
appréciation de validation ne deviendra jamais un statut métier de la fiche ni
une entrée de son score.

## 17. Synchronisation transactionnelle

### 17.1 Import d'un objet reconnu

Pour chaque observation valide, le service d'import exécute dans une
transaction :

1. calculer l'identité canonique et son empreinte ;
2. verrouiller ou créer l'identité et le lien source à l'aide de leur
   contrainte unique ;
3. retrouver la fiche existante, même masquée ou inactive ;
4. créer l'observation ou enregistrer une simple présence si son contenu est
   inchangé ;
5. mettre à jour uniquement les projections et ensembles de couche `SOURCE` ;
6. mettre à jour la filiation des valeurs source ;
7. recalculer l'éligibilité et planifier le score lorsque cela est autorisé ;
8. ne jamais écrire la note, le masquage ou une couche `USER`.

Les contraintes uniques rendent l'opération idempotente en cas de reprise.
Une collision créée par deux transactions est résolue en relisant la ligne
gagnante, jamais en créant une deuxième fiche.

### 17.2 Objet masqué

Le lien source et l'identité d'une fiche masquée restent présents. Une nouvelle
observation aboutit donc à la fiche existante. Sa projection source peut être
rafraîchie, mais `hidden_at`, son motif, sa note et ses corrections restent
inchangés. Le service de collecte ne possède aucune opération de démasquage.

Le démasquage est une commande utilisateur distincte qui efface uniquement les
colonnes de masquage. Il ne change ni les sources, ni l'état administratif, ni
l'état temporel. Un événement toujours passé ne réapparaît donc pas dans les
listes ordinaires après cette commande.

### 17.3 Absence d'une collecte

Une absence ne supprime aucune ligne. Les changements suivants exigent des
conditions supplémentaires :

- fermeture ou cessation : réponse courante explicite et fiable ;
- diffusion restreinte : statut explicite `PARTIAL` ;
- obsolescence DATAtourisme : trois cycles réussis comparables puis contrôle
  ciblé, conformément à `docs/data-sources.md` ;
- couverture : uniquement un cycle entièrement réussi.

Les compteurs d'absence ne progressent pas lors d'un cycle partiel, d'une zone
différente ou d'une requête non comparable.

### 17.4 Collecte partielle

Les observations valides d'un cycle partiel peuvent être ajoutées et leurs
valeurs source explicites actualisées, y compris un statut d'événement publié
sans ambiguïté. En revanche, le caractère incomplet du cycle :

- ne remplace pas la couverture ;
- ne prouve aucune absence ;
- ne permet d'inférer ni fermeture, ni cessation, ni annulation depuis une
  absence ;
- ne déclenche pas de retrait fondé sur un manque de résultats ;
- reste identifiable sur chaque observation et chaque page concernée.

## 18. Contraintes et index

### 18.1 Contraintes essentielles

La première série de migrations doit imposer au minimum :

- unicité du compte singleton ;
- unicité du condensat de session ;
- rayon de collecte et de recherche dans `1..50 000` mètres ;
- SIREN à neuf chiffres et SIRET à quatorze chiffres lorsqu'ils existent ;
- unicité des SIREN et SIRET actifs ;
- unicité autorité-espace de noms-empreinte externe ;
- unicité source-identité pour les liens source ;
- unicité établissement-prospect ;
- unicité des ensembles source et utilisateur courants par fiche ;
- cohérence des dates de période ;
- score dans `0..100` ;
- unicité d'une version de score et d'une version active par famille ;
- unicité d'une évaluation courante par fiche ;
- unicité des lots, pages, présences et rangs d'objets reçus dans une page ;
- unicité d'un travail actif par empreinte de requête et d'un créneau planifié
  par connecteur ;
- impossibilité de désigner sa propre fiche comme doublon.

Les contraintes qui portent sur plusieurs agrégats, comme la concordance du
type d'une fiche avec son sous-type ou la famille d'une cible de doublon, sont
vérifiées dans le service transactionnel et par des tests d'intégration. Un
déclencheur PostgreSQL n'est ajouté que si les tests montrent qu'aucune
contrainte déclarative simple ne protège suffisamment l'invariant.

### 18.2 Index de lecture

Les index initiaux sont :

- GiST sur tous les points de `location_assertion` non nuls ;
- GiST sur `reference_position.point` et `connector_coverage.center` si les
  mesures justifient ces deux petits index ;
- GiST sur les contours de communes ;
- GiST sur l'intervalle de dates des périodes effectives ;
- B-tree sur les clés étrangères fréquemment jointes ;
- B-tree ou index partiels sur masquage, type de fiche, états administratifs,
  éligibilité, statut événementiel et score courant ;
- B-tree sur les dates de prochaine occurrence utilisées pour le tri ;
- index sur type et valeur normalisée des contacts ;
- index sur la dernière observation des liens source et le résultat des
  cycles ;
- index partiel sur les sessions non révoquées avec leur expiration.

Les requêtes de distance doivent partir de `ST_DWithin` pour permettre l'usage
du GiST, puis calculer `ST_Distance` pour le tri ou l'affichage.

La recherche textuelle initiale peut utiliser les fonctions PostgreSQL sur le
nom, le titre et la commune au volume local attendu. L'extension `pg_trgm` ou
un index plein texte n'est ajouté qu'après mesure d'une requête réelle ; il ne
fait pas partie des dépendances obligatoires de la première migration.

### 18.3 Index et valeurs effectives

Les colonnes corrigées sont peu nombreuses et le volume de la zone de 50 km
reste à mesurer. Les premiers filtres peuvent donc joindre les tables de
correction et appliquer la règle effective. Si cette jointure empêche un index
critique, une colonne ou vue matérialisée effective pourra être introduite
avec une stratégie explicite d'invalidation. Aucun double stockage n'est
ajouté avant cette mesure.

## 19. Suppression, conformité et conservation

### 19.1 Suppression fonctionnelle

L'interface ne supprime définitivement ni fiche, ni note, ni provenance. Elle
masque et démasque. Les clés étrangères vers une fiche utilisent donc une
suppression restreinte par défaut. Les cascades sont réservées aux lignes qui
n'ont aucun sens seules, par exemple les contributions d'une évaluation
techniquement supprimée ou une session rattachée à un compte supprimé par une
procédure administrative exceptionnelle.

Une fiche n'est jamais supprimée parce qu'elle est passée, fermée, absente,
mal notée ou hors du rayon courant.

### 19.2 Traitement de conformité

Un retrait ou une anonymisation imposé par la diffusion ou par la loi est une
commande distincte du masquage. Elle peut :

- retirer les charges et projections source qui ne sont plus réutilisables ;
- retirer un contact ou une localisation ;
- effacer une correction ou une note qui servirait à contourner la
  restriction ;
- passer le lien source à `RESTRICTED` ;
- remplacer éventuellement une identité externe en clair par une empreinte
  HMAC, uniquement si la validation de conformité conclut que sa conservation
  est licite, nécessaire et suffisamment limitée.

L'opération consigne sa date, son motif normatif, les catégories de données
traitées et un identifiant de procédure, mais ne recopie pas la donnée retirée
dans un journal. Elle doit être idempotente.

La liste précise des données Sirene pouvant rester après un passage en
diffusion partielle est encore à valider avant le connecteur de production.
Le schéma permet le retrait des valeurs et, si elle est validée, la conservation
d'une empreinte ; ce document ne décide pas à lui seul de leur licéité.

### 19.3 Conservation technique

Le MVP n'applique aucune purge automatique aux fiches, événements passés,
observations utiles, cycles ou provenances. Les observations strictement
identiques sont factorisées par empreinte et les présences restent légères.
Une politique de rétention des détails de pages pourra être ajoutée après
mesure du volume, sans retirer les preuves nécessaires aux bilans de collecte.

Les sauvegardes doivent inclure les données utilisateur, les identités, les
observations, les référentiels actifs et l'historique des migrations. Leur
chiffrement, leur fréquence et leur restauration relèvent de
`docs/architecture.md` ou d'une future documentation d'exploitation.

## 20. Migrations et évolution du schéma

### 20.1 Alembic comme seule autorité

- Toute évolution du schéma passe par une migration Alembic versionnée.
- L'application ne crée ni ne modifie automatiquement les tables au
  démarrage.
- L'extension PostGIS est activée par une migration préalable et vérifiée au
  démarrage.
- Les migrations sont déterministes et ne dépendent d'aucun appel réseau.
- Les données de référence internes minimales peuvent être amorcées de manière
  déterministe ; les jeux externes sont chargés par des traitements séparés.

### 20.2 Discipline de migration

Avant une migration destructive ou une transformation de données :

1. sauvegarder et tester la restauration ;
2. ajouter d'abord les nouvelles colonnes ou tables ;
3. migrer et contrôler les données ;
4. faire utiliser le nouveau modèle par l'application ;
5. retirer l'ancien modèle dans une migration ultérieure seulement.

Le projet étant mono-instance et mono-utilisateur, aucune architecture de
migration distribuée n'est nécessaire. Les migrations doivent toutefois être
transactionnelles lorsque PostgreSQL le permet et échouer visiblement plutôt
que continuer avec un schéma partiel.

Chaque migration importante possède un test sur une base PostgreSQL/PostGIS
réelle. SQLite n'est pas une cible de compatibilité, car elle ne reproduit ni
les contraintes, ni les types, ni les fonctions géographiques nécessaires.

### 20.3 Évolutivité sans abstraction prématurée

Le modèle prépare les sources futures par `data_source`, les observations et
les identités externes, mais il ne crée pas :

- de table de rôle ou d'équipe ;
- de CRM ou d'historique de contact commercial ;
- de stockage vectoriel ou de résultat IA ;
- de table de carte ou d'itinéraire routier ;
- de schéma générique de formulaire dynamique ;
- de table permanente pour chaque ligne du gros fichier géographique Sirene.

Les nouvelles capacités seront ajoutées par migrations lorsqu'elles entreront
réellement dans le périmètre.

## 21. Vérifications minimales du modèle

Les tests d'intégration de la base devront démontrer au minimum que :

1. un second compte ne peut pas être inséré ;
2. aucun jeton de session brut n'est persisté et une génération ancienne est
   refusée après changement de mot de passe ;
3. un même couple source-identité métier met à jour la même fiche ;
4. deux SIRET différents d'un même SIREN peuvent produire deux prospects ;
5. deux UUID DATAtourisme différents ne fusionnent pas automatiquement ;
6. si un UUID DATAtourisme est réutilisé entre éditions distinctes, la règle
   d'identité validée crée deux fiches sans casser les mises à jour d'une même
   édition ;
7. une fiche masquée reste masquée après une nouvelle observation ;
8. une correction, une note, un ensemble de contacts utilisateur et un
   ensemble de périodes utilisateur survivent à une synchronisation ;
9. restaurer une correction fait réapparaître la dernière valeur source, pas
   une copie ancienne ;
10. une absence dans un cycle ne ferme ni ne supprime une fiche ;
11. un cycle partiel ne remplace pas la couverture réussie précédente ;
12. une position nulle reste dans « Localisation à vérifier » et n'entre pas
    arbitrairement dans un filtre de rayon ;
13. une requête `ST_DWithin` autour de Dax inclut et exclut correctement des
    points connus, indépendamment de leur département ;
14. un événement à périodes multiples est trouvé dès qu'une période effective
    chevauche le filtre ;
15. les événements passés restent présents mais sortent de la liste ordinaire ;
16. un passage explicite en diffusion partielle retire la fiche des usages de
    prospection sans la déclarer fermée ;
17. deux demandes de collecte identiques ne créent qu'un travail actif et un
    bail expiré peut être repris sans dupliquer une fiche ;
18. l'état terminal du travail correspond au résultat final du cycle ;
19. aucune migration ou observation ne contient un secret fournisseur.

## 22. Décisions encore ouvertes

Les points suivants ne bloquent pas la rédaction des autres documents, mais
doivent être clos avant les migrations correspondantes :

1. la liste exacte des champs à retirer, conserver ou transformer lorsqu'un
   établissement ou son unité légale passe en diffusion partielle, y compris
   l'autorisation éventuelle, la finalité et la durée d'une empreinte HMAC ;
2. l'ordre définitif des sources de position Sirene après comparaison entre
   les coordonnées de l'API 3.11, le fichier mensuel et le géocodeur ;
3. les codes de qualité transformés en `USABLE` ou `TO_VERIFY` ;
4. la règle d'identité d'édition DATAtourisme après vérification de la
   réutilisation éventuelle des UUID ;
5. le mapping réel des périodes et organisateurs DATAtourisme après le test
   avec une clé API ;
6. la politique de rétention à long terme des révisions et diagnostics de
   pages, à fixer seulement après mesure de leur volume.

Le modèle est volontairement indépendant des réponses à ces points : elles
modifieront des règles de résolution, de conformité ou de conservation, pas
l'identité des fiches ni les relations principales.
