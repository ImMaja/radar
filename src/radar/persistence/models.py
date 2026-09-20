"""SQLAlchemy models owned by Radar's persistence layer."""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
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


class GeometryMultiPolygon(UserDefinedType[str]):
    """Minimal SQLAlchemy declaration for a PostGIS WGS84 multipolygon."""

    cache_ok = True

    def get_col_spec(self, **_kwargs: object) -> str:
        return "geometry(MultiPolygon,4326)"


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


class CollectionCycleModel(Base):
    """Immutable geographic request and final business result of one collection."""

    __tablename__ = "collection_cycle"
    __table_args__ = (
        CheckConstraint(
            "connector IN ('SIRENE', 'DATATOURISME')",
            name="ck_collection_cycle_connector",
        ),
        CheckConstraint(
            "trigger IN ('MANUAL', 'SCHEDULED')",
            name="ck_collection_cycle_trigger",
        ),
        CheckConstraint(
            "result IS NULL OR result IN ('SUCCEEDED', 'PARTIAL', 'FAILED')",
            name="ck_collection_cycle_result",
        ),
        CheckConstraint(
            "collection_radius_meters BETWEEN 1 AND 50000",
            name="ck_collection_cycle_radius",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    connector: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    adapter_version: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_position_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("reference_position.id", ondelete="RESTRICT"),
        nullable=False,
    )
    center: Mapped[str] = mapped_column(GeographyPoint(), nullable=False)
    collection_radius_meters: Mapped[int] = mapped_column(Integer, nullable=False)
    schedule_timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    counters: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class CollectionJobModel(Base):
    """Durable PostgreSQL queue entry reserved by a collection worker."""

    __tablename__ = "collection_job"
    __table_args__ = (
        CheckConstraint(
            "connector IN ('SIRENE', 'DATATOURISME')",
            name="ck_collection_job_connector",
        ),
        CheckConstraint(
            "trigger IN ('MANUAL', 'SCHEDULED')",
            name="ck_collection_job_trigger",
        ),
        CheckConstraint(
            "state IN ('WAITING', 'RUNNING', 'WAITING_RETRY', 'SUCCEEDED', 'PARTIAL', 'FAILED')",
            name="ck_collection_job_state",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_collection_job_attempt_count"),
        CheckConstraint("max_attempts BETWEEN 1 AND 10", name="ck_collection_job_max_attempts"),
        CheckConstraint(
            "(trigger = 'MANUAL' AND scheduled_for IS NULL) OR "
            "(trigger = 'SCHEDULED' AND scheduled_for IS NOT NULL)",
            name="ck_collection_job_scheduled_trigger",
        ),
        Index(
            "uq_collection_job_active_request",
            "request_fingerprint",
            unique=True,
            postgresql_where=text("state IN ('WAITING', 'RUNNING', 'WAITING_RETRY')"),
        ),
        Index(
            "uq_collection_job_scheduled_slot",
            "connector",
            "scheduled_for",
            unique=True,
            postgresql_where=text("scheduled_for IS NOT NULL"),
        ),
        Index("ix_collection_job_reservation", "state", "available_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    cycle_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection_cycle.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    connector: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    progress: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    last_safe_checkpoint: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    last_error: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class CollectionAttemptModel(Base):
    """One effective reservation of a durable collection job."""

    __tablename__ = "collection_attempt"
    __table_args__ = (
        CheckConstraint(
            "result IS NULL OR result IN ('SUCCEEDED', 'RETRYABLE_FAILURE', 'PARTIAL', 'FAILED')",
            name="ck_collection_attempt_result",
        ),
        CheckConstraint("attempt_number >= 1", name="ck_collection_attempt_number"),
        Index(
            "uq_collection_attempt_number",
            "collection_job_id",
            "attempt_number",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    collection_job_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection_job.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_safe_checkpoint: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)


class ConnectorCoverageModel(Base):
    """Coverage proven only by a completely successful collection cycle."""

    __tablename__ = "connector_coverage"
    __table_args__ = (
        CheckConstraint(
            "connector IN ('SIRENE', 'DATATOURISME')",
            name="ck_connector_coverage_connector",
        ),
        CheckConstraint(
            "collection_radius_meters BETWEEN 1 AND 50000",
            name="ck_connector_coverage_radius",
        ),
        Index("ix_connector_coverage_center", "center", postgresql_using="gist"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    connector: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    cycle_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection_cycle.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    center: Mapped[str] = mapped_column(GeographyPoint(), nullable=False)
    collection_radius_meters: Mapped[int] = mapped_column(Integer, nullable=False)
    established_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_freshness: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    explicit_limits: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)


class DatasetReleaseModel(Base):
    """One immutable downloaded release of an external reference dataset."""

    __tablename__ = "dataset_release"
    __table_args__ = (
        CheckConstraint("file_size_bytes > 0", name="ck_dataset_release_file_size"),
        CheckConstraint(
            "status IN ('STAGED', 'VALIDATED', 'ACTIVE', 'REJECTED', 'RETIRED')",
            name="ck_dataset_release_status",
        ),
        Index(
            "uq_dataset_release_active_dataset",
            "dataset_code",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        Index(
            "ix_dataset_release_fingerprint",
            "dataset_code",
            "digest_algorithm",
            "file_digest",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)
    dataset_code: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_identifier: Mapped[str] = mapped_column(String(256), nullable=False)
    resource_url: Mapped[str] = mapped_column(Text, nullable=False)
    published_on: Mapped[date | None] = mapped_column(nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    digest_algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    file_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    expected_schema: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    license_name: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CommuneBoundaryModel(Base):
    """One metropolitan municipality boundary in a versioned release."""

    __tablename__ = "commune_boundary"
    __table_args__ = (
        CheckConstraint(
            "municipality_code ~ '^(?:[0-9]{5}|2[AB][0-9]{3})$'",
            name="ck_commune_boundary_code",
        ),
        CheckConstraint(
            "is_metropolitan_france IS TRUE",
            name="ck_commune_boundary_metropolitan",
        ),
        CheckConstraint("NOT ST_IsEmpty(boundary)", name="ck_commune_boundary_not_empty"),
        CheckConstraint("ST_IsValid(boundary)", name="ck_commune_boundary_valid"),
        Index("ix_commune_boundary_boundary", "boundary", postgresql_using="gist"),
    )

    dataset_release_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dataset_release.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    municipality_code: Mapped[str] = mapped_column(String(5), primary_key=True)
    official_name: Mapped[str] = mapped_column(Text, nullable=False)
    boundary: Mapped[str] = mapped_column(GeometryMultiPolygon(), nullable=False)
    is_metropolitan_france: Mapped[bool] = mapped_column(Boolean, nullable=False)
