"""Non-sensitive liveness and readiness endpoints."""

from typing import Annotated, Literal, Protocol, cast

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel


class ReadinessProbe(Protocol):
    """Boundary used by the web layer to query local readiness."""

    def is_ready(self) -> bool:
        """Return whether all mandatory local dependencies are ready."""


class HealthResponse(BaseModel):
    """Public health response without infrastructure details."""

    status: Literal["ok", "unavailable"]


router = APIRouter(tags=["health"])


def get_readiness_probe(request: Request) -> ReadinessProbe:
    """Resolve the process-level readiness probe from application state."""

    return cast(ReadinessProbe, request.app.state.readiness_probe)


@router.get("/health/live", response_model=HealthResponse, include_in_schema=False)
def liveness() -> HealthResponse:
    """Report process liveness without contacting external services."""

    return HealthResponse(status="ok")


@router.get(
    "/health/ready",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
    include_in_schema=False,
)
def readiness(
    response: Response,
    probe: Annotated[ReadinessProbe, Depends(get_readiness_probe)],
) -> HealthResponse:
    """Report database and schema readiness without exposing a failure reason."""

    if probe.is_ready():
        return HealthResponse(status="ok")

    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="unavailable")
