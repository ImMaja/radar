"""Tests for the bounded official municipality GeoJSON reader."""

import gzip
import hashlib
import json
from pathlib import Path

import pytest

from radar.providers.administrative_boundaries import read_municipality_file
from radar.reference_data.contracts import MunicipalityFileError


def polygon(longitude: float, latitude: float) -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [longitude - 0.01, latitude - 0.01],
                [longitude + 0.01, latitude - 0.01],
                [longitude + 0.01, latitude + 0.01],
                [longitude - 0.01, latitude + 0.01],
                [longitude - 0.01, latitude - 0.01],
            ]
        ],
    }


def feature(code: str, name: str, geometry: dict[str, object]) -> dict[str, object]:
    return {
        "type": "Feature",
        "properties": {"code": code, "nom": name},
        "geometry": geometry,
    }


def write_geojson(path: Path, features: list[dict[str, object]], *, compressed: bool) -> bytes:
    payload = json.dumps(
        {"type": "FeatureCollection", "features": features},
        separators=(",", ":"),
    ).encode()
    content = gzip.compress(payload, mtime=0) if compressed else payload
    path.write_bytes(content)
    return content


def test_reads_compressed_file_fingerprints_source_and_excludes_overseas(tmp_path: Path) -> None:
    path = tmp_path / "communes-100m.geojson.gz"
    content = write_geojson(
        path,
        [
            feature("40088", "Dax", polygon(-1.052, 43.709)),
            feature(
                "2A004",
                "Ajaccio",
                {
                    "type": "MultiPolygon",
                    "coordinates": [polygon(8.74, 41.92)["coordinates"]],
                },
            ),
            feature("97105", "Basse-Terre", polygon(-61.73, 15.99)),
        ],
        compressed=True,
    )
    expected_digest = hashlib.sha256(content).hexdigest()

    parsed = read_municipality_file(
        path,
        expected_sha256=expected_digest.upper(),
        expected_size_bytes=len(content),
    )

    assert parsed.sha256 == expected_digest
    assert parsed.source_feature_count == 3
    assert parsed.ignored_non_metropolitan_count == 1
    assert [boundary.code for boundary in parsed.boundaries] == ["2A004", "40088"]
    assert parsed.geometry_counts == {"MultiPolygon": 1, "Polygon": 2}


def test_rejects_duplicate_codes_and_an_unexpected_fingerprint(tmp_path: Path) -> None:
    path = tmp_path / "communes.geojson"
    write_geojson(
        path,
        [
            feature("40088", "Dax", polygon(-1.052, 43.709)),
            feature("40088", "Dax bis", polygon(-1.051, 43.708)),
        ],
        compressed=False,
    )

    with pytest.raises(MunicipalityFileError, match="SHA-256"):
        read_municipality_file(path, expected_sha256="0" * 64)
    with pytest.raises(MunicipalityFileError, match="occurs more than once"):
        read_municipality_file(path)


def test_rejects_a_non_polygon_geometry(tmp_path: Path) -> None:
    path = tmp_path / "communes.geojson"
    write_geojson(
        path,
        [
            feature(
                "40088",
                "Dax",
                {"type": "Point", "coordinates": [-1.052, 43.709]},
            )
        ],
        compressed=False,
    )

    with pytest.raises(MunicipalityFileError, match="unsupported geometry"):
        read_municipality_file(path)
