"""SQLAlchemy models owned by Radar's persistence layer."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import UserDefinedType


class GeographyPoint(UserDefinedType[str]):
    """Minimal SQLAlchemy declaration for a PostGIS WGS84 geography point."""

    cache_ok = True

    def get_col_spec(self, **_kwargs: object) -> str:
        return "geography(Point,4326)"


class Base(DeclarativeBase):
    """Declarative metadata shared by Radar's relational models."""


class AccountModel(Base):
    """The single local Radar account."""

    __tablename__ = "account"
    __table_args__ = (
        CheckConstraint("singleton_key = 'primary'", name="ck_account_singleton_key"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    singleton_key: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    session_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuthSessionModel(Base):
    """A revocable server-side browser session."""

    __tablename__ = "auth_session"
    __table_args__ = (
        CheckConstraint(
            "idle_expires_at <= absolute_expires_at",
            name="ck_auth_session_expiration_order",
        ),
        Index(
            "ix_auth_session_active_expiration",
            "idle_expires_at",
            "absolute_expires_at",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("account.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    account_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ReferencePositionModel(Base):
    """One immutable result proposed by the reference-address geocoder."""

    __tablename__ = "reference_position"
    __table_args__ = (
        CheckConstraint("country_code = 'FR'", name="ck_reference_position_country_code"),
        CheckConstraint(
            "is_metropolitan_france IS TRUE",
            name="ck_reference_position_metropolitan",
        ),
        CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 1)",
            name="ck_reference_position_score",
        ),
        Index("ix_reference_position_point", "point", postgresql_using="gist"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    input_address: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_label: Mapped[str] = mapped_column(Text, nullable=False)
    structured_address: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    point: Mapped[str] = mapped_column(GeographyPoint(), nullable=False)
    municipality_code: Mapped[str] = mapped_column(String(5), nullable=False, index=True)
    ban_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_url: Mapped[str] = mapped_column(Text, nullable=False)
    geocoded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    is_metropolitan_france: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ApplicationSettingModel(Base):
    """Singleton pointer to the current reference position and local radii."""

    __tablename__ = "application_setting"
    __table_args__ = (
        CheckConstraint(
            "singleton_key = 'primary'",
            name="ck_application_setting_singleton_key",
        ),
        CheckConstraint(
            "collection_radius_meters BETWEEN 1 AND 50000",
            name="ck_application_setting_collection_radius",
        ),
        CheckConstraint(
            "search_radius_meters BETWEEN 1 AND 50000",
            name="ck_application_setting_search_radius",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    singleton_key: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    current_reference_position_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("reference_position.id", ondelete="RESTRICT"),
        nullable=True,
    )
    collection_radius_meters: Mapped[int] = mapped_column(Integer, nullable=False, default=50_000)
    search_radius_meters: Mapped[int] = mapped_column(Integer, nullable=False, default=50_000)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
