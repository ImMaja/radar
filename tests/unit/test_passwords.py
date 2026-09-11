"""Tests for password policy and Argon2id storage."""

import pytest

from radar.auth.contracts import PasswordPolicyError
from radar.auth.passwords import PasswordManager


def test_password_hash_uses_the_documented_argon2id_minimum() -> None:
    manager = PasswordManager()
    password = "une phrase secrète assez longue"

    password_hash = manager.hash(password)

    assert password not in password_hash
    assert password_hash.startswith("$argon2id$v=19$m=19456,t=2,p=1$")
    assert manager.verify(password_hash, password) is True
    assert manager.verify(password_hash, "mot de passe incorrect") is False


@pytest.mark.parametrize(
    ("password", "confirmation"),
    [
        ("trop court", "trop court"),
        ("a" * 129, "a" * 129),
        ("une phrase secrète valide", "confirmation différente"),
    ],
)
def test_new_password_policy_rejects_invalid_values(password: str, confirmation: str) -> None:
    with pytest.raises(PasswordPolicyError):
        PasswordManager().validate_new(password, confirmation)


def test_new_password_policy_accepts_unicode_without_composition_rule() -> None:
    password = "é" * 15

    PasswordManager().validate_new(password, password)
