import { type FormEvent, useEffect, useState } from "react";

import { ApiError, changePassword, getSession, logIn, logOut, type SessionView } from "./api";

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

  useEffect(() => {
    let active = true;
    getSession()
      .then((session) => {
        if (active) setState({ phase: "authenticated", session });
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
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setState({ phase: "anonymous" });
      } else {
        setMessage(errorMessage(error));
      }
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
            <p>Le catalogue d’opportunités sera ajouté dans les prochains jalons.</p>
            <button className="secondary" type="button" onClick={submitLogout}>
              Se déconnecter
            </button>
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
      )}
    </main>
  );
}
