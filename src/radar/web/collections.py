"""Private HTTP contract for requesting and supervising collections."""

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from radar.auth.contracts import AuthenticatedSession, AuthenticationBackend
from radar.collections.contracts import (
    CollectionBackend,
    CollectionDashboard,
    CollectionEngineUnavailableError,
    CollectionError,
    CollectionJob,
    CollectionJobState,
    CollectionProgress,
    CollectionTrigger,
    Connector,
    ConnectorCollectionStatus,
    ConnectorCoverage,
    ConnectorNotAvailableError,
    EnqueuedCollection,
    ReferencePositionRequiredError,
)
from radar.config import Settings
from radar.web.auth import (
    current_session,
    get_authentication_backend,
    get_settings,
    require_csrf,
)
from radar.web.errors import AUTH_ERROR_RESPONSES, ApiProblem, ErrorBody

router = APIRouter(prefix="/api/v1/collections", tags=["collections"])


class CollectionErrorResponse(BaseModel):
    code: str
    message: str
    transient: bool


class CollectionProgressResponse(BaseModel):
    stage: str
    processed: int
    total: int | None
    observations: int


class CollectionJobResponse(BaseModel):
    id: UUID
    cycle_id: UUID
    connector: Connector
    trigger: CollectionTrigger
    state: CollectionJobState
    reference_label: str
    longitude: float
    latitude: float
    collection_radius_meters: int
    created_at: datetime
    available_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    heartbeat_at: datetime | None
    attempt_count: int
    max_attempts: int
    progress: CollectionProgressResponse
    last_error: CollectionErrorResponse | None


class ConnectorCoverageResponse(BaseModel):
    established_at: datetime
    longitude: float
    latitude: float
    collection_radius_meters: int
    search_circle_covered: bool


class ConnectorCollectionStatusResponse(BaseModel):
    connector: Connector
    available: bool
    active_job: CollectionJobResponse | None
    latest_job: CollectionJobResponse | None
    last_success_at: datetime | None
    coverage: ConnectorCoverageResponse | None


class CollectionDashboardResponse(BaseModel):
    connectors: list[ConnectorCollectionStatusResponse]


class EnqueuedCollectionResponse(BaseModel):
    created: bool
    job: CollectionJobResponse


COLLECTION_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    409: {"model": ErrorBody},
    503: {"model": ErrorBody},
}


def get_collection_backend(request: Request) -> CollectionBackend:
    """Resolve durable collection use cases assembled by the application."""

    return cast(CollectionBackend, request.app.state.collection_backend)


def _error_response(error: CollectionError | None) -> CollectionErrorResponse | None:
    if error is None:
        return None
    return CollectionErrorResponse(
        code=error.code,
        message=error.message,
        transient=error.transient,
    )


def _progress_response(progress: CollectionProgress) -> CollectionProgressResponse:
    return CollectionProgressResponse(
        stage=progress.stage,
        processed=progress.processed,
        total=progress.total,
        observations=progress.observations,
    )


def _job_response(job: CollectionJob | None) -> CollectionJobResponse | None:
    if job is None:
        return None
    return CollectionJobResponse(
        id=job.id,
        cycle_id=job.cycle_id,
        connector=job.connector,
        trigger=job.trigger,
        state=job.state,
        reference_label=job.reference_label,
        longitude=job.longitude,
        latitude=job.latitude,
        collection_radius_meters=job.collection_radius_meters,
        created_at=job.created_at,
        available_at=job.available_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        heartbeat_at=job.heartbeat_at,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        progress=_progress_response(job.progress),
        last_error=_error_response(job.last_error),
    )


def _coverage_response(coverage: ConnectorCoverage | None) -> ConnectorCoverageResponse | None:
    if coverage is None:
        return None
    return ConnectorCoverageResponse(
        established_at=coverage.established_at,
        longitude=coverage.longitude,
        latitude=coverage.latitude,
        collection_radius_meters=coverage.collection_radius_meters,
        search_circle_covered=coverage.search_circle_covered,
    )


def _connector_response(
    connector: ConnectorCollectionStatus,
) -> ConnectorCollectionStatusResponse:
    return ConnectorCollectionStatusResponse(
        connector=connector.connector,
        available=connector.available,
        active_job=_job_response(connector.active_job),
        latest_job=_job_response(connector.latest_job),
        last_success_at=connector.last_success_at,
        coverage=_coverage_response(connector.coverage),
    )


def _dashboard_response(dashboard: CollectionDashboard) -> CollectionDashboardResponse:
    return CollectionDashboardResponse(
        connectors=[_connector_response(connector) for connector in dashboard.connectors]
    )


def _unavailable_problem(error: CollectionEngineUnavailableError) -> ApiProblem:
    return ApiProblem(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "collection_engine_unavailable",
        "Le suivi des collectes est momentanément indisponible.",
    )


@router.get(
    "",
    response_model=CollectionDashboardResponse,
    responses=COLLECTION_ERROR_RESPONSES,
)
def read_collection_dashboard(
    _session: Annotated[AuthenticatedSession, Depends(current_session)],
    backend: Annotated[CollectionBackend, Depends(get_collection_backend)],
) -> CollectionDashboardResponse:
    """Read durable connector status without contacting an external provider."""

    try:
        return _dashboard_response(backend.dashboard())
    except CollectionEngineUnavailableError as error:
        raise _unavailable_problem(error) from error


@router.post(
    "/{connector}",
    response_model=EnqueuedCollectionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=COLLECTION_ERROR_RESPONSES,
)
def request_manual_collection(
    connector: Connector,
    request: Request,
    session: Annotated[AuthenticatedSession, Depends(current_session)],
    authentication: Annotated[AuthenticationBackend, Depends(get_authentication_backend)],
    settings: Annotated[Settings, Depends(get_settings)],
    backend: Annotated[CollectionBackend, Depends(get_collection_backend)],
) -> EnqueuedCollectionResponse:
    """Enqueue one manual job; provider work remains outside the HTTP request."""

    require_csrf(request, session, authentication, settings)
    try:
        enqueued: EnqueuedCollection = backend.request_manual(connector)
    except ReferencePositionRequiredError as error:
        raise ApiProblem(
            status.HTTP_409_CONFLICT,
            "reference_position_required",
            "Confirmez une adresse de référence avant de lancer une collecte.",
        ) from error
    except ConnectorNotAvailableError as error:
        raise ApiProblem(
            status.HTTP_409_CONFLICT,
            "connector_not_available",
            "Ce connecteur n'est pas encore disponible.",
        ) from error
    except CollectionEngineUnavailableError as error:
        raise _unavailable_problem(error) from error
    job = _job_response(enqueued.job)
    assert job is not None
    return EnqueuedCollectionResponse(created=enqueued.created, job=job)
