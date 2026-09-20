"""Reader for the official compressed GeoJSON municipality reference."""

import gzip
import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from radar.reference_data.contracts import (
    MunicipalityBoundary,
    MunicipalityBoundaryFile,
    MunicipalityFileError,
)

MAX_COMPRESSED_BYTES = 32_000_000
MAX_UNCOMPRESSED_BYTES = 100_000_000
MAX_FEATURES = 100_000

_MUNICIPALITY_CODE = re.compile(r"^(?:(?:0[1-9]|[1-8][0-9]|9[0-5])\d{3}|2[AB]\d{3})$")
_ANY_FRENCH_CODE = re.compile(r"^(?:\d{5}|2[AB]\d{3})$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _read_limited(path: Path) -> tuple[bytes, bytes]:
    try:
        compressed = path.read_bytes()
    except OSError as error:
        raise MunicipalityFileError(f"cannot read municipality file: {error}") from error
    if not compressed:
        raise MunicipalityFileError("municipality file is empty")
    if len(compressed) > MAX_COMPRESSED_BYTES:
        raise MunicipalityFileError("compressed municipality file exceeds the safety limit")

    try:
        content = gzip.decompress(compressed) if compressed.startswith(b"\x1f\x8b") else compressed
    except (gzip.BadGzipFile, EOFError, OSError) as error:
        raise MunicipalityFileError("municipality gzip file is invalid") from error
    if len(content) > MAX_UNCOMPRESSED_BYTES:
        raise MunicipalityFileError("uncompressed municipality file exceeds the safety limit")
    return compressed, content


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise MunicipalityFileError(f"{label} must be an object")
    return cast(Mapping[str, object], value)


def _required_text(data: Mapping[str, object], key: str, label: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MunicipalityFileError(f"{label}.{key} must be a non-empty string")
    return value.strip()


def _reject_non_standard_constant(value: str) -> object:
    raise MunicipalityFileError(f"municipality file contains non-standard number {value}")


def read_municipality_file(
    path: Path,
    *,
    expected_sha256: str | None = None,
    expected_size_bytes: int | None = None,
) -> MunicipalityBoundaryFile:
    """Read, fingerprint and validate one plain or gzip-compressed GeoJSON file."""

    compressed, content = _read_limited(path)
    digest = hashlib.sha256(compressed).hexdigest()
    if expected_sha256 is not None:
        normalized_digest = expected_sha256.lower()
        if _SHA256.fullmatch(normalized_digest) is None:
            raise MunicipalityFileError("expected SHA-256 must contain 64 hexadecimal characters")
        if digest != normalized_digest:
            raise MunicipalityFileError(
                "municipality file SHA-256 does not match the expected value"
            )
    if expected_size_bytes is not None and len(compressed) != expected_size_bytes:
        raise MunicipalityFileError("municipality file size does not match the expected value")

    try:
        document = json.loads(content, parse_constant=_reject_non_standard_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MunicipalityFileError("municipality file is not valid UTF-8 GeoJSON") from error
    root = _mapping(document, "GeoJSON root")
    if root.get("type") != "FeatureCollection":
        raise MunicipalityFileError("municipality GeoJSON root must be a FeatureCollection")
    raw_features = root.get("features")
    if not isinstance(raw_features, list) or not raw_features:
        raise MunicipalityFileError("municipality GeoJSON must contain features")
    if len(raw_features) > MAX_FEATURES:
        raise MunicipalityFileError("municipality GeoJSON exceeds the feature safety limit")

    seen_codes: set[str] = set()
    boundaries: list[MunicipalityBoundary] = []
    geometry_counts: Counter[str] = Counter()
    ignored_count = 0
    for index, raw_feature in enumerate(raw_features):
        feature = _mapping(raw_feature, f"feature {index}")
        if feature.get("type") != "Feature":
            raise MunicipalityFileError(f"feature {index} has an invalid type")
        properties = _mapping(feature.get("properties"), f"feature {index}.properties")
        code = _required_text(properties, "code", f"feature {index}.properties")
        name = _required_text(properties, "nom", f"feature {index}.properties")
        if _ANY_FRENCH_CODE.fullmatch(code) is None:
            raise MunicipalityFileError(f"feature {index} has an invalid municipality code")
        if code in seen_codes:
            raise MunicipalityFileError(f"municipality code {code} occurs more than once")
        seen_codes.add(code)

        geometry = _mapping(feature.get("geometry"), f"feature {index}.geometry")
        geometry_type = geometry.get("type")
        if geometry_type not in {"Polygon", "MultiPolygon"}:
            raise MunicipalityFileError(f"feature {index} has an unsupported geometry type")
        if not isinstance(geometry.get("coordinates"), list):
            raise MunicipalityFileError(f"feature {index} geometry has no coordinate array")
        geometry_counts[geometry_type] += 1

        if _MUNICIPALITY_CODE.fullmatch(code) is None:
            ignored_count += 1
            continue
        boundaries.append(
            MunicipalityBoundary(
                code=code,
                official_name=name,
                geometry_json=json.dumps(geometry, ensure_ascii=False, separators=(",", ":")),
            )
        )

    if not boundaries:
        raise MunicipalityFileError("municipality GeoJSON contains no metropolitan municipality")
    boundaries.sort(key=lambda boundary: boundary.code)
    return MunicipalityBoundaryFile(
        path=path,
        file_size_bytes=len(compressed),
        sha256=digest,
        source_feature_count=len(raw_features),
        ignored_non_metropolitan_count=ignored_count,
        geometry_counts=dict(sorted(geometry_counts.items())),
        boundaries=tuple(boundaries),
    )
