import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProspectCatalog } from "./ProspectCatalog";

const alpha = {
  id: "341c6040-ec7d-45aa-b8c4-af65ea3f3b2f",
  display_name: "Boulangerie Alpha",
  organization_type: "UNKNOWN",
  activity_code: "10.71C",
  activity_nomenclature: "NAFRev2",
  activity_label: null,
  employee_band: "12",
  employee_year: 2024,
  employee_scope: "LOCAL",
  address: {
    full_address: "12 RUE SAINT PIERRE 40100 DAX",
    street_number: "12",
    repetition_index: null,
    street_type: "RUE",
    street_label: "SAINT PIERRE",
    address_complement: null,
    postcode: "40100",
    municipality: "DAX",
    municipality_code: "40088",
  },
  distance_meters: 125.4,
  location_status: "located",
  location_precision: "ADDRESS",
  last_observed_at: "2026-09-22T12:00:00Z",
};

const beta = {
  ...alpha,
  id: "9d38002d-977e-49ce-8540-d3f1f510381d",
  display_name: "Entrepôt Beta",
  activity_code: "52.10B",
  employee_band: "22",
  address: {
    ...alpha.address,
    full_address: "1 RUE EXEMPLE 40230 SAINT-VINCENT-DE-TYROSSE",
    municipality: "SAINT-VINCENT-DE-TYROSSE",
    municipality_code: "40284",
  },
  distance_meters: 22_450,
};

const unknown = {
  ...alpha,
  id: "476069b1-96f0-4b25-9858-b4d069822a5e",
  display_name: "Adresse inconnue",
  distance_meters: null,
  location_status: "to_verify",
  location_precision: "UNKNOWN",
};

const alphaDetail = {
  ...alpha,
  description: null,
  siret: "12345678901234",
  siren: "123456789",
  legal_name: "Société exemple",
  usual_name: null,
  legal_category: "5710",
  is_head_office: false,
  eligibility: "ELIGIBLE",
  eligibility_reason: "SIRENE_FULL_PUBLIC_DIFFUSION",
  established_on: "2020-01-02",
  current_period_started_on: "2024-03-04",
  longitude: -1.051,
  latitude: 43.708,
  location_origin: "SIRENE_API",
  location_quality_code: null,
  location_match_score: null,
  first_observed_at: "2026-09-20T12:00:00Z",
  sources: [
    {
      code: "SIRENE_API",
      name: "API Sirene 3.11",
      authority: "INSEE",
      producer_name: "INSEE",
      state: "CURRENT",
      first_observed_at: "2026-09-20T12:00:00Z",
      last_observed_at: "2026-09-22T12:00:00Z",
      retrieved_at: "2026-09-22T12:00:00Z",
      source_updated_at: "2026-09-22T10:00:00Z",
    },
  ],
};

function page(items: unknown[], total = items.length, offset = 0) {
  return {
    items,
    total,
    limit: 12,
    offset,
    applied_radius_meters: 30_000,
  };
}

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("prospect catalogue", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("does not query the catalogue before a reference position is confirmed", () => {
    const configure = vi.fn();
    render(
      <ProspectCatalog
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

  it("loads local prospects and sends explicit search filters", async () => {
    fetchMock
      .mockResolvedValueOnce(response(page([alpha, beta], 2)))
      .mockResolvedValueOnce(response(page([beta], 1)));
    render(
      <ProspectCatalog
        hasReferencePosition
        configuredRadiusMeters={30_000}
        onConfigure={vi.fn()}
        onAuthenticationRequired={vi.fn()}
      />,
    );
    await screen.findByText("Boulangerie Alpha");

    fireEvent.change(screen.getByLabelText("Nom ou commune"), {
      target: { value: "Tyrosse" },
    });
    fireEvent.change(screen.getByLabelText("Distance maximale (km)"), {
      target: { value: "30" },
    });
    fireEvent.click(screen.getByText("Filtres avancés"));
    fireEvent.change(screen.getByLabelText("Code d’activité"), {
      target: { value: "52.10B" },
    });
    fireEvent.change(screen.getByLabelText("Trier par"), { target: { value: "name" } });
    fireEvent.change(screen.getByLabelText("Ordre"), { target: { value: "desc" } });
    fireEvent.click(screen.getByRole("button", { name: "Appliquer les filtres" }));

    expect(await screen.findByText("Entrepôt Beta")).toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMock).toHaveBeenLastCalledWith(
        "/api/v1/prospects?location=located&sort=name&direction=desc&limit=12&offset=0&q=Tyrosse&max_distance_meters=30000&activity_code=52.10B",
        expect.objectContaining({ credentials: "same-origin" }),
      ),
    );
  });

  it("keeps unknown locations separate and omits the distance filter", async () => {
    fetchMock
      .mockResolvedValueOnce(response(page([alpha], 1)))
      .mockResolvedValueOnce(response(page([alpha], 1)))
      .mockResolvedValueOnce(response(page([unknown], 1)));
    render(
      <ProspectCatalog
        hasReferencePosition
        configuredRadiusMeters={30_000}
        onConfigure={vi.fn()}
        onAuthenticationRequired={vi.fn()}
      />,
    );
    await screen.findByText("Boulangerie Alpha");

    fireEvent.change(screen.getByLabelText("Distance maximale (km)"), {
      target: { value: "15" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Appliquer les filtres" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    fireEvent.click(screen.getByRole("button", { name: "Localisation à vérifier" }));

    expect(await screen.findByText("Adresse inconnue")).toBeInTheDocument();
    expect(screen.getByText("Distance inconnue")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/v1/prospects?location=to_verify&sort=name&direction=asc&limit=12&offset=0",
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("opens a detailed fiche with identity and provenance", async () => {
    fetchMock
      .mockResolvedValueOnce(response(page([alpha], 1)))
      .mockResolvedValueOnce(response(alphaDetail));
    render(
      <ProspectCatalog
        hasReferencePosition
        configuredRadiusMeters={30_000}
        onConfigure={vi.fn()}
        onAuthenticationRequired={vi.fn()}
      />,
    );
    await screen.findByText("Boulangerie Alpha");

    fireEvent.click(screen.getByRole("button", { name: "Ouvrir la fiche Boulangerie Alpha" }));

    expect(
      await screen.findByRole("heading", { name: "Identité et activité" }),
    ).toBeInTheDocument();
    expect(screen.getByText("12345678901234")).toBeInTheDocument();
    expect(screen.getByText("API Sirene 3.11")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenLastCalledWith(
      `/api/v1/prospects/${alpha.id}`,
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("paginates without changing the active filters", async () => {
    fetchMock
      .mockResolvedValueOnce(response(page([alpha], 13)))
      .mockResolvedValueOnce(response(page([beta], 13, 12)));
    render(
      <ProspectCatalog
        hasReferencePosition
        configuredRadiusMeters={30_000}
        onConfigure={vi.fn()}
        onAuthenticationRequired={vi.fn()}
      />,
    );
    await screen.findByText("Page 1 sur 2");

    fireEvent.click(screen.getByRole("button", { name: "Page suivante" }));

    expect(await screen.findByText("Page 2 sur 2")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/v1/prospects?location=located&sort=distance&direction=asc&limit=12&offset=12",
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });
});
