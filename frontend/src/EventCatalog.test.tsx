import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EventDetailView, EventPageView, EventSummaryView } from "./api";
import { EventCatalog } from "./EventCatalog";

const festival: EventSummaryView = {
  id: "341c6040-ec7d-45aa-b8c4-af65ea3f3b2f",
  title: "Festival de Dax",
  types: ["Festival"],
  organizer_name: null,
  declared_status: "UNKNOWN",
  temporal_state: "UPCOMING",
  next_start_at: "2027-07-11T22:00:00Z",
  full_address: "Place de la Mairie, 40100 Dax",
  municipality: "Dax",
  distance_meters: 125.4,
  has_contact: true,
  last_observed_at: "2026-10-01T12:00:00Z",
};

const concert: EventSummaryView = {
  ...festival,
  id: "9d38002d-977e-49ce-8540-d3f1f510381d",
  title: "Concert à Tyrosse",
  types: ["Concert"],
  has_contact: false,
  distance_meters: 22_450,
};

const festivalDetail: EventDetailView = {
  ...festival,
  description: "Une fête locale ouverte au public.",
  source_uri: "https://data.datatourisme.fr/festival",
  period_layer: "SOURCE",
  periods: [
    {
      start_date: "2027-07-12",
      end_date: "2027-07-12",
      start_time: null,
      end_time: null,
      precision: "DATE_ONLY",
      source_path: "periods[0]",
    },
    {
      start_date: "2028-07-15",
      end_date: "2028-07-17",
      start_time: "19:30:00",
      end_time: "23:00:00",
      precision: "DATE_AND_TIME",
      source_path: "periods[1]",
    },
  ],
  longitude: -1.051952,
  latitude: 43.70884,
  contacts: [
    {
      type: "PHONE",
      value: "05 58 12 34 56",
      scope: "UNKNOWN",
      label: "Contact général",
      source_reference: "contacts[0]",
    },
    {
      type: "WEBSITE",
      value: "https://festival.example",
      scope: "UNKNOWN",
      label: null,
      source_reference: "contacts[1]",
    },
  ],
  sources: [
    {
      code: "DATATOURISME_API",
      name: "API DATAtourisme v1",
      authority: "DATAtourisme",
      state: "CURRENT",
      first_observed_at: "2026-09-30T12:00:00Z",
      last_observed_at: festival.last_observed_at,
      retrieved_at: festival.last_observed_at,
      source_updated_at: null,
      license_name: "Licence Ouverte 2.0",
      parties: [{ role: "CREATOR", identifier: "office-dax", legal_name: "Office de tourisme" }],
    },
  ],
};

function page(items: EventSummaryView[], total = items.length, offset = 0): EventPageView {
  return { items, total, limit: 12, offset, applied_radius_meters: 30_000 };
}

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderCatalog(onAuthenticationRequired = vi.fn()) {
  return render(
    <EventCatalog
      hasReferencePosition
      configuredRadiusMeters={30_000}
      onConfigure={vi.fn()}
      onAuthenticationRequired={onAuthenticationRequired}
    />,
  );
}

describe("event catalogue", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("requires a confirmed address before reading events", () => {
    const configure = vi.fn();
    render(
      <EventCatalog
        hasReferencePosition={false}
        configuredRadiusMeters={50_000}
        onConfigure={configure}
        onAuthenticationRequired={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Configurer l’adresse" }));
    expect(configure).toHaveBeenCalledOnce();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("applies local filters and sorts without collecting externally", async () => {
    fetchMock
      .mockResolvedValueOnce(response(page([festival])))
      .mockResolvedValueOnce(response(page([concert])));
    renderCatalog();
    await screen.findByText("Festival de Dax");
    expect(screen.getByText(/Prochaine période : 12 juil\. 2027/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Titre ou commune"), { target: { value: " Tyrosse " } });
    fireEvent.change(screen.getByLabelText("Distance maximale (km)"), { target: { value: "30" } });
    fireEvent.change(screen.getByLabelText("À partir du"), { target: { value: "2027-07-12" } });
    fireEvent.change(screen.getByLabelText("Jusqu’au"), { target: { value: "2028-07-17" } });
    fireEvent.click(screen.getByText("Filtres avancés"));
    fireEvent.change(screen.getByLabelText("Catégorie"), { target: { value: "Concert" } });
    fireEvent.change(screen.getByLabelText("Organisateur"), {
      target: { value: "Comité des fêtes" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "Avec un moyen de contact" }));
    fireEvent.change(screen.getByLabelText("Statut déclaré"), { target: { value: "CANCELLED" } });
    fireEvent.change(screen.getByLabelText("Trier par"), { target: { value: "distance" } });
    fireEvent.change(screen.getByLabelText("Ordre"), { target: { value: "desc" } });
    fireEvent.click(screen.getByRole("button", { name: "Appliquer les filtres" }));

    await screen.findByText("Concert à Tyrosse");
    const url = new URL(String(fetchMock.mock.calls[1][0]), "http://testserver");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      sort: "distance",
      direction: "desc",
      limit: "12",
      offset: "0",
      q: "Tyrosse",
      max_distance_meters: "30000",
      date_from: "2027-07-12",
      date_to: "2028-07-17",
      category: "Concert",
      organizer: "Comité des fêtes",
      has_contact: "true",
      declared_status: "CANCELLED",
    });
    expect(
      fetchMock.mock.calls.every(
        ([path, init]) => String(path).startsWith("/api/v1/events?") && init?.method === undefined,
      ),
    ).toBe(true);
  });

  it("rejects an inverted date range before making a request", async () => {
    fetchMock.mockResolvedValueOnce(response(page([festival])));
    renderCatalog();
    await screen.findByText("Festival de Dax");
    fireEvent.change(screen.getByLabelText("À partir du"), { target: { value: "2027-08-01" } });
    fireEvent.change(screen.getByLabelText("Jusqu’au"), { target: { value: "2027-07-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Appliquer les filtres" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "La date de fin de recherche doit suivre ou égaler la date de début.",
    );
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("shows every period without inventing hours or confirming an organizer", async () => {
    fetchMock
      .mockResolvedValueOnce(response(page([festival])))
      .mockResolvedValueOnce(response(festivalDetail));
    renderCatalog();
    await screen.findByText("Festival de Dax");
    fireEvent.click(screen.getByRole("button", { name: "Ouvrir la fiche Festival de Dax" }));

    await screen.findByRole("heading", { name: "Dates et périodes" });
    expect(screen.getByText("12/07/2027")).toBeInTheDocument();
    expect(screen.getByText("Horaires non indiqués")).toBeInTheDocument();
    expect(screen.getByText("Du 15/07/2028 à 19:30 au 17/07/2028 à 23:00")).toBeInTheDocument();
    expect(screen.getByText("Portée inconnue · Contact général")).toBeInTheDocument();
    expect(screen.getByText("Non indiqué")).toBeInTheDocument();
    expect(screen.getByText("API DATAtourisme v1")).toBeInTheDocument();
    expect(screen.getByText("Producteur de la donnée : Office de tourisme")).toBeInTheDocument();
    expect(screen.getByText("Licence : Licence Ouverte 2.0")).toBeInTheDocument();
    expect(screen.getByText("Date de mise à jour source inconnue")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "https://festival.example" })).toHaveAttribute(
      "href",
      "https://festival.example/",
    );
    expect(fetchMock).toHaveBeenLastCalledWith(
      `/api/v1/events/${festival.id}`,
      expect.objectContaining({ credentials: "same-origin" }),
    );

    fireEvent.click(screen.getByRole("button", { name: "← Retour aux événements" }));
    expect(screen.getByRole("heading", { name: "Agenda local" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("preserves filters across pagination and resets them together", async () => {
    fetchMock
      .mockResolvedValueOnce(response(page([festival], 13)))
      .mockResolvedValueOnce(response(page([festival], 13)))
      .mockResolvedValueOnce(response(page([concert], 13, 12)))
      .mockResolvedValueOnce(response(page([festival], 13)));
    renderCatalog();
    await screen.findByText("Festival de Dax");
    fireEvent.change(screen.getByLabelText("À partir du"), { target: { value: "2027-07-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Appliquer les filtres" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Page suivante" })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Page suivante" }));
    await screen.findByText("Page 2 sur 2");
    expect(String(fetchMock.mock.lastCall?.[0])).toContain("offset=12&date_from=2027-07-01");

    fireEvent.click(screen.getByRole("button", { name: "Réinitialiser" }));
    await screen.findByText("Page 1 sur 2");
    expect(screen.getByLabelText("À partir du")).toHaveValue("");
    expect(String(fetchMock.mock.lastCall?.[0])).not.toContain("date_from");
  });

  it("discards an older response that arrives after a new search", async () => {
    let finishFirst: (value: Response) => void = () => {
      throw new Error("response not pending");
    };
    fetchMock
      .mockReturnValueOnce(
        new Promise<Response>((resolve) => {
          finishFirst = resolve;
        }),
      )
      .mockResolvedValueOnce(response(page([concert])));
    renderCatalog();
    fireEvent.click(screen.getByRole("button", { name: "Réinitialiser" }));
    await screen.findByText("Concert à Tyrosse");
    await act(async () => finishFirst(response(page([festival]))));
    expect(screen.queryByText("Festival de Dax")).not.toBeInTheDocument();
    expect(screen.getByText("Concert à Tyrosse")).toBeInTheDocument();
  });

  it.each(["list", "detail"] as const)(
    "handles an expired session during a %s read",
    async (stage) => {
      if (stage === "detail") fetchMock.mockResolvedValueOnce(response(page([festival])));
      fetchMock.mockResolvedValueOnce(
        response({ code: "authentication_required", message: "Session expirée." }, 401),
      );
      const authenticate = vi.fn();
      renderCatalog(authenticate);
      if (stage === "detail") {
        await screen.findByText("Festival de Dax");
        fireEvent.click(screen.getByRole("button", { name: "Ouvrir la fiche Festival de Dax" }));
      }
      await waitFor(() => expect(authenticate).toHaveBeenCalledOnce());
    },
  );

  it("displays unavailable and empty catalogues without collecting automatically", async () => {
    fetchMock
      .mockResolvedValueOnce(
        response({ code: "event_catalog_unavailable", message: "Catalogue indisponible." }, 503),
      )
      .mockResolvedValueOnce(response(page([])));
    renderCatalog();
    expect(await screen.findByRole("alert")).toHaveTextContent("Catalogue indisponible.");
    fireEvent.click(screen.getByRole("button", { name: "Réinitialiser" }));
    await screen.findByText("Aucun événement trouvé");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("renders external descriptions and unsafe links as text", async () => {
    fetchMock.mockResolvedValueOnce(response(page([festival]))).mockResolvedValueOnce(
      response({
        ...festivalDetail,
        description: "<script>alert('source')</script>",
        source_uri: "javascript:alert('source')",
        contacts: [{ ...festivalDetail.contacts[1], value: "javascript:alert('contact')" }],
      }),
    );
    const { container } = renderCatalog();
    await screen.findByText("Festival de Dax");
    fireEvent.click(screen.getByRole("button", { name: "Ouvrir la fiche Festival de Dax" }));
    await screen.findByText("<script>alert('source')</script>");
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText("javascript:alert('contact')")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
