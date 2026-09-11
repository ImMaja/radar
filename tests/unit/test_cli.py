"""Tests for the non-secret administrative command surface."""

import pytest

from radar.cli import parser


def test_account_creation_has_no_password_argument() -> None:
    with pytest.raises(SystemExit):
        parser().parse_args(["create-account", "--password", "not-accepted"])
