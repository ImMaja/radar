# Radar — Définition du produit

> Statut : cadrage produit validé
>
> Dernière mise à jour : 2 septembre 2026
>
> Périmètre initial : un utilisateur, un food truck, application web privée

## 1. Résumé

Radar est une application web privée destinée à aider l'exploitant
d'un food truck à découvrir, évaluer et organiser des opportunités
commerciales autour d'une adresse configurable.

Le produit réunit deux familles d'opportunités :

- les prospects réguliers, c'est-à-dire les implantations locales susceptibles
  d'accueillir régulièrement un food truck ;
- les événements susceptibles de réunir un public suffisamment important.

L'application collecte des données externes dans une zone géographique
définie, les conserve localement, rapproche les doublons, calcule un score
commercial explicable et permet à l'utilisateur de corriger, annoter, masquer
ou démasquer les fiches obtenues.

Les Landes constituent le contexte commercial initial, mais pas une frontière
fonctionnelle. Une zone de collecte peut couvrir librement les départements
voisins.

## 2. Problème à résoudre

Les informations utiles sont dispersées entre des annuaires d'entreprises,
des répertoires publics, des agendas touristiques et des sites locaux. Leur
consultation manuelle prend du temps et produit beaucoup de résultats sans
intérêt commercial.

En particulier :

- les prospects locaux pertinents sont difficiles à recenser de manière
  systématique ;
- les agendas contiennent une majorité de visites, ateliers, conférences et
  petits rendez-vous peu adaptés à un food truck ;
- une même opportunité peut apparaître plusieurs fois ou dans plusieurs
  sources ;
- les coordonnées, descriptions et dates peuvent être incomplètes ou
  contradictoires ;
- recommencer une recherche manuelle ne permet pas de conserver facilement
  les corrections et observations déjà réalisées.

Le produit doit transformer ces données hétérogènes en une liste locale,
fiable, filtrable et priorisée.

## 3. Utilisateur et contexte d'usage

- Il existe un seul utilisateur et un seul food truck.
- Il n'existe ni rôle, ni équipe, ni inscription publique.
- L'application a vocation à être hébergée sur Internet et doit être protégée
  par une connexion sécurisée.
- L'adresse de référence change rarement, mais l'utilisateur peut la modifier
  pour explorer une autre zone.
- La prise de contact avec les prospects se fait hors de l'application dans le
  MVP.

## 4. Objectifs du produit

Le produit doit permettre de :

1. collecter progressivement un catalogue aussi large que possible de sources
   utiles, sans sacrifier la qualité ou la provenance ;
2. trouver les prospects réguliers et événements situés autour d'une
   adresse ;
3. changer instantanément le rayon de recherche dans les données déjà
   collectées ;
4. filtrer et trier les résultats selon des critères commerciaux ;
5. faire ressortir les opportunités prometteuses avec des règles de scoring
   compréhensibles ;
6. limiter autant que possible les doublons sans fusionner abusivement des
   opportunités différentes ;
7. permettre la création, la correction, l'annotation, le masquage et le
   démasquage de fiches ;
8. conserver la provenance et la fraîcheur de toute donnée externe ;
9. rester simple à utiliser, maintenir et faire évoluer.

## 5. Non-objectifs généraux

Radar n'est pas :

- un logiciel de caisse, de stocks ou de gestion des menus ;
- un outil de devis, de facturation ou de paiement ;
- une plateforme publique ou une place de marché ;
- un système de réservation automatique d'emplacements ;
- un outil d'optimisation de tournées ;
- une plateforme d'envoi massif d'emails ou de SMS ;
- un système prenant seul une décision commerciale ;
- une application destinée à collecter des coordonnées privées non
  professionnelles.

## 6. Définitions du domaine

### 6.1 Adresse de référence

Adresse configurable par l'utilisateur et convertie en position géographique.
Dans le MVP, elle sert de centre commun à la zone de collecte et au rayon de
recherche.

### 6.2 Zone de collecte

Cercle défini par l'adresse de référence et un rayon de collecte. Dans le MVP,
ce rayon vaut 50 km par défaut et ne peut pas dépasser 50 km. Une collecte
interroge les fournisseurs externes pour cette zone et stocke les résultats
localement.

La zone de collecte ne suit aucune frontière administrative. Elle peut sortir
des Landes sans restriction et sans avertissement particulier.

Chaque collecte réussie conserve la source interrogée, son centre, son rayon
et sa date. Dans le MVP, la couverture active d'une source correspond à sa
dernière collecte réussie autour de l'adresse de référence courante. Les
données d'anciennes zones restent consultables, mais ne prouvent pas que la
zone courante a été entièrement collectée.

### 6.3 Rayon de recherche

Rayon utilisé pour filtrer les données déjà présentes dans l'application. Il
est indépendant du rayon de collecte : une collecte de 50 km peut, par
exemple, être consultée avec un rayon de recherche de 30 km.

Dans le MVP, il est réglable jusqu'à 50 km. Modifier ce rayon ne déclenche
jamais de collecte externe. S'il dépasse la couverture effectivement collectée
pour une source, l'application signale seulement que les résultats de cette
source peuvent être incomplets.

### 6.4 Prospect régulier

Implantation physique locale et contactable susceptible d'accueillir un food
truck ou d'organiser des événements. Il peut s'agir d'un établissement
officiellement identifié ou, à défaut, de l'adresse opérationnelle d'une
association, d'une administration ou d'un autre organisme.

Le prospect régulier est l'opportunité affichée et évaluée. Son organisme de
rattachement n'est pas compté comme une seconde opportunité locale.

### 6.5 Organisme et unité légale

Entité juridique ou administrative à laquelle un ou plusieurs établissements
peuvent être rattachés. Pour une entreprise, il peut s'agir de l'unité légale
ou du siège. Cette entité n'est pas nécessairement le prospect local à
contacter.

### 6.6 Établissement

Site physique local d'une entreprise ou d'un organisme. Lorsqu'un identifiant
d'établissement tel qu'un SIRET existe, il identifie le site local, tandis
qu'un identifiant de l'organisme tel qu'un SIREN ne suffit pas à distinguer ses
différentes implantations.

Une même entreprise peut posséder plusieurs établissements. Ils ne sont pas
des doublons : chacun peut constituer une opportunité distincte. La distance
est calculée depuis le site physique, et non depuis un siège situé ailleurs.

### 6.7 Événement

Manifestation datée organisée dans un lieu physique. Dans le MVP, une fiche
représente une occurrence ou une édition commercialement distincte.

- Un événement continu sur plusieurs jours possède une date de début et une
  date de fin dans une seule fiche.
- Les éditions 2026 et 2027 d'un même festival sont deux fiches distinctes.
- Pour un rendez-vous fortement récurrent, le MVP conserve la granularité de
  la source qui crée la fiche. Il n'exige pas de regroupement automatique en
  série.

L'état temporel est calculé dans le fuseau Europe/Paris :

- un événement est à venir avant son début ;
- il est en cours entre son début et sa fin ;
- il est passé après sa fin ;
- si aucune heure de fin n'est connue, la fin de la dernière date connue est
  utilisée ; pour une date sans heure, il reste donc affichable jusqu'à la fin
  de cette journée.

### 6.8 Organisateur

Organisme responsable d'un événement. Un organisateur peut être lié à
plusieurs événements et peut également constituer un prospect régulier
lorsqu'il possède une implantation locale contactable.

### 6.9 Fiche

Représentation métier affichée dans l'application pour un prospect régulier ou
un événement. Une fiche n'est pas une copie brute d'une ligne fournisseur :
elle peut regrouper plusieurs observations externes, des corrections
utilisateur et une note libre.

### 6.10 Observation source

Enregistrement reçu d'un fournisseur externe. Il conserve au minimum le nom
du fournisseur, son identifiant externe ou une clé technique stable lorsqu'il
n'en fournit pas, son URL lorsqu'elle existe, sa date de collecte et sa date de
mise à jour lorsqu'elle est fournie.

### 6.11 Score commercial

Indicateur de priorité calculé à partir des caractéristiques intrinsèques
d'une fiche. Il aide à trier les opportunités ; il ne constitue ni une
prévision de vente, ni une garantie de fréquentation.

### 6.12 Fiche masquée

Fiche que l'utilisateur a volontairement retirée des listes et recherches
ordinaires. Elle reste entièrement conservée, continue d'être reconnue par la
déduplication et peut recevoir les mises à jour de ses observations externes.
Seul l'utilisateur peut la démasquer.

Le masquage ne doit pas être confondu avec l'état passé d'un événement, un
faible score ou l'absence d'une fiche dans un filtre. Ces trois situations ne
modifient pas l'état de masquage.

### 6.13 Observation potentiellement obsolète

Information externe remplacée ou qui n'est plus confirmée par sa source, par
exemple un ancien numéro de téléphone, une date corrigée ou une fiche qui
n'est plus revue lors de collectes comparables. Cela ne désigne jamais une
fiche à faible score ou écartée par les filtres.

## 7. Principes et invariants produit

1. Les recherches et filtres utilisent uniquement les données locales.
2. Une collecte externe est toujours une action distincte d'une recherche.
3. Les frontières départementales n'influencent ni la collecte ni la
   recherche.
4. La distance du MVP est la distance géodésique à vol d'oiseau.
5. Le score ne dépend ni de la distance, ni de la date de l'événement, ni de
   données CRM.
6. Les scores des prospects réguliers et des événements utilisent des règles
   distinctes.
7. Une donnée inconnue n'est pas assimilée à une valeur négative.
8. Tout score est accompagné des règles qui y ont contribué et du sens de leur
   impact.
9. Toute donnée externe conservée garde sa provenance et sa fraîcheur.
10. Une correction ou une note utilisateur survit aux synchronisations.
11. Une fusion de doublons conserve toutes les provenances connues.
12. Un rapprochement incertain ne provoque jamais une fusion silencieuse.
13. Une fiche masquée ne doit pas être recréée ni démasquée par une collecte
    tant que son identité reste reconnaissable.
14. Un filtre, un faible score ou le passage du temps ne supprime ni ne masque
    une fiche.
15. L'échec d'un fournisseur ne rend pas indisponibles les données déjà
    collectées.

## 8. Parcours utilisateur principaux

### 8.1 Accéder à l'application

1. L'utilisateur ouvre l'application hébergée sur Internet.
2. Il se connecte avec son compte unique.
3. Après authentification, il accède aux données et aux réglages.
4. Il peut se déconnecter explicitement.

### 8.2 Configurer et lancer une collecte

1. L'utilisateur saisit ou modifie l'adresse de référence.
2. L'application indique la position géographique retenue.
3. L'utilisateur choisit un rayon de collecte, limité à 50 km.
4. Il peut lancer explicitement la collecte sans attendre la prochaine
   exécution planifiée.
5. L'application affiche son état, ses erreurs éventuelles et la date du
   dernier succès pour chaque source.

Changer l'adresse ne supprime pas les données déjà collectées. Une nouvelle
collecte manuelle ou planifiée doit réussir pour alimenter correctement la
nouvelle zone.

### 8.3 Rechercher des prospects réguliers

1. L'utilisateur choisit un rayon de recherche.
2. Il applique des filtres et un ordre de tri.
3. Il consulte une liste de sites physiques locaux avec leur distance, leur
   score et leurs coordonnées disponibles.
4. Il ouvre une fiche pour consulter les détails et les sources.

### 8.4 Rechercher des événements

1. L'utilisateur choisit un rayon et une période.
2. Il filtre les catégories et la disponibilité des contacts.
3. Il trie les événements par score, distance ou date.
4. Il consulte les raisons du score avant de décider si l'événement mérite une
   recherche ou une prise de contact hors application.

### 8.5 Corriger et organiser les données

L'utilisateur peut :

- créer une fiche manuelle ;
- corriger les champs d'une fiche importée ;
- restaurer une valeur provenant de la source ;
- ajouter une note libre ;
- masquer une fiche sans intérêt ou un doublon restant ;
- consulter l'ensemble des fiches masquées ;
- démasquer une fiche.

## 9. Exigences fonctionnelles

### 9.1 Authentification et accès privé

- Toutes les pages et API contenant des données métier nécessitent une
  authentification.
- L'application possède un seul compte utilisateur.
- Elle ne propose ni inscription publique, ni invitation, ni gestion de rôles.
- Elle permet la connexion et la déconnexion.
- Une session expirée ou invalide redirige vers la connexion.
- L'utilisateur peut changer son mot de passe depuis les réglages en saisissant
  son mot de passe actuel, puis deux fois le nouveau.
- Un changement de mot de passe invalide les autres sessions encore ouvertes.
- En cas d'oubli, le remplacement du mot de passe reste une procédure
  administrative côté serveur dans le MVP ; il ne nécessite ni adresse email
  de récupération, ni service d'envoi d'email.

### 9.2 Collecte et géographie

- L'utilisateur peut configurer une adresse de référence et un rayon de
  collecte. Ce rayon vaut 50 km par défaut et ne peut pas dépasser 50 km dans
  le MVP.
- La position obtenue après géocodage doit pouvoir être vérifiée avant la
  collecte.
- Une collecte peut couvrir n'importe quelle zone circulaire en France,
  indépendamment des départements traversés.
- Le MVP utilise le même centre pour la collecte et la recherche.
- Modifier l'adresse recalcule les distances dans les données locales sans
  supprimer les anciennes données et sans lancer automatiquement une collecte.
- Le rayon de recherche reste modifiable sans appel fournisseur.
- Le rayon de recherche ne peut pas dépasser 50 km dans le MVP, même s'il peut
  être inférieur ou supérieur au rayon de la dernière collecte réussie.
- Si une recherche dépasse la couverture réellement collectée, l'application
  indique que les résultats peuvent être incomplets. Cet avertissement porte
  sur la couverture des données, jamais sur la sortie des Landes.
- La couverture est évaluée séparément pour chaque source à partir de sa
  dernière collecte réussie autour de l'adresse courante.
- Le cercle de recherche est couvert par une source uniquement s'il est inclus
  dans le cercle de cette dernière collecte réussie. Cette indication décrit
  le périmètre interrogé ; elle ne garantit pas que la source y soit
  exhaustive.
- La distance affichée et filtrée est calculée à vol d'oiseau.
- Une fiche sans position fiable reste accessible dans une liste de données
  non géolocalisées, mais elle n'apparaît pas dans un filtre par rayon.
- Une correction d'adresse peut déclencher un nouveau géocodage et un nouveau
  calcul de distance.
- Les limites de pagination ou de volume d'un fournisseur sont gérées par son
  adaptateur, notamment en subdivisant la zone si nécessaire. Une collecte
  tronquée ne doit jamais être présentée comme une couverture complète.

### 9.3 Prospects réguliers

Le catalogue doit pouvoir représenter notamment :

- entreprises et leurs établissements ;
- sites industriels ;
- entrepôts et entreprises logistiques ;
- entreprises du BTP ;
- campings ;
- administrations et implantations locales ;
- mairies et communautés de communes ;
- associations et clubs sportifs ;
- comités des fêtes ;
- offices de tourisme ;
- autres organismes susceptibles d'accueillir un food truck ou d'organiser
  des événements.

La fiche d'un prospect régulier présente, lorsque les données existent :

- le nom commercial et la raison sociale ;
- le type d'organisme et l'activité ;
- une description ;
- l'adresse du site local et sa distance ;
- la tranche d'effectif du site, ou son niveau de portée lorsqu'une source ne
  fournit qu'une donnée plus générale ;
- les emails, téléphones et sites web professionnels ;
- la portée connue de chaque contact : local, central ou inconnue ;
- le score et ses explications ;
- la provenance et la fraîcheur ;
- une note utilisateur.

Les prospects réguliers peuvent être filtrés selon :

- la distance ;
- le type d'organisme ;
- l'activité ;
- la tranche d'effectif lorsqu'elle est connue ;
- la présence d'un email ;
- la présence d'un téléphone ;
- la présence d'un site web ;
- une plage de score.

### 9.4 Événements

Le catalogue doit pouvoir représenter notamment :

- fêtes locales ;
- festivals et concerts ;
- compétitions et tournois sportifs ;
- brocantes et vide-greniers ;
- foires et salons ;
- marchés importants ;
- rassemblements ;
- autres événements susceptibles d'accueillir un public important.

La fiche d'un événement présente, lorsque les données existent :

- le titre et la description ;
- la catégorie ;
- la date ou la période de l'occurrence ;
- le statut déclaré lorsqu'il est connu : programmé, reporté ou annulé ;
- l'état temporel calculé : à venir, en cours ou passé ;
- le lieu, son adresse et sa distance ;
- l'organisateur ;
- les contacts et liens professionnels ;
- le score et ses explications ;
- la provenance et la fraîcheur ;
- une note utilisateur.

Les événements peuvent être filtrés selon :

- la distance ;
- une période ;
- la catégorie ;
- l'organisateur ;
- la disponibilité d'un contact ;
- le statut déclaré ;
- une plage de score.

Un contact événementiel est considéré comme disponible lorsqu'au moins un
canal professionnel exploitable existe : email, téléphone, site officiel,
lien de réservation ou relais de contact fourni par la source. Il ne doit pas
être présenté comme le contact confirmé de l'organisateur si sa portée n'est
pas connue.

Les événements passés restent conservés dans la base, mais ne sont pas
affichés dans les listes ordinaires du MVP. Ils ne font l'objet d'aucune purge
automatique. Une correction qui replace un événement dans le futur le rend à
nouveau visible. Les événements annulés à venir ne sont pas affichés par
défaut, mais peuvent être inclus avec le filtre de statut. La disparition d'un
événement d'une source ne suffit pas à le marquer comme annulé.

Un événement explicitement masqué reste toutefois accessible dans l'onglet
« Fiches masquées » même après être devenu passé, afin qu'il puisse toujours
être démasqué. Le démasquer ne le replace pas dans une liste ordinaire tant
qu'il reste passé.

### 9.5 Listes, recherche et tri

- Le MVP utilise des listes et des fiches détaillées, sans carte.
- Une recherche textuelle permet de retrouver une fiche par son nom, son titre
  ou sa commune.
- Les prospects réguliers peuvent au minimum être triés par score, distance et
  nom.
- Les événements peuvent au minimum être triés par score, distance et date.
- Les filtres s'appliquent aux données locales sans déclencher de collecte.
- Les critères indisponibles dans une source sont présentés comme inconnus et
  non comme absents.

### 9.6 Scoring

Deux scores déterministes et indépendants sont calculés :

- un score de potentiel commercial pour les prospects réguliers ;
- un score d'intérêt commercial pour les événements.

Chaque score est un entier visible de 0 à 100. Il peut être utilisé pour
filtrer et trier les fiches.

Le score d'un prospect régulier peut notamment utiliser :

- le type et l'activité ;
- la tranche d'effectif locale lorsqu'elle est connue ;
- les signaux indiquant un site fréquenté ou adapté ;
- la disponibilité et la portée des coordonnées professionnelles.

Le score d'un événement peut notamment utiliser :

- sa catégorie ;
- les mots et expressions de son titre et de sa description ;
- les indicateurs de fréquentation ou d'ampleur lorsqu'ils existent ;
- la présence d'un organisateur ou d'un contact exploitable ;
- des signaux positifs tels que festival, foire, fête, compétition ou appel à
  restaurateurs ;
- des signaux négatifs tels que petit atelier, visite guidée, conférence ou
  activité à capacité limitée.

Le score :

- ne dépend pas de la distance ;
- ne dépend pas de la date ou de l'urgence ;
- ne dépend pas d'un statut de prospection ;
- ne pénalise pas automatiquement une donnée inconnue ;
- affiche les règles qui l'ont augmenté ou diminué ;
- est reproductible et recalculé lorsque les données utiles ou les règles
  changent.

Le MVP ne définit pas de catégories « faible », « moyen » ou « prioritaire »
et n'applique aucun seuil qui cache automatiquement une fiche. De tels seuils
ne seront envisagés qu'après qualification d'un échantillon réel. Les
pondérations et jeux d'exemples relèvent de `docs/scoring.md`.

### 9.7 Sources, synchronisation et provenance

- La première source de prospects réguliers du MVP est l'API Recherche
  d'Entreprises. L'opportunité importée correspond à l'établissement local,
  identifié par son SIRET lorsqu'il existe, et non à la seule unité légale
  identifiée par son SIREN.
- La première source d'événements du MVP est l'API REST DATAtourisme.
- La couverture réelle de ces deux sources autour de l'adresse de référence
  est vérifiée sur un échantillon avant de considérer leurs connecteurs comme
  validés.
- De nouvelles sources sont ajoutées progressivement lorsque leur couverture,
  leur qualité et leur coût de normalisation le justifient.
- Les prospects réguliers sont actualisés automatiquement une fois par mois et
  peuvent aussi l'être à tout moment avec un bouton « Actualiser maintenant ».
- Les événements sont actualisés automatiquement chaque nuit, selon le fuseau
  Europe/Paris, et peuvent également l'être manuellement.
- Le déclenchement manuel est disponible notamment après un changement
  d'adresse ou de rayon, sans attendre la prochaine exécution planifiée.
- Deux collectes identiques ne s'exécutent jamais simultanément.
- Relancer une collecte ne doit pas recréer une fiche déjà identifiée.
- Une source peut actualiser ses observations, mais jamais les corrections ou
  notes de l'utilisateur.
- Une collecte peut actualiser les observations externes d'une fiche masquée,
  mais ne peut jamais la démasquer.
- La date de dernière observation d'une donnée externe est conservée. Une
  absence lors d'une collecte ne supprime, ne masque et ne ferme jamais
  automatiquement une fiche.
- Une donnée ne peut être marquée comme potentiellement obsolète qu'à partir
  d'un signal fiable propre à sa source ou d'absences répétées lors de
  collectes réussies et comparables. Les règles précises sont définies par
  source.
- Un échec partiel indique clairement quelles sources ou zones n'ont pas été
  actualisées.
- Une collecte échouée ne supprime et ne masque aucune donnée déjà conservée.
- Chaque observation externe conservée garde sa provenance, même lorsque
  plusieurs sources sont regroupées dans une fiche.

L'ordre d'intégration envisagé après les deux sources du MVP est :

1. l'annuaire officiel de l'administration française, pour compléter les
   administrations et leurs contacts publics ;
2. le Répertoire National des Associations, pour les associations absentes de
   SIRENE ;
3. OpenAgenda, comme complément événementiel ;
4. les données SIRENE directes et les agendas locaux si leur gain de couverture
   justifie leur complexité.

L'enrichissement automatique depuis les sites officiels n'appartient pas au
MVP.

### 9.8 Modifications, notes et masquage

- Une fiche peut être créée manuellement.
- L'utilisateur peut notamment corriger le nom ou le titre, la description, le
  type ou la catégorie, l'activité, les dates, l'adresse, l'organisateur et les
  coordonnées d'une fiche.
- Les valeurs calculées, notamment la distance, le score et la provenance, ne
  sont pas modifiées directement. Elles sont recalculées à partir des données
  corrigées lorsqu'elles en dépendent.
- Une modification utilisateur est enregistrée comme une valeur prioritaire,
  distincte de la valeur externe originale.
- L'utilisateur peut identifier la provenance d'une valeur et restaurer la
  valeur source.
- Chaque fiche possède une note libre protégée des synchronisations.
- L'utilisateur peut masquer une fiche. Un motif facultatif peut être choisi,
  par exemple « sans intérêt », « doublon », « information incorrecte » ou
  « autre ».
- Une fiche masquée disparaît de toutes les listes, recherches et résultats
  ordinaires, mais son contenu complet reste en base.
- Un onglet global « Fiches masquées » permet de rechercher et filtrer les
  fiches masquées par famille, de consulter leur motif et de les démasquer.
- Une fiche masquée reste prise en compte par la déduplication. Une collecte
  peut mettre à jour ses observations sources, mais ne peut ni la recréer sous
  la forme d'une nouvelle fiche lorsqu'elle est reconnue, ni la démasquer.
- Démasquer une fiche la rend à nouveau visible avec ses corrections, sa note,
  ses provenances et ses observations à jour.
- Aucune suppression définitive de fiche n'est proposée dans le MVP.

Le masquage d'une édition d'événement ne s'applique pas automatiquement aux
éditions futures du même événement.

### 9.9 Déduplication

Une fiche normalisée peut regrouper plusieurs observations sources.

Le rapprochement suit les principes suivants :

1. un même fournisseur et un même identifiant externe mettent à jour la fiche
   existante ;
2. un même identifiant d'établissement fiable, tel qu'un SIRET, permet un
   rapprochement automatique ;
3. un identifiant de l'organisme, tel qu'un SIREN, ne suffit pas à fusionner
   ses implantations locales ;
4. deux établissements physiques distincts d'une même entreprise ne sont pas
   des doublons ;
5. deux descriptions d'une même édition d'événement peuvent être rapprochées
   lorsque le titre, les dates, le lieu et l'organisateur concordent fortement ;
6. une correspondance incertaine n'est jamais fusionnée silencieusement ;
7. toutes les provenances d'une fiche fusionnée restent consultables ;
8. un doublon restant peut être masqué manuellement afin que le même objet
   source ne recrée pas une fiche visible.

La déduplication parfaite n'est pas un critère réaliste. La priorité est de
réduire fortement les doublons certains sans créer de fausses fusions.

Dans le MVP, masquer un doublon ne fusionne pas son contenu avec la fiche
conservée. Une fusion manuelle complète demanderait de choisir une fiche
principale, résoudre les valeurs contradictoires, rattacher toutes les sources
et conserver l'autre fiche comme alias. Cette fonction est reportée après le
MVP.

## 10. Périmètre du MVP

Le MVP valide la boucle suivante : configurer une zone, collecter des données,
faire ressortir les opportunités pertinentes et organiser manuellement les
résultats.

Il comprend :

- l'accès Internet protégé par connexion pour un compte unique ;
- le changement du mot de passe depuis les réglages ;
- une adresse de référence configurable ;
- un rayon de collecte de 50 km par défaut et limité à 50 km ;
- un rayon de recherche local distinct, réglable jusqu'à 50 km ;
- le lancement manuel des collectes ;
- l'actualisation automatique mensuelle des prospects réguliers et nocturne
  quotidienne des événements ;
- l'API Recherche d'Entreprises comme première source de prospects réguliers ;
- l'API REST DATAtourisme comme première source d'événements ;
- la conservation locale et la provenance des résultats ;
- les règles de déduplication déterministes les plus fiables ;
- les listes et fiches détaillées des prospects réguliers et événements ;
- les filtres, la recherche textuelle et les tris essentiels ;
- les scores déterministes visibles de 0 à 100 et leurs explications ;
- la création et la modification manuelles de fiches ;
- une note libre par fiche ;
- le masquage et le démasquage des fiches ainsi qu'un onglet dédié aux fiches
  masquées ;
- la conservation des événements passés sans affichage dans les listes
  ordinaires, sauf lorsqu'une fiche explicitement masquée doit rester
  accessible dans l'onglet de masquage ;
- l'affichage de l'état et de la fraîcheur des collectes.

Le MVP ne comprend pas :

- de carte ;
- de CRM, statuts de prospection, historique de contacts ou relances ;
- d'opposition au démarchage structurée ;
- de classifieur IA ;
- de crawl généraliste des sites web ;
- d'intégration simultanée de toutes les sources ;
- de synchronisation continue ou temps réel ;
- de suppression définitive des fiches ;
- de fusion manuelle complète avec résolution des conflits ;
- d'interface d'archive pour consulter les événements passés ;
- de distance routière ;
- de comptes multiples ou de rôles ;
- d'envoi d'emails ou de SMS.

## 11. Fonctionnalités futures

- ajout de l'annuaire officiel de l'administration française, puis du
  Répertoire National des Associations ;
- ajout d'OpenAgenda comme source événementielle complémentaire, puis
  d'agendas locaux lorsque leur apport est démontré ;
- recours aux données SIRENE directes si le gain d'exhaustivité justifie la
  complexité supplémentaire ;
- enrichissement contrôlé depuis les sites web officiels ;
- réglage avancé de la fréquence et des horaires de collecte si nécessaire ;
- rapprochement avancé, détection des doublons probables et fusion manuelle
  avec choix de la fiche principale, résolution des conflits et conservation
  des alias ;
- regroupement des événements fortement récurrents en séries ;
- interface d'archive pour rechercher et consulter les événements passés ;
- vue cartographique ;
- CRM avec statuts, notes de prospection, historique des contacts, relances et
  opposition future au démarchage ;
- rappels, alertes et synthèses périodiques ;
- export et intégrations email ou calendrier ;
- calcul de distance ou de temps routier si cela apporte une valeur démontrée ;
- classifieur IA entraîné sur des exemples qualifiés ;
- interface minimale indépendante du fournisseur de modèle, compatible avec
  un modèle local tel qu'Ollama ou une API externe ;
- authentification multifacteur si le niveau de risque le justifie.

Le multi-utilisateur et les rôles restent hors scope tant que le produit est
destiné à un seul exploitant.

## 12. Exigences non fonctionnelles

### 12.1 Performance

- Sur un jeu de référence représentant le volume local attendu, au moins 95 %
  des recherches, changements de rayon, filtres et tris doivent produire leur
  résultat côté serveur en moins d'une seconde.
- Aucune requête fournisseur n'est effectuée pendant ces opérations.
- Le volume du jeu de référence sera fixé après la première collecte réelle.

### 12.2 Sécurité

- Toute communication Internet avec l'application utilise HTTPS.
- Aucun contenu métier n'est accessible sans authentification.
- Les mots de passe ne sont jamais conservés ni journalisés en clair ; seul un
  condensat salé produit par un algorithme adapté est stocké.
- Le mot de passe n'est transmis que via HTTPS et n'existe en clair que de
  manière transitoire pendant sa saisie et sa vérification.
- Une session devient inutilisable après déconnexion ou expiration.
- Après un changement de mot de passe, les autres sessions deviennent
  inutilisables.
- Les tentatives de connexion répétées sont limitées ou temporairement
  bloquées.
- Aucun secret fournisseur n'est exposé dans l'interface ou les journaux.
- PostgreSQL n'est jamais exposé directement sur Internet.
- Des sauvegardes adaptées aux données utilisateur sont prévues avant une mise
  en production réelle.

Les mécanismes techniques précis relèvent de `docs/architecture.md`.

### 12.3 Fiabilité et qualité des données

- Une collecte est relançable sans créer de doublons certains.
- Les résultats d'une collecte partiellement échouée sont identifiables.
- Les données déjà collectées restent consultables en cas d'indisponibilité
  d'un fournisseur.
- Les dates de collecte et de dernière observation sont visibles.
- Les données absentes, inconnues, obsolètes ou corrigées sont distinguables.
- Les fiches masquées, les événements passés et les observations
  potentiellement obsolètes sont trois états distincts.

### 12.4 Conformité

- La collecte se limite aux informations professionnelles publiques utiles au
  produit.
- La provenance des coordonnées de contact est conservée.
- Les licences et conditions d'utilisation de chaque fournisseur doivent être
  validées avant son intégration.
- Toute future extraction depuis un site officiel doit respecter les règles
  applicables, la proportionnalité et une politique de conservation définie.

## 13. Critères d'acceptation du MVP

Le MVP est acceptable lorsque :

1. une personne non connectée ne peut consulter aucune donnée métier ;
2. l'utilisateur peut se connecter et se déconnecter avec son compte unique,
   puis changer son mot de passe en fournissant le mot de passe actuel et deux
   saisies identiques du nouveau ; les autres sessions sont alors invalidées ;
3. il peut saisir ou modifier une adresse, vérifier sa position et définir un
   rayon de collecte valant 50 km par défaut et limité à 50 km, sans supprimer
   les données existantes ni déclencher immédiatement une collecte ;
4. il peut lancer manuellement une collecte qui dépasse les frontières des
   Landes ;
5. les prospects réguliers sont actualisés automatiquement une fois par mois
   et les événements chaque nuit selon le fuseau Europe/Paris ;
6. une collecte réussie depuis l'API Recherche d'Entreprises et une autre
   depuis l'API REST DATAtourisme créent des fiches normalisées, consultables
   et accompagnées de leur provenance ;
7. une seconde collecte identique ne recrée pas les fiches déjà identifiées et
   deux collectes identiques ne s'exécutent pas simultanément ;
8. une collecte de 50 km peut être filtrée localement à 30 km, et tout autre
   changement de filtre ou de tri peut être appliqué, sans nouvel appel
   externe ;
9. une recherche dépassant la dernière couverture réussie d'une source est
   signalée comme potentiellement incomplète, sans avertissement lié aux
   frontières administratives ;
10. un prospect régulier est localisé depuis son implantation physique et non
   depuis son seul siège juridique ;
11. les prospects réguliers prennent en charge tous les filtres de la section
    9.3, et les événements tous ceux de la section 9.4 ;
12. chaque fiche importée affiche au minimum son fournisseur, un lien vers
    l'original lorsqu'il existe et sa date d'observation ; son identifiant
    externe ou sa clé technique stable est conservé par le système ;
13. chaque fiche affiche un score compris entre 0 et 100 ainsi que le libellé
    et le sens, positif ou négatif, de chaque règle qui y a contribué ; aucun
    seuil ne cache automatiquement une fiche ;
14. changer l'adresse, le rayon, la période ou les filtres ne modifie pas le
    score intrinsèque d'une fiche ;
15. l'utilisateur peut créer une fiche, corriger ses champs et ajouter une
    note ;
16. une collecte ultérieure ne remplace pas les corrections ou notes de
    l'utilisateur ;
17. l'utilisateur peut masquer une fiche, la retrouver dans l'onglet « Fiches
    masquées » et la démasquer ; une collecte ne la recrée pas et ne la
    démasque pas lorsqu'elle est reconnue ;
18. les événements passés restent en base sans apparaître dans les listes
    ordinaires ; un événement explicitement masqué reste néanmoins accessible
    dans l'onglet « Fiches masquées » même après être devenu passé ;
19. un faible score, l'absence dans un filtre ou une observation devenue
    potentiellement obsolète ne provoque ni suppression ni masquage ;
20. en cas d'échec total ou partiel d'un fournisseur, l'écran de collecte
    affiche la source concernée, l'état d'échec et la date du dernier succès,
    tandis que les anciennes données restent consultables ;
21. un contact central ou de portée inconnue n'est jamais présenté comme un
    contact confirmé de l'implantation locale ;
22. en production, les accès utilisent HTTPS, le mot de passe n'est pas stocké
    en clair et une session ne fonctionne plus après déconnexion ou expiration.

## 14. Critères de succès produit

Les premiers indicateurs doivent mesurer l'utilité réelle plutôt que le volume
brut collecté :

- temps nécessaire pour obtenir une courte liste d'opportunités exploitables ;
- proportion d'événements pertinents parmi les mieux classés ;
- proportion de doublons dans les premiers résultats ;
- proportion de fiches disposant d'une position exploitable ;
- provenance renseignée pour toutes les données importées ;
- absence de recréation ou de démasquage depuis le même objet source après
  masquage ;
- absence d'écrasement des corrections et notes utilisateur ;
- fraîcheur obtenue pour chaque famille de sources.

Les objectifs chiffrés de pertinence et de déduplication seront fixés après
qualification manuelle d'un premier échantillon réel dans la zone d'activité.

## 15. Risques et hypothèses

- La couverture et la qualité réelles des sources dans la zone choisie restent
  à mesurer.
- Ajouter des sources améliore potentiellement la couverture, mais augmente la
  normalisation, les conflits et les doublons.
- Les limites de pagination, de volume ou de quota des fournisseurs peuvent
  rendre une collecte de 50 km incomplète si l'adaptateur ne subdivise pas et
  ne contrôle pas correctement la zone.
- Les données d'effectif et de contact local seront souvent absentes ou
  imprécises.
- Un géocodage incorrect peut fausser les filtres de distance ; la position
  retenue doit donc être vérifiable et corrigeable.
- Une déduplication trop agressive peut fusionner deux opportunités distinctes.
- Une fiche utile peut être masquée par erreur ; le caractère réversible du
  masquage et l'onglet dédié permettent de la retrouver.
- Le scoring initial devra être ajusté avec des exemples réels et des retours
  utilisateur.
- Une collecte automatique doit échouer de manière visible et sans altérer les
  données précédemment collectées.
- L'hébergement sur Internet impose une configuration sécurisée même si
  l'application ne compte qu'un utilisateur.

## 16. Décisions de mise en œuvre restant à documenter

Les décisions produit principales sont arrêtées. Les points suivants ne
changent pas le périmètre du MVP, mais devront être précisés dans les documents
spécialisés avant leur implémentation :

- fournisseur de géocodage et procédure de correction d'une position erronée,
  dans `docs/data-sources.md` ;
- règles, pondérations et exemples initiaux des deux scores, dans
  `docs/scoring.md` ;
- critères propres à chaque source pour déclarer une observation
  potentiellement obsolète et niveau d'historisation des anciennes valeurs,
  dans `docs/data-sources.md` et `docs/database.md` ;
- heure exacte, politique de reprise et supervision des collectes mensuelles et
  nocturnes, dans `docs/architecture.md` ;
- création initiale du compte unique et commande ou procédure administrative
  de remplacement d'un mot de passe oublié, dans `docs/architecture.md`.
