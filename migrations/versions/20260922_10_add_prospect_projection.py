"""Add stable Sirene prospect projections and their source lineage.

Revision ID: 20260922_10
Revises: 20260921_09
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType

revision: str = "20260922_10"
down_revision: str | None = "20260921_09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class GeographyPoint(UserDefinedType[str]):
    """PostGIS WGS84 geography point used by this migration."""

    cache_ok = True

    def get_col_spec(self, **_kwargs: object) -> str:
        return "geography(Point,4326)"


def upgrade() -> None:
    """Create the source-owned prospect projection without user override tables."""

    op.create_table(
        "opportunity",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("creation_origin", sa.String(length=16), nullable=False),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hidden_reason", sa.String(length=32), nullable=True),
        sa.Column("duplicate_of_opportunity_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('PROSPECT', 'EVENT')", name="ck_opportunity_kind"),
        sa.CheckConstraint(
            "creation_origin IN ('SOURCE', 'MANUAL')",
            name="ck_opportunity_creation_origin",
        ),
        sa.CheckConstraint(
            "hidden_reason IS NULL OR hidden_reason IN ("
            "'NOT_RELEVANT', 'DUPLICATE', 'INCORRECT_INFORMATION', 'OTHER')",
            name="ck_opportunity_hidden_reason",
        ),
        sa.CheckConstraint(
            "duplicate_of_opportunity_id IS NULL OR ("
            "hidden_at IS NOT NULL AND hidden_reason = 'DUPLICATE' "
            "AND duplicate_of_opportunity_id <> id)",
            name="ck_opportunity_duplicate_hidden",
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_of_opportunity_id"],
            ["opportunity.id"],
            name="fk_opportunity_duplicate",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_opportunity")),
    )
    op.create_index(
        "ix_opportunity_visible_kind",
        "opportunity",
        ["kind"],
        unique=False,
        postgresql_where=sa.text("hidden_at IS NULL"),
    )

    op.create_table(
        "organization",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("siren", sa.String(length=9), nullable=True),
        sa.Column("legal_name", sa.Text(), nullable=True),
        sa.Column("usual_name", sa.Text(), nullable=True),
        sa.Column("organization_type", sa.String(length=64), nullable=False),
        sa.Column("legal_category", sa.String(length=8), nullable=True),
        sa.Column("administrative_state", sa.String(length=16), nullable=False),
        sa.Column("diffusion_status", sa.String(length=16), nullable=False),
        sa.Column("current_observation_id", sa.Uuid(), nullable=True),
        sa.Column("administrative_state_observation_id", sa.Uuid(), nullable=True),
        sa.Column("diffusion_status_observation_id", sa.Uuid(), nullable=True),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "siren IS NULL OR siren ~ '^[0-9]{9}$'",
            name="ck_organization_siren",
        ),
        sa.CheckConstraint(
            "administrative_state IN ('ACTIVE', 'CEASED', 'UNKNOWN')",
            name="ck_organization_administrative_state",
        ),
        sa.CheckConstraint(
            "diffusion_status IN ('FULL', 'PARTIAL', 'UNKNOWN')",
            name="ck_organization_diffusion_status",
        ),
        sa.ForeignKeyConstraint(
            ["current_observation_id"],
            ["source_observation.id"],
            name="fk_organization_current_observation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["administrative_state_observation_id"],
            ["source_observation.id"],
            name="fk_organization_administrative_observation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["diffusion_status_observation_id"],
            ["source_observation.id"],
            name="fk_organization_diffusion_observation",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization")),
        sa.UniqueConstraint("siren", name="uq_organization_siren"),
    )

    op.create_table(
        "establishment",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("siret", sa.String(length=14), nullable=True),
        sa.Column("is_head_office", sa.Boolean(), nullable=True),
        sa.Column(
            "source_names",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("activity_code", sa.String(length=16), nullable=True),
        sa.Column("activity_nomenclature", sa.String(length=64), nullable=True),
        sa.Column("activity_label", sa.Text(), nullable=True),
        sa.Column("employee_band", sa.String(length=8), nullable=True),
        sa.Column("employee_year", sa.Integer(), nullable=True),
        sa.Column("employee_scope", sa.String(length=16), nullable=False),
        sa.Column("administrative_state", sa.String(length=16), nullable=False),
        sa.Column("diffusion_status", sa.String(length=16), nullable=False),
        sa.Column("established_on", sa.Date(), nullable=True),
        sa.Column("current_period_started_on", sa.Date(), nullable=True),
        sa.Column("source_processed_at", sa.String(length=64), nullable=True),
        sa.Column("current_observation_id", sa.Uuid(), nullable=True),
        sa.Column("administrative_state_observation_id", sa.Uuid(), nullable=True),
        sa.Column("diffusion_status_observation_id", sa.Uuid(), nullable=True),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "siret IS NULL OR siret ~ '^[0-9]{14}$'",
            name="ck_establishment_siret",
        ),
        sa.CheckConstraint(
            "(activity_code IS NULL) = (activity_nomenclature IS NULL)",
            name="ck_establishment_activity_pair",
        ),
        sa.CheckConstraint(
            "employee_scope IN ('LOCAL', 'GENERAL', 'UNKNOWN')",
            name="ck_establishment_employee_scope",
        ),
        sa.CheckConstraint(
            "employee_year IS NULL OR employee_year BETWEEN 1800 AND 2200",
            name="ck_establishment_employee_year",
        ),
        sa.CheckConstraint(
            "administrative_state IN ('ACTIVE', 'CLOSED', 'UNKNOWN')",
            name="ck_establishment_administrative_state",
        ),
        sa.CheckConstraint(
            "diffusion_status IN ('FULL', 'PARTIAL', 'UNKNOWN')",
            name="ck_establishment_diffusion_status",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organization.id"],
            name="fk_establishment_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["current_observation_id"],
            ["source_observation.id"],
            name="fk_establishment_current_observation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["administrative_state_observation_id"],
            ["source_observation.id"],
            name="fk_establishment_administrative_observation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["diffusion_status_observation_id"],
            ["source_observation.id"],
            name="fk_establishment_diffusion_observation",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_establishment")),
        sa.UniqueConstraint("siret", name="uq_establishment_siret"),
    )
    op.create_index(
        "ix_establishment_activity",
        "establishment",
        ["activity_nomenclature", "activity_code"],
        unique=False,
    )
    op.create_index(
        op.f("ix_establishment_organization_id"),
        "establishment",
        ["organization_id"],
        unique=False,
    )

    op.create_table(
        "prospect",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("establishment_id", sa.Uuid(), nullable=False),
        sa.Column("source_display_name", sa.Text(), nullable=False),
        sa.Column("source_description", sa.Text(), nullable=True),
        sa.Column("source_organization_type", sa.String(length=64), nullable=False),
        sa.Column(
            "source_business_signals",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("eligibility", sa.String(length=16), nullable=False),
        sa.Column("eligibility_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("eligibility_reason", sa.String(length=64), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "eligibility IN ('ELIGIBLE', 'RESTRICTED', 'UNKNOWN')",
            name="ck_prospect_eligibility",
        ),
        sa.ForeignKeyConstraint(
            ["id"],
            ["opportunity.id"],
            name="fk_prospect_opportunity",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["establishment_id"],
            ["establishment.id"],
            name="fk_prospect_establishment",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prospect")),
        sa.UniqueConstraint("establishment_id", name="uq_prospect_establishment"),
    )

    op.create_table(
        "source_binding",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("data_source_code", sa.String(length=64), nullable=False),
        sa.Column("external_identity_id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("producer_name", sa.Text(), nullable=True),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_observation_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("consecutive_absence_count", sa.Integer(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('CURRENT', 'POTENTIALLY_STALE', 'RESTRICTED')",
            name="ck_source_binding_state",
        ),
        sa.CheckConstraint(
            "consecutive_absence_count >= 0",
            name="ck_source_binding_absence_count",
        ),
        sa.ForeignKeyConstraint(
            ["data_source_code"],
            ["data_source.code"],
            name="fk_source_binding_data_source",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["external_identity_id"],
            ["external_identity.id"],
            name="fk_source_binding_external_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunity.id"],
            name="fk_source_binding_opportunity",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["current_observation_id"],
            ["source_observation.id"],
            name="fk_source_binding_current_observation",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_binding")),
        sa.UniqueConstraint(
            "data_source_code",
            "external_identity_id",
            name="uq_source_binding_source_identity",
        ),
    )
    op.create_index(
        op.f("ix_source_binding_opportunity_id"),
        "source_binding",
        ["opportunity_id"],
        unique=False,
    )

    op.create_table(
        "location_assertion",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("layer", sa.String(length=16), nullable=False),
        sa.Column("full_address", sa.Text(), nullable=True),
        sa.Column(
            "structured_address",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("municipality_code", sa.String(length=5), nullable=True),
        sa.Column("postcode", sa.String(length=16), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("point", GeographyPoint(), nullable=True),
        sa.Column("position_origin", sa.String(length=32), nullable=False),
        sa.Column("source_crs", sa.String(length=32), nullable=True),
        sa.Column("quality_code", sa.String(length=32), nullable=True),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("precision", sa.String(length=32), nullable=False),
        sa.Column("usability", sa.String(length=32), nullable=False),
        sa.Column("address_observation_id", sa.Uuid(), nullable=True),
        sa.Column("position_observation_id", sa.Uuid(), nullable=True),
        sa.Column("dataset_release_id", sa.Uuid(), nullable=True),
        sa.Column("candidate_position_id", sa.Uuid(), nullable=True),
        sa.Column("rule_version", sa.String(length=64), nullable=False),
        sa.Column(
            "diagnostics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("layer IN ('SOURCE', 'USER')", name="ck_location_assertion_layer"),
        sa.CheckConstraint("country_code = 'FR'", name="ck_location_assertion_country"),
        sa.CheckConstraint(
            "position_origin IN ('SIRENE_DATASET', 'SIRENE_API', "
            "'GEOPLATFORM_GEOCODER', 'DATATOURISME', 'USER_CONFIRMED', 'OTHER')",
            name="ck_location_assertion_origin",
        ),
        sa.CheckConstraint(
            "precision IN ('ROOFTOP', 'ADDRESS', 'STREET', 'MUNICIPALITY', 'UNKNOWN')",
            name="ck_location_assertion_precision",
        ),
        sa.CheckConstraint(
            "usability IN ('USABLE', 'TO_VERIFY', 'MISSING')",
            name="ck_location_assertion_usability",
        ),
        sa.CheckConstraint(
            "match_score IS NULL OR (match_score >= 0 AND match_score <= 1)",
            name="ck_location_assertion_match_score",
        ),
        sa.CheckConstraint(
            "is_current OR retired_at IS NOT NULL",
            name="ck_location_assertion_retired",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunity.id"],
            name="fk_location_assertion_opportunity",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["address_observation_id"],
            ["source_observation.id"],
            name="fk_location_assertion_address_observation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["position_observation_id"],
            ["source_observation.id"],
            name="fk_location_assertion_position_observation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_release_id"],
            ["dataset_release.id"],
            name="fk_location_assertion_dataset_release",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_position_id"],
            ["candidate_position.id"],
            name="fk_location_assertion_candidate_position",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_location_assertion")),
    )
    op.create_index(
        "uq_location_assertion_current_layer",
        "location_assertion",
        ["opportunity_id", "layer"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_index(
        "ix_location_assertion_point",
        "location_assertion",
        ["point"],
        unique=False,
        postgresql_using="gist",
    )

    op.create_table(
        "field_lineage",
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("field_code", sa.String(length=64), nullable=False),
        sa.Column("source_observation_id", sa.Uuid(), nullable=False),
        sa.Column("source_path", sa.String(length=256), nullable=False),
        sa.Column("resolution_rule", sa.String(length=64), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunity.id"],
            name="fk_field_lineage_opportunity",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_observation_id"],
            ["source_observation.id"],
            name="fk_field_lineage_observation",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "opportunity_id",
            "field_code",
            name=op.f("pk_field_lineage"),
        ),
    )

    op.create_table(
        "source_sighting",
        sa.Column("source_binding_id", sa.Uuid(), nullable=False),
        sa.Column("collection_cycle_id", sa.Uuid(), nullable=False),
        sa.Column("source_observation_id", sa.Uuid(), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_binding_id"],
            ["source_binding.id"],
            name="fk_source_sighting_binding",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_cycle_id"],
            ["collection_cycle.id"],
            name="fk_source_sighting_cycle",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_observation_id"],
            ["source_observation.id"],
            name="fk_source_sighting_observation",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "source_binding_id",
            "collection_cycle_id",
            name=op.f("pk_source_sighting"),
        ),
    )

    op.add_column("external_identity", sa.Column("organization_id", sa.Uuid(), nullable=True))
    op.add_column("external_identity", sa.Column("establishment_id", sa.Uuid(), nullable=True))
    op.add_column("external_identity", sa.Column("opportunity_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_external_identity_organization",
        "external_identity",
        "organization",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_external_identity_establishment",
        "external_identity",
        "establishment",
        ["establishment_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_external_identity_opportunity",
        "external_identity",
        "opportunity",
        ["opportunity_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_external_identity_single_target",
        "external_identity",
        "num_nonnulls(organization_id, establishment_id, opportunity_id) <= 1",
    )

    op.add_column("source_observation", sa.Column("source_binding_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_source_observation_binding",
        "source_observation",
        "source_binding",
        ["source_binding_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_source_observation_source_binding_id"),
        "source_observation",
        ["source_binding_id"],
        unique=False,
    )

    op.add_column("collection_item", sa.Column("opportunity_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_collection_item_opportunity",
        "collection_item",
        "opportunity",
        ["opportunity_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_collection_item_opportunity_id"),
        "collection_item",
        ["opportunity_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove source projections while preserving the earlier staging schema."""

    op.drop_index(op.f("ix_collection_item_opportunity_id"), table_name="collection_item")
    op.drop_column("collection_item", "opportunity_id")
    op.drop_index(
        op.f("ix_source_observation_source_binding_id"),
        table_name="source_observation",
    )
    op.drop_column("source_observation", "source_binding_id")
    op.drop_constraint(
        "ck_external_identity_single_target",
        "external_identity",
        type_="check",
    )
    op.drop_column("external_identity", "opportunity_id")
    op.drop_column("external_identity", "establishment_id")
    op.drop_column("external_identity", "organization_id")
    op.drop_table("source_sighting")
    op.drop_table("field_lineage")
    op.drop_index("ix_location_assertion_point", table_name="location_assertion")
    op.drop_index("uq_location_assertion_current_layer", table_name="location_assertion")
    op.drop_table("location_assertion")
    op.drop_index(op.f("ix_source_binding_opportunity_id"), table_name="source_binding")
    op.drop_table("source_binding")
    op.drop_table("prospect")
    op.drop_index(op.f("ix_establishment_organization_id"), table_name="establishment")
    op.drop_index("ix_establishment_activity", table_name="establishment")
    op.drop_table("establishment")
    op.drop_table("organization")
    op.drop_index("ix_opportunity_visible_kind", table_name="opportunity")
    op.drop_table("opportunity")
