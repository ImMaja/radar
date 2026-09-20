"""Provider-neutral prospect candidate values produced by source adapters."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Activity:
    """An activity code that is meaningful only with its nomenclature."""

    code: str
    nomenclature: str


@dataclass(frozen=True)
class LambertCoordinates:
    """Raw official coordinates whose own source and CRS remain explicit."""

    x: float
    y: float
    crs: str = "EPSG:2154"


@dataclass(frozen=True)
class EstablishmentAddress:
    """Public establishment address fields without inferred values."""

    address_identifier: str | None
    street_number: str | None
    repetition_index: str | None
    street_type: str | None
    street_label: str | None
    address_complement: str | None
    postcode: str | None
    municipality_label: str | None
    municipality_code: str
    coordinates: LambertCoordinates | None


@dataclass(frozen=True)
class ProspectCandidate:
    """Reusable, currently active establishment in full public diffusion."""

    siret: str
    siren: str
    is_head_office: bool
    establishment_names: tuple[str, ...]
    legal_name: str | None
    legal_usual_names: tuple[str, ...]
    legal_category: str | None
    activity: Activity | None
    employee_band: str | None
    employee_year: int | None
    address: EstablishmentAddress
    establishment_created_on: str | None
    current_period_started_on: str
    establishment_processed_at: str | None
    legal_unit_processed_at: str | None
