# Radar

Radar is a private web application used to discover and manage
commercial opportunities for a food truck.

## Documentation

Before making significant changes, read the relevant documentation:

- Product requirements: `docs/product.md`
- Architecture: `docs/architecture.md`
- Database: `docs/database.md`
- External data sources: `docs/data-sources.md`
- Lead/event scoring: `docs/scoring.md`
- Roadmap: `docs/roadmap.md`

These files are the source of truth.

If implementation and documentation disagree, report the discrepancy
instead of silently choosing one.

## Development principles

- Prefer simple solutions over speculative abstractions.
- Keep the application as a modular monolith.
- Do not add infrastructure unless currently needed.
- Do not introduce a dependency without justification.
- Keep external data providers isolated behind adapters.
- External providers must never write directly to database models.
- Preserve data provenance.
- Do not silently change architectural decisions.

## Backend

Planned stack:

- Python
- FastAPI
- PostgreSQL
- PostGIS
- SQLAlchemy
- Alembic
- Pydantic
- httpx

## Quality

All production code must be typed.

Features must include relevant tests.

Before considering implementation complete, run the configured:
- formatter/linter
- type checker
- tests

Never hide failing tests.

## Git

Do not create commits unless explicitly asked.

Before finishing a coding task:
- show the files modified
- summarize important decisions
- report tests executed and their results
