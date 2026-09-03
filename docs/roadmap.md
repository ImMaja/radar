# Radar — Roadmap

> Statut : proposition de séquencement du MVP
>
> Dernière mise à jour : 3 septembre 2026
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

La conception peut avancer sans secret. Les validations réelles des
connecteurs nécessitent toutefois :

- une clé publique pour l'API Sirene 3.11 ;
- une clé pour l'API DATAtourisme v1 ;
- un accès au millésime courant des contours administratifs ;
- tant qu'il reste dans le MVP, un accès au fichier mensuel de géolocalisation
  Sirene.

Les clés sont configurées localement et ne sont jamais ajoutées au dépôt.

Avant le jalon 3 et sa première interface utilisateur, il faudra également
choisir le frontend. La recommandation initiale est une application
TypeScript/React simple sans rendu serveur, car Radar est privé et n'a aucun
besoin de référencement. Ce choix
n'est pas bloquant pour les premières tranches backend et ne doit être figé
qu'après un prototype minimal.

## 4. Jalons du MVP

### Jalon 0 — Cadrage documentaire

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

**But :** éliminer les principales incertitudes avant de bâtir les imports.

Travaux :

- géocoder et vérifier la mairie de Dax ;
- sélectionner les communes qui intersectent le cercle de 50 km ;
- tester la requête Sirene garantissant l'état courant ;
- vérifier les statuts administratifs et de diffusion ;
- parcourir un curseur Sirene jusqu'à son terme et contrôler les totaux ;
- comparer les coordonnées de l'API Sirene 3.11 au fichier mensuel officiel ;
- décider si ce fichier reste nécessaire au MVP ;
- tester l'endpoint événementiel DATAtourisme, ses champs, ses occurrences et
  sa pagination `next` ;
- répéter une collecte afin de vérifier la stabilité des identifiants ;
- comparer plusieurs éditions d'événements récurrents afin de déterminer si un
  UUID DATAtourisme peut être utilisé seul comme identité d'édition.

Livrable : un compte rendu daté selon le protocole de
`docs/data-sources.md`, sans secret ni donnée personnelle inutile.

Critère de sortie : les deux contrats d'entrée peuvent être reproduits, leurs
limites sont connues et la stratégie de géolocalisation Sirene est arrêtée.

### Jalon 2 — Socle applicatif minimal

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

### Jalon 5 — Exécution durable des collectes

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

### Jalon 6 — Prospects Sirene de bout en bout

**But :** livrer la première boucle métier réellement utilisable.

Travaux :

- charger le référentiel de communes retenu ;
- énumérer et lotir les communes candidates ;
- intégrer l'adaptateur Sirene avec quota et curseur ;
- contrôler l'état courant, la diffusion et les totaux ;
- appliquer le traitement conforme lorsqu'un établissement ou son unité
  légale passe en diffusion partielle ;
- géolocaliser les établissements selon la décision du jalon 1 ;
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

### Jalon 7 — Événements DATAtourisme de bout en bout

**But :** livrer la deuxième famille d'opportunités.

Travaux :

- intégrer l'adaptateur DATAtourisme avec clé en en-tête ;
- collecter les événements du cercle sans horizon futur maximal ;
- suivre chaque lien de pagination validé jusqu'à la fin ;
- normaliser lieu, catégories, description, contacts et provenance ;
- conserver plusieurs périodes sur une fiche ;
- calculer les états à venir, en cours et passé ;
- reconnaître la même identité d'édition lors d'une relance, selon la décision
  du jalon 1 ;
- ne pas confondre producteur de donnée et organisateur ;
- conserver les événements passés hors de l'interface ordinaire.

Interface minimale :

- liste et fiche événement ;
- recherche textuelle par titre ou commune ;
- filtres distance, période, catégorie, organisateur, contact et statut ;
- tris par date et distance ;
- affichage des occurrences et de la fraîcheur.

Critère de sortie : des événements simples, sur plusieurs jours et récurrents
sont importés puis mis à jour sans perdre leurs périodes.

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

| Décision | Échéance maximale | Recommandation actuelle |
| --- | --- | --- |
| Coordonnées API Sirene ou fichier mensuel | Fin du jalon 1 | Préférer l'API si sa couverture réelle est suffisante |
| Frontend du MVP | Avant le jalon 3 | TypeScript, React et outil de build simple ; Next.js seulement si un besoin apparaît |
| Processus de tâches longues | Début du jalon 5 | Même code applicatif, file durable en PostgreSQL, sans broker |
| Serveur et mode de déploiement | Avant le jalon 11 | Un seul serveur privé, composants non publics sauf le proxy HTTPS |
| Destination et capacité des sauvegardes | Avant le jalon 11 | Valider la rétention initiale de l'architecture et tester une restauration |

Une décision prise met à jour les documents spécialisés avant son
implémentation. Une option reportée ne doit pas conduire à développer les deux
solutions « au cas où ».

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
