import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearObtainCache, clearShardCache, loadIndex, loadObtain, loadShard } from "./load.js";

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

describe("loadShard", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
    clearShardCache();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    clearShardCache();
  });

  it("loads and returns shard payload when valid", async () => {
    const mockShard = {
      schemaVersion: 1,
      entities: [
        {
          id: "minecraft:creeper",
          kind: "mob",
          name: "Creeper",
          blurb: "A common hostile mob.",
        },
      ],
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockShard),
    });

    const shard = await loadShard("mob-0");
    expect(shard.schemaVersion).toBe(1);
    expect(shard.entities).toHaveLength(1);
    expect((shard.entities[0] as { name: string }).name).toBe("Creeper");
  });

  it("rejects non-OK responses naming HTTP status", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
    });

    await expect(loadShard("mob-99")).rejects.toThrow("HTTP 404");
  });

  it("rejects when schemaVersion is not 1 naming both versions", async () => {
    const staleShard = {
      schemaVersion: 3,
      entities: [],
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(staleShard),
    });

    await expect(loadShard("mob-0")).rejects.toThrow(/expected 1.*got 3/i);
  });

  it("caches loaded shard in memory and avoids second fetch", async () => {
    const mockShard = {
      schemaVersion: 1,
      entities: [{ id: "minecraft:iron_ingot" }],
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockShard),
    });
    globalThis.fetch = fetchMock;

    const first = await loadShard("item-0");
    const second = await loadShard("item-0");

    expect(first).toBe(second);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("loadObtain", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
    clearObtainCache();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    clearObtainCache();
  });

  it("loads and returns obtain payload when valid", async () => {
    const mockObtain = {
      schemaVersion: 1,
      producers: {
        "minecraft:iron_ingot": [
          {
            m: "smelting",
            src: "smelting/iron_ingot",
            c: 1,
          },
        ],
      },
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockObtain),
    });

    const obtain = await loadObtain();
    expect(obtain.schemaVersion).toBe(1);
    expect(obtain.producers["minecraft:iron_ingot"]).toHaveLength(1);
  });

  it("rejects non-OK responses naming HTTP status", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
    });

    await expect(loadObtain()).rejects.toThrow("HTTP 404");
  });

  it("rejects when schemaVersion is not 1 naming both versions", async () => {
    const staleObtain = {
      schemaVersion: 2,
      producers: {},
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(staleObtain),
    });

    await expect(loadObtain()).rejects.toThrow(/expected 1.*got 2/i);
  });

  it("caches loaded obtain graph in memory and avoids second fetch", async () => {
    const mockObtain = {
      schemaVersion: 1,
      producers: {},
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockObtain),
    });
    globalThis.fetch = fetchMock;

    const first = await loadObtain();
    const second = await loadObtain();

    expect(first).toBe(second);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
