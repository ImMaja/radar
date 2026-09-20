"""Collection request and supervision use cases."""

import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from radar.collections.contracts import (
    CollectionBackend,
    CollectionDashboard,
    CollectionEngineUnavailableError,
    CollectionRepository,
    Connector,
    ConnectorNotAvailableError,
    ConnectorSpecification,
    EnqueuedCollection,
)


def utc_now() -> datetime:
    """Return an aware UTC instant."""

    return datetime.now(UTC)


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


CONNECTOR_SPECIFICATIONS: dict[Connector, ConnectorSpecification] = {
    "SIRENE": ConnectorSpecification(
        adapter_version="sirene-v1",
        configuration_fingerprint=_fingerprint("sirene-contract-2026-09"),
    ),
    "DATATOURISME": ConnectorSpecification(
        adapter_version="datatourisme-v1",
        configuration_fingerprint=_fingerprint("datatourisme-contract-2026-09"),
    ),
}


class CollectionService:
    """Create idempotent manual jobs and expose their durable status."""

    def __init__(
        self,
        repository: CollectionRepository,
        enabled_connectors: frozenset[Connector] = frozenset(),
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._enabled_connectors = enabled_connectors
        self._clock = clock

    def request_manual(self, connector: Connector) -> EnqueuedCollection:
        """Capture the current zone in a manual job without doing provider I/O."""

        if connector not in self._enabled_connectors:
            raise ConnectorNotAvailableError("the connector adapter is not installed")
        return self._repository.enqueue(
            connector,
            "MANUAL",
            CONNECTOR_SPECIFICATIONS[connector],
            self._clock(),
        )

    def dashboard(self) -> CollectionDashboard:
        """Read latest jobs and successes without contacting providers."""

        dashboard = self._repository.dashboard()
        return CollectionDashboard(
            tuple(
                replace(
                    connector,
                    available=connector.connector in self._enabled_connectors,
                )
                for connector in dashboard.connectors
            )
        )


class UnavailableCollectionBackend(CollectionBackend):
    """Fail closed in API-only tests that deliberately omit persistence."""

    def request_manual(self, connector: Connector) -> EnqueuedCollection:
        del connector
        raise CollectionEngineUnavailableError("collection persistence is unavailable")

    def dashboard(self) -> CollectionDashboard:
        raise CollectionEngineUnavailableError("collection persistence is unavailable")
