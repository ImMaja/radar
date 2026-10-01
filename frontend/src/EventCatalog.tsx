import { type FormEvent, useEffect, useState } from "react";

import {
  ApiError,
  type EventDeclaredStatus,
  type EventDetailView,
  type EventPageView,
  type EventPeriodView,
  type EventQuery,
  type EventSort,
  getEvent,
  getEvents,
  type SortDirection,
} from "./api";

const PAGE_SIZE = 12;

interface EventCatalogProps {
  hasReferencePosition: boolean;
  configuredRadiusMeters: number;
  onConfigure: () => void;
  onAuthenticationRequired: () => void;
}

interface FilterDraft {
  q: string;
  maxDistanceKilometers: string;
  dateFrom: string;
  dateTo: string;
  category: string;
  organizer: string;
  hasContact: boolean;
  declaredStatus: EventDeclaredStatus | "";
  sort: EventSort;
  direction: SortDirection;
}

const initialDraft: FilterDraft = {
  q: "",
  maxDistanceKilometers: "",
  dateFrom: "",
  dateTo: "",
  category: "",
  organizer: "",
  hasContact: false,
  declaredStatus: "",
  sort: "date",
  direction: "asc",
};

const initialQuery: EventQuery = {
  sort: "date",
  direction: "asc",
  limit: PAGE_SIZE,
  offset: 0,
};

const statusLabels: Record<EventDeclaredStatus, string> = {
  SCHEDULED: "Programmé",
  POSTPONED: "Reporté",
  CANCELLED: "Annulé",
  UNKNOWN: "Statut non indiqué",
};

const contactLabels = {
  EMAIL: "Email",
  PHONE: "Téléphone",
  WEBSITE: "Site web",
  BOOKING_URL: "Réservation",
  CONTACT_RELAY: "Relais de contact",
};

const scopeLabels = {
  LOCAL: "Contact local",
  CENTRAL: "Contact central",
  UNKNOWN: "Portée inconnue",
};

const sourcePartyLabels = {
  CREATOR: "Producteur de la donnée",
  PUBLISHER: "Diffuseur de la donnée",
  OWNER: "Propriétaire de la donnée",
};

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Une erreur inattendue est survenue.";
}

function formatDistance(value: number | null): string {
  if (value === null) return "Distance inconnue";
  if (value < 1000) return `${Math.round(value).toLocaleString("fr-FR")} m`;
  return `${(value / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} km`;
}

function formatDate(value: string): string {
  const [year, month, day] = value.split("-");
  return `${day}/${month}/${year}`;
}

function formatInstant(value: string, withTime = true): string {
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "medium",
    ...(withTime ? { timeStyle: "short" as const } : {}),
    timeZone: "Europe/Paris",
  }).format(new Date(value));
}

function periodLabel(period: EventPeriodView): string {
  const start = `${formatDate(period.start_date)}${period.start_time ? ` à ${period.start_time.slice(0, 5)}` : ""}`;
  if (period.start_date === period.end_date) {
    return period.end_time ? `${start} — fin à ${period.end_time.slice(0, 5)}` : start;
  }
  const end = `${formatDate(period.end_date)}${period.end_time ? ` à ${period.end_time.slice(0, 5)}` : ""}`;
  return `Du ${start} au ${end}`;
}

function optionalFilter(value: string): string | undefined {
  return value.trim() || undefined;
}

function safeWebLink(value: string | null): string | undefined {
  if (value === null) return undefined;
  try {
    const url = new URL(value);
    if ((url.protocol === "https:" || url.protocol === "http:") && !url.username && !url.password) {
      return url.href;
    }
  } catch {
    // An unrecognised source value remains visible as text.
  }
  return undefined;
}

export function EventCatalog({
  hasReferencePosition,
  configuredRadiusMeters,
  onConfigure,
  onAuthenticationRequired,
}: EventCatalogProps) {
  const [draft, setDraft] = useState<FilterDraft>(initialDraft);
  const [query, setQuery] = useState<EventQuery>(initialQuery);
  const [filterError, setFilterError] = useState<string | null>(null);
  const [page, setPage] = useState<EventPageView | null>(null);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<EventDetailView | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  useEffect(() => {
    setPage(null);
    if (!hasReferencePosition) return;
    let active = true;
    setListLoading(true);
    setListError(null);
    getEvents(query)
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
    setDetail(null);
    setDetailError(null);
    if (selectedId === null) return;
    let active = true;
    setDetailLoading(true);
    getEvent(selectedId)
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

  function submitFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (draft.dateFrom && draft.dateTo && draft.dateTo < draft.dateFrom) {
      setFilterError("La date de fin de recherche doit suivre ou égaler la date de début.");
      return;
    }
    setFilterError(null);
    setQuery({
      q: optionalFilter(draft.q),
      maxDistanceMeters:
        draft.maxDistanceKilometers !== ""
          ? Math.round(Number(draft.maxDistanceKilometers) * 1000)
          : undefined,
      dateFrom: optionalFilter(draft.dateFrom),
      dateTo: optionalFilter(draft.dateTo),
      category: optionalFilter(draft.category),
      organizer: optionalFilter(draft.organizer),
      hasContact: draft.hasContact || undefined,
      declaredStatus: draft.declaredStatus || undefined,
      sort: draft.sort,
      direction: draft.direction,
      limit: PAGE_SIZE,
      offset: 0,
    });
  }

  function resetFilters() {
    setDraft(initialDraft);
    setFilterError(null);
    setQuery({ ...initialQuery });
  }

  if (!hasReferencePosition) {
    return (
      <section className="panel catalog-panel" aria-labelledby="events-title">
        <p className="section-label">Événements</p>
        <h2 id="events-title">Agenda local</h2>
        <p className="hint">
          Confirmez une adresse de référence avant de rechercher les événements autour de vous.
        </p>
        <button type="button" onClick={onConfigure}>
          Configurer l’adresse
        </button>
      </section>
    );
  }

  if (selectedId !== null) {
    const sourceLink = safeWebLink(detail?.source_uri ?? null);
    return (
      <section className="catalog-detail" aria-label="Fiche événement">
        <button className="text-button" type="button" onClick={() => setSelectedId(null)}>
          ← Retour aux événements
        </button>
        {detailLoading && <p className="loading">Chargement de la fiche…</p>}
        {detailError && (
          <p className="notice" role="alert">
            {detailError}
          </p>
        )}
        {detail && (
          <article className="panel detail-card">
            <p className="section-label">
              Événement · {detail.temporal_state === "ONGOING" ? "En cours" : "À venir"}
            </p>
            <h2>{detail.title}</h2>
            <p className="detail-address">
              {detail.full_address ?? detail.municipality ?? "Adresse non indiquée"} ·{" "}
              {formatDistance(detail.distance_meters)}
            </p>
            <div className="detail-grid">
              <section aria-labelledby="event-periods-title">
                <h3 id="event-periods-title">Dates et périodes</h3>
                <p className="hint">
                  Heures locales françaises. Les horaires inconnus restent non indiqués.
                </p>
                {detail.period_layer === "USER" && (
                  <p className="hint">Dates corrigées par vous.</p>
                )}
                <ul className="event-periods">
                  {detail.periods.map((period) => (
                    <li key={`${period.source_path}-${period.start_date}-${period.start_time}`}>
                      {periodLabel(period)}
                      {period.start_time === null && period.end_time === null && (
                        <small>Horaires non indiqués</small>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
              <section aria-labelledby="event-information-title">
                <h3 id="event-information-title">Informations</h3>
                <dl className="facts">
                  <div>
                    <dt>Catégories</dt>
                    <dd>{detail.types.join(", ") || "Non indiquées"}</dd>
                  </div>
                  <div>
                    <dt>Organisateur</dt>
                    <dd>{detail.organizer_name ?? "Non indiqué"}</dd>
                  </div>
                  <div>
                    <dt>Statut déclaré</dt>
                    <dd>{statusLabels[detail.declared_status]}</dd>
                  </div>
                  <div>
                    <dt>Commune</dt>
                    <dd>{detail.municipality ?? "Non indiquée"}</dd>
                  </div>
                </dl>
              </section>
            </div>
            <section aria-labelledby="event-description-title">
              <h3 id="event-description-title">Description</h3>
              <p className="event-description">
                {detail.description ?? "Aucune description disponible."}
              </p>
            </section>
            <section className="contacts" aria-labelledby="event-contacts-title">
              <h3 id="event-contacts-title">Contacts professionnels</h3>
              <p className="hint">
                Un contact à portée inconnue n’est pas un contact confirmé de l’organisateur.
              </p>
              {detail.contacts.length === 0 ? (
                <p className="hint">Aucun moyen de contact connu dans les sources actuelles.</p>
              ) : (
                <ul>
                  {detail.contacts.map((contact) => {
                    const link =
                      contact.type === "WEBSITE" ||
                      contact.type === "BOOKING_URL" ||
                      contact.type === "CONTACT_RELAY"
                        ? safeWebLink(contact.value)
                        : undefined;
                    return (
                      <li key={`${contact.type}-${contact.value}-${contact.scope}`}>
                        <span>{contactLabels[contact.type]}</span>
                        {link ? (
                          <a href={link} target="_blank" rel="noopener noreferrer">
                            {contact.value}
                          </a>
                        ) : (
                          <strong>{contact.value}</strong>
                        )}
                        <small>
                          {scopeLabels[contact.scope]}
                          {contact.label ? ` · ${contact.label}` : ""}
                        </small>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
            <section className="provenance" aria-labelledby="event-provenance-title">
              <h3 id="event-provenance-title">Provenance et fraîcheur</h3>
              {sourceLink && (
                <a href={sourceLink} target="_blank" rel="noopener noreferrer">
                  Voir la ressource d’origine
                </a>
              )}
              {detail.sources.length === 0 ? (
                <p className="hint">Aucune provenance externe n’est associée.</p>
              ) : (
                <ul>
                  {detail.sources.map((source) => (
                    <li key={source.code}>
                      <strong>{source.name}</strong>
                      <span>{source.authority}</span>
                      {source.parties.map((party) => (
                        <small key={`${party.role}-${party.identifier}-${party.legal_name}`}>
                          {sourcePartyLabels[party.role]} :{" "}
                          {party.legal_name ?? party.identifier ?? "Non indiqué"}
                        </small>
                      ))}
                      <small>Licence : {source.license_name ?? "Non indiquée"}</small>
                      <small>Dernière observation : {formatInstant(source.last_observed_at)}</small>
                      <small>Données récupérées le {formatInstant(source.retrieved_at)}</small>
                      <small>
                        {source.source_updated_at
                          ? `Mise à jour publiée : ${formatInstant(source.source_updated_at)}`
                          : "Date de mise à jour source inconnue"}
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
  const categories = [...new Set(page?.items.flatMap((item) => item.types) ?? [])].sort();

  return (
    <section className="catalog" aria-labelledby="events-title">
      <div className="catalog-heading">
        <div>
          <p className="section-label">Événements</p>
          <h2 id="events-title">Agenda local</h2>
          <p className="hint">Événements à venir ou en cours, dans les données déjà collectées.</p>
        </div>
        {page && (
          <div className="catalog-count" aria-live="polite">
            <strong>{page.total.toLocaleString("fr-FR")}</strong>
            <span>{page.total > 1 ? "événements" : "événement"}</span>
          </div>
        )}
      </div>
      <form className="catalog-filters" onSubmit={submitFilters}>
        <div className="filter-primary">
          <div>
            <label htmlFor="event-search">Titre ou commune</label>
            <input
              id="event-search"
              type="search"
              value={draft.q}
              maxLength={200}
              placeholder="Ex. Dax ou festival"
              onChange={(event) => setDraft({ ...draft, q: event.target.value })}
            />
          </div>
          <div>
            <label htmlFor="event-distance">Distance maximale (km)</label>
            <input
              id="event-distance"
              type="number"
              min="0.001"
              max="50"
              step="0.001"
              value={draft.maxDistanceKilometers}
              placeholder={`${configuredRadiusMeters / 1000}`}
              onChange={(event) =>
                setDraft({ ...draft, maxDistanceKilometers: event.target.value })
              }
            />
          </div>
          <div>
            <label htmlFor="event-date-from">À partir du</label>
            <input
              id="event-date-from"
              type="date"
              value={draft.dateFrom}
              onChange={(event) => setDraft({ ...draft, dateFrom: event.target.value })}
            />
          </div>
          <div>
            <label htmlFor="event-date-to">Jusqu’au</label>
            <input
              id="event-date-to"
              type="date"
              value={draft.dateTo}
              onChange={(event) => setDraft({ ...draft, dateTo: event.target.value })}
            />
          </div>
        </div>
        <details>
          <summary>Filtres avancés</summary>
          <div className="filter-grid">
            <div>
              <label htmlFor="event-category">Catégorie</label>
              <input
                id="event-category"
                list="event-categories"
                maxLength={100}
                value={draft.category}
                placeholder="Ex. Festival"
                onChange={(event) => setDraft({ ...draft, category: event.target.value })}
              />
              <datalist id="event-categories">
                {categories.map((category) => (
                  <option key={category} value={category} />
                ))}
              </datalist>
            </div>
            <div>
              <label htmlFor="event-organizer">Organisateur</label>
              <input
                id="event-organizer"
                maxLength={200}
                value={draft.organizer}
                placeholder="Nom de l’organisateur, s’il est connu"
                onChange={(event) => setDraft({ ...draft, organizer: event.target.value })}
              />
            </div>
            <div>
              <label htmlFor="event-status">Statut déclaré</label>
              <select
                id="event-status"
                value={draft.declaredStatus}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    declaredStatus: event.target.value as EventDeclaredStatus | "",
                  })
                }
              >
                <option value="">Tous sauf annulés</option>
                <option value="SCHEDULED">Programmé</option>
                <option value="POSTPONED">Reporté</option>
                <option value="CANCELLED">Annulé</option>
                <option value="UNKNOWN">Statut non indiqué</option>
              </select>
            </div>
            <fieldset className="contact-filters">
              <legend>Disponibilité d’un contact</legend>
              <label>
                <input
                  type="checkbox"
                  checked={draft.hasContact}
                  onChange={(event) => setDraft({ ...draft, hasContact: event.target.checked })}
                />
                Avec un moyen de contact
              </label>
            </fieldset>
            <div>
              <label htmlFor="event-sort">Trier par</label>
              <select
                id="event-sort"
                value={draft.sort}
                onChange={(event) => setDraft({ ...draft, sort: event.target.value as EventSort })}
              >
                <option value="date">Date</option>
                <option value="distance">Distance</option>
              </select>
            </div>
            <div>
              <label htmlFor="event-direction">Ordre</label>
              <select
                id="event-direction"
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
        {filterError && (
          <p className="notice" role="alert">
            {filterError}
          </p>
        )}
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
      {listLoading && <p className="loading">Recherche des événements…</p>}
      {!listLoading && page?.items.length === 0 && (
        <div className="empty-state">
          <h3>Aucun événement trouvé</h3>
          <p>
            Essayez un rayon plus large, retirez un filtre ou actualisez DATAtourisme depuis les
            réglages.
          </p>
          <button className="secondary" type="button" onClick={onConfigure}>
            Ouvrir les réglages
          </button>
        </div>
      )}
      {page && page.items.length > 0 && (
        <>
          <div className="event-list">
            {page.items.map((item) => (
              <article className="event-card" key={item.id}>
                <div>
                  <p className="event-meta">
                    <span>{item.temporal_state === "ONGOING" ? "En cours" : "À venir"}</span>
                    <span>{formatDistance(item.distance_meters)}</span>
                  </p>
                  <h3>{item.title}</h3>
                  <p className="event-next-date">
                    {item.temporal_state === "ONGOING"
                      ? "Début de la période en cours : "
                      : "Prochaine période : "}
                    {formatInstant(item.next_start_at, false)}
                  </p>
                  <p>{item.full_address ?? item.municipality ?? "Adresse non indiquée"}</p>
                  <ul className="event-signals">
                    {item.types.map((type) => (
                      <li key={type}>{type}</li>
                    ))}
                    <li>{statusLabels[item.declared_status]}</li>
                    <li>{item.has_contact ? "Contact disponible" : "Contact inconnu"}</li>
                  </ul>
                  <small className="hint">Observé le {formatInstant(item.last_observed_at)}</small>
                </div>
                <button
                  className="secondary"
                  type="button"
                  aria-label={`Ouvrir la fiche ${item.title}`}
                  onClick={() => setSelectedId(item.id)}
                >
                  Ouvrir la fiche
                </button>
              </article>
            ))}
          </div>
          <nav className="pagination" aria-label="Pagination des événements">
            <button
              className="secondary"
              type="button"
              disabled={page.offset === 0 || listLoading}
              onClick={() =>
                setQuery((current) => ({
                  ...current,
                  offset: Math.max(0, page.offset - page.limit),
                }))
              }
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
              onClick={() =>
                setQuery((current) => ({ ...current, offset: page.offset + page.limit }))
              }
            >
              Page suivante
            </button>
          </nav>
        </>
      )}
    </section>
  );
}
