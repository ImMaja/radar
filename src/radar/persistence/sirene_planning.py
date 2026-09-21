"""PostgreSQL persistence for immutable Sirene municipality plans."""

import hashlib
from collections.abc import Sequence
from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, text
from sqlalchemy.exc import SQLAlchemyError

from radar.collections.contracts import ReservedCollection
from radar.prospects.planning import (
    SireneCollectionPlan,
    SireneMunicipalityBatch,
    SirenePlanningError,
)
from radar.reference_data.contracts import MunicipalitySelection

SELECTION_REASON = "INTERSECTS_EXPANDED_COLLECTION_CIRCLE"


def _batch_key(order_number: int, codes: Sequence[str]) -> str:
    digest = hashlib.sha256(",".join(codes).encode("ascii")).hexdigest()[:16]
    return f"municipalities:{order_number:04d}:{digest}"


def _plan_from_rows(
    release: RowMapping,
    rows: Sequence[RowMapping],
    *,
    newly_created: bool,
) -> SireneCollectionPlan:
    batches = tuple(
        SireneMunicipalityBatch(
            id=cast(UUID, row["batch_id"]),
            key=cast(str, row["batch_key"]),
            order_number=cast(int, row["order_number"]),
            municipality_codes=tuple(cast(Sequence[str], row["municipality_codes"])),
            state=cast(str, row["state"]),
        )
        for row in rows
    )
    return SireneCollectionPlan(
        cycle_id=cast(UUID, release["collection_cycle_id"]),
        source_run_id=cast(UUID, release["source_run_id"]),
        dataset_release_id=cast(UUID, release["dataset_release_id"]),
        resource_identifier=cast(str, release["resource_identifier"]),
        margin_meters=cast(int, release["selection_margin_meters"]),
        municipality_count=sum(len(batch.municipality_codes) for batch in batches),
        batches=batches,
        newly_created=newly_created,
    )


class SqlAlchemySirenePlanRepository:
    """Persist the selected release and disjoint batches once per cycle."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get(self, cycle_id: UUID) -> SireneCollectionPlan | None:
        """Load an existing plan without consulting the active reference release."""

        with self._engine.connect() as connection:
            return self._load(connection, cycle_id, newly_created=False)

    def create(
        self,
        reservation: ReservedCollection,
        selection: MunicipalitySelection,
        batches: tuple[tuple[str, ...], ...],
        contract_version: str,
        now: datetime,
    ) -> SireneCollectionPlan:
        """Atomically bind one running cycle to its release, communes and batches."""

        self._validate_plan(reservation, selection, batches)
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:cycle_id, 0))"),
                    {"cycle_id": str(reservation.cycle_id)},
                )
                existing = self._load(connection, reservation.cycle_id, newly_created=False)
                if existing is not None:
                    return existing

                active_attempt = connection.execute(
                    text(
                        """
                        SELECT job.id
                        FROM collection_job AS job
                        JOIN collection_cycle AS cycle ON cycle.id = job.cycle_id
                        JOIN collection_attempt AS attempt
                            ON attempt.collection_job_id = job.id
                        WHERE cycle.id = :cycle_id
                          AND cycle.connector = 'SIRENE'
                          AND job.id = :job_id
                          AND job.state = 'RUNNING'
                          AND attempt.id = :attempt_id
                          AND attempt.finished_at IS NULL
                        FOR UPDATE OF job
                        """
                    ),
                    {
                        "cycle_id": reservation.cycle_id,
                        "job_id": reservation.job_id,
                        "attempt_id": reservation.attempt_id,
                    },
                ).scalar_one_or_none()
                if active_attempt is None:
                    raise SirenePlanningError(
                        "the Sirene plan requires the cycle's active reservation"
                    )

                connection.execute(
                    text(
                        """
                        INSERT INTO collection_reference_usage (
                            collection_cycle_id, dataset_release_id, role, used_at
                        ) VALUES (
                            :cycle_id, :dataset_release_id, 'MUNICIPALITY_BOUNDARIES', :used_at
                        )
                        """
                    ),
                    {
                        "cycle_id": reservation.cycle_id,
                        "dataset_release_id": selection.dataset_release_id,
                        "used_at": now,
                    },
                )
                source_run_id = uuid4()
                connection.execute(
                    text(
                        """
                        INSERT INTO collection_source_run (
                            id,
                            collection_cycle_id,
                            source,
                            dataset_release_id,
                            status,
                            counters,
                            metadata,
                            request_count,
                            retry_count,
                            error_count,
                            contract_version,
                            created_at,
                            updated_at
                        ) VALUES (
                            :id,
                            :cycle_id,
                            'SIRENE_API',
                            NULL,
                            'PLANNED',
                            '{}'::jsonb,
                            '{}'::jsonb,
                            0,
                            0,
                            0,
                            :contract_version,
                            :created_at,
                            :updated_at
                        )
                        """
                    ),
                    {
                        "id": source_run_id,
                        "cycle_id": reservation.cycle_id,
                        "contract_version": contract_version,
                        "created_at": now,
                        "updated_at": now,
                    },
                )

                municipalities_by_code = {
                    municipality.code: municipality for municipality in selection.municipalities
                }
                for order_number, codes in enumerate(batches, start=1):
                    batch_id = uuid4()
                    connection.execute(
                        text(
                            """
                            INSERT INTO collection_batch (
                                id,
                                collection_cycle_id,
                                source_run_id,
                                batch_type,
                                batch_key,
                                order_number,
                                state,
                                attempt_count,
                                resume_state,
                                processing_counts,
                                created_at,
                                updated_at
                            ) VALUES (
                                :id,
                                :cycle_id,
                                :source_run_id,
                                'SIRENE_MUNICIPALITIES',
                                :batch_key,
                                :order_number,
                                'WAITING',
                                0,
                                '{}'::jsonb,
                                '{}'::jsonb,
                                :created_at,
                                :updated_at
                            )
                            """
                        ),
                        {
                            "id": batch_id,
                            "cycle_id": reservation.cycle_id,
                            "source_run_id": source_run_id,
                            "batch_key": _batch_key(order_number, codes),
                            "order_number": order_number,
                            "created_at": now,
                            "updated_at": now,
                        },
                    )
                    connection.execute(
                        text(
                            """
                            INSERT INTO collection_cycle_commune (
                                collection_cycle_id,
                                dataset_release_id,
                                municipality_code,
                                collection_batch_id,
                                selection_reason,
                                selection_margin_meters,
                                state,
                                created_at,
                                updated_at
                            ) VALUES (
                                :cycle_id,
                                :dataset_release_id,
                                :municipality_code,
                                :batch_id,
                                :selection_reason,
                                :selection_margin_meters,
                                'WAITING',
                                :created_at,
                                :updated_at
                            )
                            """
                        ),
                        [
                            {
                                "cycle_id": reservation.cycle_id,
                                "dataset_release_id": selection.dataset_release_id,
                                "municipality_code": municipalities_by_code[code].code,
                                "batch_id": batch_id,
                                "selection_reason": SELECTION_REASON,
                                "selection_margin_meters": selection.margin_meters,
                                "created_at": now,
                                "updated_at": now,
                            }
                            for code in codes
                        ],
                    )

                created = self._load(connection, reservation.cycle_id, newly_created=True)
                if created is None:
                    raise SirenePlanningError("the persisted Sirene plan cannot be reloaded")
                return created
        except SirenePlanningError:
            raise
        except SQLAlchemyError as error:
            raise SirenePlanningError("cannot persist the Sirene collection plan") from error

    def _load(
        self,
        connection: Connection,
        cycle_id: UUID,
        *,
        newly_created: bool,
    ) -> SireneCollectionPlan | None:
        release = (
            connection.execute(
                text(
                    """
                    SELECT
                        usage.collection_cycle_id,
                        usage.dataset_release_id,
                        release.resource_identifier,
                        source_run.id AS source_run_id,
                        min(commune.selection_margin_meters) AS selection_margin_meters,
                        max(commune.selection_margin_meters) AS maximum_margin_meters
                    FROM collection_reference_usage AS usage
                    JOIN dataset_release AS release ON release.id = usage.dataset_release_id
                    JOIN collection_source_run AS source_run
                        ON source_run.collection_cycle_id = usage.collection_cycle_id
                       AND source_run.source = 'SIRENE_API'
                    JOIN collection_cycle_commune AS commune
                        ON commune.collection_cycle_id = usage.collection_cycle_id
                       AND commune.dataset_release_id = usage.dataset_release_id
                    WHERE usage.collection_cycle_id = :cycle_id
                      AND usage.role = 'MUNICIPALITY_BOUNDARIES'
                    GROUP BY
                        usage.collection_cycle_id,
                        usage.dataset_release_id,
                        release.resource_identifier,
                        source_run.id
                    """
                ),
                {"cycle_id": cycle_id},
            )
            .mappings()
            .one_or_none()
        )
        if release is None:
            return None
        if release["selection_margin_meters"] != release["maximum_margin_meters"]:
            raise SirenePlanningError("a persisted Sirene plan contains inconsistent margins")
        rows = (
            connection.execute(
                text(
                    """
                    SELECT
                        batch.id AS batch_id,
                        batch.batch_key,
                        batch.order_number,
                        batch.state,
                        array_agg(commune.municipality_code ORDER BY commune.municipality_code)
                            AS municipality_codes
                    FROM collection_batch AS batch
                    JOIN collection_cycle_commune AS commune
                        ON commune.collection_batch_id = batch.id
                    WHERE batch.collection_cycle_id = :cycle_id
                      AND batch.batch_type = 'SIRENE_MUNICIPALITIES'
                    GROUP BY batch.id
                    ORDER BY batch.order_number
                    """
                ),
                {"cycle_id": cycle_id},
            )
            .mappings()
            .all()
        )
        if not rows:
            raise SirenePlanningError("a persisted Sirene plan has no municipality batch")
        return _plan_from_rows(release, rows, newly_created=newly_created)

    @staticmethod
    def _validate_plan(
        reservation: ReservedCollection,
        selection: MunicipalitySelection,
        batches: tuple[tuple[str, ...], ...],
    ) -> None:
        selected_codes = tuple(municipality.code for municipality in selection.municipalities)
        flattened_codes = tuple(code for batch in batches for code in batch)
        if selection.collection_radius_meters != reservation.collection_radius_meters:
            raise SirenePlanningError("selection radius differs from the collection cycle")
        if len(set(selected_codes)) != len(selected_codes):
            raise SirenePlanningError("the municipality selection contains duplicates")
        if flattened_codes != selected_codes:
            raise SirenePlanningError("Sirene batches do not exactly preserve the selection")
        if not batches or any(not batch or len(batch) > 30 for batch in batches):
            raise SirenePlanningError("Sirene batches must contain between 1 and 30 communes")
