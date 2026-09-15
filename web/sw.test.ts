import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { collectPrecacheFiles, getCacheName } from "../vite.config.js";

describe("service worker precache and versioning", () => {
  const distDir = path.resolve(import.meta.dirname, "dist");
  const manifestPath = path.resolve(import.meta.dirname, "../data/dist/manifest.json");

  it("constructs cache name from manifest version and builtAt", () => {
    const rawManifest = fs.readFileSync(manifestPath, "utf-8");
    const manifest = JSON.parse(rawManifest) as { minecraftVersion: string; builtAt: string };
    const cacheName = getCacheName(manifestPath);

    expect(cacheName).toBe(`mc-fastwiki-${manifest.minecraftVersion}-${manifest.builtAt}`);
  });

  it("collects all 26 emitted files and excludes sw.js itself", () => {
    if (!fs.existsSync(distDir)) {
      return;
    }

    const precacheList = collectPrecacheFiles(distDir);

    // Shell (index.html), 2 assets (css, js), 5 root data files, 18 entity shards = 26 files
    expect(precacheList.length).toBe(26);
    expect(precacheList).not.toContain("sw.js");
    expect(precacheList).toContain("index.html");
    expect(precacheList).toContain("data/index.json");
    expect(precacheList).toContain("data/manifest.json");
    expect(precacheList).toContain("data/obtain.json");
    expect(precacheList).toContain("data/sprites.json");
    expect(precacheList).toContain("data/sprites.png");

    const shardEntries = precacheList.filter((f) => f.startsWith("data/entities/"));
    expect(shardEntries.length).toBe(18);

    // Every precached file must exist on disk
    for (const relPath of precacheList) {
      const fullPath = path.join(distDir, relPath);
      expect(fs.existsSync(fullPath)).toBe(true);
    }
  });

  it("emitted sw.js contains the precache list and cache name", () => {
    const swPath = path.join(distDir, "sw.js");
    if (!fs.existsSync(swPath)) {
      return;
    }

    const swContent = fs.readFileSync(swPath, "utf-8");
    const cacheName = getCacheName(manifestPath);

    expect(swContent).toContain(cacheName);
    expect(swContent).toContain("data/index.json");
    expect(swContent).toContain("index.html");
    expect(swContent).not.toContain("__PRECACHE_URLS__");
    expect(swContent).not.toContain("__CACHE_NAME__");
  });
});
