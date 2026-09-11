import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const session = { authenticated: true, display_name: "Radar" };

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
      .mockResolvedValueOnce(response(session));
    render(<App />);
    const password = await screen.findByLabelText("Mot de passe");

    fireEvent.change(password, { target: { value: "une phrase secrète assez longue" } });
    fireEvent.click(screen.getByRole("button", { name: "Se connecter" }));

    expect(await screen.findByText("Bonjour Radar")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/v1/auth/login",
      expect.objectContaining({ method: "POST", credentials: "same-origin" }),
    );
  });

  it("changes the password with the CSRF cookie and confirms session revocation", async () => {
    // biome-ignore lint/suspicious/noDocumentCookie: jsdom has no Cookie Store API.
    document.cookie = "radar_csrf=csrf-value; Path=/";
    fetchMock.mockResolvedValueOnce(response(session)).mockResolvedValueOnce(response(session));
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
      expect(fetchMock).toHaveBeenLastCalledWith(
        "/api/v1/auth/password",
        expect.objectContaining({
          headers: expect.objectContaining({ "X-CSRF-Token": "csrf-value" }),
        }),
      ),
    );
  });
});
