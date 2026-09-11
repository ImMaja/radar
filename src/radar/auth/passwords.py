"""Password policy and Argon2id hashing."""

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

from radar.auth.contracts import PasswordPolicyError

MIN_PASSWORD_LENGTH = 15
MAX_PASSWORD_LENGTH = 128


class PasswordManager:
    """Validate and hash passwords using Radar's current Argon2id profile."""

    def __init__(self) -> None:
        self._hasher = PasswordHasher(
            time_cost=2,
            memory_cost=19_456,
            parallelism=1,
            hash_len=32,
            salt_len=16,
            type=Type.ID,
        )

    def validate_new(self, password: str, confirmation: str) -> None:
        """Apply length and confirmation rules without composition requirements."""

        if password != confirmation:
            raise PasswordPolicyError("La confirmation du mot de passe ne correspond pas.")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise PasswordPolicyError(
                f"Le mot de passe doit contenir au moins {MIN_PASSWORD_LENGTH} caractères."
            )
        if len(password) > MAX_PASSWORD_LENGTH:
            raise PasswordPolicyError(
                f"Le mot de passe doit contenir au maximum {MAX_PASSWORD_LENGTH} caractères."
            )

    def hash(self, password: str) -> str:
        """Create a salted Argon2id password hash in PHC format."""

        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        """Verify the full password while hiding malformed hash details."""

        try:
            return self._hasher.verify(password_hash, password)
        except (InvalidHashError, VerificationError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        """Return whether a valid hash should use the current parameters."""

        try:
            return self._hasher.check_needs_rehash(password_hash)
        except InvalidHashError:
            return False
