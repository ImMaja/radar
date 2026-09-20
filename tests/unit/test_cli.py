"""Tests for the non-secret administrative command surface."""

import pytest

from radar.cli import parser


def test_account_creation_has_no_password_argument() -> None:
    with pytest.raises(SystemExit):
        parser().parse_args(["create-account", "--password", "not-accepted"])


def test_municipality_import_exposes_only_non_secret_provenance_arguments() -> None:
    parsed = parser().parse_args(
        [
            "import-municipalities",
            "communes.geojson.gz",
            "--resource-identifier",
            "2026",
            "--resource-url",
            "https://example.data.gouv.fr/communes.geojson.gz",
        ]
    )

    assert parsed.command == "import-municipalities"
    assert parsed.resource_identifier == "2026"
    assert not hasattr(parsed, "password")
