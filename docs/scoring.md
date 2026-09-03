# Radar — Scoring commercial

> Statut : règles initiales provisoires à qualifier sur des données réelles
>
> Dernière mise à jour : 3 septembre 2026
>
> Versions candidates du MVP : `prospect-v1` et `evenement-v1`

## 1. Objet du document

Ce document définit les deux scores déterministes du MVP :

- le potentiel commercial d'un prospect régulier ;
- l'intérêt commercial d'un événement.

Il précise leurs entrées, leurs pondérations initiales, leur explication et le
protocole qui permettra de les ajuster autour de Dax.

Un score sert uniquement à ordonner et filtrer des opportunités. Ce n'est ni
une probabilité de vente, ni une estimation de chiffre d'affaires, ni une
décision automatique. Les deux scores ne sont pas comparables entre eux : un
prospect à 70 et un événement à 70 appartiennent à deux classements distincts.

Les pondérations de ce document constituent une hypothèse de départ. Elles ne
seront considérées comme validées qu'après la qualification de l'échantillon
réel décrit en section 11.

## 2. Principes invariants

### 2.1 Deux calculs indépendants

Un prospect utilise uniquement `prospect-v1`. Un événement utilise uniquement
`evenement-v1`. Une règle d'une famille ne peut pas contribuer au score de
l'autre famille.

### 2.2 Score intrinsèque

Le score ne dépend jamais :

- de la distance à l'adresse de référence ;
- du rayon de collecte ou de recherche ;
- de la date de l'événement, du délai restant ou de l'urgence à contacter ;
- d'une date limite ou de l'état d'ouverture des candidatures ;
- de l'état temporel à venir, en cours ou passé ;
- du statut programmé, reporté ou annulé ;
- du masquage de la fiche ;
- de l'état administratif d'un prospect ;
- d'une future donnée CRM, d'une relance ou d'une réponse commerciale ;
- de la note libre de l'utilisateur ;
- de la source, de la fraîcheur ou du nombre d'observations externes ;
- de la position géographique ou de sa qualité.

Ces informations peuvent modifier la visibilité, les filtres ou l'ordre de
tri demandé par l'utilisateur, mais pas la valeur intrinsèque du score.

### 2.3 Inconnue neutre

Une information inconnue contribue toujours pour `0` point. En particulier :

- l'absence d'un email dans une source n'est pas la preuve qu'il n'existe pas ;
- l'absence d'une tranche d'effectif ne vaut pas « zéro salarié » ;
- une fréquentation non publiée ne vaut pas « faible fréquentation » ;
- un organisateur non renseigné ne rend pas automatiquement l'événement peu
  intéressant.

Une contribution négative n'est appliquée qu'à partir d'une information
positive et explicite, par exemple un code Sirene indiquant un établissement
non employeur ou sans salarié à la date de référence, une activité principale
de restauration mobile ou une capacité annoncée de moins de 50 personnes.

### 2.4 Données effectives

Le calcul utilise les valeurs effectives de la fiche : une correction
utilisateur valide remplace la valeur source correspondante pour le calcul,
sans effacer cette dernière. Restaurer la valeur source recalcule le score.

La note libre n'est jamais analysée. Elle peut contenir des informations de
prospection, des hypothèses ou des données sensibles qui ne doivent pas
modifier automatiquement un score.

Les données externes non réutilisables pour la prospection ne sont jamais
utilisées. Une fiche devenue non prospectable à cause d'une restriction de
diffusion sort des scores d'opportunités ordinaires conformément à
`docs/product.md` ; cela ne transforme pas son ancien score en zéro.

### 2.5 Calcul borné et reproductible

Chaque version utilise :

- un socle fixe ;
- un nombre limité de familles de règles ;
- au plus une contribution par famille, sauf pour les canaux de contact
  explicitement additionnés ;
- des contributions entières dont les minima et maxima garantissent déjà un
  résultat entre 0 et 100.

Aucun arrondi ni écrêtage n'est donc nécessaire pour les versions initiales.
À données et version identiques, le résultat et ses explications sont
identiques.

## 3. Données normalisées utilisées

Le moteur de score ne lit pas directement les objets Sirene, DATAtourisme ou
d'un futur fournisseur. Les adaptateurs traduisent leurs valeurs dans des
caractéristiques métier normalisées, en conservant la provenance.

### 3.1 Entrées possibles d'un prospect

- profil d'activité principal ;
- type d'organisme ou de site ;
- tranche d'effectif du site local et portée de cette donnée ;
- signaux explicites d'accueil ou d'incompatibilité du site ;
- emails, téléphones et sites web professionnels ainsi que leur portée.

Un effectif de l'unité légale entière n'est pas utilisé comme effectif local.
Un contact central n'est pas présenté comme local et reçoit une contribution
plus faible.

Les codes d'activité restent accompagnés de leur nomenclature. Le mapping
vers les profils de la section 6 doit être explicite et versionné séparément
pour chaque nomenclature, notamment lors du passage de la NAF 2008 à la
NAF 2025. Un code non mappé produit le profil `autre_ou_inconnu`, soit zéro
point ; il n'est jamais deviné à partir d'un code ressemblant.

### 3.2 Entrées possibles d'un événement

- format principal normalisé ;
- fréquentation attendue ou capacité propre à l'événement lorsqu'elle est
  publiée ;
- signaux textuels d'ampleur ;
- signaux explicites concernant les food trucks, restaurateurs ou vendeurs ;
- organisateur identifié ;
- contact professionnel et site officiel.

La capacité générale d'un lieu n'est pas assimilée à la fréquentation de
l'événement. Un nombre n'est exploité que si son contexte indique clairement
des visiteurs, participants, spectateurs, personnes attendues ou places pour
cet événement.

## 4. Normalisation et règles textuelles

Les règles textuelles restent volontairement simples. Elles s'appliquent au
nom, au titre, à la description et aux libellés métier effectifs prévus par la
règle. Elles ne s'appliquent ni aux notes utilisateur, ni aux URL, ni au texte
libre des coordonnées de contact.

Avant la recherche d'une expression, Radar :

1. retire les balises HTML sans concaténer artificiellement des mots ;
2. normalise Unicode et la casse ;
3. crée une représentation sans accents pour la comparaison, tout en gardant
   le texte original comme preuve ;
4. harmonise les apostrophes, les tirets et les espaces ;
5. recherche des mots entiers ou des expressions complètes.

La version initiale n'utilise ni recherche floue, ni racinisation, ni
embeddings, ni modèle de langage. Les variantes utiles de singulier, pluriel
et graphie sont écrites explicitement dans les dictionnaires versionnés. Le
mot `salon`, par exemple, n'est pas reconnu à l'intérieur d'un autre mot.

Une même expression répétée ne compte qu'une fois. Plusieurs expressions d'un
même groupe ne cumulent pas leurs points. Lorsqu'une information structurée
fiable contredit un mot générique de la description, l'information structurée
prévaut. Une incompatibilité explicite, telle que « restauration extérieure
interdite », prévaut sur un signal positif plus vague de la même famille.

Les extraits qui ont déclenché une règle sont conservés avec l'explication du
calcul. Les dictionnaires exacts et leurs tests font partie de la version du
score ; les modifier impose une nouvelle version.

## 5. Explication affichée

Pour chaque calcul, Radar conserve et peut afficher :

- la famille et la version du score ;
- le socle de départ ;
- l'identifiant stable de chaque règle appliquée ;
- son libellé compréhensible ;
- sa contribution signée ;
- la caractéristique ou l'extrait ayant déclenché la règle ;
- la date du calcul.

Exemple d'explication :

```text
Socle prospect                                      40
P-ACT-18 — Industrie ou logistique                 +18
P-EFF-14 — Effectif local connu : 50 à 99          +14
P-SITE-06 — Espace extérieur ou accueil régulier    +6
P-CONTACT — Email local, téléphone local et site    +8
Score prospect-v1                                   86
```

Une entrée inconnue peut être indiquée dans l'interface sous la forme
« Effectif local inconnu : 0 », afin d'expliquer son traitement, mais elle ne
constitue pas une contribution positive ou négative.

## 6. Score des prospects réguliers — `prospect-v1`

### 6.1 Formule

```text
score = 40 + activité + effectif local + aptitude du site + contacts
```

| Famille | Minimum | Maximum |
| --- | ---: | ---: |
| Socle | 40 | 40 |
| Activité principale | -20 | +18 |
| Effectif local | -8 | +22 |
| Aptitude explicite du site | -12 | +12 |
| Contacts professionnels | 0 | +8 |
| **Score final** | **0** | **100** |

Le socle de 40 place une fiche très peu décrite dans une position neutre sans
la faire disparaître. Il ne signifie pas que cette fiche a 40 % de chances de
devenir cliente.

### 6.2 Activité principale

Une seule ligne de ce tableau contribue au score. L'activité principale
structurée et son type de site priment sur un mot isolé du nom. Si plusieurs
activités sont réellement publiées sans activité principale identifiable, la
contribution vaut zéro.

| ID | Profil normalisé | Exemples de portée | Points |
| --- | --- | --- | ---: |
| `P-ACT-M20` | Restauration mobile concurrente | Food truck, camion-restaurant, restauration ambulante | -20 |
| `P-ACT-M12` | Restauration déjà au cœur du site | Restaurant, restauration rapide, café, traiteur comme activité principale | -12 |
| `P-ACT-18` | Fort potentiel de présence ou de passage | Industrie manufacturière, usine, entrepôt ou plateforme logistique, camping ou hôtellerie de plein air | +18 |
| `P-ACT-14` | Potentiel collectif ou événementiel | BTP et génie civil, équipement ou club sportif, lieu culturel ou de loisirs, organisateur d'événements, comité des fêtes, parc d'exposition | +14 |
| `P-ACT-10` | Collectivité ou grand site de service | Administration locale, collectivité, enseignement, santé ou action sociale disposant d'un site physique | +10 |
| `P-ACT-06` | Passage professionnel possible | Commerce de gros, commerce non alimentaire ou service exercé dans un site accueillant du personnel ou du public | +6 |
| `P-ACT-00` | Autre, mixte ou inconnu | Activité non mappée ou information insuffisante | 0 |

Les catégories sont des hypothèses commerciales, pas des jugements sur les
organismes. La restauration reçoit une contribution négative parce qu'elle
offre déjà le service vendu par le food truck, mais ce choix devra être
confronté aux pratiques locales : certains bars ou lieux de restauration
peuvent au contraire accueillir ponctuellement un food truck.

Le mapping précis des codes sources vers ces profils doit respecter leur sens
et non leur seule section générale. Par exemple, une activité située dans une
grande section « transport » ne devient pas automatiquement une plateforme
logistique.

### 6.3 Effectif du site local

Une seule tranche contribue. Pour Sirene, le tableau reprend la sémantique des
tranches d'effectif de l'établissement, et non celle de l'unité légale.
Les libellés des codes, notamment la distinction entre `NN` et `00`, suivent
la [description officielle des variables
Sirene](https://www.insee.fr/fr/statistiques/fichier/3711695/Description-liste-sirene-fr.pdf).

| ID | Effectif local connu | Code Sirene courant indicatif | Points |
| --- | ---: | --- | ---: |
| `P-EFF-M08` | 0 salarié ou établissement non employeur | `00` ou `NN` | -8 |
| `P-EFF-M06` | 1 à 2 | `01` | -6 |
| `P-EFF-M03` | 3 à 5 | `02` | -3 |
| `P-EFF-00` | 6 à 9 | `03` | 0 |
| `P-EFF-05` | 10 à 19 | `11` | +5 |
| `P-EFF-10` | 20 à 49 | `12` | +10 |
| `P-EFF-14` | 50 à 99 | `21` | +14 |
| `P-EFF-18` | 100 à 199 | `22` | +18 |
| `P-EFF-22` | 200 ou plus | `31` à `53` | +22 |
| `P-EFF-UNK` | Inconnu ou portée non locale | Absent ou non applicable | 0 |

L'année de l'effectif reste affichable mais ne change pas les points. La
fraîcheur appartient à l'explication de la donnée, pas au potentiel
intrinsèque. Un effectif connu mais ancien ne doit toutefois pas être présenté
comme une mesure actuelle sans sa date.

### 6.4 Aptitude explicite du site

Une seule contribution est retenue. L'ordre du tableau est aussi l'ordre de
priorité en cas de conflit.

| ID | Signal établi dans une donnée effective | Points |
| --- | --- | ---: |
| `P-SITE-M12` | Refus explicite des vendeurs extérieurs, absence explicite d'accueil ou simple domiciliation sans site exploitable | -12 |
| `P-SITE-12` | Le site indique accueillir ou rechercher des food trucks ou emplacements de restauration mobile | +12 |
| `P-SITE-06` | Présence explicite d'un espace extérieur adapté, d'un parking utilisable, d'un accueil régulier du public ou de manifestations sur le site | +6 |
| `P-SITE-00` | Aucun signal fiable ou information inconnue | 0 |

La simple présence du mot « parking » dans une adresse ou à proximité ne
suffit pas. Le signal doit décrire le site lui-même. Radar ne déduit pas
l'accessibilité d'une photographie, d'une carte ou d'une catégorie générale.

### 6.5 Contacts professionnels

Au plus un contact par canal contribue. Si plusieurs valeurs existent pour un
même canal, Radar retient la portée la plus utile sans additionner les
doublons.

| Canal | Portée locale confirmée | Portée inconnue | Portée centrale | Inconnu |
| --- | ---: | ---: | ---: | ---: |
| Email professionnel | +4 | +2 | +1 | 0 |
| Téléphone professionnel | +3 | +1 | +1 | 0 |
| Site officiel | +1 | +1 | +1 | 0 |

La somme maximale est donc `+8`. Un site officiel peut être celui du site
local ou de son organisme de rattachement ; son explication indique sa portée.
L'absence d'un canal ne retire aucun point.

## 7. Exemples de prospects

### 7.1 Site industriel documenté

Une usine de 50 à 99 salariés possède un parking décrit comme utilisable et
un email local, un téléphone local et un site officiel :

```text
40 + 18 + 14 + 6 + 8 = 86
```

Le score élevé vient de quatre signaux connus. La distance de l'usine ne
change pas ce résultat.

### 7.2 Fiche très incomplète

Un établissement de service possède une activité non mappée, sans tranche
d'effectif ni contact publié et sans information sur l'accueil :

```text
40 + 0 + 0 + 0 + 0 = 40
```

Les informations manquantes restent neutres. La fiche demeure visible et
peut être enrichie ou corrigée.

### 7.3 Concurrent direct de petite taille

Une activité de restauration mobile déclarée sans salarié et sans autre
signal connu obtient :

```text
40 - 20 - 8 + 0 + 0 = 12
```

Ce faible résultat ne masque ni ne supprime la fiche.

### 7.4 Administration locale avec contacts

Une mairie dont l'effectif local est inconnu, qui indique organiser des
manifestations sur son site et publie un email local, un téléphone local et un
site officiel obtient :

```text
40 + 10 + 0 + 6 + 8 = 64
```

## 8. Score des événements — `evenement-v1`

### 8.1 Formule

```text
score = 35 + format + ampleur + adéquation commerciale + accès organisateur
```

| Famille | Minimum | Maximum |
| --- | ---: | ---: |
| Socle | 35 | 35 |
| Format principal | -15 | +15 |
| Ampleur ou capacité | -10 | +25 |
| Adéquation avec la restauration mobile | -10 | +18 |
| Organisateur et contact | 0 | +7 |
| **Score final** | **0** | **100** |

Le socle inférieur à celui des prospects reflète le bruit attendu dans les
agendas touristiques, sans pénaliser une valeur inconnue à l'intérieur d'une
famille.

### 8.2 Format principal

Une seule contribution est appliquée. Une correction manuelle explicite du
format prévaut. Sinon, Radar utilise le type structuré le plus spécifique de
la source, complété par le titre lorsque celui-ci décrit sans ambiguïté
l'activité réellement annoncée.

Un petit rendez-vous intitulé « Atelier enfants du Festival X » reste ainsi un
atelier même si sa source le rattache aussi à un festival. Lorsque plusieurs
formats incompatibles restent possibles et qu'aucun n'est clairement
principal, la valeur est `mixte_ou_inconnu` et contribue pour zéro.

| ID | Format normalisé | Exemples | Points |
| --- | --- | --- | ---: |
| `E-FMT-15` | Grand format public | Festival, fête locale ou populaire, foire, salon, carnaval, grand rassemblement | +15 |
| `E-FMT-12` | Format collectif généralement fréquenté | Compétition, tournoi, course, rallye, brocante, vide-greniers, braderie | +12 |
| `E-FMT-08` | Spectacle ou marché | Concert, spectacle, marché ouvert au public | +8 |
| `E-FMT-00` | Neutre, mixte ou inconnu | Exposition sans ampleur connue, catégorie générique, format indéterminé | 0 |
| `E-FMT-M08` | Format principalement discursif | Conférence, colloque, débat, rencontre littéraire | -8 |
| `E-FMT-M12` | Petite découverte encadrée | Visite guidée, dégustation commentée, animation en petit groupe | -12 |
| `E-FMT-M15` | Activité de faible capacité par nature | Atelier, cours, formation, stage, activité pédagogique en petit groupe | -15 |

Le mot « national » ou « international » n'affecte pas le format. Il peut
constituer un signal d'ampleur seulement lorsqu'il décrit réellement le
périmètre de l'événement.

### 8.3 Ampleur ou capacité

Radar utilise en priorité une fréquentation attendue propre à l'édition. À
défaut, une capacité d'inscription propre à l'événement peut être utilisée. Le
nombre de places d'un bâtiment générique ne l'est pas.

| ID | Nombre fiable | Points |
| --- | ---: | ---: |
| `E-AMP-25` | 5 000 ou plus | +25 |
| `E-AMP-21` | 2 000 à 4 999 | +21 |
| `E-AMP-17` | 1 000 à 1 999 | +17 |
| `E-AMP-12` | 500 à 999 | +12 |
| `E-AMP-06` | 200 à 499 | +6 |
| `E-AMP-02` | 100 à 199 | +2 |
| `E-AMP-00` | 50 à 99 | 0 |
| `E-AMP-M10` | 1 à 49 | -10 |
| `E-AMP-UNK` | Inconnu | 0 |

En l'absence de nombre fiable, une seule contribution textuelle de repli peut
être appliquée :

| ID | Signal textuel non ambigu | Points |
| --- | --- | ---: |
| `E-AMP-T17` | Plusieurs milliers de visiteurs, participants ou spectateurs explicitement annoncés | +17 |
| `E-AMP-T10` | Événement explicitement majeur, à grande affluence ou destiné à un très large public | +10 |
| `E-AMP-T05` | Public nombreux explicitement annoncé | +5 |
| `E-AMP-TM10` | Petit groupe ou capacité explicitement inférieure à 50 | -10 |
| `E-AMP-T00` | Aucun signal fiable | 0 |

Une expression chiffrée n'est reconnue que si elle relie sans ambiguïté le
nombre à des visiteurs, participants, spectateurs, personnes attendues ou
places de l'événement. Les années, tarifs, numéros de téléphone et nombres de
stands ne sont pas interprétés comme une fréquentation.

Si la source publie à la fois un nombre actuel fiable et une formule vague,
le nombre prévaut. Une fréquentation d'une édition passée peut être conservée
comme provenance, mais elle n'est utilisée pour l'édition courante que si la
source la présente explicitement comme estimation de celle-ci.

### 8.4 Adéquation avec la restauration mobile

Une seule contribution est retenue. Une incompatibilité structurelle
explicite avec des vendeurs extérieurs prévaut sur les signaux positifs.

| ID | Signal explicite | Points |
| --- | --- | ---: |
| `E-FOOD-M10` | Restauration mobile ou vendeurs extérieurs explicitement interdits | -10 |
| `E-FOOD-M06` | Repas couvrant le public explicitement inclus ou restauration exclusivement réservée à un prestataire | -6 |
| `E-FOOD-18` | Appel, candidature ou recherche visant explicitement des food trucks ou restaurateurs | +18 |
| `E-FOOD-12` | Village de restauration, espace food trucks ou accueil de vendeurs alimentaires explicitement annoncé | +12 |
| `E-FOOD-08` | Appel à exposants ou vendeurs compatible avec le format de l'événement, sans mention alimentaire plus précise | +8 |
| `E-FOOD-04` | Buvette, restauration ou repas sur place simplement annoncé | +4 |
| `E-FOOD-00` | Aucune information fiable | 0 |

La mention d'une buvette ou d'un repas ne prouve pas qu'un emplacement est
disponible. Sa faible contribution indique seulement que la restauration fait
partie du fonctionnement de l'événement. La disponibilité réelle reste à
vérifier auprès de l'organisateur.

La date limite et l'état ouvert ou fermé d'une candidature ne changent pas ce
score intrinsèque. Un ancien appel à food trucks reste donc un signal
d'adéquation du format ; il ne prétend pas qu'une candidature est encore
possible. Le moteur de score ne remplace pas la vérification opérationnelle
auprès de l'organisateur.

### 8.5 Organisateur et contact

Les contributions suivantes s'additionnent dans la limite théorique de `+7` :

| ID | Information connue | Points |
| --- | --- | ---: |
| `E-ORG-02` | Organisateur explicitement identifié | +2 |
| `E-CONTACT-03` | Au moins un email ou téléphone professionnel confirmé comme contact de l'organisateur | +3 |
| `E-CONTACT-01` | À défaut, au moins un relais professionnel ou contact de portée inconnue | +1 |
| `E-WEB-02` | Site officiel de l'événement ou de l'organisateur | +2 |

`E-CONTACT-03` et `E-CONTACT-01` sont mutuellement exclusifs. Plusieurs emails
ou téléphones ne cumulent pas davantage de points. Le producteur de la donnée
DATAtourisme n'est pas considéré comme organisateur, conformément à
`docs/data-sources.md`.

## 9. Exemples d'événements

### 9.1 Festival recherchant des restaurateurs

Un festival annonce 4 000 visiteurs attendus, recherche explicitement des
food trucks et possède un organisateur, un contact direct et un site officiel :

```text
35 + 15 + 21 + 18 + 7 = 96
```

La date du festival, qu'il ait lieu dans deux semaines ou dans dix mois, ne
change pas son score.

### 9.2 Petit atelier sans contact

Un atelier limité à 20 personnes, sans information sur la restauration,
l'organisateur ou les contacts, obtient :

```text
35 - 15 - 10 + 0 + 0 = 10
```

Il reste visible et filtrable. Radar ne le masque pas automatiquement.

### 9.3 Brocante avec fréquentation connue

Une brocante annonce 600 visiteurs, identifie son organisateur et fournit
seulement un relais de contact :

```text
35 + 12 + 12 + 0 + 3 = 62
```

Les `3` points d'accès correspondent à l'organisateur (`+2`) et au relais
(`+1`).

### 9.4 Événement générique très incomplet

Un événement sans format précis, sans fréquentation, sans signal de
restauration et sans organisateur ni contact obtient :

```text
35 + 0 + 0 + 0 + 0 = 35
```

L'absence d'information n'est pas confondue avec une faible capacité.

## 10. Cycle de calcul et versionnement

### 10.1 Identité d'une version

Les premières versions sont nommées `prospect-v1` et `evenement-v1`. Chaque
version fige ensemble :

- le socle et les pondérations ;
- les bornes de tranche ;
- les mappings des profils et formats normalisés ;
- les dictionnaires et priorités des signaux textuels ;
- la logique de sélection des contributions.

Le code contient ces règles sous une forme lisible et testée. Le MVP ne
nécessite ni éditeur graphique de règles, ni moteur générique de règles, ni
configuration modifiable à chaud.

Toute modification susceptible de changer un résultat crée une nouvelle
version. Corriger uniquement un libellé d'affichage sans changer le calcul ne
le nécessite pas.

### 10.2 Déclencheurs

Une fiche est recalculée :

- à sa création ;
- lorsque l'import change une donnée effective utilisée par le score ;
- lorsqu'une correction utilisateur modifie ou restaure une telle donnée ;
- lorsqu'une nouvelle version de son score est activée.

Changer l'adresse de référence, le rayon, un filtre, la date courante, une
note ou l'état de masquage ne déclenche pas de recalcul.

### 10.3 Activation d'une nouvelle version

Avant l'activation, la nouvelle version recalcule toutes les fiches de sa
famille et vérifie ses invariants. En cas d'échec, l'ancienne version reste
active. L'interface ne mélange pas silencieusement deux versions dans un même
tri ou filtre.

La persistance physique sera détaillée dans `docs/database.md`, mais elle doit
au minimum permettre de retrouver la version, le score final et les
contributions qui expliquent le résultat courant. Les résultats de
qualification définis en section 11 sont associés à la version évaluée.

## 11. Qualification sur la zone de Dax

### 11.1 But

La qualification vérifie que les données réellement disponibles permettent
de calculer les règles, puis que le classement aide l'utilisateur à trouver
les opportunités évidentes. Elle ne cherche pas à prouver une prédiction de
revenu.

Le jeu provient d'un cercle de 50 km centré sur l'adresse vérifiée de la mairie
de Dax, avec les connecteurs validés selon `docs/data-sources.md`.

### 11.2 Constitution de l'échantillon

Les deux familles sont évaluées séparément.

Pour les prospects, l'échantillon initial contient 50 fiches, ou toutes les
fiches si la collecte en produit moins. Il couvre autant que
possible :

- les différents profils d'activité ;
- toutes les tranches d'effectif présentes ;
- des fiches avec et sans contact publié ;
- des données complètes et incomplètes ;
- l'ensemble de la distribution des scores provisoires.

Pour les événements, l'échantillon contient tous les événements non terminés
si leur nombre ne dépasse pas 100. Au-delà, 100 fiches sont sélectionnées en
répartissant les formats, les niveaux d'information et la distribution des
scores. Il doit inclure des festivals, fêtes, compétitions, brocantes,
marchés, concerts, visites, conférences et ateliers lorsqu'ils existent dans
la collecte.

La sélection et l'identifiant du cycle source sont conservés pour rendre la
comparaison reproductible. Une fiche n'est pas retirée de l'échantillon parce
que son premier score paraît aberrant.

### 11.3 Qualification manuelle

Sans afficher le score ni ses contributions, l'utilisateur classe chaque
fiche dans l'une des appréciations suivantes :

- clairement intéressante ;
- clairement peu intéressante ;
- incertaine.

Il ajoute une justification courte fondée sur l'intérêt commercial pour le
food truck. Cette appréciation sert à l'évaluation et ne devient ni un statut
de fiche, ni un seuil visible dans le produit.

Après cette qualification indépendante, Radar révèle les scores et leurs
explications. L'examen recherche notamment :

- la proportion de cas clairement intéressants dans les 20 et 50 premiers ;
- la proportion de cas clairement peu intéressants dans les 20 derniers ;
- les cas intéressants classés sous de nombreux cas faibles ;
- les faux scores élevés dus à un mot ambigu ou à un mauvais mapping ;
- les faux scores faibles dus à une inconnue traitée comme négative ;
- les contributions jamais déclenchées ou déclenchées trop souvent ;
- les différences entre les fiches complètes et incomplètes.

Ces nombres décrivent la version, mais aucun objectif chiffré n'est fixé avant
la première mesure. Le critère initial reste celui de `docs/product.md` : les
cas clairement intéressants doivent être globalement classés avant les cas
clairement faibles, les calculs doivent rester explicables et les inconnues
neutres.

### 11.4 Ajustement

Chaque anomalie est classée comme :

- donnée source manquante ou erronée ;
- erreur de normalisation ou de mapping ;
- expression textuelle ambiguë ;
- pondération inadaptée ;
- information commerciale non encore représentée.

Une correction de donnée ne justifie pas une règle spéciale visant un nom, un
SIRET ou un UUID précis. Une nouvelle règle n'est ajoutée que si elle exprime
un signal général compréhensible et observé dans plusieurs cas, ou un cas
métier manifestement nécessaire.

Après ajustement, une nouvelle version est calculée sur le même échantillon et
les changements de classement sont documentés. Une collecte ultérieure fournit
ensuite un second échantillon de contrôle afin d'éviter d'adapter toutes les
règles aux seuls exemples initiaux.

Le compte rendu doit conclure séparément pour `prospect-v1` et
`evenement-v1` :

- version acceptable pour démarrer le MVP ;
- version à corriger avant affichage ;
- données disponibles insuffisantes pour appliquer certaines règles.

## 12. Tests attendus

L'implémentation devra couvrir au minimum :

- chaque règle et chaque borne numérique ;
- toutes les valeurs inconnues ;
- les priorités entre signaux contradictoires ;
- l'absence de cumul d'une même expression répétée ;
- la normalisation des accents, apostrophes, tirets, majuscules et espaces ;
- la non-détection à l'intérieur d'un autre mot ;
- l'exclusion des notes, dates, distances, états et données CRM ;
- les exemples calculés de ce document ;
- les bornes mathématiques 0 et 100 ;
- la stabilité du résultat à entrées et version identiques ;
- le recalcul après correction d'une entrée utile ;
- l'absence de recalcul après modification d'un champ exclu ;
- le passage contrôlé d'une version à la suivante.

Des tests de contrat vérifieront séparément les mappings Sirene et
DATAtourisme sur des réponses anonymisées ou des fixtures minimales. Une
évolution inconnue d'un code fournisseur doit produire une valeur neutre et
un signal de mapping à compléter, jamais une classification inventée.

## 13. Présentation et absence de seuil automatique

Toutes les fiches autorisées par leur état produit restent accessibles quel
que soit leur score, y compris un score de `0`. Le MVP :

- affiche la valeur numérique et ses raisons ;
- permet un tri croissant ou décroissant ;
- permet à l'utilisateur de choisir une plage de score ;
- ne définit aucune étiquette automatique « faible », « moyen » ou
  « prioritaire » ;
- ne masque, ne supprime, n'annule et ne rend jamais inactive une fiche à
  cause de son score ;
- n'utilise aucun seuil implicite dans une collecte ou une liste.

Le non-affichage ordinaire d'une fiche masquée, d'un événement passé ou d'un
prospect non prospectable résulte de son état produit et non de son score.

## 14. Évolutions postérieures au MVP

Après plusieurs échantillons qualifiés, les règles pourront être complétées ou
rééquilibrées. Des libellés ou seuils d'aide à la lecture ne seront introduits
que s'ils apportent une valeur démontrée et ne cachent aucune fiche.

Un futur classifieur IA reste hors du MVP. S'il est ajouté, son résultat, sa
version et ses explications seront distincts du score déterministe. Le moteur
déterministe restera disponible comme référence et solution de repli ; le
choix d'Ollama ou d'une API externe ne devra pas modifier le domaine métier.
