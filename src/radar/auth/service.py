"""Authentication use cases independent from HTTP and SQLAlchemy."""

import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from radar.auth.contracts import (
    AccountAlreadyExistsError,
    AccountNotFoundError,
    AuthenticatedSession,
    AuthRepository,
    InvalidCurrentPasswordError,
    IssuedSession,
    PasswordPolicyError,
    SessionRotationError,
    SessionSecrets,
)
from radar.auth.passwords import PasswordManager


def utc_now() -> datetime:
    """Return an aware UTC instant."""

    return datetime.now(UTC)


def secret_hash(value: str) -> str:
    """Hash a high-entropy opaque browser secret for database lookup."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_session_secrets() -> SessionSecrets:
    """Generate independent 256-bit session and CSRF secrets."""

    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    return SessionSecrets(
        token=token,
        token_hash=secret_hash(token),
        csrf_token=csrf_token,
        csrf_token_hash=secret_hash(csrf_token),
    )


class AuthService:
    """Coordinate password verification and transactional session persistence."""

    def __init__(
        self,
        repository: AuthRepository,
        idle_timeout: timedelta,
        absolute_timeout: timedelta,
        password_manager: PasswordManager | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._idle_timeout = idle_timeout
        self._absolute_timeout = absolute_timeout
        self._passwords = password_manager or PasswordManager()
        self._clock = clock
        self._dummy_hash = self._passwords.hash(secrets.token_urlsafe(32))

    def create_account(
        self,
        password: str,
        confirmation: str,
        display_name: str | None = None,
    ) -> None:
        """Create the singleton account or refuse an implicit replacement."""

        self._passwords.validate_new(password, confirmation)
        password_hash = self._passwords.hash(password)
        normalized_name = display_name.strip() if display_name and display_name.strip() else None
        if normalized_name is not None and len(normalized_name) > 100:
            raise PasswordPolicyError("Le nom d'affichage ne peut pas dépasser 100 caractères.")
        if not self._repository.create_account(password_hash, normalized_name, self._clock()):
            raise AccountAlreadyExistsError("Le compte Radar existe déjà.")

    def reset_password(self, password: str, confirmation: str) -> None:
        """Administratively replace a forgotten password and revoke every session."""

        self._passwords.validate_new(password, confirmation)
        if not self._repository.replace_password(self._passwords.hash(password), self._clock()):
            raise AccountNotFoundError("Le compte Radar n'existe pas.")

    def login(self, password: str) -> IssuedSession | None:
        """Verify the singleton account and issue a fresh opaque session."""

        account = self._repository.get_account()
        if account is None:
            self._passwords.verify(self._dummy_hash, password)
            return None
        if not self._passwords.verify(account.password_hash, password):
            return None

        if self._passwords.needs_rehash(account.password_hash):
            replacement = self._passwords.hash(password)
            self._repository.update_password_hash(
                account.id,
                account.password_hash,
                replacement,
                self._clock(),
            )

        issued_secrets = new_session_secrets()
        current = self._repository.create_session(
            account,
            issued_secrets,
            self._clock(),
            self._idle_timeout,
            self._absolute_timeout,
        )
        return IssuedSession(current=current, secrets=issued_secrets)

    def authenticate(self, token: str) -> AuthenticatedSession | None:
        """Resolve and refresh a valid session from its raw browser token."""

        if not token or len(token) > 256:
            return None
        return self._repository.find_valid_session(
            secret_hash(token),
            self._clock(),
            self._idle_timeout,
        )

    def logout(self, session_id: UUID) -> None:
        """Revoke the current session without exposing whether it already expired."""

        self._repository.revoke_session(session_id, self._clock(), "logout")

    def csrf_is_valid(self, session: AuthenticatedSession, token: str) -> bool:
        """Compare a presented CSRF secret with the session-bound hash."""

        if not token or len(token) > 256:
            return False
        return hmac.compare_digest(session.csrf_token_hash, secret_hash(token))

    def change_password(
        self,
        session: AuthenticatedSession,
        current_password: str,
        new_password: str,
        confirmation: str,
    ) -> IssuedSession:
        """Change the password and atomically replace the initiating session."""

        self._passwords.validate_new(new_password, confirmation)
        account = self._repository.get_account()
        if account is None or account.id != session.account_id:
            raise SessionRotationError("the authenticated account changed")
        if not self._passwords.verify(account.password_hash, current_password):
            raise InvalidCurrentPasswordError("the current password is invalid")

        issued_secrets = new_session_secrets()
        current = self._repository.change_password_and_rotate_session(
            account,
            session.id,
            self._passwords.hash(new_password),
            issued_secrets,
            self._clock(),
            self._idle_timeout,
            self._absolute_timeout,
        )
        if current is None:
            raise SessionRotationError("the authenticated session changed")
        return IssuedSession(current=current, secrets=issued_secrets)
