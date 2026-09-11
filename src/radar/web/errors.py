"""Stable non-sensitive API errors."""

from typing import Any

from fastapi import Request
from pydantic import BaseModel
from starlette.responses import JSONResponse


class ErrorBody(BaseModel):
    """Public error contract shared by Radar API routes."""

    code: str
    message: str
    request_id: str


class ApiProblem(Exception):
    """A controlled API error safe to expose to the browser."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers
        super().__init__(message)


async def api_problem_handler(request: Request, exception: Exception) -> JSONResponse:
    """Render one controlled failure without a traceback or secret."""

    if not isinstance(exception, ApiProblem):
        raise exception
    request_id = getattr(request.state, "request_id", "unknown")
    body = ErrorBody(
        code=exception.code,
        message=exception.message,
        request_id=request_id,
    )
    return JSONResponse(
        status_code=exception.status_code,
        content=body.model_dump(mode="json"),
        headers=exception.headers,
    )


async def request_validation_handler(
    request: Request,
    _exception: Exception,
) -> JSONResponse:
    """Hide submitted values, especially passwords, from validation responses."""

    request_id = getattr(request.state, "request_id", "unknown")
    body = ErrorBody(
        code="invalid_request",
        message="La requête contient une valeur invalide.",
        request_id=request_id,
    )
    return JSONResponse(
        status_code=422,
        content=body.model_dump(mode="json"),
    )


AUTH_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorBody},
    401: {"model": ErrorBody},
    403: {"model": ErrorBody},
    415: {"model": ErrorBody},
    422: {"model": ErrorBody},
    429: {"model": ErrorBody},
}
