"""Add durable normalized candidate provenance before prospect creation.

Revision ID: 20260921_07
Revises: 20260920_06
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260921_07"
down_revision: str | None = "20260920_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the minimal provenance and collection-item staging tables."""

    op.create_table(
        "data_source",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("authority", sa.String(length=160), nullable=False),
        sa.Column("documentation_url", sa.Text(), nullable=True),
        sa.Column("terms_reference", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_data_source")),
    )
    op.execute(
        """
        INSERT INTO data_source (
            code,
            name,
            authority,
            documentation_url,
            terms_reference,
            is_active,
            metadata,
            created_at,
            updated_at
        ) VALUES (
            'SIRENE_API',
            'API Sirene 3.11',
            'INSEE',
            'https://www.data.gouv.fr/dataservices/api-sirene-open-data',
            NULL,
            TRUE,
            '{"api_version": "3.11"}'::jsonb,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
        """
    )

    op.create_table(
        "external_identity",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("authority", sa.String(length=64), nullable=False),
        sa.Column("namespace", sa.String(length=64), nullable=False),
        sa.Column("canonical_value", sa.String(length=512), nullable=True),
        sa.Column("identifier_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("fingerprint_algorithm", sa.String(length=32), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("restricted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "namespace <> 'SIRET' OR canonical_value IS NULL OR canonical_value ~ '^[0-9]{14}$'",
            name="ck_external_identity_siret",
        ),
        sa.CheckConstraint(
            "fingerprint_algorithm = 'SHA-256'",
            name="ck_external_identity_fingerprint_algorithm",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_identity")),
        sa.UniqueConstraint(
            "authority",
            "namespace",
            "identifier_fingerprint",
            name="uq_external_identity_authority_namespace_fingerprint",
        ),
    )

    op.create_table(
        "source_observation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("data_source_code", sa.String(length=64), nullable=False),
        sa.Column("external_identity_id", sa.Uuid(), nullable=True),
        sa.Column("collection_cycle_id", sa.Uuid(), nullable=True),
        sa.Column("collection_batch_id", sa.Uuid(), nullable=True),
        sa.Column("collection_page_id", sa.Uuid(), nullable=True),
        sa.Column("dataset_release_id", sa.Uuid(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("adapter_version", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("validation_status", sa.String(length=32), nullable=False),
        sa.Column(
            "normalization_error",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("redacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "validation_status IN ('VALID', 'REJECTED', 'IDENTITY_CONFLICT')",
            name="ck_source_observation_validation_status",
        ),
        sa.ForeignKeyConstraint(
            ["data_source_code"],
            ["data_source.code"],
            name="fk_source_observation_data_source",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["external_identity_id"],
            ["external_identity.id"],
            name="fk_source_observation_external_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["collection_cycle_id"],
            ["collection_cycle.id"],
            name="fk_source_observation_cycle",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["collection_batch_id"],
            ["collection_batch.id"],
            name="fk_source_observation_batch",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["collection_page_id"],
            ["collection_page.id"],
            name="fk_source_observation_page",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_release_id"],
            ["dataset_release.id"],
            name="fk_source_observation_dataset_release",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_observation")),
        sa.UniqueConstraint(
            "data_source_code",
            "external_identity_id",
            "content_fingerprint",
            name="uq_source_observation_identity_content",
        ),
    )
    op.create_index(
        op.f("ix_source_observation_collection_cycle_id"),
        "source_observation",
        ["collection_cycle_id"],
        unique=False,
    )

    op.create_table(
        "collection_item",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("collection_cycle_id", sa.Uuid(), nullable=False),
        sa.Column("collection_batch_id", sa.Uuid(), nullable=False),
        sa.Column("collection_attempt_id", sa.Uuid(), nullable=False),
        sa.Column("collection_page_id", sa.Uuid(), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("item_rank", sa.Integer(), nullable=False),
        sa.Column("authority", sa.String(length=64), nullable=False),
        sa.Column("namespace", sa.String(length=64), nullable=False),
        sa.Column("identifier_value", sa.String(length=512), nullable=True),
        sa.Column("identifier_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("external_identity_id", sa.Uuid(), nullable=True),
        sa.Column("source_observation_id", sa.Uuid(), nullable=True),
        sa.Column("normalization_result", sa.String(length=32), nullable=False),
        sa.Column("geographic_classification", sa.String(length=48), nullable=True),
        sa.Column("distance_meters", sa.Float(), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=True),
        sa.Column("reason", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("page_number >= 1", name="ck_collection_item_page_number"),
        sa.CheckConstraint("item_rank >= 1", name="ck_collection_item_rank"),
        sa.CheckConstraint(
            "normalization_result IN ('VALID', 'REJECTED', 'IDENTITY_CONFLICT')",
            name="ck_collection_item_normalization_result",
        ),
        sa.CheckConstraint(
            "geographic_classification IS NULL OR geographic_classification IN ("
            "'IN_RADIUS', 'OUTSIDE_RADIUS', 'LOCATION_UNKNOWN', "
            "'OUTSIDE_METROPOLITAN_FRANCE', 'NOT_APPLICABLE')",
            name="ck_collection_item_geographic_classification",
        ),
        sa.CheckConstraint(
            "distance_meters IS NULL OR distance_meters >= 0",
            name="ck_collection_item_distance",
        ),
        sa.CheckConstraint(
            "decision IS NULL OR decision IN ("
            "'CREATED', 'UPDATED', 'UNCHANGED', 'COUNTED_ONLY', 'REJECTED', 'ERROR')",
            name="ck_collection_item_decision",
        ),
        sa.ForeignKeyConstraint(
            ["collection_cycle_id"],
            ["collection_cycle.id"],
            name="fk_collection_item_cycle",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_batch_id"],
            ["collection_batch.id"],
            name="fk_collection_item_batch",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_attempt_id"],
            ["collection_attempt.id"],
            name="fk_collection_item_attempt",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["collection_page_id"],
            ["collection_page.id"],
            name="fk_collection_item_page",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["external_identity_id"],
            ["external_identity.id"],
            name="fk_collection_item_external_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_observation_id"],
            ["source_observation.id"],
            name="fk_collection_item_source_observation",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_item")),
        sa.UniqueConstraint(
            "collection_attempt_id",
            "collection_batch_id",
            "page_number",
            "item_rank",
            name="uq_collection_item_attempt_batch_page_rank",
        ),
    )
    op.create_index(
        "ix_collection_item_cycle_identity",
        "collection_item",
        ["collection_cycle_id", "authority", "namespace", "identifier_fingerprint"],
        unique=False,
    )
    op.create_index(
        op.f("ix_collection_item_collection_page_id"),
        "collection_item",
        ["collection_page_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop normalized candidate staging in dependency order."""

    op.drop_table("collection_item")
    op.drop_table("source_observation")
    op.drop_table("external_identity")
    op.drop_table("data_source")
