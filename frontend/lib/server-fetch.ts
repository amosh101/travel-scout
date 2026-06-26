import { type NextRequest, NextResponse } from "next/server";
import { apiFetch, ApiError } from "./api";

/**
 * Server-side helper for route handlers and server components.
 * Forwards the Authorization header from the incoming request.
 */
export async function serverFetch<T>(
  req: NextRequest,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const auth = req.headers.get("authorization") ?? undefined;
  try {
    return await apiFetch<T>(path, {
      ...init,
      accessToken: auth?.replace(/^Bearer\s+/i, ""),
      headers: { ...(init.headers ?? {}) },
    });
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      throw new NextResponse(
        JSON.stringify({ error: "unauthorized" }),
        { status: 401, headers: { "content-type": "application/json" } },
      );
    }
    throw err;
  }
}