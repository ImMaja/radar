import { type FormEvent, useEffect, useState } from "react";

import {
  ApiError,
  getProspect,
  getProspects,
  type ProspectDetailView,
  type ProspectLocation,
  type ProspectPageView,
  type ProspectQuery,
  type ProspectSort,
  type SortDirection,
} from "./api";

const PAGE_SIZE = 12;

interface ProspectCatalogProps {
  hasReferencePosition: boolean;
  configuredRadiusMeters: number;
  onConfigure: () => void;
  onAuthenticationRequired: () => void;
}

interface FilterDraft {
  q: string;
  maxDistanceKilometers: string;
  organizationType: string;
  activityCode: string;
  employeeBand: string;
  hasEmail: boolean;
  hasPhone: boolean;
  hasWebsite: boolean;
  sort: ProspectSort;
  direction: SortDirection;
}

const initialDraft: FilterDraft = {
  q: "",
  maxDistanceKilometers: "",
  organizationType: "",
  activityCode: "",
  employeeBand: "",
  hasEmail: false,
  hasPhone: false,
  hasWebsite: false,
  sort: "distance",
  direction: "asc",
};

const initialQuery: ProspectQuery = {
  location: "located",
  sort: "distance",
  direction: "asc",
  limit: PAGE_SIZE,
  offset: 0,
};

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Une erreur inattendue est survenue.";
}

function formatDistance(value: number | null): string {
  if (value === null) return "Distance inconnue";
  if (value < 1000) return `${Math.round(value).toLocaleString("fr-FR")} m`;
  return `${(value / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} km`;
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatDate(value: string | null): string {
  if (value === null) return "Non indiquée";
  const [year, month, day] = value.split("-");
  return day && month && year ? `${day}/${month}/${year}` : value;
}

function optionalFilter(value: string): string | undefined {
  const normalized = value.trim();
  return normalized || undefined;
}

function organizationTypeLabel(value: string): string {
  return value === "UNKNOWN" ? "Type inconnu" : value;
}

function locationPrecisionLabel(value: string): string {
  const labels: Record<string, string> = {
    ROOFTOP: "Bâtiment",
    ADDRESS: "Adresse",
    STREET: "Voie",
    MUNICIPALITY: "Commune",
    UNKNOWN: "Précision inconnue",
  };
  return labels[value] ?? value;
}

function contactTypeLabel(value: string): string {
  const labels: Record<string, string> = {
    EMAIL: "Email",
    PHONE: "Téléphone",
    WEBSITE: "Site web",
    BOOKING_URL: "Réservation",
    CONTACT_RELAY: "Relais de contact",
  };
  return labels[value] ?? value;
}

function contactScopeLabel(value: string): string {
  const labels: Record<string, string> = {
    LOCAL: "Contact local",
    CENTRAL: "Contact central",
    UNKNOWN: "Portée inconnue",
  };
  return labels[value] ?? value;
}

export function ProspectCatalog({
  hasReferencePosition,
  configuredRadiusMeters,
  onConfigure,
  onAuthenticationRequired,
}: ProspectCatalogProps) {
  const [draft, setDraft] = useState<FilterDraft>(initialDraft);
  const [query, setQuery] = useState<ProspectQuery>(initialQuery);
  const [page, setPage] = useState<ProspectPageView | null>(null);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ProspectDetailView | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  useEffect(() => {
    if (!hasReferencePosition) {
      setPage(null);
      return;
    }
    let active = true;
    setListLoading(true);
    setListError(null);
    getProspects(query)
      .then((result) => {
        if (active) setPage(result);
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (error instanceof ApiError && error.status === 401) {
          onAuthenticationRequired();
        } else {
          setListError(errorMessage(error));
        }
      })
      .finally(() => {
        if (active) setListLoading(false);
      });
    return () => {
      active = false;
    };
  }, [hasReferencePosition, onAuthenticationRequired, query]);

  useEffect(() => {
    if (selectedId === null) {
      setDetail(null);
      setDetailError(null);
      return;
    }
    let active = true;
    setDetail(null);
    setDetailLoading(true);
    setDetailError(null);
    getProspect(selectedId)
      .then((result) => {
        if (active) setDetail(result);
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (error instanceof ApiError && error.status === 401) {
          onAuthenticationRequired();
        } else {
          setDetailError(errorMessage(error));
        }
      })
      .finally(() => {
        if (active) setDetailLoading(false);
      });
    return () => {
      active = false;
    };
  }, [onAuthenticationRequired, selectedId]);

  function selectLocation(location: ProspectLocation) {
    setSelectedId(null);
    const sort = location === "to_verify" && draft.sort === "distance" ? "name" : draft.sort;
    setDraft((current) => ({ ...current, sort }));
    setQuery((current) => ({
      ...current,
      location,
      maxDistanceMeters: location === "to_verify" ? undefined : current.maxDistanceMeters,
      sort,
      offset: 0,
    }));
  }

  function submitFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const distance = Number(draft.maxDistanceKilometers);
    setSelectedId(null);
    setQuery((current) => ({
      q: optionalFilter(draft.q),
      maxDistanceMeters:
        current.location === "located" && draft.maxDistanceKilometers !== ""
          ? Math.round(distance * 1000)
          : undefined,
      organizationType: optionalFilter(draft.organizationType),
      activityCode: optionalFilter(draft.activityCode),
      employeeBand: optionalFilter(draft.employeeBand),
      hasEmail: draft.hasEmail || undefined,
      hasPhone: draft.hasPhone || undefined,
      hasWebsite: draft.hasWebsite || undefined,
      location: current.location,
      sort: draft.sort,
      direction: draft.direction,
      limit: PAGE_SIZE,
      offset: 0,
    }));
  }

  function resetFilters() {
    const resetDraft = {
      ...initialDraft,
      sort: query.location === "located" ? "distance" : "name",
    } satisfies FilterDraft;
    setDraft(resetDraft);
    setSelectedId(null);
    setQuery({
      ...initialQuery,
      location: query.location,
      sort: resetDraft.sort,
    });
  }

  function changePage(offset: number) {
    setSelectedId(null);
    setQuery((current) => ({ ...current, offset }));
  }

  if (!hasReferencePosition) {
    return (
      <section className="panel catalog-panel" aria-labelledby="prospects-title">
        <p className="section-label">Prospects réguliers</p>
        <h2 id="prospects-title">Catalogue local</h2>
        <p className="hint">
          Confirmez une adresse de référence avant de rechercher les établissements autour de vous.
        </p>
        <button type="button" onClick={onConfigure}>
          Configurer l’adresse
        </button>
      </section>
    );
  }

  if (selectedId !== null) {
    return (
      <section className="catalog-detail" aria-labelledby="prospect-detail-title">
        <button className="text-button" type="button" onClick={() => setSelectedId(null)}>
          ← Retour aux prospects
        </button>
        {detailLoading && <p className="loading">Chargement de la fiche…</p>}
        {detailError && (
          <p className="notice" role="alert">
            {detailError}
          </p>
        )}
        {detail && (
          <article className="panel detail-card">
            <p className="section-label">Prospect régulier</p>
            <h2 id="prospect-detail-title">{detail.display_name}</h2>
            <p className="detail-address">
              {detail.address.full_address ?? "Adresse non indiquée"} ·{" "}
              {formatDistance(detail.distance_meters)}
            </p>

            <div className="detail-grid">
              <section aria-labelledby="identity-title">
                <h3 id="identity-title">Identité et activité</h3>
                <dl className="facts">
                  <div>
                    <dt>Raison sociale</dt>
                    <dd>{detail.legal_name ?? "Non indiquée"}</dd>
                  </div>
                  <div>
                    <dt>Type</dt>
                    <dd>{organizationTypeLabel(detail.organization_type)}</dd>
                  </div>
                  <div>
                    <dt>Activité</dt>
                    <dd>
                      {detail.activity_code
                        ? `${detail.activity_code} · ${detail.activity_label ?? detail.activity_nomenclature ?? "Libellé inconnu"}`
                        : "Non indiquée"}
                    </dd>
                  </div>
                  <div>
                    <dt>Effectif</dt>
                    <dd>
                      {detail.employee_band
                        ? `Tranche ${detail.employee_band}${detail.employee_year ? ` (${detail.employee_year})` : ""}`
                        : "Non indiqué"}
                    </dd>
                  </div>
                  <div>
                    <dt>SIRET</dt>
                    <dd>{detail.siret ?? "Non indiqué"}</dd>
                  </div>
                  <div>
                    <dt>SIREN</dt>
                    <dd>{detail.siren ?? "Non indiqué"}</dd>
                  </div>
                  <div>
                    <dt>Création du site</dt>
                    <dd>{formatDate(detail.established_on)}</dd>
                  </div>
                  <div>
                    <dt>Siège</dt>
                    <dd>
                      {detail.is_head_office === null
                        ? "Non indiqué"
                        : detail.is_head_office
                          ? "Oui"
                          : "Non"}
                    </dd>
                  </div>
                </dl>
              </section>

              <section aria-labelledby="location-title">
                <h3 id="location-title">Localisation</h3>
                <dl className="facts">
                  <div>
                    <dt>Adresse</dt>
                    <dd>{detail.address.full_address ?? "Non indiquée"}</dd>
                  </div>
                  <div>
                    <dt>Commune</dt>
                    <dd>{detail.address.municipality ?? "Non indiquée"}</dd>
                  </div>
                  <div>
                    <dt>Précision</dt>
                    <dd>{locationPrecisionLabel(detail.location_precision)}</dd>
                  </div>
                  <div>
                    <dt>Origine</dt>
                    <dd>{detail.location_origin}</dd>
                  </div>
                </dl>
              </section>
            </div>

            <section className="contacts" aria-labelledby="contacts-title">
              <h3 id="contacts-title">Contacts professionnels</h3>
              {detail.contacts.length === 0 ? (
                <p className="hint">Aucun moyen de contact connu dans les sources actuelles.</p>
              ) : (
                <ul>
                  {detail.contacts.map((contact) => (
                    <li key={`${contact.type}-${contact.value}-${contact.scope}`}>
                      <span>{contactTypeLabel(contact.type)}</span>
                      <strong>{contact.value}</strong>
                      <small>
                        {contactScopeLabel(contact.scope)}
                        {contact.label ? ` · ${contact.label}` : ""}
                      </small>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="provenance" aria-labelledby="provenance-title">
              <h3 id="provenance-title">Provenance</h3>
              {detail.sources.length === 0 ? (
                <p className="hint">Aucune provenance externe n’est associée.</p>
              ) : (
                <ul>
                  {detail.sources.map((source) => (
                    <li key={source.code}>
                      <strong>{source.name}</strong>
                      <span>{source.authority}</span>
                      <small>
                        Dernière observation : {formatDateTime(source.last_observed_at)}
                      </small>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </article>
        )}
      </section>
    );
  }

  const currentPage = page ? Math.floor(page.offset / page.limit) + 1 : 1;
  const pageCount = page ? Math.max(1, Math.ceil(page.total / page.limit)) : 1;

  return (
    <section className="catalog" aria-labelledby="prospects-title">
      <div className="catalog-heading">
        <div>
          <p className="section-label">Prospects réguliers</p>
          <h2 id="prospects-title">Catalogue local</h2>
          <p className="hint">
            Recherche dans les données déjà collectées, sans appel à une source externe.
          </p>
        </div>
        {page && (
          <div className="catalog-count" aria-live="polite">
            <strong>{page.total.toLocaleString("fr-FR")}</strong>
            <span>{page.total > 1 ? "fiches" : "fiche"}</span>
          </div>
        )}
      </div>

      <nav className="catalog-tabs" aria-label="État de localisation">
        <button
          type="button"
          className={query.location === "located" ? "active" : ""}
          aria-pressed={query.location === "located"}
          onClick={() => selectLocation("located")}
        >
          Prospects localisés
        </button>
        <button
          type="button"
          className={query.location === "to_verify" ? "active" : ""}
          aria-pressed={query.location === "to_verify"}
          onClick={() => selectLocation("to_verify")}
        >
          Localisation à vérifier
        </button>
      </nav>

      <form className="catalog-filters" onSubmit={submitFilters}>
        <div className="filter-primary">
          <div>
            <label htmlFor="prospect-search">Nom ou commune</label>
            <input
              id="prospect-search"
              type="search"
              value={draft.q}
              maxLength={200}
              placeholder="Ex. Dax ou boulangerie"
              onChange={(event) => setDraft({ ...draft, q: event.target.value })}
            />
          </div>
          <div>
            <label htmlFor="prospect-distance">Distance maximale (km)</label>
            <input
              id="prospect-distance"
              type="number"
              min="0.001"
              max="50"
              step="0.001"
              value={draft.maxDistanceKilometers}
              disabled={query.location === "to_verify"}
              placeholder={`${configuredRadiusMeters / 1000}`}
              onChange={(event) =>
                setDraft({ ...draft, maxDistanceKilometers: event.target.value })
              }
            />
          </div>
        </div>

        <details>
          <summary>Filtres avancés</summary>
          <div className="filter-grid">
            <div>
              <label htmlFor="prospect-type">Type d’organisme</label>
              <input
                id="prospect-type"
                value={draft.organizationType}
                maxLength={64}
                placeholder="Ex. COMPANY"
                onChange={(event) => setDraft({ ...draft, organizationType: event.target.value })}
              />
            </div>
            <div>
              <label htmlFor="prospect-activity">Code d’activité</label>
              <input
                id="prospect-activity"
                value={draft.activityCode}
                maxLength={16}
                placeholder="Ex. 10.71C"
                onChange={(event) => setDraft({ ...draft, activityCode: event.target.value })}
              />
            </div>
            <div>
              <label htmlFor="prospect-workforce">Tranche d’effectif</label>
              <input
                id="prospect-workforce"
                value={draft.employeeBand}
                maxLength={8}
                placeholder="Ex. 12"
                onChange={(event) => setDraft({ ...draft, employeeBand: event.target.value })}
              />
            </div>
            <fieldset className="contact-filters">
              <legend>Moyens de contact connus</legend>
              <label>
                <input
                  type="checkbox"
                  checked={draft.hasEmail}
                  onChange={(event) => setDraft({ ...draft, hasEmail: event.target.checked })}
                />
                Email
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={draft.hasPhone}
                  onChange={(event) => setDraft({ ...draft, hasPhone: event.target.checked })}
                />
                Téléphone
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={draft.hasWebsite}
                  onChange={(event) => setDraft({ ...draft, hasWebsite: event.target.checked })}
                />
                Site web
              </label>
            </fieldset>
            <div>
              <label htmlFor="prospect-sort">Trier par</label>
              <select
                id="prospect-sort"
                value={draft.sort}
                onChange={(event) =>
                  setDraft({ ...draft, sort: event.target.value as ProspectSort })
                }
              >
                <option value="distance">Distance</option>
                <option value="name">Nom</option>
              </select>
            </div>
            <div>
              <label htmlFor="prospect-direction">Ordre</label>
              <select
                id="prospect-direction"
                value={draft.direction}
                onChange={(event) =>
                  setDraft({ ...draft, direction: event.target.value as SortDirection })
                }
              >
                <option value="asc">Croissant</option>
                <option value="desc">Décroissant</option>
              </select>
            </div>
          </div>
        </details>

        <div className="filter-actions">
          <button type="submit" disabled={listLoading}>
            Appliquer les filtres
          </button>
          <button className="secondary" type="button" onClick={resetFilters}>
            Réinitialiser
          </button>
        </div>
      </form>

      {listError && (
        <p className="notice" role="alert">
          {listError}
        </p>
      )}
      {listLoading && <p className="loading">Recherche des prospects…</p>}
      {!listLoading && page?.items.length === 0 && (
        <div className="empty-state">
          <h3>Aucune fiche trouvée</h3>
          <p>
            {query.location === "located"
              ? "Essayez un rayon plus large ou retirez un filtre."
              : "Aucune localisation ne nécessite de vérification avec ces filtres."}
          </p>
        </div>
      )}

      {page && page.items.length > 0 && (
        <>
          <div className="prospect-list">
            {page.items.map((prospect) => (
              <article className="prospect-card" key={prospect.id}>
                <div>
                  <p className="prospect-meta">
                    <span>{organizationTypeLabel(prospect.organization_type)}</span>
                    <span>{formatDistance(prospect.distance_meters)}</span>
                  </p>
                  <h3>{prospect.display_name}</h3>
                  <p>{prospect.address.full_address ?? "Adresse non indiquée"}</p>
                  <ul className="prospect-signals">
                    <li>{prospect.activity_code ?? "Activité inconnue"}</li>
                    <li>
                      {prospect.employee_band
                        ? `Effectif ${prospect.employee_band}`
                        : "Effectif inconnu"}
                    </li>
                    <li>{locationPrecisionLabel(prospect.location_precision)}</li>
                    {prospect.has_email && <li>Email</li>}
                    {prospect.has_phone && <li>Téléphone</li>}
                    {prospect.has_website && <li>Site web</li>}
                  </ul>
                </div>
                <button
                  className="secondary"
                  type="button"
                  aria-label={`Ouvrir la fiche ${prospect.display_name}`}
                  onClick={() => setSelectedId(prospect.id)}
                >
                  Ouvrir la fiche
                </button>
              </article>
            ))}
          </div>

          <nav className="pagination" aria-label="Pagination des prospects">
            <button
              className="secondary"
              type="button"
              disabled={page.offset === 0 || listLoading}
              onClick={() => changePage(Math.max(0, page.offset - page.limit))}
            >
              Page précédente
            </button>
            <span>
              Page {currentPage} sur {pageCount}
            </span>
            <button
              className="secondary"
              type="button"
              disabled={page.offset + page.limit >= page.total || listLoading}
              onClick={() => changePage(page.offset + page.limit)}
            >
              Page suivante
            </button>
          </nav>
        </>
      )}
    </section>
  );
}
