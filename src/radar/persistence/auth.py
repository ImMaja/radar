"""SQLAlchemy implementation of authentication persistence."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import Engine, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from radar.auth.contracts import (
    AccountCredentials,
    AuthenticatedSession,
    SessionSecrets,
)
from radar.persistence.models import AccountModel, AuthSessionModel

SINGLETON_KEY = "primary"


def account_record(model: AccountModel) -> AccountCredentials:
    """Copy a persistence model into an infrastructure-free value."""

    return AccountCredentials(
        id=model.id,
        display_name=model.display_name,
        password_hash=model.password_hash,
        session_generation=model.session_generation,
    )


def authenticated_session(
    session: AuthSessionModel,
    account: AccountModel,
) -> AuthenticatedSession:
    """Copy a validated session into an infrastructure-free value."""

    return AuthenticatedSession(
        id=session.id,
        account_id=account.id,
        display_name=account.display_name,
        csrf_token_hash=session.csrf_token_hash,
    )


class SqlAlchemyAuthRepository:
    """Keep authentication transactions inside the persistence adapter."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_account(self) -> AccountCredentials | None:
        """Load the singleton credentials without exposing an ORM object."""

        with Session(self._engine) as database_session:
            model = database_session.scalar(
                select(AccountModel).where(AccountModel.singleton_key == SINGLETON_KEY)
            )
            return account_record(model) if model is not None else None

    def create_account(
        self,
        password_hash: str,
        display_name: str | None,
        now: datetime,
    ) -> bool:
        """Insert the singleton account, returning false on the uniqueness guard."""

        try:
            with Session(self._engine) as database_session, database_session.begin():
                database_session.add(
                    AccountModel(
                        id=uuid4(),
                        singleton_key=SINGLETON_KEY,
                        display_name=display_name,
                        password_hash=password_hash,
                        password_changed_at=now,
                        session_generation=1,
                        created_at=now,
                        updated_at=now,
                    )
                )
        except IntegrityError:
            return False
        return True

    def replace_password(self, password_hash: str, now: datetime) -> bool:
        """Administratively replace the password and revoke every session."""

        with Session(self._engine) as database_session, database_session.begin():
            account = database_session.scalar(
                select(AccountModel)
                .where(AccountModel.singleton_key == SINGLETON_KEY)
                .with_for_update()
            )
            if account is None:
                return False
            account.password_hash = password_hash
            account.password_changed_at = now
            account.session_generation += 1
            account.updated_at = now
            self._revoke_account_sessions(database_session, account.id, now, "admin_reset")
        return True

    def update_password_hash(
        self,
        account_id: UUID,
        expected_hash: str,
        password_hash: str,
        now: datetime,
    ) -> None:
        """Upgrade Argon2 parameters opportunistically without rotating sessions."""

        with Session(self._engine) as database_session, database_session.begin():
            database_session.execute(
                update(AccountModel)
                .where(
                    AccountModel.id == account_id,
                    AccountModel.password_hash == expected_hash,
                )
                .values(password_hash=password_hash, updated_at=now)
            )

    def create_session(
        self,
        account: AccountCredentials,
        secrets: SessionSecrets,
        now: datetime,
        idle_timeout: timedelta,
        absolute_timeout: timedelta,
    ) -> AuthenticatedSession:
        """Persist only hashes for a newly authenticated browser session."""

        session_id = uuid4()
        session_model = AuthSessionModel(
            id=session_id,
            account_id=account.id,
            token_hash=secrets.token_hash,
            csrf_token_hash=secrets.csrf_token_hash,
            account_generation=account.session_generation,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + idle_timeout,
            absolute_expires_at=now + absolute_timeout,
            revoked_at=None,
            revocation_reason=None,
        )
        with Session(self._engine) as database_session, database_session.begin():
            database_session.add(session_model)
        return AuthenticatedSession(
            id=session_id,
            account_id=account.id,
            display_name=account.display_name,
            csrf_token_hash=secrets.csrf_token_hash,
        )

    def find_valid_session(
        self,
        token_hash: str,
        now: datetime,
        idle_timeout: timedelta,
    ) -> AuthenticatedSession | None:
        """Validate revocation, both expirations and the account generation."""

        with Session(self._engine) as database_session, database_session.begin():
            row = database_session.execute(
                select(AuthSessionModel, AccountModel)
                .join(AccountModel, AccountModel.id == AuthSessionModel.account_id)
                .where(AuthSessionModel.token_hash == token_hash)
                .with_for_update()
            ).one_or_none()
            if row is None:
                return None
            session_model, account = row

            invalid_reason = self._invalid_reason(session_model, account, now)
            if invalid_reason is not None:
                if session_model.revoked_at is None:
                    session_model.revoked_at = now
                    session_model.revocation_reason = invalid_reason
                return None

            session_model.last_seen_at = now
            session_model.idle_expires_at = min(
                now + idle_timeout, session_model.absolute_expires_at
            )
            return authenticated_session(session_model, account)

    def revoke_session(self, session_id: UUID, now: datetime, reason: str) -> None:
        """Revoke one session idempotently."""

        with Session(self._engine) as database_session, database_session.begin():
            session_model = database_session.get(AuthSessionModel, session_id)
            if session_model is not None and session_model.revoked_at is None:
                session_model.revoked_at = now
                session_model.revocation_reason = reason

    def change_password_and_rotate_session(
        self,
        account: AccountCredentials,
        current_session_id: UUID,
        password_hash: str,
        secrets: SessionSecrets,
        now: datetime,
        idle_timeout: timedelta,
        absolute_timeout: timedelta,
    ) -> AuthenticatedSession | None:
        """Atomically update credentials, revoke sessions and issue one replacement."""

        with Session(self._engine) as database_session, database_session.begin():
            account_model = database_session.scalar(
                select(AccountModel).where(AccountModel.id == account.id).with_for_update()
            )
            current = database_session.scalar(
                select(AuthSessionModel)
                .where(AuthSessionModel.id == current_session_id)
                .with_for_update()
            )
            if (
                account_model is None
                or account_model.password_hash != account.password_hash
                or current is None
                or current.account_id != account.id
                or self._invalid_reason(current, account_model, now) is not None
            ):
                return None

            account_model.password_hash = password_hash
            account_model.password_changed_at = now
            account_model.session_generation += 1
            account_model.updated_at = now
            self._revoke_account_sessions(
                database_session,
                account_model.id,
                now,
                "password_changed",
            )

            replacement = AuthSessionModel(
                id=uuid4(),
                account_id=account_model.id,
                token_hash=secrets.token_hash,
                csrf_token_hash=secrets.csrf_token_hash,
                account_generation=account_model.session_generation,
                created_at=now,
                last_seen_at=now,
                idle_expires_at=now + idle_timeout,
                absolute_expires_at=now + absolute_timeout,
                revoked_at=None,
                revocation_reason=None,
            )
            database_session.add(replacement)
            database_session.flush()
            return authenticated_session(replacement, account_model)

    @staticmethod
    def _invalid_reason(
        session: AuthSessionModel,
        account: AccountModel,
        now: datetime,
    ) -> str | None:
        if session.revoked_at is not None:
            return "revoked"
        if session.account_generation != account.session_generation:
            return "generation_changed"
        if session.idle_expires_at <= now or session.absolute_expires_at <= now:
            return "expired"
        return None

    @staticmethod
    def _revoke_account_sessions(
        database_session: Session,
        account_id: UUID,
        now: datetime,
        reason: str,
    ) -> None:
        database_session.execute(
            update(AuthSessionModel)
            .where(
                AuthSessionModel.account_id == account_id,
                AuthSessionModel.revoked_at.is_(None),
            )
            .values(revoked_at=now, revocation_reason=reason)
        )
