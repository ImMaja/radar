"""SQLAlchemy engine lifecycle and readiness checks."""

from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from radar.persistence.schema import EXPECTED_SCHEMA_REVISION


class Database:
    """Own the process SQLAlchemy engine and expose a non-sensitive probe."""

    def __init__(self, database_url: SecretStr) -> None:
        self._engine: Engine = create_engine(
            database_url.get_secret_value(),
            pool_pre_ping=True,
        )

    @property
    def engine(self) -> Engine:
        """Expose the engine to persistence code assembled by the application."""

        return self._engine

    def is_ready(self) -> bool:
        """Return whether PostgreSQL, PostGIS and the schema revision are ready."""

        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1")).scalar_one()
                has_postgis = connection.execute(
                    text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis')")
                ).scalar_one()
                revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()
        except SQLAlchemyError:
            return False

        return bool(has_postgis) and revision == EXPECTED_SCHEMA_REVISION

    def close(self) -> None:
        """Dispose all pooled connections owned by this process."""

        self._engine.dispose()
