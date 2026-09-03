import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { loadIndex } from "./load.js";

describe("loadIndex", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("loads and returns index payload when valid", async () => {
    const mockIndex = {
      schemaVersion: 1,
      entities: [
        {
          id: "minecraft:stone",
          n: "Stone",
          k: "block",
          a: [],
          s: "block-0",
        },
      ],
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockIndex),
    });

    const index = await loadIndex();
    expect(index.schemaVersion).toBe(1);
    expect(index.entities).toHaveLength(1);
    expect(index.entities[0].n).toBe("Stone");
  });

  it("rejects non-OK responses naming HTTP status", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
    });

    await expect(loadIndex()).rejects.toThrow("HTTP 404");
  });

  it("rejects when schemaVersion is not 1 naming both versions", async () => {
    const staleIndex = {
      schemaVersion: 2,
      entities: [],
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(staleIndex),
    });

    await expect(loadIndex()).rejects.toThrow(/expected 1.*got 2/i);
  });
});
