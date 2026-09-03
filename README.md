# Radar

Radar est une application web privée destinée à aider l'exploitant d'un food
truck à découvrir et prioriser des opportunités commerciales autour d'une
adresse en France métropolitaine.

Le projet couvre deux familles d'opportunités :

- les établissements et organismes susceptibles d'accueillir régulièrement
  un food truck ;
- les événements susceptibles de réunir un public important.

Radar conservera les données localement, leur provenance et les corrections
de l'utilisateur. Les recherches par distance et les filtres n'appelleront
pas les fournisseurs externes.

## État du projet

Le projet est actuellement en phase de conception documentaire. Aucun code
applicatif ni aucune infrastructure ne sont encore créés.

Le MVP est prévu pour un seul utilisateur et un seul food truck. Il sera
accessible sur Internet derrière une authentification, sans exposer
PostgreSQL publiquement.

## Sources prévues pour le MVP

- API Sirene 3.11 de l'Insee pour les établissements ;
- référentiels géographiques officiels et Géoplateforme pour la localisation ;
- API DATAtourisme v1 pour les événements.

Les sources supplémentaires, l'enrichissement des sites officiels, le CRM et
le classifieur IA sont postérieurs au MVP.

## Architecture envisagée

Radar restera un monolithe modulaire.

Backend prévu :

- Python et FastAPI ;
- PostgreSQL et PostGIS ;
- SQLAlchemy et Alembic ;
- Pydantic ;
- httpx.

Le frontend sera choisi avant la première tranche d'interface. La préférence
actuelle est TypeScript avec React, sans imposer Next.js tant qu'aucun besoin
de rendu serveur ne le justifie.

## Documentation

- [Définition du produit](docs/product.md)
- [Sources de données](docs/data-sources.md)
- [Scoring](docs/scoring.md)
- [Architecture](docs/architecture.md)
- [Modèle de données](docs/database.md)
- [Roadmap](docs/roadmap.md)

Ces documents sont les sources de vérité du projet. Toute implémentation qui
s'en écarte doit signaler l'écart au lieu de choisir silencieusement une autre
solution.

## Principes de développement

- avancer par petites fonctionnalités testables ;
- privilégier les solutions simples et maintenables ;
- préserver la provenance des données externes ;
- isoler chaque fournisseur derrière un adaptateur ;
- protéger les corrections et notes utilisateur des synchronisations ;
- éviter microservices, abstractions prématurées et dépendances inutiles ;
- typer le code de production et accompagner chaque fonctionnalité de tests.

## Démarrage

Il n'existe pas encore de commande d'installation ou de lancement. Elles
seront ajoutées avec le premier socle exécutable, sans documenter par avance
des commandes qui n'existent pas.

Avant toute contribution, lire `AGENTS.md` puis les documents concernés par la
modification.

Les clés Sirene, DATAtourisme et tout autre secret devront être fournis par la
configuration locale ou de production. Aucun secret ne devra être ajouté au
dépôt.
