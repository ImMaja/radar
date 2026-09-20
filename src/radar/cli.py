"""Administrative commands that never accept passwords as shell arguments."""

import argparse
import getpass
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from radar.auth.contracts import (
    AccountAlreadyExistsError,
    AccountNotFoundError,
    PasswordPolicyError,
)
from radar.auth.service import AuthService
from radar.config import Settings, get_settings
from radar.persistence.auth import SqlAlchemyAuthRepository
from radar.persistence.database import Database
from radar.persistence.reference_data import SqlAlchemyMunicipalityReferenceRepository
from radar.reference_data.contracts import (
    MunicipalityReferenceError,
    MunicipalityReleaseSource,
)
from radar.reference_data.service import MunicipalityReferenceService


def parser() -> argparse.ArgumentParser:
    """Build the intentionally small administrative CLI."""

    command_parser = argparse.ArgumentParser(prog="radar-admin")
    subcommands = command_parser.add_subparsers(dest="command", required=True)
    create = subcommands.add_parser("create-account", help="create the only Radar account")
    create.add_argument("--display-name", default=None)
    subcommands.add_parser("reset-password", help="replace a forgotten password")
    municipalities = subcommands.add_parser(
        "import-municipalities",
        help="validate and activate an official municipality GeoJSON file",
    )
    municipalities.add_argument("file", type=Path)
    municipalities.add_argument("--resource-identifier", required=True)
    municipalities.add_argument("--resource-url", required=True)
    municipalities.add_argument("--published-on", type=date.fromisoformat, default=None)
    municipalities.add_argument("--license", dest="license_name", default="ODbL-1.0")
    municipalities.add_argument("--expected-sha256", default=None)
    municipalities.add_argument("--expected-size-bytes", type=int, default=None)
    return command_parser


def read_new_password() -> tuple[str, str]:
    """Read a password twice without echoing or placing it in shell history."""

    return (
        getpass.getpass("Nouveau mot de passe : "),
        getpass.getpass("Confirmez le nouveau mot de passe : "),
    )


def build_service(settings: Settings, database: Database) -> AuthService:
    """Compose the same authentication use cases used by the web process."""

    return AuthService(
        SqlAlchemyAuthRepository(database.engine),
        idle_timeout=timedelta(seconds=settings.session_idle_seconds),
        absolute_timeout=timedelta(seconds=settings.session_absolute_seconds),
    )


def import_municipalities(parsed: argparse.Namespace, database: Database) -> None:
    """Run the non-interactive reference import without reading a password."""

    now = datetime.now(UTC)
    source = MunicipalityReleaseSource(
        resource_identifier=parsed.resource_identifier,
        resource_url=parsed.resource_url,
        published_on=parsed.published_on,
        retrieved_at=now,
        license_name=parsed.license_name,
        expected_sha256=parsed.expected_sha256,
        expected_size_bytes=parsed.expected_size_bytes,
    )
    service = MunicipalityReferenceService(
        SqlAlchemyMunicipalityReferenceRepository(database.engine),
        clock=lambda: now,
    )
    release = service.import_file(parsed.file, source)
    state = "était déjà active" if release.already_active else "a été activée"
    print(
        f"La version {release.resource_identifier} {state} "
        f"avec {release.boundary_count} communes métropolitaines."
    )


def main(arguments: Sequence[str] | None = None) -> int:
    """Execute one safe account administration operation."""

    parsed = parser().parse_args(arguments)
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        if parsed.command == "import-municipalities":
            import_municipalities(parsed, database)
            return 0
        service = build_service(settings, database)
        password, confirmation = read_new_password()
        if parsed.command == "create-account":
            service.create_account(password, confirmation, parsed.display_name)
            print("Le compte Radar a été créé.")
        else:
            service.reset_password(password, confirmation)
            print("Le mot de passe a été remplacé et toutes les sessions ont été révoquées.")
    except (
        AccountAlreadyExistsError,
        AccountNotFoundError,
        MunicipalityReferenceError,
        PasswordPolicyError,
        ValueError,
    ) as error:
        print(f"Erreur : {error}")
        return 1
    finally:
        database.close()
    return 0
