"""Private-session HTTP contract."""

import logging
import time
from typing import Annotated, Literal, cast
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field

from radar.auth.contracts import (
    AuthenticatedSession,
    AuthenticationBackend,
    InvalidCurrentPasswordError,
    IssuedSession,
    PasswordPolicyError,
    SessionRotationError,
)
from radar.auth.passwords import MAX_PASSWORD_LENGTH
from radar.auth.rate_limit import LoginRateLimiter
from radar.config import Settings
from radar.web.errors import AUTH_ERROR_RESPONSES, ApiProblem

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
logger = logging.getLogger(__name__)


class LoginRequest(BaseModel):
    """Credentials for Radar's only account."""

    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class ChangePasswordRequest(BaseModel):
    """Current and confirmed replacement password."""

    current_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    confirmation: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class SessionResponse(BaseModel):
    """Non-sensitive state returned to an authenticated interface."""

    authenticated: Literal[True] = True
    display_name: str | None


def get_authentication_backend(request: Request) -> AuthenticationBackend:
    """Resolve the authentication application service."""

    return cast(AuthenticationBackend, request.app.state.authentication_backend)


def get_settings(request: Request) -> Settings:
    """Resolve validated process settings."""

    return cast(Settings, request.app.state.settings)


def get_rate_limiter(request: Request) -> LoginRateLimiter:
    """Resolve the process-level login limiter."""

    return cast(LoginRateLimiter, request.app.state.login_rate_limiter)


def current_session(
    request: Request,
    backend: Annotated[AuthenticationBackend, Depends(get_authentication_backend)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticatedSession:
    """Require a valid, non-expired server-side session cookie."""

    raw_token = request.cookies.get(settings.session_cookie_name, "")
    authenticated = backend.authenticate(raw_token)
    if authenticated is None:
        raise ApiProblem(
            status.HTTP_401_UNAUTHORIZED,
            "authentication_required",
            "Une connexion valide est nécessaire.",
        )
    return authenticated


def request_origin(value: str) -> str | None:
    """Reduce an Origin or Referer value to its exact web origin."""

    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def require_same_origin(request: Request, settings: Settings) -> None:
    """Reject state changes that cannot prove the configured browser origin."""

    supplied = request.headers.get("origin") or request.headers.get("referer")
    if supplied is None or request_origin(supplied) != settings.public_origin:
        raise ApiProblem(
            status.HTTP_403_FORBIDDEN,
            "invalid_origin",
            "L'origine de la requête n'est pas autorisée.",
        )


def require_json(request: Request) -> None:
    """Reject browser-simple content types on state-changing API requests."""

    content_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    if content_type != "application/json":
        raise ApiProblem(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "json_required",
            "Cette opération nécessite un contenu JSON.",
        )


def require_csrf(
    request: Request,
    session: AuthenticatedSession,
    backend: AuthenticationBackend,
    settings: Settings,
) -> None:
    """Validate same-origin JSON transport and the session-bound CSRF secret."""

    require_same_origin(request, settings)
    require_json(request)
    header_token = request.headers.get("x-csrf-token", "")
    cookie_token = request.cookies.get(settings.csrf_cookie_name, "")
    if (
        not header_token
        or header_token != cookie_token
        or not backend.csrf_is_valid(session, header_token)
    ):
        raise ApiProblem(
            status.HTTP_403_FORBIDDEN,
            "invalid_csrf_token",
            "La protection de la session est invalide ou expirée.",
        )


def set_authentication_cookies(
    response: Response,
    issued: IssuedSession,
    settings: Settings,
) -> None:
    """Send non-persistent same-site browser cookies for a new session."""

    response.set_cookie(
        settings.session_cookie_name,
        issued.secrets.token,
        secure=settings.secure_cookies,
        httponly=True,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        issued.secrets.csrf_token,
        secure=settings.secure_cookies,
        httponly=False,
        samesite="strict",
        path="/",
    )


def clear_authentication_cookies(response: Response, settings: Settings) -> None:
    """Expire both authentication cookies with their original attributes."""

    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=settings.secure_cookies,
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie(
        settings.csrf_cookie_name,
        path="/",
        secure=settings.secure_cookies,
        httponly=False,
        samesite="strict",
    )


@router.post("/login", response_model=SessionResponse, responses=AUTH_ERROR_RESPONSES)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    backend: Annotated[AuthenticationBackend, Depends(get_authentication_backend)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[LoginRateLimiter, Depends(get_rate_limiter)],
) -> SessionResponse:
    """Authenticate the singleton account and rotate browser secrets."""

    require_same_origin(request, settings)
    require_json(request)
    client_key = request.client.host if request.client is not None else "unknown"
    retry_after = limiter.begin_attempt(client_key, time.monotonic())
    if retry_after is not None:
        logger.warning("authentication_rate_limited", extra={"client_address": client_key})
        raise ApiProblem(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "login_rate_limited",
            "Trop de tentatives. Réessayez plus tard.",
            headers={"Retry-After": str(retry_after)},
        )

    issued = backend.login(payload.password)
    if issued is None:
        logger.warning("authentication_failed", extra={"client_address": client_key})
        raise ApiProblem(
            status.HTTP_401_UNAUTHORIZED,
            "invalid_credentials",
            "Le mot de passe est incorrect.",
        )

    limiter.clear(client_key)
    set_authentication_cookies(response, issued, settings)
    return SessionResponse(display_name=issued.current.display_name)


@router.get("/session", response_model=SessionResponse, responses=AUTH_ERROR_RESPONSES)
def read_session(
    session: Annotated[AuthenticatedSession, Depends(current_session)],
) -> SessionResponse:
    """Return the minimal account state needed by the private interface."""

    return SessionResponse(display_name=session.display_name)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=AUTH_ERROR_RESPONSES,
)
def logout(
    request: Request,
    response: Response,
    session: Annotated[AuthenticatedSession, Depends(current_session)],
    backend: Annotated[AuthenticationBackend, Depends(get_authentication_backend)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Revoke the current server-side session and expire its cookies."""

    require_csrf(request, session, backend, settings)
    backend.logout(session.id)
    clear_authentication_cookies(response, settings)


@router.post("/password", response_model=SessionResponse, responses=AUTH_ERROR_RESPONSES)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    session: Annotated[AuthenticatedSession, Depends(current_session)],
    backend: Annotated[AuthenticationBackend, Depends(get_authentication_backend)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionResponse:
    """Replace the password, revoke every session and issue one new session."""

    require_csrf(request, session, backend, settings)
    try:
        issued = backend.change_password(
            session,
            payload.current_password,
            payload.new_password,
            payload.confirmation,
        )
    except InvalidCurrentPasswordError as error:
        raise ApiProblem(
            status.HTTP_400_BAD_REQUEST,
            "invalid_current_password",
            "Le mot de passe actuel est incorrect.",
        ) from error
    except PasswordPolicyError as error:
        raise ApiProblem(
            status.HTTP_400_BAD_REQUEST,
            "invalid_new_password",
            str(error),
        ) from error
    except SessionRotationError as error:
        raise ApiProblem(
            status.HTTP_401_UNAUTHORIZED,
            "session_changed",
            "La session a changé. Reconnectez-vous.",
        ) from error

    set_authentication_cookies(response, issued, settings)
    return SessionResponse(display_name=issued.current.display_name)
