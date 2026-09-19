import { type FormEvent, useEffect, useState } from "react";

import {
  ApiError,
  changePassword,
  confirmReferencePosition,
  type GeographySettingsView,
  geocodeReferenceAddress,
  getGeographySettings,
  getSession,
  logIn,
  logOut,
  type ReferencePositionView,
  type SessionView,
  updateGeographyRadii,
} from "./api";

type AppState =
  | { phase: "loading" }
  | { phase: "anonymous" }
  | { phase: "authenticated"; session: SessionView };

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Une erreur inattendue est survenue.";
}

export function App() {
  const [state, setState] = useState<AppState>({ phase: "loading" });
  const [message, setMessage] = useState<string | null>(null);
  const [geography, setGeography] = useState<GeographySettingsView | null>(null);
  const [candidate, setCandidate] = useState<ReferencePositionView | null>(null);
  const [geographyBusy, setGeographyBusy] = useState(false);

  useEffect(() => {
    let active = true;
    getSession()
      .then(async (session) => {
        if (!active) return;
        setState({ phase: "authenticated", session });
        try {
          const settings = await getGeographySettings();
          if (active) setGeography(settings);
        } catch (error) {
          if (!active) return;
          if (error instanceof ApiError && error.status === 401) {
            setState({ phase: "anonymous" });
          } else {
            setMessage(errorMessage(error));
          }
        }
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (error instanceof ApiError && error.status === 401) {
          setState({ phase: "anonymous" });
        } else {
          setMessage(errorMessage(error));
          setState({ phase: "anonymous" });
        }
      });
    return () => {
      active = false;
    };
  }, []);

  async function submitLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    try {
      const session = await logIn(String(form.get("password") ?? ""));
      formElement.reset();
      setState({ phase: "authenticated", session });
      setGeography(await getGeographySettings());
    } catch (error) {
      setMessage(errorMessage(error));
    }
  }

  async function submitPasswordChange(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    try {
      const session = await changePassword(
        String(form.get("currentPassword") ?? ""),
        String(form.get("newPassword") ?? ""),
        String(form.get("confirmation") ?? ""),
      );
      formElement.reset();
      setState({ phase: "authenticated", session });
      setMessage("Le mot de passe a été remplacé. Les autres sessions sont déconnectées.");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setState({ phase: "anonymous" });
      }
      setMessage(errorMessage(error));
    }
  }

  async function submitLogout() {
    setMessage(null);
    try {
      await logOut();
      setState({ phase: "anonymous" });
      setGeography(null);
      setCandidate(null);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setState({ phase: "anonymous" });
      } else {
        setMessage(errorMessage(error));
      }
    }
  }

  async function submitAddress(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    setCandidate(null);
    setGeographyBusy(true);
    const form = new FormData(event.currentTarget);
    try {
      setCandidate(await geocodeReferenceAddress(String(form.get("address") ?? "")));
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setGeographyBusy(false);
    }
  }

  async function confirmCandidate() {
    if (candidate === null) return;
    setMessage(null);
    setGeographyBusy(true);
    try {
      setGeography(await confirmReferencePosition(candidate.id));
      setCandidate(null);
      setMessage("L'adresse de référence est confirmée. Aucune collecte n'a été lancée.");
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setGeographyBusy(false);
    }
  }

  async function submitRadii(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    setGeographyBusy(true);
    const form = new FormData(event.currentTarget);
    const collectionKilometers = Number(form.get("collectionRadius"));
    const searchKilometers = Number(form.get("searchRadius"));
    try {
      setGeography(
        await updateGeographyRadii(
          Math.round(collectionKilometers * 1000),
          Math.round(searchKilometers * 1000),
        ),
      );
      setMessage("Les rayons ont été enregistrés sans nouvelle collecte.");
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setGeographyBusy(false);
    }
  }

  return (
    <main className="shell">
      <header className="brand">
        <span className="brand-mark" aria-hidden="true">
          R
        </span>
        <div>
          <p className="eyebrow">Food truck · Opportunités locales</p>
          <h1>Radar</h1>
        </div>
      </header>

      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}

      {state.phase === "loading" && <p className="loading">Vérification de la session…</p>}

      {state.phase === "anonymous" && (
        <section className="panel login-panel" aria-labelledby="login-title">
          <p className="section-label">Accès privé</p>
          <h2 id="login-title">Connexion</h2>
          <p className="hint">Utilisez le mot de passe du compte unique Radar.</p>
          <form onSubmit={submitLogin}>
            <label htmlFor="password">Mot de passe</label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              maxLength={128}
              required
            />
            <button type="submit">Se connecter</button>
          </form>
        </section>
      )}

      {state.phase === "authenticated" && (
        <div className="private-layout">
          <section className="welcome" aria-labelledby="welcome-title">
            <p className="section-label">Session active</p>
            <h2 id="welcome-title">
              {state.session.display_name
                ? `Bonjour ${state.session.display_name}`
                : "Bienvenue dans Radar"}
            </h2>
            <p>
              Définissez le centre des futures collectes. Les opportunités seront ajoutées dans les
              prochains jalons.
            </p>
            <button className="secondary" type="button" onClick={submitLogout}>
              Se déconnecter
            </button>
          </section>

          <div className="settings-stack">
            <section className="panel" aria-labelledby="geography-title">
              <p className="section-label">Zone de travail</p>
              <h2 id="geography-title">Adresse de référence</h2>

              {geography === null ? (
                <p className="loading">Chargement des réglages…</p>
              ) : (
                <>
                  {geography.reference_position ? (
                    <div className="current-position">
                      <span>Position actuelle</span>
                      <strong>{geography.reference_position.normalized_label}</strong>
                      <small>
                        {geography.reference_position.latitude.toFixed(6)},{" "}
                        {geography.reference_position.longitude.toFixed(6)} · code commune{" "}
                        {geography.reference_position.municipality_code}
                      </small>
                      <small>Source : {geography.reference_position.provider_name}</small>
                    </div>
                  ) : (
                    <p className="hint">Aucune adresse n’est encore confirmée.</p>
                  )}

                  <form onSubmit={submitAddress}>
                    <label htmlFor="address">
                      {geography.reference_position ? "Rechercher une autre adresse" : "Adresse"}
                    </label>
                    <input
                      id="address"
                      name="address"
                      type="text"
                      autoComplete="street-address"
                      minLength={3}
                      maxLength={300}
                      placeholder="12 rue Saint-Pierre, 40100 Dax"
                      required
                    />
                    <button type="submit" disabled={geographyBusy}>
                      Vérifier l’adresse
                    </button>
                  </form>

                  {candidate && (
                    <article className="candidate" aria-labelledby="candidate-title">
                      <p className="section-label">Résultat à confirmer</p>
                      <h3 id="candidate-title">{candidate.normalized_label}</h3>
                      <dl>
                        <div>
                          <dt>Commune</dt>
                          <dd>{candidate.structured_address.city ?? "Non indiquée"}</dd>
                        </div>
                        <div>
                          <dt>Coordonnées</dt>
                          <dd>
                            {candidate.latitude.toFixed(6)}, {candidate.longitude.toFixed(6)}
                          </dd>
                        </div>
                        <div>
                          <dt>Confiance</dt>
                          <dd>
                            {candidate.score === null
                              ? "Non indiquée"
                              : `${Math.round(candidate.score * 100)} %`}
                          </dd>
                        </div>
                        <div>
                          <dt>Source</dt>
                          <dd>{candidate.provider_name}</dd>
                        </div>
                      </dl>
                      <p className="hint">
                        Vérifiez ce libellé et ces coordonnées avant de les utiliser comme centre.
                      </p>
                      <button type="button" onClick={confirmCandidate} disabled={geographyBusy}>
                        Confirmer cette position
                      </button>
                    </article>
                  )}

                  <form className="radii-form" onSubmit={submitRadii}>
                    <div className="field-pair">
                      <div>
                        <label htmlFor="collectionRadius">Rayon de collecte (km)</label>
                        <input
                          key={`collection-${geography.collection_radius_meters}`}
                          id="collectionRadius"
                          name="collectionRadius"
                          type="number"
                          min="0.001"
                          max="50"
                          step="0.001"
                          defaultValue={geography.collection_radius_meters / 1000}
                          required
                        />
                      </div>
                      <div>
                        <label htmlFor="searchRadius">Rayon de recherche (km)</label>
                        <input
                          key={`search-${geography.search_radius_meters}`}
                          id="searchRadius"
                          name="searchRadius"
                          type="number"
                          min="0.001"
                          max="50"
                          step="0.001"
                          defaultValue={geography.search_radius_meters / 1000}
                          required
                        />
                      </div>
                    </div>
                    <button type="submit" className="secondary" disabled={geographyBusy}>
                      Enregistrer les rayons
                    </button>
                  </form>

                  {geography.reference_position ? (
                    <p className="coverage-warning" role="status">
                      Aucune collecte réussie ne couvre encore cette zone. Les futures données ne
                      seront considérées comme complètes qu’après une collecte réussie pour chaque
                      source.
                    </p>
                  ) : (
                    <p className="coverage-warning" role="status">
                      Confirmez d’abord une adresse pour définir le centre des futures collectes.
                    </p>
                  )}
                </>
              )}
            </section>

            <section className="panel" aria-labelledby="password-title">
              <p className="section-label">Réglages du compte</p>
              <h2 id="password-title">Changer le mot de passe</h2>
              <p className="hint">Utilisez une phrase d’au moins 15 caractères.</p>
              <form onSubmit={submitPasswordChange}>
                <label htmlFor="currentPassword">Mot de passe actuel</label>
                <input
                  id="currentPassword"
                  name="currentPassword"
                  type="password"
                  autoComplete="current-password"
                  maxLength={128}
                  required
                />

                <label htmlFor="newPassword">Nouveau mot de passe</label>
                <input
                  id="newPassword"
                  name="newPassword"
                  type="password"
                  autoComplete="new-password"
                  minLength={15}
                  maxLength={128}
                  required
                />

                <label htmlFor="confirmation">Confirmer le nouveau mot de passe</label>
                <input
                  id="confirmation"
                  name="confirmation"
                  type="password"
                  autoComplete="new-password"
                  minLength={15}
                  maxLength={128}
                  required
                />
                <button type="submit">Enregistrer le nouveau mot de passe</button>
              </form>
            </section>
          </div>
        </div>
      )}
    </main>
  );
}
