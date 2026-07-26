/**
 * API client. Base URL via NEXT_PUBLIC_API_URL; no hardcoded hostnames.
 * Throws ApiError on non-2xx so callers can handle uniformly.
 */

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface FetchOpts extends Omit<RequestInit, "body"> {
  body?: unknown;
  accessToken?: string;
}

export async function apiFetch<T>(
  path: string,
  { body, accessToken, headers, ...rest }: FetchOpts = {},
): Promise<T> {
  const url = path.startsWith("http") ? path : `${BASE_URL}${path}`;
  // If the caller didn't pass a token, try to read it from localStorage.
  // This keeps the api client usable outside React (e.g. in loaders) and
  // means components don't have to thread the token everywhere.
  let token = accessToken;
  if (!token && typeof window !== "undefined") {
    try {
      token = window.localStorage.getItem("travel_scout_token") ?? undefined;
    } catch {
      // ignore
    }
  }
  const init: RequestInit = {
    ...rest,
    headers: {
      // Skip the default JSON Content-Type if the caller is sending a
      // FormData (the browser sets the multipart boundary itself).
      ...(body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(headers ?? {}),
    },
  };
  if (body !== undefined) {
    // FormData goes through as-is (don't stringify). Strings go through
    // verbatim (the caller already serialised). Anything else (plain
    // object) gets JSON-encoded.
    if (body instanceof FormData || typeof body === "string") {
      init.body = body;
    } else {
      init.body = JSON.stringify(body);
    }
  }
  const res = await fetch(url, init);
  if (!res.ok) {
    let parsed: unknown;
    try {
      parsed = await res.json();
    } catch {
      parsed = await res.text();
    }
    throw new ApiError(`HTTP ${res.status} on ${path}`, res.status, parsed);
  }
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") ?? "";
  if (ct.includes("application/json")) {
    return (await res.json()) as T;
  }
  return (await res.text()) as unknown as T;
}