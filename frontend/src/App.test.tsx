import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const session = { authenticated: true, display_name: "Radar" };
const geography = {
  reference_position: null,
  collection_radius_meters: 50_000,
  search_radius_meters: 50_000,
  updated_at: "2026-09-19T12:00:00Z",
};
const candidate = {
  id: "a81516f3-4d34-4d45-a9b6-3240e2143936",
  input_address: "12 rue Saint-Pierre 40100 Dax",
  normalized_label: "12 Rue Saint Pierre 40100 Dax",
  structured_address: {
    house_number: "12",
    street: "Rue Saint Pierre",
    postcode: "40100",
    city: "Dax",
    context: "40, Landes, Nouvelle-Aquitaine",
  },
  longitude: -1.051952,
  latitude: 43.70884,
  municipality_code: "40088",
  ban_id: "40088_1750_00012",
  result_type: "housenumber",
  score: 0.9653,
  provider_name: "Géoplateforme",
  provider_url: "https://data.geopf.fr/geocodage/search",
  geocoded_at: "2026-09-19T12:00:00Z",
  confirmed_at: null,
};
const collections = {
  connectors: [
    {
      connector: "SIRENE",
      available: true,
      active_job: null,
      latest_job: null,
      last_success_at: null,
      coverage: null,
    },
    {
      connector: "DATATOURISME",
      available: true,
      active_job: null,
      latest_job: null,
      last_success_at: null,
      coverage: null,
    },
  ],
};
const waitingJob = {
  id: "d24d7eef-1c58-4d0e-b8cb-8db5cb7671cd",
  cycle_id: "f7391956-d270-4621-b21f-e9374bf454e4",
  connector: "SIRENE",
  trigger: "MANUAL",
  state: "WAITING",
  reference_label: candidate.normalized_label,
  longitude: candidate.longitude,
  latitude: candidate.latitude,
  collection_radius_meters: 50_000,
  created_at: "2026-09-20T12:00:00Z",
  available_at: "2026-09-20T12:00:00Z",
  started_at: null,
  finished_at: null,
  heartbeat_at: null,
  attempt_count: 0,
  max_attempts: 3,
  progress: { stage: "waiting", processed: 0, total: null, observations: 0 },
  last_error: null,
};

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("authentication interface", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("shows the login screen when no valid session exists", async () => {
    fetchMock.mockResolvedValueOnce(
      response(
        {
          code: "authentication_required",
          message: "Une connexion valide est nécessaire.",
        },
        401,
      ),
    );

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Connexion" })).toBeInTheDocument();
    expect(screen.queryByText("Une connexion valide est nécessaire.")).not.toBeInTheDocument();
  });

  it("submits the unique-account password and opens the private screen", async () => {
    fetchMock
      .mockResolvedValueOnce(response({ code: "authentication_required" }, 401))
      .mockResolvedValueOnce(response(session))
      .mockResolvedValueOnce(response(geography))
      .mockResolvedValueOnce(response(collections));
    render(<App />);
    const password = await screen.findByLabelText("Mot de passe");

    fireEvent.change(password, { target: { value: "une phrase secrète assez longue" } });
    fireEvent.click(screen.getByRole("button", { name: "Se connecter" }));

    expect(await screen.findByText("Bonjour Radar")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/auth/login",
      expect.objectContaining({ method: "POST", credentials: "same-origin" }),
    );
  });

  it("changes the password with the CSRF cookie and confirms session revocation", async () => {
    // biome-ignore lint/suspicious/noDocumentCookie: jsdom has no Cookie Store API.
    document.cookie = "radar_csrf=csrf-value; Path=/";
    fetchMock
      .mockResolvedValueOnce(response(session))
      .mockResolvedValueOnce(response(geography))
      .mockResolvedValueOnce(response(collections))
      .mockResolvedValueOnce(response(session));
    render(<App />);
    await screen.findByText("Bonjour Radar");

    fireEvent.change(screen.getByLabelText("Mot de passe actuel"), {
      target: { value: "une phrase secrète assez longue" },
    });
    fireEvent.change(screen.getByLabelText("Nouveau mot de passe"), {
      target: { value: "une nouvelle phrase secrète valide" },
    });
    fireEvent.change(screen.getByLabelText("Confirmer le nouveau mot de passe"), {
      target: { value: "une nouvelle phrase secrète valide" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Enregistrer le nouveau mot de passe" }));

    expect(
      await screen.findByText(
        "Le mot de passe a été remplacé. Les autres sessions sont déconnectées.",
      ),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/auth/password",
        expect.objectContaining({
          headers: expect.objectContaining({ "X-CSRF-Token": "csrf-value" }),
        }),
      ),
    );
  });

  it("geocodes an address and requires confirmation before making it current", async () => {
    // biome-ignore lint/suspicious/noDocumentCookie: jsdom has no Cookie Store API.
    document.cookie = "radar_csrf=csrf-value; Path=/";
    fetchMock
      .mockResolvedValueOnce(response(session))
      .mockResolvedValueOnce(response(geography))
      .mockResolvedValueOnce(response(collections))
      .mockResolvedValueOnce(response(candidate))
      .mockResolvedValueOnce(
        response({
          ...geography,
          reference_position: { ...candidate, confirmed_at: "2026-09-19T12:01:00Z" },
        }),
      )
      .mockResolvedValueOnce(response(collections));
    render(<App />);
    await screen.findByRole("heading", { name: "Adresse de référence" });

    fireEvent.change(screen.getByLabelText("Adresse"), {
      target: { value: "12 rue Saint-Pierre 40100 Dax" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Vérifier l’adresse" }));

    expect(await screen.findByText("12 Rue Saint Pierre 40100 Dax")).toBeInTheDocument();
    expect(screen.queryByText("Position actuelle")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Confirmer cette position" }));

    expect(await screen.findByText("Position actuelle")).toBeInTheDocument();
    expect(
      screen.getByText("L'adresse de référence est confirmée. Aucune collecte n'a été lancée."),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/settings/geography/reference-position",
        expect.objectContaining({
          method: "POST",
          headers: expect.objectContaining({ "X-CSRF-Token": "csrf-value" }),
        }),
      ),
    );
  });

  it("updates the search radius without making a geocoding request", async () => {
    // biome-ignore lint/suspicious/noDocumentCookie: jsdom has no Cookie Store API.
    document.cookie = "radar_csrf=csrf-value; Path=/";
    fetchMock
      .mockResolvedValueOnce(response(session))
      .mockResolvedValueOnce(response(geography))
      .mockResolvedValueOnce(response(collections))
      .mockResolvedValueOnce(
        response({ ...geography, collection_radius_meters: 50_000, search_radius_meters: 30_000 }),
      )
      .mockResolvedValueOnce(response(collections));
    render(<App />);
    await screen.findByRole("heading", { name: "Adresse de référence" });

    fireEvent.change(screen.getByLabelText("Rayon de recherche (km)"), {
      target: { value: "30" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Enregistrer les rayons" }));

    expect(
      await screen.findByText("Les rayons ont été enregistrés sans nouvelle collecte."),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/settings/geography/radii",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({
          collection_radius_meters: 50_000,
          search_radius_meters: 30_000,
        }),
      }),
    );
    expect(fetchMock).toHaveBeenCalledTimes(5);
  });

  it("queues a manual collection and displays its durable waiting state", async () => {
    // biome-ignore lint/suspicious/noDocumentCookie: jsdom has no Cookie Store API.
    document.cookie = "radar_csrf=csrf-value; Path=/";
    const confirmedGeography = {
      ...geography,
      reference_position: { ...candidate, confirmed_at: "2026-09-19T12:01:00Z" },
    };
    const activeCollections = {
      connectors: [
        { ...collections.connectors[0], active_job: waitingJob, latest_job: waitingJob },
        collections.connectors[1],
      ],
    };
    fetchMock
      .mockResolvedValueOnce(response(session))
      .mockResolvedValueOnce(response(confirmedGeography))
      .mockResolvedValueOnce(response(collections))
      .mockResolvedValueOnce(response({ created: true, job: waitingJob }, 202))
      .mockResolvedValueOnce(response(activeCollections));
    render(<App />);
    await screen.findByRole("heading", { name: "Collectes" });

    fireEvent.click(screen.getAllByRole("button", { name: "Actualiser maintenant" })[0]);

    expect(
      await screen.findByText("La collecte SIRENE a été placée en attente."),
    ).toBeInTheDocument();
    expect(screen.getByText("En attente")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/collections/SIRENE",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "X-CSRF-Token": "csrf-value" }),
      }),
    );
  });

  it("opens the prospect catalogue without querying it before an address is confirmed", async () => {
    fetchMock
      .mockResolvedValueOnce(response(session))
      .mockResolvedValueOnce(response(geography))
      .mockResolvedValueOnce(response(collections));
    render(<App />);
    await screen.findByText("Bonjour Radar");

    fireEvent.click(screen.getByRole("button", { name: "Prospects" }));

    expect(await screen.findByRole("heading", { name: "Catalogue local" })).toBeInTheDocument();
    expect(screen.getByText(/Confirmez une adresse de référence/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);

    fireEvent.click(screen.getByRole("button", { name: "Configurer l’adresse" }));
    expect(
      await screen.findByRole("heading", { name: "Adresse de référence" }),
    ).toBeInTheDocument();
  });
});
