import type { Index } from "../types/index.js";

/**
 * Loads the search index from /data/index.json relative to the app base URL.
 *
 * Rejects non-OK responses with the HTTP status, and rejects payloads whose
 * schemaVersion is not 1 with an error naming both the expected and actual version.
 */
export async function loadIndex(url?: string): Promise<Index> {
  const base = import.meta.env.BASE_URL.endsWith("/")
    ? import.meta.env.BASE_URL
    : `${import.meta.env.BASE_URL}/`;
  const targetUrl = url ?? `${base}data/index.json`;

  const response = await fetch(targetUrl);
  if (!response.ok) {
    throw new Error(`Failed to load search index: HTTP ${response.status.toString()}`);
  }

  const data = (await response.json()) as Partial<Index>;
  if (data.schemaVersion !== 1) {
    throw new Error(`Index schemaVersion mismatch: expected 1, got ${String(data.schemaVersion)}`);
  }

  return data as Index;
}
