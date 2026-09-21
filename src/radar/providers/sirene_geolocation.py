"""Bounded reader for the official monthly Sirene geolocation Parquet file."""

import hashlib
import re
import stat
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import duckdb

MAX_FILE_SIZE_BYTES = 2_000_000_000
DEFAULT_BATCH_SIZE = 5_000
MAX_BATCH_SIZE = 100_000

REQUIRED_COLUMNS = frozenset(
    {
        "SIRET",
        "X",
        "Y",
        "QUALITE_XY",
        "EPSG",
        "PLG_CODE_COMMUNE",
        "DISTANCE_PRECISION",
        "y_latitude",
        "x_longitude",
    }
)
TEXT_COLUMNS = frozenset({"SIRET", "QUALITE_XY", "EPSG", "PLG_CODE_COMMUNE"})
NUMERIC_COLUMNS = REQUIRED_COLUMNS - TEXT_COLUMNS

_SIRET = re.compile(r"^[0-9]{14}$")
_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_NUMERIC_DUCKDB_TYPES = (
    "BIGINT",
    "DECIMAL",
    "DOUBLE",
    "FLOAT",
    "HUGEINT",
    "INTEGER",
    "REAL",
    "SMALLINT",
    "TINYINT",
    "UBIGINT",
    "UHUGEINT",
    "UINTEGER",
    "USMALLINT",
    "UTINYINT",
)


class SireneGeolocationFileError(RuntimeError):
    """The monthly geolocation file cannot be used without risking bad positions."""


@dataclass(frozen=True)
class SireneGeolocationRecord:
    """One source row selected by SIRET, before geographic business rules."""

    siret: str
    lambert_x: float | None
    lambert_y: float | None
    quality_code: str | None
    epsg: str | None
    municipality_code: str | None
    distance_precision_meters: float | None
    latitude: float | None
    longitude: float | None


@dataclass(frozen=True)
class SireneGeolocationFile:
    """Validated immutable file evidence reusable by a candidate scan."""

    path: Path
    file_size_bytes: int
    sha1: str
    sha256: str
    source_row_count: int
    columns: tuple[str, ...]
    device: int
    inode: int
    modified_at_ns: int


@dataclass(frozen=True)
class SireneGeolocationScan:
    """Reconciled evidence for one local Parquet scan."""

    file_size_bytes: int
    sha1: str
    sha256: str
    source_row_count: int
    requested_siret_count: int
    matched_siret_count: int
    missing_siret_count: int
    emitted_batch_count: int
    columns: tuple[str, ...]


def _validate_targets(target_sirets: Collection[str]) -> tuple[str, ...]:
    targets = tuple(target_sirets)
    if any(_SIRET.fullmatch(siret) is None for siret in targets):
        raise ValueError("Sirene geolocation targets must be 14-digit SIRETs")
    if len(set(targets)) != len(targets):
        raise ValueError("Sirene geolocation targets must be unique")
    return targets


def _validate_expected_values(
    *,
    expected_sha1: str | None,
    expected_size_bytes: int | None,
    batch_size: int,
) -> str | None:
    if expected_sha1 is not None:
        normalized_sha1 = expected_sha1.lower()
        if _SHA1.fullmatch(normalized_sha1) is None:
            raise ValueError("expected SHA-1 must contain 40 hexadecimal characters")
    else:
        normalized_sha1 = None
    if expected_size_bytes is not None and expected_size_bytes < 1:
        raise ValueError("expected geolocation file size must be positive")
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError("geolocation batch size is outside the safety bounds")
    return normalized_sha1


def _fingerprints(path: Path) -> tuple[int, str, str, int, int, int]:
    try:
        file_stat = path.stat()
        if not stat.S_ISREG(file_stat.st_mode):
            raise SireneGeolocationFileError("Sirene geolocation path is not a regular file")
        if file_stat.st_size < 1:
            raise SireneGeolocationFileError("Sirene geolocation file is empty")
        if file_stat.st_size > MAX_FILE_SIZE_BYTES:
            raise SireneGeolocationFileError("Sirene geolocation file exceeds the safety limit")

        sha1 = hashlib.sha1(usedforsecurity=False)
        sha256 = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(8 * 1024 * 1024):
                sha1.update(chunk)
                sha256.update(chunk)
    except SireneGeolocationFileError:
        raise
    except OSError as error:
        raise SireneGeolocationFileError("cannot read Sirene geolocation file") from error
    return (
        file_stat.st_size,
        sha1.hexdigest(),
        sha256.hexdigest(),
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_mtime_ns,
    )


def _schema(connection: duckdb.DuckDBPyConnection, path: Path) -> dict[str, str]:
    rows = connection.execute(
        "DESCRIBE SELECT * FROM read_parquet(?)",
        [str(path)],
    ).fetchall()
    schema = {cast(str, row[0]): cast(str, row[1]).upper() for row in rows}
    missing = REQUIRED_COLUMNS - schema.keys()
    if missing:
        raise SireneGeolocationFileError(
            "Sirene geolocation schema is missing required columns: "
            + ", ".join(sorted(missing))
        )
    invalid_text = sorted(
        column for column in TEXT_COLUMNS if not schema[column].startswith("VARCHAR")
    )
    invalid_numeric = sorted(
        column
        for column in NUMERIC_COLUMNS
        if not schema[column].startswith(_NUMERIC_DUCKDB_TYPES)
    )
    if invalid_text or invalid_numeric:
        invalid = ", ".join(invalid_text + invalid_numeric)
        raise SireneGeolocationFileError(
            f"Sirene geolocation columns have unexpected types: {invalid}"
        )
    return schema


def _record(row: Sequence[object]) -> SireneGeolocationRecord:
    return SireneGeolocationRecord(
        siret=cast(str, row[0]),
        lambert_x=cast(float | None, row[1]),
        lambert_y=cast(float | None, row[2]),
        quality_code=cast(str | None, row[3]),
        epsg=cast(str | None, row[4]),
        municipality_code=cast(str | None, row[5]),
        distance_precision_meters=cast(float | None, row[6]),
        latitude=cast(float | None, row[7]),
        longitude=cast(float | None, row[8]),
    )


def inspect_sirene_geolocation_file(
    path: Path,
    *,
    expected_sha1: str | None = None,
    expected_size_bytes: int | None = None,
) -> SireneGeolocationFile:
    """Fingerprint and validate one local monthly Parquet before staging data."""

    normalized_sha1 = _validate_expected_values(
        expected_sha1=expected_sha1,
        expected_size_bytes=expected_size_bytes,
        batch_size=DEFAULT_BATCH_SIZE,
    )
    file_size, actual_sha1, actual_sha256, device, inode, modified_at_ns = _fingerprints(path)
    if expected_size_bytes is not None and file_size != expected_size_bytes:
        raise SireneGeolocationFileError(
            "Sirene geolocation file size does not match the expected value"
        )
    if normalized_sha1 is not None and actual_sha1 != normalized_sha1:
        raise SireneGeolocationFileError(
            "Sirene geolocation file SHA-1 does not match the expected value"
        )

    try:
        with duckdb.connect(":memory:") as connection:
            connection.execute("SET threads = 2")
            connection.execute("SET preserve_insertion_order = false")
            schema = _schema(connection, path)
            count_row = connection.execute(
                "SELECT count(*) FROM read_parquet(?)",
                [str(path)],
            ).fetchone()
            if count_row is None:
                raise SireneGeolocationFileError(
                    "Sirene geolocation file row count is unavailable"
                )
            source_row_count = cast(int, count_row[0])
            if source_row_count < 1:
                raise SireneGeolocationFileError("Sirene geolocation file has no rows")
    except SireneGeolocationFileError:
        raise
    except duckdb.Error as error:
        raise SireneGeolocationFileError(
            "cannot inspect the Sirene geolocation Parquet file"
        ) from error

    return SireneGeolocationFile(
        path=path,
        file_size_bytes=file_size,
        sha1=actual_sha1,
        sha256=actual_sha256,
        source_row_count=source_row_count,
        columns=tuple(schema),
        device=device,
        inode=inode,
        modified_at_ns=modified_at_ns,
    )


def _ensure_file_unchanged(file: SireneGeolocationFile) -> None:
    try:
        file_stat = file.path.stat()
    except OSError as error:
        raise SireneGeolocationFileError(
            "Sirene geolocation file disappeared during its scan"
        ) from error
    identity = (file_stat.st_size, file_stat.st_dev, file_stat.st_ino, file_stat.st_mtime_ns)
    expected = (file.file_size_bytes, file.device, file.inode, file.modified_at_ns)
    if identity != expected:
        raise SireneGeolocationFileError(
            "Sirene geolocation file changed during its scan"
        )


def scan_sirene_geolocation_file(
    path: Path,
    target_sirets: Collection[str],
    on_batch: Callable[[tuple[SireneGeolocationRecord, ...]], None],
    *,
    expected_sha1: str | None = None,
    expected_size_bytes: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    inspected_file: SireneGeolocationFile | None = None,
) -> SireneGeolocationScan:
    """Validate one Parquet and emit only requested SIRETs in bounded batches."""

    targets = _validate_targets(target_sirets)
    _validate_expected_values(
        expected_sha1=expected_sha1,
        expected_size_bytes=expected_size_bytes,
        batch_size=batch_size,
    )
    if inspected_file is not None and inspected_file.path != path:
        raise ValueError("inspected Sirene geolocation evidence belongs to another path")
    file = inspected_file or inspect_sirene_geolocation_file(
        path,
        expected_sha1=expected_sha1,
        expected_size_bytes=expected_size_bytes,
    )
    _ensure_file_unchanged(file)

    try:
        with duckdb.connect(":memory:") as connection:
            connection.execute("SET threads = 2")
            connection.execute("SET preserve_insertion_order = false")
            if not targets:
                return SireneGeolocationScan(
                    file_size_bytes=file.file_size_bytes,
                    sha1=file.sha1,
                    sha256=file.sha256,
                    source_row_count=file.source_row_count,
                    requested_siret_count=0,
                    matched_siret_count=0,
                    missing_siret_count=0,
                    emitted_batch_count=0,
                    columns=file.columns,
                )

            connection.execute(
                "CREATE TEMP TABLE target_siret AS SELECT unnest(?)::VARCHAR AS siret",
                [list(targets)],
            )
            connection.execute("CREATE UNIQUE INDEX target_siret_pk ON target_siret(siret)")
            duplicate = connection.execute(
                """
                SELECT source.SIRET
                FROM read_parquet(?) AS source
                JOIN target_siret AS target ON target.siret = source.SIRET
                GROUP BY source.SIRET
                HAVING count(*) > 1
                LIMIT 1
                """,
                [str(path)],
            ).fetchone()
            if duplicate is not None:
                raise SireneGeolocationFileError(
                    "Sirene geolocation file contains a duplicate requested SIRET"
                )

            result = connection.execute(
                """
                SELECT
                    source.SIRET,
                    try_cast(source.X AS DOUBLE),
                    try_cast(source.Y AS DOUBLE),
                    nullif(trim(source.QUALITE_XY), ''),
                    nullif(trim(source.EPSG), ''),
                    nullif(trim(source.PLG_CODE_COMMUNE), ''),
                    try_cast(source.DISTANCE_PRECISION AS DOUBLE),
                    try_cast(source.y_latitude AS DOUBLE),
                    try_cast(source.x_longitude AS DOUBLE)
                FROM read_parquet(?) AS source
                JOIN target_siret AS target ON target.siret = source.SIRET
                """,
                [str(path)],
            )
            matched_count = 0
            emitted_batch_count = 0
            while rows := result.fetchmany(batch_size):
                records = tuple(_record(row) for row in rows)
                on_batch(records)
                matched_count += len(records)
                emitted_batch_count += 1
    except SireneGeolocationFileError:
        raise
    except duckdb.Error as error:
        raise SireneGeolocationFileError(
            "cannot inspect the Sirene geolocation Parquet file"
        ) from error

    _ensure_file_unchanged(file)

    return SireneGeolocationScan(
        file_size_bytes=file.file_size_bytes,
        sha1=file.sha1,
        sha256=file.sha256,
        source_row_count=file.source_row_count,
        requested_siret_count=len(targets),
        matched_siret_count=matched_count,
        missing_siret_count=len(targets) - matched_count,
        emitted_batch_count=emitted_batch_count,
        columns=file.columns,
    )
