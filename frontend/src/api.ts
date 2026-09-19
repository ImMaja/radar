export interface SessionView {
  authenticated: true;
  display_name: string | null;
}

export interface StructuredAddressView {
  house_number: string | null;
  street: string | null;
  postcode: string | null;
  city: string | null;
  context: string | null;
}

export interface ReferencePositionView {
  id: string;
  input_address: string;
  normalized_label: string;
  structured_address: StructuredAddressView;
  longitude: number;
  latitude: number;
  municipality_code: string;
  ban_id: string | null;
  result_type: string | null;
  score: number | null;
  provider_name: string;
  provider_url: string;
  geocoded_at: string;
  confirmed_at: string | null;
}

export interface ConnectorCoverageView {
  connector: "SIRENE" | "DATATOURISME";
  status: "NOT_COLLECTED";
  search_circle_covered: false;
}

export interface GeographySettingsView {
  reference_position: ReferencePositionView | null;
  collection_radius_meters: number;
  search_radius_meters: number;
  updated_at: string;
  coverage: ConnectorCoverageView[];
}

interface ErrorBody {
  code?: string;
  message?: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

function cookie(name: string): string | null {
  const prefix = `${encodeURIComponent(name)}=`;
  for (const part of document.cookie.split(";")) {
    const candidate = part.trim();
    if (candidate.startsWith(prefix)) {
      return decodeURIComponent(candidate.slice(prefix.length));
    }
  }
  return null;
}

function csrfToken(): string | null {
  return cookie("__Host-radar_csrf") ?? cookie("radar_csrf");
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...init.headers,
    },
  });

  if (!response.ok) {
    let error: ErrorBody = {};
    try {
      error = (await response.json()) as ErrorBody;
    } catch {
      // The stable fallback avoids exposing an unexpected server response.
    }
    throw new ApiError(
      response.status,
      error.code ?? "unexpected_error",
      error.message ?? "Une erreur inattendue est survenue.",
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

function jsonMutation(method: "POST" | "PUT" | "PATCH" | "DELETE", body: unknown): RequestInit {
  const csrf = csrfToken();
  return {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(csrf === null ? {} : { "X-CSRF-Token": csrf }),
    },
    body: JSON.stringify(body),
  };
}

export function getSession(): Promise<SessionView> {
  return request<SessionView>("/api/v1/auth/session");
}

export function logIn(password: string): Promise<SessionView> {
  return request<SessionView>("/api/v1/auth/login", jsonMutation("POST", { password }));
}

export function logOut(): Promise<void> {
  return request<void>("/api/v1/auth/logout", jsonMutation("POST", {}));
}

export function changePassword(
  currentPassword: string,
  newPassword: string,
  confirmation: string,
): Promise<SessionView> {
  return request<SessionView>(
    "/api/v1/auth/password",
    jsonMutation("POST", {
      current_password: currentPassword,
      new_password: newPassword,
      confirmation,
    }),
  );
}

export function getGeographySettings(): Promise<GeographySettingsView> {
  return request<GeographySettingsView>("/api/v1/settings/geography");
}

export function geocodeReferenceAddress(address: string): Promise<ReferencePositionView> {
  return request<ReferencePositionView>(
    "/api/v1/settings/geography/geocodings",
    jsonMutation("POST", { address }),
  );
}

export function confirmReferencePosition(candidateId: string): Promise<GeographySettingsView> {
  return request<GeographySettingsView>(
    "/api/v1/settings/geography/reference-position",
    jsonMutation("POST", { candidate_id: candidateId }),
  );
}

export function updateGeographyRadii(
  collectionRadiusMeters: number,
  searchRadiusMeters: number,
): Promise<GeographySettingsView> {
  return request<GeographySettingsView>(
    "/api/v1/settings/geography/radii",
    jsonMutation("PATCH", {
      collection_radius_meters: collectionRadiusMeters,
      search_radius_meters: searchRadiusMeters,
    }),
  );
}
