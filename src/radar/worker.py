"""Command-line process for Radar's durable single-concurrency worker."""

import argparse
import os
import socket
import threading
from collections.abc import Mapping, Sequence
from uuid import uuid4

from radar.collections.contracts import CollectionExecutor, Connector
from radar.collections.worker import CollectionWorker
from radar.config import Settings, get_settings
from radar.persistence.collections import SqlAlchemyCollectionRepository
from radar.persistence.database import Database


def parser() -> argparse.ArgumentParser:
    """Build the worker command surface."""

    command_parser = argparse.ArgumentParser(prog="radar-worker")
    command_parser.add_argument(
        "--once",
        action="store_true",
        help="reserve at most one job and then exit",
    )
    return command_parser


def build_executors(_settings: Settings) -> Mapping[Connector, CollectionExecutor]:
    """Return implemented provider adapters; milestones 6 and 7 will register them."""

    return {}


def worker_identity() -> str:
    """Create a diagnostic lease owner without exposing configuration secrets."""

    return f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:12]}"


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the worker loop separately from the FastAPI process."""

    parsed = parser().parse_args(arguments)
    settings = get_settings()
    executors = build_executors(settings)
    if not executors:
        print("Aucun connecteur de collecte n'est encore installé dans le worker.")
        return 1

    database = Database(settings.database_url)
    stopped = threading.Event()
    try:
        worker = CollectionWorker(
            SqlAlchemyCollectionRepository(database.engine),
            executors,
            worker_identity(),
        )
        if parsed.once:
            worker.run_once()
            return 0
        while not stopped.is_set():
            if not worker.run_once():
                stopped.wait(5)
    except KeyboardInterrupt:
        stopped.set()
    finally:
        database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
