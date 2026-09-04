import type { Atlas } from "../types/atlas.js";
import type { Index } from "../types/index.js";
import type { Shard } from "../types/shard.js";

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

const shardCache = new Map<string, Promise<Shard>>();

/**
 * Loads an entity shard from /data/entities/<shardName>.json relative to the app base URL.
 *
 * Caches loaded shards in memory so repeated requests for the same shard
 * do not perform duplicate fetches.
 *
 * Rejects non-OK responses with the HTTP status, and rejects payloads whose
 * schemaVersion is not 1 with an error naming both the expected and actual version.
 */
export async function loadShard(shardName: string, url?: string): Promise<Shard> {
  if (!url) {
    const cached = shardCache.get(shardName);
    if (cached) {
      return cached;
    }
  }

  const base = import.meta.env.BASE_URL.endsWith("/")
    ? import.meta.env.BASE_URL
    : `${import.meta.env.BASE_URL}/`;
  const targetUrl = url ?? `${base}data/entities/${shardName}.json`;

  const promise = (async () => {
    const response = await fetch(targetUrl);
    if (!response.ok) {
      throw new Error(`Failed to load shard ${shardName}: HTTP ${response.status.toString()}`);
    }

    const data = (await response.json()) as Partial<Shard>;
    if (data.schemaVersion !== 1) {
      throw new Error(
        `Shard schemaVersion mismatch: expected 1, got ${String(data.schemaVersion)}`,
      );
    }

    return data as Shard;
  })();

  if (!url) {
    shardCache.set(shardName, promise);
  }

  return promise;
}

/**
 * Clears the in-memory shard cache. Useful in tests.
 */
export function clearShardCache(): void {
  shardCache.clear();
}

let atlasPromise: Promise<Atlas> | null = null;

/**
 * Loads the sprite atlas coordinate map from /data/sprites.json.
 */
export async function loadAtlas(url?: string): Promise<Atlas> {
  if (!url && atlasPromise) {
    return atlasPromise;
  }

  const base = import.meta.env.BASE_URL.endsWith("/")
    ? import.meta.env.BASE_URL
    : `${import.meta.env.BASE_URL}/`;
  const targetUrl = url ?? `${base}data/sprites.json`;

  const promise = (async () => {
    const response = await fetch(targetUrl);
    if (!response.ok) {
      throw new Error(`Failed to load sprite atlas: HTTP ${response.status.toString()}`);
    }

    const data = (await response.json()) as Partial<Atlas>;
    if (data.schemaVersion !== 1) {
      throw new Error(
        `Atlas schemaVersion mismatch: expected 1, got ${String(data.schemaVersion)}`,
      );
    }

    return data as Atlas;
  })();

  if (!url) {
    atlasPromise = promise;
  }

  return promise;
}

export function clearAtlasCache(): void {
  atlasPromise = null;
}
