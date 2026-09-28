"""End-to-end orchestration of the restart-safe Sirene prospect stages."""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from radar.collections.contracts import (
    CollectionOutcome,
    CollectionProgress,
    PermanentCollectionError,
    ProgressReporter,
    ReservedCollection,
    RetryableCollectionError,
)
from radar.prospects.fallback_geocoding import (
    SireneFallbackGeocodingError,
    SireneFallbackGeocodingSummary,
)
from radar.prospects.geolocation import (
    SireneGeolocationImportError,
    SireneGeolocationReleaseSource,
)
from radar.prospects.planning import SirenePlanningError
from radar.prospects.position_resolution import (
    SirenePositionResolutionError,
    SirenePositionResolutionSummary,
)
from radar.prospects.projection import (
    SireneProspectProjectionError,
    SireneProspectProjectionSummary,
)
from radar.prospects.sirene_collection import SireneEnumerationResult, SireneExecutionError
from radar.prospects.status_reconciliation import (
    SireneKnownStatusError,
    SireneKnownStatusSummary,
)
from radar.providers.sirene_geolocation import SireneGeolocationScan


class SireneEnumerator(Protocol):
    """Enumerate and durably stage every current reusable Sirene candidate."""

    def enumerate(
        self,
        reservation: ReservedCollection,
        reporter: ProgressReporter,
    ) -> SireneEnumerationResult: ...


class SireneGeolocationImporter(Protocol):
    """Join staged candidates to one validated monthly geolocation file."""

    def import_file(
        self,
        reservation: ReservedCollection,
        path: Path,
        source: SireneGeolocationReleaseSource,
    ) -> SireneGeolocationScan: ...


class SirenePositionResolver(Protocol):
    """Choose one effective position for every staged candidate."""

    def resolve(
        self,
        reservation: ReservedCollection,
    ) -> SirenePositionResolutionSummary: ...


class SireneFallbackGeocoder(Protocol):
    """Resolve only addresses left pending by API and monthly-file positions."""

    def geocode_pending(
        self,
        reservation: ReservedCollection,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> SireneFallbackGeocodingSummary: ...


class SireneProspectProjector(Protocol):
    """Materialize final candidate decisions as stable prospect fiches."""

    def project(
        self,
        reservation: ReservedCollection,
    ) -> SireneProspectProjectionSummary: ...


class SireneKnownStatusReconciler(Protocol):
    """Reconcile known fiches absent from the complete active selection."""

    def reconcile(
        self,
        reservation: ReservedCollection,
        reporter: ProgressReporter,
    ) -> SireneKnownStatusSummary: ...


class SireneProspectCollectionExecutor:
    """Compose the validated Sirene stages without bypassing durable boundaries."""

    def __init__(
        self,
        enumerator: SireneEnumerator,
        geolocation_importer: SireneGeolocationImporter,
        geolocation_path: Path,
        geolocation_source: SireneGeolocationReleaseSource,
        position_resolver: SirenePositionResolver,
        fallback_geocoder: SireneFallbackGeocoder,
        projector: SireneProspectProjector,
        status_reconciler: SireneKnownStatusReconciler,
    ) -> None:
        self._enumerator = enumerator
        self._geolocation_importer = geolocation_importer
        self._geolocation_path = geolocation_path
        self._geolocation_source = geolocation_source
        self._position_resolver = position_resolver
        self._fallback_geocoder = fallback_geocoder
        self._projector = projector
        self._status_reconciler = status_reconciler

    def collect(
        self,
        reservation: ReservedCollection,
        reporter: ProgressReporter,
    ) -> CollectionOutcome:
        """Run or resume every stage and publish coverage only after reconciliation."""

        if reservation.connector != "SIRENE":
            raise ValueError("only a Sirene collection can use the Sirene executor")

        try:
            enumeration = self._enumerator.enumerate(reservation, reporter)
        except (SirenePlanningError, SireneExecutionError) as error:
            raise PermanentCollectionError(
                "sirene_enumeration_persistence_failed",
                "La préparation de la collecte Sirene n'a pas pu être réconciliée.",
            ) from error
        preserved = enumeration.importable_count
        self._report(
            reporter,
            "sirene_geolocation",
            0,
            enumeration.importable_count,
            preserved,
            "sirene_enumeration",
        )

        try:
            geolocation = self._geolocation_importer.import_file(
                reservation,
                self._geolocation_path,
                self._geolocation_source,
            )
            self._report(
                reporter,
                "sirene_position_resolution",
                geolocation.requested_siret_count,
                geolocation.requested_siret_count,
                preserved,
                "sirene_geolocation",
            )
            initial_resolution = self._position_resolver.resolve(reservation)
            self._report(
                reporter,
                "sirene_fallback_geocoding",
                0,
                initial_resolution.geocoding_required_count,
                preserved,
                "sirene_position_resolution_initial",
            )
            fallback = self._fallback_geocoder.geocode_pending(
                reservation,
                lambda processed, total: self._report(
                    reporter,
                    "sirene_fallback_geocoding",
                    processed,
                    total,
                    preserved,
                    "sirene_position_resolution_initial",
                ),
            )
            final_resolution = self._position_resolver.resolve(reservation)
            if final_resolution.geocoding_required_count != 0:
                raise SirenePositionResolutionError(
                    "fallback geocoding left candidates in a pending state"
                )
            self._report(
                reporter,
                "sirene_projection",
                0,
                enumeration.importable_count,
                preserved,
                "sirene_position_resolution_final",
            )
            projection = self._projector.project(reservation)
            self._report(
                reporter,
                "sirene_known_status",
                0,
                None,
                preserved,
                "sirene_projection",
            )
            statuses = self._status_reconciler.reconcile(reservation, reporter)
        except SireneGeolocationImportError as error:
            raise PermanentCollectionError(
                "sirene_geolocation_import_failed",
                "Le fichier de géolocalisation Sirene n'a pas pu être validé.",
                observations_preserved=preserved,
            ) from error
        except SireneFallbackGeocodingError as error:
            failure_type = RetryableCollectionError if error.transient else PermanentCollectionError
            raise failure_type(
                error.code,
                "Le géocodage de repli Sirene n'a pas pu être terminé.",
                observations_preserved=preserved,
            ) from error
        except SirenePositionResolutionError as error:
            raise PermanentCollectionError(
                "sirene_position_resolution_failed",
                "Les positions Sirene n'ont pas pu être réconciliées.",
                observations_preserved=preserved,
            ) from error
        except SireneProspectProjectionError as error:
            raise PermanentCollectionError(
                "sirene_projection_failed",
                "Les prospects Sirene n'ont pas pu être projetés.",
                observations_preserved=preserved,
            ) from error
        except SireneKnownStatusError as error:
            raise PermanentCollectionError(
                "sirene_known_status_persistence_failed",
                "Le contrôle des fiches Sirene connues n'a pas pu être réconcilié.",
                observations_preserved=preserved,
            ) from error

        self._report(
            reporter,
            "sirene_complete",
            enumeration.received_count,
            enumeration.announced_total,
            preserved,
            "sirene_known_status",
        )
        counters: dict[str, object] = {
            "processed": enumeration.received_count,
            "total": enumeration.announced_total,
            "observations": preserved,
            "unique_siret_count": enumeration.unique_siret_count,
            "importable_count": enumeration.importable_count,
            "rejection_counts": enumeration.rejection_counts,
            "file_matched_count": geolocation.matched_siret_count,
            "file_missing_count": geolocation.missing_siret_count,
            "geocoder_requested_count": fallback.requested_count,
            "geocoder_usable_count": fallback.usable_count,
            "geocoder_skipped_count": fallback.skipped_count,
            "location_unresolved_count": final_resolution.unresolved_count,
            "prospect_created_count": projection.created_count,
            "prospect_updated_count": projection.updated_count,
            "prospect_unchanged_count": projection.unchanged_count,
            "outside_radius_count": projection.counted_only_count,
            "known_status_checked_count": statuses.checked_count,
            "known_status_restricted_count": statuses.restricted_count,
        }
        return CollectionOutcome(
            "SUCCEEDED",
            counters,
            source_freshness={
                "sirene_api": enumeration.source_metadata.get("freshness", []),
                "sirene_geolocation": self._geolocation_source.resource_identifier,
            },
            explicit_limits={
                "search_circle_complete": True,
                "location_unknown_count": projection.location_unknown_count,
            },
        )

    @staticmethod
    def _report(
        reporter: ProgressReporter,
        stage: str,
        processed: int,
        total: int | None,
        observations: int,
        completed_stage: str,
    ) -> None:
        reporter.update(
            CollectionProgress(stage, processed, total, observations),
            {"completed_stage": completed_stage},
        )
