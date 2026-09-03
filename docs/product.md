# Radar — Définition du produit

> Statut : cadrage produit validé
>
> Dernière mise à jour : 3 septembre 2026
>
> Périmètre initial : un utilisateur, un food truck, France métropolitaine,
> application web privée

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
voisins. Radar couvre uniquement la France métropolitaine.

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
  professionnelles ;
- un outil de découverte d'opportunités situées hors de France métropolitaine.

## 6. Définitions du domaine

### 6.1 Adresse de référence

Adresse configurable par l'utilisateur et convertie en position géographique.
Dans le MVP, elle sert de centre commun à la zone de collecte et au rayon de
recherche. Elle doit être située en France métropolitaine.

### 6.2 Zone de collecte

Cercle défini par l'adresse de référence et un rayon de collecte. Dans le MVP,
ce rayon vaut 50 km par défaut et ne peut pas dépasser 50 km. Une collecte
interroge les fournisseurs externes pour cette zone et stocke les résultats
localement.

La zone de collecte ne suit aucune frontière départementale ou régionale. Elle
peut sortir des Landes sans restriction et sans avertissement particulier,
mais seules les opportunités situées en France métropolitaine sont collectées.
Lorsqu'un cercle traverse une frontière nationale, sa partie étrangère reste
hors scope et n'est pas présentée comme couverte.

Chaque cycle de collecte conserve le connecteur exécuté, son centre, son rayon,
ses dates de début et de fin ainsi que, pour chaque source ou jeu utilisé, sa
date de publication ou de mise à jour. Un cycle est réussi uniquement lorsque
toute la pagination et toutes les étapes prévues ont été exécutées sans erreur
ni troncature.

Un connecteur est l'intégration d'une famille de données externes dans Radar.
Il peut combiner plusieurs sources : le connecteur Sirene utilise par exemple
l'API Sirene pour les établissements et un jeu distinct pour leur
géolocalisation. La provenance de ces sources reste séparée.

Pour les prospects Sirene, un cycle complet doit :

- énumérer toutes les communes dont le territoire intersecte le cercle de
  collecte ;
- interroger l'état courant des établissements administrativement actifs pour
  lesquels le statut de diffusion de l'établissement et celui de son unité
  légale sont tous deux en diffusion totale (`O`) dans ces communes, et dont la
  réutilisation pour la prospection est autorisée ;
- n'appliquer aucun filtre commercial d'activité pendant cette énumération ;
  l'activité sert ensuite aux filtres et au scoring dans la base locale ;
- pour chaque requête ou lot de communes, parcourir la pagination par curseur
  jusqu'à son terme et comptabiliser tous les résultats annoncés par l'API ;
- vérifier les totaux annoncés pour chaque requête, puis le nombre global de
  SIRET uniques reçus ;
- appliquer le jeu officiel de géolocalisation retenu et classer chaque
  établissement candidat comme situé dans le rayon, hors du rayon ou à
  localisation indéterminée.

Un tel succès garantit que tous les résultats annoncés par les requêtes du
cycle ont été reçus et comptabilisés. L'API étant consultée en direct, il ne
constitue pas un instantané atomique du répertoire à une seconde précise. Il ne
garantit pas non plus que tout organisme réel soit inscrit dans Sirene, que
toute donnée protégée soit réutilisable, ni que toute adresse publiée soit
exacte ou géolocalisable.

Dans le MVP, la couverture active d'un connecteur correspond à son dernier
cycle réussi autour de l'adresse de référence courante. Les données d'anciennes
zones restent consultables.

### 6.3 Rayon de recherche

Rayon utilisé pour filtrer les données déjà présentes dans l'application. Il
est indépendant du rayon de collecte : une collecte de 50 km peut, par
exemple, être consultée avec un rayon de recherche de 30 km.

Dans le MVP, il est réglable jusqu'à 50 km. Modifier ce rayon ne déclenche
jamais de collecte externe. S'il dépasse la couverture effectivement collectée
par un connecteur, l'application signale seulement que les résultats de ce
connecteur peuvent être incomplets.

### 6.4 Prospect régulier

Implantation physique locale susceptible d'accueillir un food truck ou
d'organiser des événements. Il peut s'agir d'un établissement officiellement
identifié ou, à défaut, de l'adresse opérationnelle d'une association, d'une
administration ou d'un autre organisme.

La présence d'un email, d'un téléphone ou d'un site web n'est pas nécessaire
pour qu'une implantation constitue un prospect régulier.

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
représente une manifestation ou une édition commercialement distincte et peut
contenir une ou plusieurs périodes d'occurrence publiées par sa source.

- Un événement continu sur plusieurs jours possède une seule période avec une
  date de début et une date de fin.
- Un événement récurrent à des dates non consécutives, tel qu'un marché
  hebdomadaire, reste une seule fiche lorsque la source le décrit comme un seul
  événement ; ses différentes périodes sont conservées.
- Les éditions 2026 et 2027 d'un même festival sont deux fiches distinctes.
- Le MVP conserve le regroupement fourni par la source. Il n'invente pas
  d'occurrences non publiées et ne regroupe pas automatiquement plusieurs
  fiches distinctes en une série.

L'état temporel est calculé dans le fuseau Europe/Paris :

- un événement est en cours lorsqu'au moins une de ses périodes est en cours ;
- il est à venir lorsqu'aucune période n'est en cours et qu'au moins une
  période future est connue ;
- il est passé lorsque toutes ses périodes connues sont terminées ;
- pour chaque période sans heure de fin, la fin de sa dernière date connue est
  utilisée ; pour une date sans heure, elle reste donc active jusqu'à la fin
  de cette journée.

### 6.8 Organisateur

Organisme responsable d'un événement. Un organisateur peut être lié à
plusieurs événements et peut également constituer un prospect régulier
lorsqu'il possède une implantation locale.

### 6.9 Fiche

Représentation métier affichée dans l'application pour un prospect régulier ou
un événement. Une fiche n'est pas une copie brute d'une ligne fournisseur :
elle peut regrouper plusieurs observations externes, des corrections
utilisateur et une note libre.

### 6.10 Observation source

Enregistrement reçu d'un fournisseur externe. Tant que les règles applicables
en autorisent la conservation, il conserve au minimum le nom du fournisseur,
son identifiant externe ou une clé technique dont la stabilité et l'unicité ont
été vérifiées lorsqu'il n'en fournit pas, son URL lorsqu'elle existe, sa date de
collecte et sa date de mise à jour lorsqu'elle est fournie. Une clé technique
sert à reconnaître une observation de cette source ; elle ne constitue jamais
à elle seule un identifiant commun à plusieurs fournisseurs.

### 6.11 Score commercial

Indicateur de priorité calculé à partir des caractéristiques intrinsèques
d'une fiche. Il aide à trier les opportunités ; il ne constitue ni une
prévision de vente, ni une garantie de fréquentation.

### 6.12 Fiche masquée

Fiche que l'utilisateur a volontairement retirée des listes et recherches
ordinaires. Hors traitement de conformité obligatoire, elle reste entièrement
conservée, continue d'être reconnue par la déduplication et peut recevoir les
mises à jour de ses observations externes. Seul l'utilisateur peut la
démasquer.

Le masquage ne doit pas être confondu avec l'état administratif inactif d'un
prospect, l'état passé d'un événement, un faible score ou l'absence d'une fiche
dans un filtre. Ces situations ne modifient pas l'état de masquage.

### 6.13 Observation potentiellement obsolète

Information externe remplacée ou qui n'est plus confirmée par sa source, par
exemple un ancien numéro de téléphone, une date corrigée ou une fiche qui
n'est plus revue lors de collectes comparables. Cela ne désigne jamais une
fiche à faible score ou écartée par les filtres.

### 6.14 État administratif d'un prospect

Dans Sirene, un établissement est actif ou fermé, tandis que son unité légale
est active ou cessée. Ces deux informations décrivent une situation
administrative et ne correspondent jamais aux horaires d'ouverture quotidiens
d'un commerce.

Un établissement déjà fermé ou rattaché à une unité légale cessée lors de sa
première découverte n'est pas créé comme prospect dans le MVP. Lorsqu'un
établissement déjà connu ferme ou que son unité légale cesse, sa fiche, ses
provenances, ses corrections et sa note restent conservées sous réserve des
obligations légales ou de diffusion, mais elle est exclue des listes ordinaires.

La découverte initiale étant limitée aux établissements actifs, tout SIRET
déjà connu qui disparaît de cette sélection est contrôlé explicitement auprès
de Sirene dans son état courant. Seule une réponse explicite indiquant sa
fermeture ou la cessation de son unité légale peut faire évoluer la fiche vers
cet état. Une absence, une erreur de collecte ou une restriction de diffusion
ne constitue jamais une preuve de fermeture.

Cet état reste distinct du masquage volontaire. Une fiche administrativement
inactive n'apparaît pas dans l'onglet « Fiches masquées » pour ce seul motif.
Si son établissement et son unité légale sont ensuite de nouveau déclarés
actifs, son état administratif est réactivé. Elle ne redevient visible dans les
listes de prospection que si les statuts de diffusion et les règles de
réutilisation l'autorisent, et si l'utilisateur ne l'avait pas également
masquée.

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
10. Une correction ou une note utilisateur survit aux synchronisations, sous
    réserve de l'exception de conformité définie au point 19.
11. Une fusion de doublons conserve toutes les provenances dont la conservation
    reste autorisée.
12. Un rapprochement incertain ne provoque jamais une fusion silencieuse.
13. Une fiche masquée ne doit pas être recréée ni démasquée par une collecte
    tant que son identité reste reconnaissable.
14. Un filtre, un faible score ou le passage du temps ne supprime ni ne masque
    une fiche.
15. L'échec d'un fournisseur ne rend pas indisponibles les données déjà
    collectées.
16. Seul un état administratif explicite provenant d'une source fiable peut
    rendre automatiquement un prospect connu inactif ou le réactiver ; sa
    simple absence lors d'une collecte ne suffit pas.
17. Aucun établissement candidat actif et réutilisable pour la prospection
    n'est écarté au seul motif que sa position est absente ou incertaine ; il
    reste visible avec une localisation à vérifier.
18. Les informations dont la diffusion ou la réutilisation pour la prospection
    est interdite ne sont ni utilisées pour créer une opportunité, ni exposées
    comme données de contact.
19. Une obligation de diffusion ou de conformité prévaut sur la conservation
    ordinaire des observations, corrections et notes ; une donnée saisie
    manuellement ne peut pas servir à contourner une restriction de
    prospection.

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
   dernier succès pour chaque connecteur.
6. Pour Sirene, le bilan affiche les communes terminées ou en échec, compare
   pour chaque requête le total annoncé au nombre de SIRET uniques reçus et
   distingue les établissements confirmés dans le rayon, ceux écartés après
   calcul de distance et ceux dont la localisation reste à vérifier.

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
- Une collecte peut être centrée sur n'importe quelle adresse de France
  métropolitaine, indépendamment des départements ou régions traversés.
- Seule la partie française métropolitaine du cercle est couverte. Sa partie
  éventuelle située à l'étranger ne donne lieu à aucune collecte.
- Le MVP utilise le même centre pour la collecte et la recherche.
- Modifier l'adresse recalcule les distances dans les données locales sans
  supprimer les anciennes données et sans lancer automatiquement une collecte.
- Le rayon de recherche reste modifiable sans appel fournisseur.
- Le rayon de recherche ne peut pas dépasser 50 km dans le MVP, même s'il peut
  être inférieur ou supérieur au rayon de la dernière collecte réussie.
- Si une recherche dépasse la couverture réellement collectée, l'application
  indique que les résultats peuvent être incomplets. Cet avertissement porte
  sur la couverture des données, jamais sur la sortie des Landes.
- La couverture est évaluée séparément pour chaque connecteur à partir de sa
  dernière collecte réussie autour de l'adresse courante.
- Le cercle de recherche est couvert par un connecteur uniquement s'il est
  inclus dans le cercle de cette dernière collecte réussie. Cette indication
  décrit le périmètre interrogé et le niveau de complétude défini pour ce
  connecteur ; elle ne garantit pas que ses sources représentent tout ce qui
  existe dans le monde réel.
- La distance affichée et filtrée est calculée à vol d'oiseau.
- La position d'un établissement Sirene est d'abord recherchée par jointure de
  son SIRET avec le jeu officiel de géolocalisation, puis, si nécessaire et si
  son adresse est publique, par un géocodage de repli.
- Un établissement actif, réutilisable pour la prospection et situé dans une
  commune candidate qui reste sans position fiable est conservé dans une liste
  « Localisation à vérifier ». Sa distance est inconnue et il n'apparaît pas
  arbitrairement dans un filtre par rayon, mais il reste visible afin de ne
  jamais constituer un oubli silencieux.
- Une correction d'adresse peut déclencher un nouveau géocodage et un nouveau
  calcul de distance.
- Les limites de pagination ou de volume d'un fournisseur sont gérées par son
  adaptateur. Une interruption, un curseur inachevé, une incohérence de
  comptage ou une étape inachevée rend la collecte partielle ; elle n'est jamais
  présentée comme ayant couvert tout son périmètre déclaré.

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
- la présence connue d'un email ;
- la présence connue d'un téléphone ;
- la présence connue d'un site web ;
- une plage de score.

Une fiche sans moyen de contact reste une fiche valide et visible. Lorsqu'une
source ne fournit pas un type de contact, celui-ci est inconnu et non considéré
comme définitivement absent. Les filtres de présence sélectionnent uniquement
les fiches pour lesquelles le moyen demandé est effectivement connu.

La découverte Sirene retient les établissements dont l'état courant est actif
et pour lesquels le statut de diffusion de l'établissement et celui de son
unité légale sont tous deux en diffusion totale (`O`) et dont la réutilisation
pour la prospection est autorisée. Elle écarte les établissements déjà fermés
ou rattachés à une unité légale cessée lors de leur première découverte.

Tout SIRET connu qui ne figure plus dans cette sélection active est ensuite
contrôlé directement. Seul un état administratif explicite et fiable peut
rendre un prospect connu inactif ; sa simple absence lors d'une collecte ne
suffit pas. Aucun établissement candidat n'est écarté silencieusement faute de
coordonnées fiables.

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
- la ou les périodes d'occurrence ;
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

Le filtre de période retient une fiche dès qu'au moins une de ses occurrences
chevauche la période recherchée.

Un contact événementiel est considéré comme disponible lorsqu'au moins un
canal professionnel exploitable existe : email, téléphone, site officiel,
lien de réservation ou relais de contact fourni par la source. Il ne doit pas
être présenté comme le contact confirmé de l'organisateur si sa portée n'est
pas connue.

Les événements passés restent conservés dans la base, mais ne sont pas
accessibles dans l'interface ordinaire du MVP. Ils ne font l'objet d'aucune
purge automatique. Si une mise à jour reçue de la source ajoute ou déplace une
occurrence non terminée, la fiche redevient automatiquement visible. Les
événements annulés à venir ne sont pas affichés par défaut, mais peuvent être
inclus avec le filtre de statut. La disparition d'un événement d'une source ne
suffit pas à le marquer comme annulé.

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

Avant de considérer les premières règles comme validées, un échantillon réel
et varié est qualifié manuellement comme « clairement intéressant »,
« clairement peu intéressant » ou « incertain », avec une justification. Ces
jugements servent uniquement à vérifier le classement et ne deviennent pas des
catégories affichées. Les règles initiales sont acceptables lorsqu'elles sont
calculables à partir des données réellement disponibles, restent explicables,
traitent les inconnues de manière neutre et classent globalement les cas
évidemment intéressants avant les cas évidemment faibles.

### 9.7 Sources, synchronisation et provenance

- Le connecteur de prospects réguliers du MVP utilise l'API Sirene open data
  de l'Insee pour obtenir les établissements et le jeu officiel mensuel de
  géolocalisation Sirene pour obtenir leurs coordonnées.
- L'opportunité importée correspond à l'établissement local identifié par son
  SIRET, et non à la seule unité légale identifiée par son SIREN.
- Le connecteur événementiel du MVP utilise l'API REST DATAtourisme.
- Le connecteur Sirene et le connecteur DATAtourisme sont vérifiés dans la zone
  réelle avant d'être considérés comme validés. Le premier combine deux jeux
  officiels dont les provenances et dates restent distinctes.
- De nouvelles sources sont ajoutées progressivement lorsque leur couverture,
  leur qualité et leur coût de normalisation le justifient.
- Les prospects réguliers sont actualisés automatiquement une fois par mois et
  peuvent aussi l'être à tout moment avec un bouton « Actualiser maintenant ».
- Les événements sont actualisés automatiquement chaque nuit, selon le fuseau
  Europe/Paris, et peuvent également l'être manuellement.
- Chaque collecte événementielle cherche tous les événements publiés dans la
  zone qui possèdent au moins une occurrence non terminée, sans imposer de date
  maximale dans le futur. L'horizon réellement disponible dépend uniquement
  de ce que la source a déjà publié.
- Le déclenchement manuel est disponible notamment après un changement
  d'adresse ou de rayon, sans attendre la prochaine exécution planifiée.
- Deux collectes identiques ne s'exécutent jamais simultanément.
- Relancer une collecte ne doit pas recréer une fiche déjà identifiée.
- Une source peut actualiser ses observations sans écraser les corrections ou
  notes de l'utilisateur, sous réserve des obligations de diffusion décrites
  ci-dessous.
- Une collecte peut actualiser les observations externes d'une fiche masquée,
  mais ne peut jamais la démasquer.
- La date de dernière observation d'une donnée externe est conservée. Une
  absence lors d'une collecte ne supprime, ne masque et ne ferme jamais
  automatiquement une fiche.
- Une donnée ne peut être marquée comme potentiellement obsolète qu'à partir
  d'un signal fiable propre à sa source ou d'absences répétées lors de
  collectes réussies et comparables. Les règles précises sont définies par
  source.
- Seule la fermeture d'un établissement ou la cessation de son unité légale,
  fournie explicitement par une source jugée fiable, peut rendre un prospect
  connu administrativement inactif. Son état administratif est réactivé si
  l'établissement et l'unité légale sont ensuite déclarés actifs ; il ne
  réintègre les listes de prospection que si les statuts de diffusion et les
  règles de réutilisation l'autorisent.
- Un échec partiel indique clairement quels connecteurs, requêtes ou jeux n'ont
  pas été actualisés.
- Une collecte échouée ne supprime et ne masque aucune donnée déjà conservée.
- Chaque observation externe conservée conformément aux règles applicables
  garde sa provenance, même lorsque plusieurs sources sont regroupées dans une
  fiche.

Pour chaque cycle Sirene, Radar :

1. détermine, depuis un référentiel géographique officiel, toutes les communes
   dont le territoire intersecte le cercle de collecte ;
2. interroge l'API Sirene sur l'état courant des établissements actifs de ces
   communes, dont le statut de diffusion et celui de leur unité légale sont
   tous deux en diffusion totale et dont la réutilisation pour la prospection
   est autorisée, sans appliquer de filtre commercial d'activité ;
3. suit la pagination par curseur jusqu'au dernier résultat et contrôle les
   totaux annoncés pour chaque requête, les pages reçues et les SIRET uniques ;
4. joint les établissements au fichier officiel de géolocalisation par SIRET,
   puis tente un géocodage de l'adresse publique lorsque la position reste
   absente ou insuffisamment fiable ;
5. calcule la distance exacte à vol d'oiseau et classe chaque établissement
   candidat dans le rayon, hors du rayon ou dans « Localisation à vérifier » ;
6. contrôle séparément l'état courant des SIRET déjà connus qui ont disparu de
   la sélection active avant de décider d'une fermeture ou d'une cessation.

Si un établissement ou son unité légale passe en diffusion partielle (`P`),
cela ne signifie ni que l'établissement est fermé ni que l'unité légale est
cessée. La fiche devient immédiatement « non prospectable — diffusion
restreinte » et sort des listes, recherches, filtres et scores d'opportunités
ordinaires. Les données externes qui ne sont plus réutilisables pour la
prospection ne sont plus affichées ni utilisées. Radar conserve uniquement les
éléments dont la conservation reste autorisée et qui sont nécessaires pour
reconnaître la restriction et éviter une réimportation incorrecte. Les
corrections et notes utilisateur ne servent jamais à contourner cette
restriction ; elles ne sont conservées que si leur conservation possède un
fondement indépendant et licite. Les champs précis à retirer, anonymiser ou
conserver sont documentés et validés avant l'implémentation du connecteur.

La validation manuelle initiale des connecteurs utilise un cercle réel de
50 km centré sur l'adresse géocodée et vérifiée de la mairie de Dax, ainsi qu'un
ensemble varié de prospects et d'événements. Pour Sirene, elle vérifie
notamment l'état courant, le régime de diffusion, la pagination complète, la
concordance des totaux, la jointure par SIRET, la qualité des coordonnées et
les localisations restant à vérifier. Pour DATAtourisme, elle vérifie notamment
les identifiants, la localisation, les dates, les occurrences et la pagination.
La provenance et les erreurs évidentes sont vérifiées dans les deux cas.
L'absence de contacts, d'effectifs ou d'organisateur ne rend ni une fiche ni
une source invalide.

L'ordre d'intégration envisagé après les deux connecteurs métier du MVP est :

1. l'annuaire officiel de l'administration française, pour compléter les
   administrations et leurs contacts publics ;
2. le Répertoire National des Associations, pour les associations absentes de
   Sirene ;
3. OpenAgenda, comme complément événementiel ;
4. les agendas locaux si leur gain de couverture justifie leur complexité.

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
- Chaque fiche possède une note libre protégée des synchronisations, sous
  réserve d'une obligation légale ou de diffusion contraire.
- L'utilisateur peut masquer une fiche. Un motif facultatif peut être choisi,
  par exemple « sans intérêt », « doublon », « information incorrecte » ou
  « autre ».
- Lorsque le motif est « doublon », l'utilisateur peut facultativement
  désigner la fiche conservée. Ce lien ne fusionne ni ne transfère aucun
  contenu.
- Une fiche masquée disparaît de toutes les listes, recherches et résultats
  ordinaires, mais son contenu complet reste en base hors traitement imposé
  par une restriction de diffusion ou une obligation légale.
- Un onglet global « Fiches masquées » permet de rechercher et filtrer les
  fiches masquées par famille, de consulter leur motif et de les démasquer.
- Une fiche masquée reste prise en compte par la déduplication. Une collecte
  peut mettre à jour ses observations sources, mais ne peut ni la recréer sous
  la forme d'une nouvelle fiche lorsqu'elle est reconnue, ni la démasquer.
- Démasquer une fiche la rend à nouveau visible avec les corrections, la note,
  les provenances et les observations dont la conservation reste autorisée.
- Aucune suppression définitive de fiche à l'initiative de l'utilisateur n'est
  proposée dans le MVP. Cette règle n'empêche pas un retrait ou une
  anonymisation imposé par une obligation légale ou de diffusion.

Le masquage d'une édition d'événement ne s'applique pas automatiquement aux
éditions futures du même événement.

### 9.9 Déduplication

Une fiche normalisée peut regrouper plusieurs observations sources.

Le rapprochement suit les principes suivants :

1. un même fournisseur et un même identifiant externe reconnu comme stable
   mettent à jour la fiche existante ;
2. un même identifiant d'établissement fiable, tel qu'un SIRET, permet un
   rapprochement automatique ;
3. un identifiant de l'organisme, tel qu'un SIREN, ne suffit pas à fusionner
   ses implantations locales ;
4. deux établissements physiques distincts d'une même entreprise ne sont pas
   des doublons ;
5. pour un événement, seul le même couple fournisseur-identifiant externe
   stable permet de reconnaître automatiquement la même fiche ; pour la source
   initiale, ce couple est formé de DATAtourisme et de son UUID ;
6. pour les événements, deux identifiants externes différents restent deux
   fiches distinctes, même lorsque leur titre, leurs dates, leur lieu ou leur
   organisateur se ressemblent fortement ;
7. ces ressemblances pourront servir ultérieurement à signaler un doublon
   probable, mais jamais à provoquer seules une fusion automatique ;
8. toutes les provenances d'une fiche regroupée dont la conservation reste
   autorisée restent consultables ;
9. un doublon constaté par l'utilisateur peut être masqué et éventuellement
   relié à la fiche conservée afin que le même objet source ne recrée pas une
   fiche visible.

La stabilité et l'unicité d'un identifiant externe sont vérifiées lors de la
validation de chaque source. Si une source réutilise un identifiant entre des
éditions commercialement distinctes, son adaptateur doit appliquer une règle
d'identité spécifique documentée.

La déduplication parfaite n'est pas un critère réaliste. Le MVP ne cherche pas
automatiquement les doublons probables : sa priorité est d'éviter la création
répétée d'une fiche certaine sans produire de fausses fusions.

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
- une couverture limitée à la France métropolitaine ;
- un rayon de collecte de 50 km par défaut et limité à 50 km ;
- un rayon de recherche local distinct, réglable jusqu'à 50 km ;
- le lancement manuel des collectes ;
- l'actualisation automatique mensuelle des prospects réguliers et nocturne
  quotidienne des événements ;
- l'API Sirene open data de l'Insee et le jeu officiel de géolocalisation
  Sirene comme premières sources des prospects réguliers ;
- l'API REST DATAtourisme comme première source d'événements ;
- la pagination complète de Sirene, le contrôle des totaux par requête et la
  comptabilisation de chaque SIRET candidat ;
- la conservation locale et la provenance des résultats ;
- la déduplication automatique limitée aux identifiants fiables ;
- les listes et fiches détaillées des prospects réguliers et événements ;
- les filtres, la recherche textuelle et les tris essentiels ;
- la conservation d'une ou plusieurs périodes par fiche d'événement et la
  collecte sans borne future maximale des occurrences non terminées publiées ;
- l'import et le scoring des fiches même lorsqu'aucun moyen de contact n'est
  connu ;
- l'exclusion des établissements déjà fermés ou rattachés à une unité légale
  cessée lors de leur première découverte, ainsi que la conservation et la
  réactivation éventuelle des prospects connus dont l'état administratif
  évolue ;
- le retrait des listes de prospection et le traitement conforme des fiches
  dont l'établissement ou l'unité légale passe en diffusion partielle ;
- une liste « Localisation à vérifier » pour les établissements actifs et
  réutilisables des communes candidates qui restent sans position fiable ;
- les scores déterministes visibles de 0 à 100 et leurs explications ;
- la création et la modification manuelles de fiches ;
- une note libre par fiche ;
- le masquage et le démasquage des fiches ainsi qu'un onglet dédié aux fiches
  masquées ;
- la conservation des événements passés sans accès dans l'interface ordinaire,
  sauf lorsqu'une fiche explicitement masquée doit rester accessible dans
  l'onglet de masquage ;
- l'affichage de l'état et de la fraîcheur des collectes.

Le MVP ne comprend pas :

- de carte ;
- de CRM, statuts de prospection, historique de contacts ou relances ;
- d'opposition au démarchage structurée ;
- de classifieur IA ;
- de crawl généraliste des sites web ;
- d'intégration simultanée de toutes les sources ;
- de synchronisation continue ou temps réel ;
- de suppression définitive des fiches à l'initiative de l'utilisateur ;
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
- enrichissement contrôlé depuis les sites web officiels ;
- réglage avancé de la fréquence et des horaires de collecte si nécessaire ;
- rapprochement avancé, détection des doublons probables et fusion manuelle
  avec choix de la fiche principale, résolution des conflits et conservation
  des alias ;
- regroupement automatique de plusieurs fiches distinctes d'événements
  récurrents en séries ;
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
- La date et l'heure de chaque requête Sirene, la date de dernière mise à jour
  annoncée par Sirene, le millésime ou la date de publication du jeu de
  géolocalisation et la date d'un éventuel géocodage de repli restent
  distinguables.
- Les données absentes, inconnues, obsolètes ou corrigées sont distinguables.
- Les fiches masquées, les prospects administrativement inactifs, les fiches
  non prospectables pour restriction de diffusion, les événements passés et
  les observations potentiellement obsolètes sont des états distincts.

### 12.4 Conformité

- La collecte se limite aux informations professionnelles publiques utiles au
  produit.
- Seules les données Sirene en diffusion totale et réutilisables pour la
  prospection alimentent les opportunités. Un passage ultérieur en diffusion
  partielle interrompt l'utilisation des données externes désormais protégées
  sans être interprété comme une fermeture.
- Une restriction de diffusion prévaut sur la conservation ordinaire des
  observations et sur les corrections utilisateur ; aucune donnée locale ne
  sert à contourner une opposition à la prospection.
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
3. il peut saisir ou modifier une adresse située en France métropolitaine,
   vérifier sa position et définir un rayon de collecte valant 50 km par défaut
   et limité à 50 km, sans supprimer les données existantes ni déclencher
   immédiatement une collecte ;
4. il peut lancer manuellement une collecte qui dépasse les frontières des
   Landes ;
5. les prospects réguliers sont actualisés automatiquement une fois par mois
   et les événements chaque nuit selon le fuseau Europe/Paris ;
6. le connecteur de prospects Sirene et le connecteur événementiel
   DATAtourisme ont été vérifiés manuellement dans un cercle de 50 km centré sur
   l'adresse géocodée et vérifiée de la mairie de Dax ;
   chaque connecteur parcourt toute sa pagination, crée des fiches normalisées
   accompagnées de leur provenance et signale comme partiel tout cycle qui ne
   peut pas terminer les étapes prévues ;
7. une seconde collecte reconnaît le même couple fournisseur-identifiant
   externe stable et met à jour la fiche au lieu de la recréer ; deux collectes
   identiques ne s'exécutent pas simultanément ;
8. une collecte de 50 km peut être filtrée localement à 30 km, et tout autre
   changement de filtre ou de tri peut être appliqué, sans nouvel appel
   externe ;
9. une recherche dépassant la dernière couverture réussie d'un connecteur est
   signalée comme potentiellement incomplète, sans avertissement lié aux
   frontières administratives ;
10. un prospect Sirene correspond à son établissement local identifié par son
    SIRET, et non au seul siège ou à la seule unité légale ; toutes les communes
    intersectant le cercle sont interrogées sans filtre commercial d'activité,
    chaque curseur est suivi jusqu'à son terme et les résultats reçus sont
    rapprochés du total annoncé pour chaque requête ; chaque établissement
    actif dont le statut de diffusion et celui de son unité légale sont tous
    deux en diffusion totale, et dont la réutilisation pour la prospection est
    autorisée, est comptabilisé comme situé dans le rayon, hors du rayon ou à
    localisation indéterminée ;
11. un établissement déjà fermé ou rattaché à une unité légale cessée lors de
    sa première découverte n'est pas importé ; si un prospect connu acquiert
    ensuite l'un de ces états, sa fiche reste en base mais disparaît des listes
    ordinaires sans devenir une fiche masquée ; son état administratif est
    réactivé lorsque l'établissement et l'unité légale sont de nouveau actifs,
    mais la fiche ne redevient visible que si sa diffusion et sa réutilisation
    pour la prospection sont autorisées et qu'elle n'est pas volontairement
    masquée ; tout SIRET connu absent de la sélection active est contrôlé
    explicitement avant ce changement d'état ;
12. les prospects réguliers prennent en charge tous les filtres de la section
    9.3, et les événements tous ceux de la section 9.4 ; une fiche sans contact
    reste importée, visible et scorée ;
13. chaque fiche importée affiche au minimum son fournisseur, un lien vers
    l'original lorsqu'il existe et sa date d'observation ; son identifiant
    externe ou sa clé technique dont la stabilité a été vérifiée est conservé
    par le système ; pour un prospect Sirene, les provenances et dates des
    données d'établissement, de la géolocalisation officielle et d'un éventuel
    géocodage de repli restent distinctes ;
14. chaque fiche affiche un score compris entre 0 et 100 ainsi que le libellé
    et le sens, positif ou négatif, de chaque règle qui y a contribué ; aucun
    seuil ne cache automatiquement une fiche ;
15. changer l'adresse, le rayon, la période ou les filtres ne modifie pas le
    score intrinsèque d'une fiche ;
16. l'utilisateur peut créer une fiche, corriger ses champs et ajouter une
    note ;
17. une collecte ultérieure ne remplace pas les corrections ou notes de
    l'utilisateur, sauf lorsque le critère 26 impose un traitement de
    conformité ;
18. l'utilisateur peut masquer une fiche, la retrouver dans l'onglet « Fiches
    masquées » et la démasquer ; une collecte ne la recrée pas et ne la
    démasque pas lorsqu'elle est reconnue ;
19. les événements passés restent en base sans être accessibles dans
    l'interface ordinaire ; une mise à jour source ajoutant une occurrence non
    terminée les rend à nouveau visibles, et un événement explicitement masqué
    reste accessible dans l'onglet « Fiches masquées » même après être devenu
    passé ;
20. un faible score, l'absence dans un filtre ou une observation devenue
    potentiellement obsolète ne provoque ni suppression ni masquage ;
21. en cas d'échec total ou partiel d'un fournisseur, l'écran de collecte
    affiche la source concernée, l'état d'échec et la date du dernier succès,
    tandis que les anciennes données restent consultables ;
22. un contact central ou de portée inconnue n'est jamais présenté comme un
    contact confirmé de l'implantation locale ;
23. en production, les accès utilisent HTTPS, le mot de passe n'est pas stocké
    en clair et une session ne fonctionne plus après déconnexion ou expiration ;
24. une fiche événementielle peut conserver plusieurs occurrences non
    consécutives et reste visible tant qu'au moins l'une d'elles n'est pas
    terminée ; un événement publié plusieurs mois ou années à l'avance est
    collecté sans borne future maximale ;
25. deux événements portant des identifiants externes différents ne sont
    jamais fusionnés automatiquement dans le MVP ; l'utilisateur peut masquer
    le doublon constaté et, facultativement, le relier à la fiche conservée ;
26. un établissement Sirene actif, dont le statut de diffusion et celui de son
    unité légale sont tous deux en diffusion totale et dont la réutilisation
    pour la prospection est autorisée, n'est jamais perdu en raison d'une
    position absente : il reste consultable dans « Localisation à vérifier » ;
    si l'établissement ou son unité légale passe en diffusion partielle, la
    fiche devient non prospectable sans être déclarée fermée, sort des listes
    et scores ordinaires, et aucune donnée restreinte n'est affichée ni utilisée
    pour la prospection.

## 14. Critères de succès produit

Les premiers indicateurs doivent mesurer l'utilité réelle plutôt que le volume
brut collecté :

- temps nécessaire pour obtenir une courte liste d'opportunités exploitables ;
- proportion d'événements pertinents parmi les mieux classés ;
- proportion de doublons dans les premiers résultats ;
- proportion de fiches disposant d'une position exploitable ;
- pour tout cycle Sirene déclaré réussi, égalité entre le total annoncé par
  chaque requête logique et le nombre de SIRET uniques reçus pour cette
  requête, puis égalité entre la somme de ces résultats et le nombre global de
  SIRET uniques, hors recouvrements attendus et explicitement documentés ;
- nombre et proportion d'établissements restant dans « Localisation à
  vérifier » ;
- provenance renseignée pour toutes les données importées ;
- absence de recréation ou de démasquage depuis le même objet source après
  masquage ;
- absence d'écrasement injustifié des corrections et notes utilisateur ;
- fraîcheur obtenue pour chaque famille de sources, en distinguant le registre
  Sirene du jeu de géolocalisation.

Les objectifs chiffrés de pertinence et de déduplication seront fixés après
qualification manuelle d'un premier échantillon réel dans la zone d'activité.
Le compte rendu de validation des sources consigne séparément leur couverture,
les champs réellement disponibles, les limites de pagination et les anomalies
observées.

## 15. Risques et hypothèses

- La couverture et la qualité réelles des sources dans la zone choisie restent
  à mesurer.
- Ajouter des sources améliore potentiellement la couverture, mais augmente la
  normalisation, les conflits et les doublons.
- Une interruption, un quota ou une mauvaise reprise du curseur de l'API
  Sirene peut rendre une collecte incomplète ; les totaux et les SIRET uniques
  doivent donc être contrôlés avant de déclarer son succès.
- Le registre Sirene et le fichier mensuel de géolocalisation peuvent ne pas
  représenter exactement la même date. Un établissement récent peut rester
  temporairement à localiser.
- Certaines coordonnées sont absentes, approximatives ou erronées. Conserver
  les cas indéterminés évite les omissions silencieuses mais peut demander une
  vérification manuelle.
- La complétude visée est celle des résultats annoncés par les requêtes Sirene
  du cycle pour les établissements actifs et réutilisables. Elle ne constitue
  pas un instantané atomique et Sirene ne recense pas nécessairement tous les
  organismes réels, notamment certaines associations sans SIRET.
- Les données passées en diffusion partielle ne peuvent plus être utilisées
  comme auparavant pour la prospection et exigent un traitement conforme.
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

## 16. Décisions et validations restant ouvertes

Les documents spécialisés définissent désormais l'architecture, le modèle de
données, les sources, le scoring et l'ordre de réalisation. Les décisions
produit principales sont arrêtées. Les points suivants ne changent pas le
périmètre du MVP, mais doivent être clos avant l'implémentation ou la mise en
production concernée :

- tester avec une clé réelle la requête d'état courant, les curseurs, les lots
  et les contrôles de totaux de l'API Sirene ;
- comparer autour de Dax les coordonnées de l'API Sirene 3.11, le fichier
  mensuel officiel et le géocodage de repli, puis décider si le fichier reste
  dans le MVP et fixer les niveaux de qualité acceptables ;
- valider sur des réponses DATAtourisme réelles les champs, les périodes, les
  contacts, les statuts et les formes de pagination `next` ;
- vérifier si un UUID DATAtourisme reste propre à une édition ou s'il faut une
  identité d'édition spécifique pour les événements récurrents ;
- valider les données qui peuvent licitement être conservées, retirées ou
  transformées lorsqu'un établissement Sirene passe en diffusion partielle ;
- qualifier manuellement l'échantillon de Dax et ajuster les pondérations et
  mappings initiaux des scores ;
- arrêter le frontend avant le jalon qui introduit l'interface de connexion ;
- calibrer sur l'hébergement réel les paramètres de sécurité, les tailles de
  lots et le mode d'exploitation avant leur mise en production.

Le détail, le protocole et l'échéance de ces décisions figurent dans
`docs/data-sources.md`, `docs/scoring.md`, `docs/architecture.md`,
`docs/database.md` et `docs/roadmap.md`.
