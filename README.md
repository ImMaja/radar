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

Le cadrage, la validation réelle des contrats externes autour de Dax, le socle
applicatif, l'accès privé et le réglage géographique sont terminés. Radar
fournit une application FastAPI, une base PostgreSQL/PostGIS, des migrations
Alembic et une interface React statique pour le compte unique. L'utilisateur
peut géocoder puis confirmer une adresse de France métropolitaine et régler
séparément les rayons de collecte et de recherche jusqu'à 50 km. La prochaine
tranche est l'exécution durable des collectes du jalon 5.

Le MVP est prévu pour un seul utilisateur et un seul food truck. Il sera
accessible sur Internet derrière une authentification, sans exposer
PostgreSQL publiquement.

## Sources prévues pour le MVP

- API Sirene 3.11 de l'Insee pour les établissements et leurs coordonnées
  courantes ;
- fichier mensuel de géolocalisation Sirene comme complément et repli, puis
  Géoplateforme pour les cas à géocoder ;
- référentiel officiel des contours de communes ;
- API DATAtourisme v1 pour les événements.

Les sources supplémentaires, l'enrichissement des sites officiels, le CRM et
le classifieur IA sont postérieurs au MVP.

## Architecture envisagée

Radar restera un monolithe modulaire.

Backend :

- Python et FastAPI ;
- PostgreSQL et PostGIS ;
- SQLAlchemy et Alembic ;
- Pydantic ;
- httpx.

Le frontend utilise TypeScript, React et Vite. Son build est statique et servi
sous la même origine que l'API ; Radar n'ajoute ni Next.js ni processus Node en
production.

## Documentation

- [Définition du produit](docs/product.md)
- [Sources de données](docs/data-sources.md)
- [Scoring](docs/scoring.md)
- [Architecture](docs/architecture.md)
- [Modèle de données](docs/database.md)
- [Roadmap](docs/roadmap.md)
- [Validation des sources autour de Dax](docs/source-validation-dax-2026-09.md)

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

Prérequis :

- Python 3.13 ou 3.14 ;
- Node.js 22.12 ou plus récent pour construire et tester l'interface ;
- Docker avec le plugin Compose, ou Podman avec un fournisseur Compose.

Depuis la racine du dépôt :

```bash
cp -n .env.example .env.local
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
docker compose up -d database
.venv/bin/python -m alembic upgrade head
npm ci --prefix frontend
npm run build --prefix frontend
.venv/bin/radar-admin create-account --display-name "Food truck Radar"
.venv/bin/python -m uvicorn radar.main:app --reload
```

La commande de création demande deux fois le mot de passe de manière
interactive et refuse de remplacer un compte existant. En cas d'oubli :

```bash
.venv/bin/radar-admin reset-password
```

Cette seconde commande révoque toutes les sessions existantes. Aucun mot de
passe n'est accepté en argument ou variable d'environnement.

Avec Podman Compose, remplacer `docker compose` par `podman compose`.
L'application répond ensuite sur `http://127.0.0.1:8000`. Les contrôles
`/health/live` et `/health/ready` vérifient respectivement le processus et la
base avec son schéma. La documentation interactive est disponible sur
`/docs` hors production.

Le port PostgreSQL local est lié uniquement à `127.0.0.1`. Les identifiants
du fichier Compose sont réservés au développement et ne doivent jamais être
réutilisés en production.

Si `.env.local` existe déjà, ne pas l'écraser : y ajouter seulement les
variables manquantes présentes dans `.env.example`.

## Contrôles qualité

La suite rapide ne nécessite pas de base :

```bash
.venv/bin/python -m ruff format --check .
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy
.venv/bin/python -m pytest -m "not integration"
npm run check --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
```

Le test de migration repart de zéro sur la base dédiée `radar_test`. Il refuse
explicitement toute autre base :

```bash
RADAR_TEST_DATABASE_URL=postgresql+psycopg://radar:radar-local-only@127.0.0.1:5432/radar_test \
  .venv/bin/python -m pytest tests/integration
```

Pour travailler avec le rechargement à chaud du frontend, démarrer FastAPI en
configurant `RADAR_PUBLIC_ORIGIN=http://127.0.0.1:5173`, puis exécuter
`npm run dev --prefix frontend`. Vite relaie les appels locaux vers FastAPI ;
le navigateur reste sur une origine unique.

Avant toute contribution, lire `AGENTS.md` puis les documents concernés par la
modification.

Les clés Sirene, DATAtourisme et tout autre secret devront être fournis par la
configuration locale ou de production. Aucun secret ne devra être ajouté au
dépôt.

Le fichier `.env.example` documente uniquement les noms de variables. Les
valeurs locales vont dans `.env.local`, ignoré par Git ; elles ne sont jamais
recopiées dans une documentation ou une sortie de diagnostic.
