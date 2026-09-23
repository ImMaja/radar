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
applicatif, l'accès privé, le réglage géographique et le moteur durable de
collecte sont terminés. Radar fournit une application FastAPI, une base
PostgreSQL/PostGIS, des migrations Alembic, un worker séparé et une interface
React statique pour le compte unique. L'utilisateur peut géocoder puis
confirmer une adresse de France métropolitaine, régler séparément les rayons
de collecte et de recherche jusqu'à 50 km et consulter l'état durable des
connecteurs. Le jalon 6 est en cours : le contrat de lecture de l'API Sirene,
le référentiel PostGIS versionné des communes et la planification durable des
lots sont implémentés. Leur exécution persistée réconcilie les pages et les
totaux, conserve les preuves non sensibles par tentative et reprend un lot
interrompu depuis son début. Les candidats publics sont préparés par page avec
leur identité, leur observation normalisée et leur occurrence de collecte ;
les coordonnées API valides sont déjà contrôlées et classées exactement par
PostGIS, sans créer prématurément de fiche prospect. Le lecteur du fichier
mensuel Parquet est également arrêté : il valide le schéma et les empreintes,
puis joint uniquement les SIRET du cycle par lots bornés avec DuckDB, sans
charger les 38 millions de lignes en mémoire. Ses positions sont persistées
avec un millésime et une qualité propres, contrôlées par PostGIS et activées
seulement après réconciliation complète ; une qualité communale `33` reste à
vérifier. La résolution déterministe retient maintenant la position API
utilisable, puis le fichier, et conserve les écarts entre sources supérieurs à
un kilomètre. Le repli Géoplateforme des seules adresses encore indéterminées
est persistant et rejouable : chaque résultat possède sa provenance, passe les
contrôles PostGIS et n'est retenu automatiquement que s'il localise une adresse
ou une voie dans la commune attendue. Une absence ou un résultat insuffisant
reste explicitement sans position. Les résultats finaux sont maintenant
projetés page par page en organismes, établissements et fiches prospects
stables liées au SIRET. Les candidats hors du rayon exact sont comptabilisés
sans créer de fiche ; ceux dont la position reste inconnue sont conservés pour
la liste « Localisation à vérifier ». Une API privée permet désormais de
rechercher et paginer les prospects locaux, de les filtrer par rayon, type,
activité, effectif, moyens de contact connus et état de localisation, de les
trier par nom ou distance, puis d'ouvrir leur détail avec les contacts effectifs
et la provenance courante. Les contacts sont versionnés séparément par couche
source et utilisateur ; Sirene n'en fournissant pas, Radar n'en invente aucun.
Le contrôle ciblé des SIRET déjà connus mais absents d'une nouvelle sélection
est également implémenté par lots de 1 000 au maximum. Il ne ferme jamais une
fiche par déduction : seuls un état fermé ou une unité légale cessée explicitement
renvoyés par Sirene modifient les états administratifs. Un résultat introuvable
reste une preuve d'absence sans fermeture. Les contrôles sont persistés et une
reprise ne répète pas les lots déjà validés. Toutes les lectures du catalogue
restent dans PostgreSQL/PostGIS et n'appellent aucun fournisseur. L'interface
React propose la même liste paginée, les filtres email, téléphone et site web,
l'onglet « Localisation à vérifier » et la fiche détaillée avec ses contacts et
ses sources. Le vrai millésime 2026 et la
sélection autour de Dax ont été validés. Le connecteur reste désactivé jusqu'à
la composition complète du worker et à la résolution du point de conformité
sur la diffusion partielle.

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
- httpx ;
- DuckDB, uniquement pour lire et joindre localement le grand Parquet Sirene.

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

Le référentiel communal se charge séparément après téléchargement du fichier
officiel. La migration ne contacte jamais une source externe :

```bash
.venv/bin/radar-admin import-municipalities communes-100m.geojson.gz \
  --resource-identifier 2026 \
  --resource-url https://etalab-datasets.geo.data.gouv.fr/contours-administratifs/2026/geojson/communes-100m.geojson.gz \
  --expected-sha256 4530cbf87a3af387c2da95935376f74b93eabd0a7595eacc5b7e0ed94a0b3778 \
  --expected-size-bytes 8237354
```

La commande n'active la nouvelle version qu'après validation intégrale par
PostGIS. Le téléchargement automatisé du prochain millésime n'est pas encore
implémenté.

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
