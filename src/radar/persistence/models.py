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
    ForeignKeyConstraint,
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


class CollectionSourceRunModel(Base):
    """Per-source freshness, contract and counters inside one collection cycle."""

    __tablename__ = "collection_source_run"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PLANNED', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED')",
            name="ck_collection_source_run_status",
        ),
        CheckConstraint(
            "request_count >= 0 AND retry_count >= 0 AND error_count >= 0",
            name="ck_collection_source_run_counts",
        ),
        Index(
            "uq_collection_source_run_cycle_source",
            "collection_cycle_id",
            "source",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    collection_cycle_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection_cycle.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_release_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dataset_release.id", ondelete="RESTRICT"),
        nullable=True,
    )
    freshness_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    counters: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CollectionBatchModel(Base):
    """One stable, restartable logical unit inside a source run."""

    __tablename__ = "collection_batch"
    __table_args__ = (
        CheckConstraint("order_number >= 1", name="ck_collection_batch_order"),
        CheckConstraint("attempt_count >= 0", name="ck_collection_batch_attempt_count"),
        CheckConstraint(
            "state IN ('WAITING', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED')",
            name="ck_collection_batch_state",
        ),
        CheckConstraint(
            "(announced_total IS NULL OR announced_total >= 0) AND "
            "(received_count IS NULL OR received_count >= 0) AND "
            "(unique_identifier_count IS NULL OR unique_identifier_count >= 0)",
            name="ck_collection_batch_counts",
        ),
        Index("uq_collection_batch_cycle_key", "collection_cycle_id", "batch_key", unique=True),
        Index("uq_collection_batch_source_order", "source_run_id", "order_number", unique=True),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    collection_cycle_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection_cycle.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection_source_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    last_collection_attempt_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection_attempt.id", ondelete="RESTRICT"),
        nullable=True,
    )
    batch_type: Mapped[str] = mapped_column(String(64), nullable=False)
    batch_key: Mapped[str] = mapped_column(String(160), nullable=False)
    order_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    announced_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    received_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unique_identifier_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resume_state: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    processing_counts: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    error: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CollectionPageModel(Base):
    """Non-sensitive proof of one fetched provider page."""

    __tablename__ = "collection_page"
    __table_args__ = (
        CheckConstraint(
            "http_status IS NULL OR http_status BETWEEN 100 AND 599",
            name="ck_collection_page_http_status",
        ),
        CheckConstraint(
            "received_count >= 0 AND unique_identifier_count >= 0 AND "
            "(announced_total IS NULL OR announced_total >= 0) AND "
            "(announced_page_count IS NULL OR announced_page_count >= 0)",
            name="ck_collection_page_counts",
        ),
        CheckConstraint(
            "state IN ('RECEIVED', 'PROCESSED', 'FAILED')",
            name="ck_collection_page_state",
        ),
        Index("uq_collection_page_batch_key", "collection_batch_id", "page_key", unique=True),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    collection_batch_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection_batch.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    collection_attempt_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection_attempt.id", ondelete="RESTRICT"),
        nullable=True,
    )
    page_key: Mapped[str] = mapped_column(String(160), nullable=False)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    received_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unique_identifier_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    announced_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    announced_page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_cursor_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    next_link_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_terminal: Mapped[bool] = mapped_column(Boolean, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DataSourceModel(Base):
    """Non-secret reference data describing one technical provider source."""

    __tablename__ = "data_source"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    authority: Mapped[str] = mapped_column(String(160), nullable=False)
    documentation_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExternalIdentityModel(Base):
    """A source authority identifier retained only while its use is permitted."""

    __tablename__ = "external_identity"
    __table_args__ = (
        CheckConstraint(
            "namespace <> 'SIRET' OR canonical_value IS NULL OR canonical_value ~ '^[0-9]{14}$'",
            name="ck_external_identity_siret",
        ),
        CheckConstraint(
            "fingerprint_algorithm = 'SHA-256'",
            name="ck_external_identity_fingerprint_algorithm",
        ),
        CheckConstraint(
            "num_nonnulls(organization_id, establishment_id, opportunity_id) <= 1",
            name="ck_external_identity_single_target",
        ),
        Index(
            "uq_external_identity_authority_namespace_fingerprint",
            "authority",
            "namespace",
            "identifier_fingerprint",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    authority: Mapped[str] = mapped_column(String(64), nullable=False)
    namespace: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_value: Mapped[str | None] = mapped_column(String(512), nullable=True)
    identifier_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    restricted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    organization_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organization.id", ondelete="RESTRICT"),
        nullable=True,
    )
    establishment_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("establishment.id", ondelete="RESTRICT"),
        nullable=True,
    )
    opportunity_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("opportunity.id", ondelete="RESTRICT"),
        nullable=True,
    )


class SourceObservationModel(Base):
    """Immutable normalized provider revision, optionally awaiting a business fiche."""

    __tablename__ = "source_observation"
    __table_args__ = (
        CheckConstraint(
            "validation_status IN ('VALID', 'REJECTED', 'IDENTITY_CONFLICT')",
            name="ck_source_observation_validation_status",
        ),
        Index(
            "uq_source_observation_identity_content",
            "data_source_code",
            "external_identity_id",
            "content_fingerprint",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    data_source_code: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("data_source.code", ondelete="RESTRICT"),
        nullable=False,
    )
    external_identity_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("external_identity.id", ondelete="RESTRICT"),
        nullable=True,
    )
    source_binding_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_binding.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    collection_cycle_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection_cycle.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    collection_batch_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection_batch.id", ondelete="RESTRICT"),
        nullable=True,
    )
    collection_page_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection_page.id", ondelete="RESTRICT"),
        nullable=True,
    )
    dataset_release_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dataset_release.id", ondelete="RESTRICT"),
        nullable=True,
    )
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    adapter_version: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    source_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    normalization_error: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    redacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CollectionItemModel(Base):
    """One normalized candidate occurrence within a provider page attempt."""

    __tablename__ = "collection_item"
    __table_args__ = (
        CheckConstraint("page_number >= 1", name="ck_collection_item_page_number"),
        CheckConstraint("item_rank >= 1", name="ck_collection_item_rank"),
        CheckConstraint(
            "normalization_result IN ('VALID', 'REJECTED', 'IDENTITY_CONFLICT')",
            name="ck_collection_item_normalization_result",
        ),
        CheckConstraint(
            "geographic_classification IS NULL OR geographic_classification IN ("
            "'IN_RADIUS', 'OUTSIDE_RADIUS', 'LOCATION_UNKNOWN', "
            "'OUTSIDE_METROPOLITAN_FRANCE', 'NOT_APPLICABLE')",
            name="ck_collection_item_geographic_classification",
        ),
        CheckConstraint(
            "distance_meters IS NULL OR distance_meters >= 0",
            name="ck_collection_item_distance",
        ),
        CheckConstraint(
            "decision IS NULL OR decision IN ("
            "'CREATED', 'UPDATED', 'UNCHANGED', 'COUNTED_ONLY', 'REJECTED', 'ERROR')",
            name="ck_collection_item_decision",
        ),
        Index(
            "uq_collection_item_attempt_batch_page_rank",
            "collection_attempt_id",
            "collection_batch_id",
            "page_number",
            "item_rank",
            unique=True,
        ),
        Index(
            "ix_collection_item_cycle_identity",
            "collection_cycle_id",
            "authority",
            "namespace",
            "identifier_fingerprint",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    collection_cycle_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection_cycle.id", ondelete="CASCADE"),
        nullable=False,
    )
    collection_batch_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection_batch.id", ondelete="CASCADE"),
        nullable=False,
    )
    collection_attempt_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection_attempt.id", ondelete="RESTRICT"),
        nullable=False,
    )
    collection_page_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection_page.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    item_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    authority: Mapped[str] = mapped_column(String(64), nullable=False)
    namespace: Mapped[str] = mapped_column(String(64), nullable=False)
    identifier_value: Mapped[str | None] = mapped_column(String(512), nullable=True)
    identifier_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_identity_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("external_identity.id", ondelete="RESTRICT"),
        nullable=True,
    )
    source_observation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_observation.id", ondelete="RESTRICT"),
        nullable=True,
    )
    opportunity_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("opportunity.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    normalization_result: Mapped[str] = mapped_column(String(32), nullable=False)
    geographic_classification: Mapped[str | None] = mapped_column(String(48), nullable=True)
    distance_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CandidatePositionModel(Base):
    """One independently assessed source position for a collected candidate."""

    __tablename__ = "candidate_position"
    __table_args__ = (
        CheckConstraint(
            "origin IN ('SIRENE_API', 'SIRENE_GEOLOCATION', 'GEOPLATFORM_GEOCODER')",
            name="ck_candidate_position_origin",
        ),
        CheckConstraint(
            "precision IN ('ROOFTOP', 'ADDRESS', 'STREET', 'MUNICIPALITY', 'UNKNOWN')",
            name="ck_candidate_position_precision",
        ),
        CheckConstraint(
            "usability IN ('USABLE', 'TO_VERIFY', 'MISSING')",
            name="ck_candidate_position_usability",
        ),
        CheckConstraint(
            "geographic_classification IN ("
            "'IN_RADIUS', 'OUTSIDE_RADIUS', 'LOCATION_UNKNOWN', "
            "'OUTSIDE_METROPOLITAN_FRANCE')",
            name="ck_candidate_position_geographic_classification",
        ),
        CheckConstraint(
            "distance_meters IS NULL OR distance_meters >= 0",
            name="ck_candidate_position_distance",
        ),
        CheckConstraint(
            "geographic_classification NOT IN ('IN_RADIUS', 'OUTSIDE_RADIUS') "
            "OR (point IS NOT NULL AND usability = 'USABLE' "
            "AND municipality_consistent IS TRUE AND distance_meters IS NOT NULL)",
            name="ck_candidate_position_exact_classification",
        ),
        CheckConstraint(
            "geographic_classification <> 'LOCATION_UNKNOWN' OR distance_meters IS NULL",
            name="ck_candidate_position_unknown_distance",
        ),
        Index(
            "uq_candidate_position_item_origin",
            "collection_item_id",
            "origin",
            unique=True,
        ),
        Index("ix_candidate_position_point", "point", postgresql_using="gist"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    collection_item_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection_item.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_observation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_observation.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    dataset_release_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dataset_release.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    point: Mapped[str | None] = mapped_column(GeographyPoint(), nullable=True)
    source_crs: Mapped[str | None] = mapped_column(String(32), nullable=True)
    quality_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    precision: Mapped[str] = mapped_column(String(32), nullable=False)
    usability: Mapped[str] = mapped_column(String(32), nullable=False)
    municipality_consistent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    geographic_classification: Mapped[str] = mapped_column(String(48), nullable=False)
    distance_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    diagnostics: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OpportunityModel(Base):
    """Stable user-visible fiche root shared by prospects and events."""

    __tablename__ = "opportunity"
    __table_args__ = (
        CheckConstraint("kind IN ('PROSPECT', 'EVENT')", name="ck_opportunity_kind"),
        CheckConstraint(
            "creation_origin IN ('SOURCE', 'MANUAL')",
            name="ck_opportunity_creation_origin",
        ),
        CheckConstraint(
            "hidden_reason IS NULL OR hidden_reason IN ("
            "'NOT_RELEVANT', 'DUPLICATE', 'INCORRECT_INFORMATION', 'OTHER')",
            name="ck_opportunity_hidden_reason",
        ),
        CheckConstraint(
            "duplicate_of_opportunity_id IS NULL OR ("
            "hidden_at IS NOT NULL AND hidden_reason = 'DUPLICATE' "
            "AND duplicate_of_opportunity_id <> id)",
            name="ck_opportunity_duplicate_hidden",
        ),
        Index(
            "ix_opportunity_visible_kind",
            "kind",
            postgresql_where=text("hidden_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    creation_origin: Mapped[str] = mapped_column(String(16), nullable=False)
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hidden_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    duplicate_of_opportunity_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("opportunity.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OrganizationModel(Base):
    """Legal entity shared by one or more physical establishments."""

    __tablename__ = "organization"
    __table_args__ = (
        CheckConstraint("siren IS NULL OR siren ~ '^[0-9]{9}$'", name="ck_organization_siren"),
        CheckConstraint(
            "administrative_state IN ('ACTIVE', 'CEASED', 'UNKNOWN')",
            name="ck_organization_administrative_state",
        ),
        CheckConstraint(
            "diffusion_status IN ('FULL', 'PARTIAL', 'UNKNOWN')",
            name="ck_organization_diffusion_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    siren: Mapped[str | None] = mapped_column(String(9), nullable=True, unique=True)
    legal_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    usual_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    organization_type: Mapped[str] = mapped_column(String(64), nullable=False)
    legal_category: Mapped[str | None] = mapped_column(String(8), nullable=True)
    administrative_state: Mapped[str] = mapped_column(String(16), nullable=False)
    diffusion_status: Mapped[str] = mapped_column(String(16), nullable=False)
    current_observation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_observation.id", ondelete="RESTRICT"),
        nullable=True,
    )
    administrative_state_observation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_observation.id", ondelete="RESTRICT"),
        nullable=True,
    )
    diffusion_status_observation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_observation.id", ondelete="RESTRICT"),
        nullable=True,
    )
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EstablishmentModel(Base):
    """One physical local site identified by SIRET when available."""

    __tablename__ = "establishment"
    __table_args__ = (
        CheckConstraint(
            "siret IS NULL OR siret ~ '^[0-9]{14}$'",
            name="ck_establishment_siret",
        ),
        CheckConstraint(
            "(activity_code IS NULL) = (activity_nomenclature IS NULL)",
            name="ck_establishment_activity_pair",
        ),
        CheckConstraint(
            "employee_scope IN ('LOCAL', 'GENERAL', 'UNKNOWN')",
            name="ck_establishment_employee_scope",
        ),
        CheckConstraint(
            "employee_year IS NULL OR employee_year BETWEEN 1800 AND 2200",
            name="ck_establishment_employee_year",
        ),
        CheckConstraint(
            "administrative_state IN ('ACTIVE', 'CLOSED', 'UNKNOWN')",
            name="ck_establishment_administrative_state",
        ),
        CheckConstraint(
            "diffusion_status IN ('FULL', 'PARTIAL', 'UNKNOWN')",
            name="ck_establishment_diffusion_status",
        ),
        Index("ix_establishment_activity", "activity_nomenclature", "activity_code"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organization.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    siret: Mapped[str | None] = mapped_column(String(14), nullable=True, unique=True)
    is_head_office: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source_names: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    activity_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    activity_nomenclature: Mapped[str | None] = mapped_column(String(64), nullable=True)
    activity_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    employee_band: Mapped[str | None] = mapped_column(String(8), nullable=True)
    employee_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    employee_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    administrative_state: Mapped[str] = mapped_column(String(16), nullable=False)
    diffusion_status: Mapped[str] = mapped_column(String(16), nullable=False)
    established_on: Mapped[date | None] = mapped_column(nullable=True)
    current_period_started_on: Mapped[date | None] = mapped_column(nullable=True)
    source_processed_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_observation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_observation.id", ondelete="RESTRICT"),
        nullable=True,
    )
    administrative_state_observation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_observation.id", ondelete="RESTRICT"),
        nullable=True,
    )
    diffusion_status_observation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_observation.id", ondelete="RESTRICT"),
        nullable=True,
    )
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProspectModel(Base):
    """Source projection for one user-visible regular prospect."""

    __tablename__ = "prospect"
    __table_args__ = (
        CheckConstraint(
            "eligibility IN ('ELIGIBLE', 'RESTRICTED', 'UNKNOWN')",
            name="ck_prospect_eligibility",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("opportunity.id", ondelete="CASCADE"),
        primary_key=True,
    )
    establishment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("establishment.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    source_display_name: Mapped[str] = mapped_column(Text, nullable=False)
    source_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_organization_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_business_signals: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    eligibility: Mapped[str] = mapped_column(String(16), nullable=False)
    eligibility_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    eligibility_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ContactSetModel(Base):
    """One current or retired source/user contact collection for an opportunity."""

    __tablename__ = "contact_set"
    __table_args__ = (
        CheckConstraint("layer IN ('SOURCE', 'USER')", name="ck_contact_set_layer"),
        CheckConstraint(
            "(layer = 'SOURCE' AND source_observation_id IS NOT NULL) OR "
            "(layer = 'USER' AND source_observation_id IS NULL)",
            name="ck_contact_set_observation_layer",
        ),
        CheckConstraint(
            "is_current OR retired_at IS NOT NULL",
            name="ck_contact_set_retired",
        ),
        Index(
            "uq_contact_set_current_layer",
            "opportunity_id",
            "layer",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    opportunity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("opportunity.id", ondelete="CASCADE"),
        nullable=False,
    )
    layer: Mapped[str] = mapped_column(String(16), nullable=False)
    source_observation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_observation.id", ondelete="RESTRICT"),
        nullable=True,
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ContactPointModel(Base):
    """One professional contact value in a versioned effective contact set."""

    __tablename__ = "contact_point"
    __table_args__ = (
        CheckConstraint(
            "type IN ('EMAIL', 'PHONE', 'WEBSITE', 'BOOKING_URL', 'CONTACT_RELAY')",
            name="ck_contact_point_type",
        ),
        CheckConstraint(
            "scope IN ('LOCAL', 'CENTRAL', 'UNKNOWN')",
            name="ck_contact_point_scope",
        ),
        CheckConstraint(
            "length(btrim(display_value)) > 0 AND length(btrim(normalized_value)) > 0",
            name="ck_contact_point_non_empty",
        ),
        CheckConstraint("display_order >= 0", name="ck_contact_point_display_order"),
        Index("ix_contact_point_type_normalized", "type", "normalized_value"),
        Index(
            "uq_contact_point_set_type_value_scope",
            "contact_set_id",
            "type",
            "normalized_value",
            "scope",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    contact_set_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("contact_set.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    display_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SourceBindingModel(Base):
    """Stable provider object attached to an opportunity, including hidden ones."""

    __tablename__ = "source_binding"
    __table_args__ = (
        CheckConstraint(
            "state IN ('CURRENT', 'POTENTIALLY_STALE', 'RESTRICTED')",
            name="ck_source_binding_state",
        ),
        CheckConstraint(
            "consecutive_absence_count >= 0",
            name="ck_source_binding_absence_count",
        ),
        Index(
            "uq_source_binding_source_identity",
            "data_source_code",
            "external_identity_id",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    data_source_code: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("data_source.code", ondelete="RESTRICT"),
        nullable=False,
    )
    external_identity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("external_identity.id", ondelete="RESTRICT"),
        nullable=False,
    )
    opportunity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("opportunity.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    producer_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_observation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_observation.id", ondelete="RESTRICT"),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    consecutive_absence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LocationAssertionModel(Base):
    """Versioned source or user location for one opportunity."""

    __tablename__ = "location_assertion"
    __table_args__ = (
        CheckConstraint("layer IN ('SOURCE', 'USER')", name="ck_location_assertion_layer"),
        CheckConstraint("country_code = 'FR'", name="ck_location_assertion_country"),
        CheckConstraint(
            "position_origin IN ('SIRENE_DATASET', 'SIRENE_API', "
            "'GEOPLATFORM_GEOCODER', 'DATATOURISME', 'USER_CONFIRMED', 'OTHER')",
            name="ck_location_assertion_origin",
        ),
        CheckConstraint(
            "precision IN ('ROOFTOP', 'ADDRESS', 'STREET', 'MUNICIPALITY', 'UNKNOWN')",
            name="ck_location_assertion_precision",
        ),
        CheckConstraint(
            "usability IN ('USABLE', 'TO_VERIFY', 'MISSING')",
            name="ck_location_assertion_usability",
        ),
        CheckConstraint(
            "match_score IS NULL OR (match_score >= 0 AND match_score <= 1)",
            name="ck_location_assertion_match_score",
        ),
        CheckConstraint(
            "is_current OR retired_at IS NOT NULL",
            name="ck_location_assertion_retired",
        ),
        Index(
            "uq_location_assertion_current_layer",
            "opportunity_id",
            "layer",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        Index("ix_location_assertion_point", "point", postgresql_using="gist"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    opportunity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("opportunity.id", ondelete="CASCADE"),
        nullable=False,
    )
    layer: Mapped[str] = mapped_column(String(16), nullable=False)
    full_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    structured_address: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    municipality_code: Mapped[str | None] = mapped_column(String(5), nullable=True)
    postcode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    point: Mapped[str | None] = mapped_column(GeographyPoint(), nullable=True)
    position_origin: Mapped[str] = mapped_column(String(32), nullable=False)
    source_crs: Mapped[str | None] = mapped_column(String(32), nullable=True)
    quality_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    precision: Mapped[str] = mapped_column(String(32), nullable=False)
    usability: Mapped[str] = mapped_column(String(32), nullable=False)
    address_observation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_observation.id", ondelete="RESTRICT"),
        nullable=True,
    )
    position_observation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_observation.id", ondelete="RESTRICT"),
        nullable=True,
    )
    dataset_release_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dataset_release.id", ondelete="RESTRICT"),
        nullable=True,
    )
    candidate_position_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("candidate_position.id", ondelete="RESTRICT"),
        nullable=True,
    )
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    diagnostics: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FieldLineageModel(Base):
    """Current observation selected for one scalar source-projection field."""

    __tablename__ = "field_lineage"

    opportunity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("opportunity.id", ondelete="CASCADE"),
        primary_key=True,
    )
    field_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_observation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_observation.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_path: Mapped[str] = mapped_column(String(256), nullable=False)
    resolution_rule: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SourceSightingModel(Base):
    """Evidence that one stable source object appeared in a collection cycle."""

    __tablename__ = "source_sighting"

    source_binding_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_binding.id", ondelete="CASCADE"),
        primary_key=True,
    )
    collection_cycle_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection_cycle.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    source_observation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_observation.id", ondelete="RESTRICT"),
        nullable=False,
    )
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SireneKnownStatusCheckModel(Base):
    """Durable outcome of one targeted check for a known SIRET absent from discovery."""

    __tablename__ = "sirene_known_status_check"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('ACTIVE', 'CLOSED', 'CEASED', 'NOT_FOUND')",
            name="ck_sirene_known_status_check_outcome",
        ),
        CheckConstraint(
            "(outcome = 'NOT_FOUND' AND source_observation_id IS NULL) OR "
            "(outcome <> 'NOT_FOUND' AND source_observation_id IS NOT NULL)",
            name="ck_sirene_known_status_check_observation",
        ),
        Index(
            "uq_sirene_known_status_check_cycle_binding",
            "collection_cycle_id",
            "source_binding_id",
            unique=True,
        ),
        Index(
            "uq_sirene_known_status_check_cycle_identity",
            "collection_cycle_id",
            "external_identity_id",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    collection_cycle_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection_cycle.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_binding_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_binding.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_identity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("external_identity.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_observation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_observation.id", ondelete="RESTRICT"),
        nullable=True,
    )
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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


class CollectionReferenceUsageModel(Base):
    """Reference-dataset version frozen into one collection cycle."""

    __tablename__ = "collection_reference_usage"
    __table_args__ = (
        CheckConstraint(
            "role IN ('MUNICIPALITY_BOUNDARIES', 'SIRENE_GEOLOCATION')",
            name="ck_collection_reference_usage_role",
        ),
    )

    collection_cycle_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection_cycle.id", ondelete="CASCADE"),
        primary_key=True,
    )
    dataset_release_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dataset_release.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(64), primary_key=True)
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CollectionCycleCommuneModel(Base):
    """A municipality frozen into exactly one Sirene enumeration batch."""

    __tablename__ = "collection_cycle_commune"
    __table_args__ = (
        CheckConstraint(
            "selection_margin_meters BETWEEN 0 AND 10000",
            name="ck_collection_cycle_commune_margin",
        ),
        CheckConstraint(
            "state IN ('WAITING', 'RUNNING', 'SUCCEEDED', 'FAILED')",
            name="ck_collection_cycle_commune_state",
        ),
        ForeignKeyConstraint(
            ["dataset_release_id", "municipality_code"],
            ["commune_boundary.dataset_release_id", "commune_boundary.municipality_code"],
            name="fk_collection_cycle_commune_boundary",
            ondelete="RESTRICT",
        ),
    )

    collection_cycle_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection_cycle.id", ondelete="CASCADE"),
        primary_key=True,
    )
    dataset_release_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    municipality_code: Mapped[str] = mapped_column(String(5), primary_key=True)
    collection_batch_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection_batch.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    selection_reason: Mapped[str] = mapped_column(String(96), nullable=False)
    selection_margin_meters: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
