"""Typed boundaries and values used by authentication."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class AccountCredentials:
    """Minimum account state needed to verify a password."""

    id: UUID
    display_name: str | None
    password_hash: str
    session_generation: int


@dataclass(frozen=True)
class AuthenticatedSession:
    """A server-side session that passed all validity checks."""

    id: UUID
    account_id: UUID
    display_name: str | None
    csrf_token_hash: str


@dataclass(frozen=True)
class SessionSecrets:
    """Raw browser secrets issued once and their server-side hashes."""

    token: str
    token_hash: str
    csrf_token: str
    csrf_token_hash: str


@dataclass(frozen=True)
class IssuedSession:
    """A newly issued authenticated session and its browser secrets."""

    current: AuthenticatedSession
    secrets: SessionSecrets


class AuthRepository(Protocol):
    """Persistence boundary required by authentication use cases."""

    def get_account(self) -> AccountCredentials | None: ...

    def create_account(
        self,
        password_hash: str,
        display_name: str | None,
        now: datetime,
    ) -> bool: ...

    def replace_password(self, password_hash: str, now: datetime) -> bool: ...

    def update_password_hash(
        self,
        account_id: UUID,
        expected_hash: str,
        password_hash: str,
        now: datetime,
    ) -> None: ...

    def create_session(
        self,
        account: AccountCredentials,
        secrets: SessionSecrets,
        now: datetime,
        idle_timeout: timedelta,
        absolute_timeout: timedelta,
    ) -> AuthenticatedSession: ...

    def find_valid_session(
        self,
        token_hash: str,
        now: datetime,
        idle_timeout: timedelta,
    ) -> AuthenticatedSession | None: ...

    def revoke_session(self, session_id: UUID, now: datetime, reason: str) -> None: ...

    def change_password_and_rotate_session(
        self,
        account: AccountCredentials,
        current_session_id: UUID,
        password_hash: str,
        secrets: SessionSecrets,
        now: datetime,
        idle_timeout: timedelta,
        absolute_timeout: timedelta,
    ) -> AuthenticatedSession | None: ...


class AuthenticationBackend(Protocol):
    """Web-facing authentication use cases."""

    def login(self, password: str) -> IssuedSession | None: ...

    def authenticate(self, token: str) -> AuthenticatedSession | None: ...

    def logout(self, session_id: UUID) -> None: ...

    def csrf_is_valid(self, session: AuthenticatedSession, token: str) -> bool: ...

    def change_password(
        self,
        session: AuthenticatedSession,
        current_password: str,
        new_password: str,
        confirmation: str,
    ) -> IssuedSession: ...


class PasswordPolicyError(ValueError):
    """Raised when a new password does not satisfy the public policy."""


class AccountAlreadyExistsError(RuntimeError):
    """Raised when the singleton account already exists."""


class AccountNotFoundError(RuntimeError):
    """Raised when an administrative operation has no account to update."""


class InvalidCurrentPasswordError(ValueError):
    """Raised when password confirmation cannot authorize a sensitive change."""


class SessionRotationError(RuntimeError):
    """Raised when a concurrent security change invalidates a session rotation."""
