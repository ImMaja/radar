"""Tests for bounded selection from the monthly Sirene geolocation Parquet."""

import hashlib
import math
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import duckdb
import pytest

from radar.collections.contracts import ReservedCollection
from radar.prospects.geolocation import (
    SireneGeolocationImportError,
    SireneGeolocationImportService,
    SireneGeolocationRelease,
    SireneGeolocationReleaseSource,
    SireneGeolocationTarget,
    StagedSireneGeolocationPosition,
    normalize_sirene_geolocation_record,
)
from radar.providers.sirene_geolocation import (
    SireneGeolocationFile,
    SireneGeolocationFileError,
    SireneGeolocationRecord,
    SireneGeolocationScan,
    scan_sirene_geolocation_file,
)


def write_parquet(path: Path, rows: list[tuple[object, ...]]) -> None:
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE geolocation (
                SIRET VARCHAR,
                X DOUBLE,
                Y DOUBLE,
                QUALITE_XY VARCHAR,
                EPSG VARCHAR,
                PLG_CODE_COMMUNE VARCHAR,
                DISTANCE_PRECISION DOUBLE,
                y_latitude DOUBLE,
                x_longitude DOUBLE,
                EXTRA_COLUMN VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO geolocation VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.execute("COPY geolocation TO ? (FORMAT PARQUET)", [str(path)])


def row(
    siret: str,
    *,
    quality: str = "11",
    municipality_code: str = "40088",
) -> tuple[object, ...]:
    return (
        siret,
        372_000.0,
        6_280_000.0,
        quality,
        "2154",
        municipality_code,
        12.5,
        43.71,
        -1.05,
        "ignored",
    )


def test_scans_only_requested_sirets_in_bounded_batches(tmp_path: Path) -> None:
    path = tmp_path / "geolocation.parquet"
    write_parquet(
        path,
        [
            row("11111111111111"),
            row("22222222222222", quality="33"),
            row("33333333333333"),
            row("99999999999999"),
        ],
    )
    content = path.read_bytes()
    batches: list[tuple[SireneGeolocationRecord, ...]] = []

    summary = scan_sirene_geolocation_file(
        path,
        ("11111111111111", "22222222222222", "33333333333333", "44444444444444"),
        batches.append,
        expected_sha1=hashlib.sha1(content, usedforsecurity=False).hexdigest(),
        expected_size_bytes=len(content),
        batch_size=2,
    )

    records = [record for batch in batches for record in batch]
    assert len(batches) == 2
    assert {record.siret for record in records} == {
        "11111111111111",
        "22222222222222",
        "33333333333333",
    }
    quality_33 = next(record for record in records if record.siret == "22222222222222")
    assert quality_33.quality_code == "33"
    assert quality_33.epsg == "2154"
    assert quality_33.municipality_code == "40088"
    assert quality_33.distance_precision_meters == 12.5
    assert summary.file_size_bytes == len(content)
    assert summary.sha256 == hashlib.sha256(content).hexdigest()
    assert summary.source_row_count == 4
    assert summary.requested_siret_count == 4
    assert summary.matched_siret_count == 3
    assert summary.missing_siret_count == 1
    assert summary.emitted_batch_count == 2
    assert "EXTRA_COLUMN" in summary.columns


def test_rejects_schema_drift_before_emitting_rows(tmp_path: Path) -> None:
    path = tmp_path / "wrong-schema.parquet"
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "COPY (SELECT '11111111111111'::VARCHAR AS SIRET) TO ? (FORMAT PARQUET)",
            [str(path)],
        )
    batches: list[tuple[SireneGeolocationRecord, ...]] = []

    with pytest.raises(SireneGeolocationFileError, match="missing required columns"):
        scan_sirene_geolocation_file(path, ("11111111111111",), batches.append)

    assert batches == []


def test_rejects_a_duplicate_requested_siret_before_emitting_rows(tmp_path: Path) -> None:
    path = tmp_path / "duplicates.parquet"
    write_parquet(
        path,
        [row("11111111111111"), row("11111111111111")],
    )
    batches: list[tuple[SireneGeolocationRecord, ...]] = []

    with pytest.raises(SireneGeolocationFileError, match="duplicate requested SIRET"):
        scan_sirene_geolocation_file(path, ("11111111111111",), batches.append)

    assert batches == []


def test_rejects_wrong_identity_input_and_expected_file_evidence(tmp_path: Path) -> None:
    path = tmp_path / "valid.parquet"
    write_parquet(path, [row("11111111111111")])

    with pytest.raises(ValueError, match="14-digit"):
        scan_sirene_geolocation_file(path, ("not-a-siret",), lambda _: None)
    with pytest.raises(ValueError, match="unique"):
        scan_sirene_geolocation_file(
            path,
            ("11111111111111", "11111111111111"),
            lambda _: None,
        )
    with pytest.raises(SireneGeolocationFileError, match="size"):
        scan_sirene_geolocation_file(
            path,
            ("11111111111111",),
            lambda _: None,
            expected_size_bytes=path.stat().st_size + 1,
        )
    with pytest.raises(SireneGeolocationFileError, match="SHA-1"):
        scan_sirene_geolocation_file(
            path,
            ("11111111111111",),
            lambda _: None,
            expected_sha1="0" * 40,
        )


def test_normalizes_file_quality_without_copying_it_to_another_source() -> None:
    target = SireneGeolocationTarget(
        collection_item_id=uuid4(),
        external_identity_id=uuid4(),
        siret="11111111111111",
        municipality_code="40088",
    )
    record = SireneGeolocationRecord(
        siret=target.siret,
        lambert_x=372_000.0,
        lambert_y=6_280_000.0,
        quality_code="12",
        epsg="2154",
        municipality_code="40088",
        distance_precision_meters=math.nan,
        latitude=43.71,
        longitude=-1.05,
    )

    first = normalize_sirene_geolocation_record(target, record)
    repeated = normalize_sirene_geolocation_record(target, record)

    assert first == repeated
    assert first.quality_code == "12"
    assert first.payload["quality"] == {
        "code": "12",
        "distance_precision_meters": None,
    }
    assert first.payload["position"] == {
        "lambert_x": 372_000.0,
        "lambert_y": 6_280_000.0,
        "epsg": "2154",
        "longitude": -1.05,
        "latitude": 43.71,
    }

    mismatched = SireneGeolocationRecord(
        siret="22222222222222",
        lambert_x=None,
        lambert_y=None,
        quality_code=None,
        epsg=None,
        municipality_code=None,
        distance_precision_meters=None,
        latitude=None,
        longitude=None,
    )
    with pytest.raises(SireneGeolocationImportError, match="identity"):
        normalize_sirene_geolocation_record(target, mismatched)


class FailingStagingBackend:
    def __init__(self, target: SireneGeolocationTarget) -> None:
        self.target = target
        self.failed_codes: list[str] = []

    def targets(self, _reservation: ReservedCollection) -> tuple[SireneGeolocationTarget, ...]:
        return (self.target,)

    def prepare_release(
        self,
        _reservation: ReservedCollection,
        _source: SireneGeolocationReleaseSource,
        _file: SireneGeolocationFile,
        _now: datetime,
    ) -> SireneGeolocationRelease:
        return SireneGeolocationRelease(
            id=uuid4(),
            source_run_id=uuid4(),
            status="RUNNING",
            newly_created=True,
        )

    def stage_positions(
        self,
        _reservation: ReservedCollection,
        _release: SireneGeolocationRelease,
        _positions: tuple[StagedSireneGeolocationPosition, ...],
        _now: datetime,
    ) -> None:
        raise SireneGeolocationImportError("controlled staging failure")

    def complete_release(
        self,
        _reservation: ReservedCollection,
        _release: SireneGeolocationRelease,
        _scan: SireneGeolocationScan,
        _now: datetime,
    ) -> None:
        raise AssertionError("a failed stage cannot complete")

    def completed_scan(
        self,
        _reservation: ReservedCollection,
        _release: SireneGeolocationRelease,
    ) -> SireneGeolocationScan:
        raise AssertionError("a running stage is not complete")

    def fail_release(
        self,
        _reservation: ReservedCollection,
        _release: SireneGeolocationRelease,
        *,
        code: str,
        now: datetime,
    ) -> None:
        assert now.tzinfo is not None
        self.failed_codes.append(code)


def test_import_service_marks_a_partially_staged_release_failed(tmp_path: Path) -> None:
    path = tmp_path / "failure.parquet"
    write_parquet(path, [row("11111111111111")])
    target = SireneGeolocationTarget(
        collection_item_id=uuid4(),
        external_identity_id=uuid4(),
        siret="11111111111111",
        municipality_code="40088",
    )
    backend = FailingStagingBackend(target)
    now = datetime(2026, 9, 21, 18, tzinfo=UTC)
    service = SireneGeolocationImportService(backend, clock=lambda: now)
    reservation = ReservedCollection(
        job_id=uuid4(),
        cycle_id=uuid4(),
        attempt_id=uuid4(),
        attempt_number=1,
        max_attempts=3,
        connector="SIRENE",
        longitude=-1.05,
        latitude=43.71,
        collection_radius_meters=50_000,
        last_safe_checkpoint=None,
    )
    source = SireneGeolocationReleaseSource(
        resource_identifier="fixture",
        resource_url="https://example.data.gouv.fr/geolocation.parquet",
        published_on=None,
        retrieved_at=now,
        license_name="Licence Ouverte 2.0",
    )

    with pytest.raises(SireneGeolocationImportError, match="controlled"):
        service.import_file(reservation, path, source)

    assert backend.failed_codes == ["sirene_geolocation_import_failed"]
