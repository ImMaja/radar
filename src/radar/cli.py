"""Administrative commands that never accept passwords as shell arguments."""

import argparse
import getpass
from collections.abc import Sequence
from datetime import timedelta

from radar.auth.contracts import (
    AccountAlreadyExistsError,
    AccountNotFoundError,
    PasswordPolicyError,
)
from radar.auth.service import AuthService
from radar.config import Settings, get_settings
from radar.persistence.auth import SqlAlchemyAuthRepository
from radar.persistence.database import Database


def parser() -> argparse.ArgumentParser:
    """Build the intentionally small administrative CLI."""

    command_parser = argparse.ArgumentParser(prog="radar-admin")
    subcommands = command_parser.add_subparsers(dest="command", required=True)
    create = subcommands.add_parser("create-account", help="create the only Radar account")
    create.add_argument("--display-name", default=None)
    subcommands.add_parser("reset-password", help="replace a forgotten password")
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


def main(arguments: Sequence[str] | None = None) -> int:
    """Execute one safe account administration operation."""

    parsed = parser().parse_args(arguments)
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        service = build_service(settings, database)
        password, confirmation = read_new_password()
        if parsed.command == "create-account":
            service.create_account(password, confirmation, parsed.display_name)
            print("Le compte Radar a été créé.")
        else:
            service.reset_password(password, confirmation)
            print("Le mot de passe a été remplacé et toutes les sessions ont été révoquées.")
    except (AccountAlreadyExistsError, AccountNotFoundError, PasswordPolicyError) as error:
        print(f"Erreur : {error}")
        return 1
    finally:
        database.close()
    return 0
