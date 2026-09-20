"""FastAPI application composition."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles

from radar.auth.contracts import AuthenticationBackend
from radar.auth.rate_limit import LoginRateLimiter
from radar.auth.service import AuthService
from radar.collections.contracts import CollectionBackend
from radar.collections.service import CollectionService, UnavailableCollectionBackend
from radar.config import Settings, get_settings
from radar.geography.contracts import GeographyBackend
from radar.geography.service import GeographyService
from radar.persistence.auth import SqlAlchemyAuthRepository
from radar.persistence.collections import SqlAlchemyCollectionRepository
from radar.persistence.database import Database
from radar.persistence.geography import SqlAlchemyGeographyRepository
from radar.providers.geoplatform import GeoPlatformGeocoder
from radar.web.auth import router as auth_router
from radar.web.collections import router as collections_router
from radar.web.errors import ApiProblem, api_problem_handler, request_validation_handler
from radar.web.geography import router as geography_router
from radar.web.health import ReadinessProbe
from radar.web.health import router as health_router
from radar.web.middleware import add_security_headers


def create_app(
    settings: Settings | None = None,
    readiness_probe: ReadinessProbe | None = None,
    authentication_backend: AuthenticationBackend | None = None,
    login_rate_limiter: LoginRateLimiter | None = None,
    geography_backend: GeographyBackend | None = None,
    collection_backend: CollectionBackend | None = None,
) -> FastAPI:
    """Build one Radar web process with explicit dependencies."""

    resolved_settings = settings or get_settings()
    owned_database = (
        Database(resolved_settings.database_url)
        if (readiness_probe is None or authentication_backend is None or geography_backend is None)
        else None
    )
    owned_geocoder: GeoPlatformGeocoder | None = None

    if readiness_probe is None:
        assert owned_database is not None
        readiness_probe = owned_database
    if authentication_backend is None:
        assert owned_database is not None
        authentication_backend = AuthService(
            SqlAlchemyAuthRepository(owned_database.engine),
            idle_timeout=timedelta(seconds=resolved_settings.session_idle_seconds),
            absolute_timeout=timedelta(seconds=resolved_settings.session_absolute_seconds),
        )
    if geography_backend is None:
        assert owned_database is not None
        owned_geocoder = GeoPlatformGeocoder()
        geography_backend = GeographyService(
            SqlAlchemyGeographyRepository(owned_database.engine),
            owned_geocoder,
        )
    if collection_backend is None:
        collection_backend = (
            CollectionService(SqlAlchemyCollectionRepository(owned_database.engine))
            if owned_database is not None
            else UnavailableCollectionBackend()
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if owned_geocoder is not None:
                owned_geocoder.close()
            if owned_database is not None:
                owned_database.close()

    expose_docs = resolved_settings.environment != "production"
    app = FastAPI(
        title="Radar",
        version="0.1.0",
        docs_url="/docs" if expose_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if expose_docs else None,
        lifespan=lifespan,
    )
    app.middleware("http")(add_security_headers)
    app.add_exception_handler(ApiProblem, api_problem_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.state.settings = resolved_settings
    app.state.readiness_probe = readiness_probe
    app.state.authentication_backend = authentication_backend
    app.state.login_rate_limiter = login_rate_limiter or LoginRateLimiter()
    app.state.geography_backend = geography_backend
    app.state.collection_backend = collection_backend
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(geography_router)
    app.include_router(collections_router)
    if resolved_settings.frontend_directory.joinpath("index.html").is_file():
        app.mount(
            "/",
            StaticFiles(directory=resolved_settings.frontend_directory, html=True),
            name="frontend",
        )
    return app
