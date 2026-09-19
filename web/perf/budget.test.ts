/**
 * Performance Budget Enforcement
 *
 * This test enforces the two central performance promises of MC-FastWiki:
 *
 * 1. Keystroke Budget:
 *    - Product promise: <= 16 ms per keystroke (60 fps frame budget).
 *    - Gate threshold: <= 35 ms (headroom to prevent CI runner noise flaking).
 *
 * 2. Rendered Window Budget:
 *    - Product promise: <= 100 ms to open and render an entity window.
 *    - Gate threshold: <= 180 ms (headroom to prevent CI runner noise flaking).
 *
 * Both tests measure over real committed data (index.json, obtain.json, and entity
 * shards), and both aggregate in two steps: the FASTEST of several iterations per
 * subject, then the MEDIAN across subjects.
 *
 * The per-subject minimum is what makes this a measurement of the code rather than
 * of the machine. Each iteration runs identical deterministic work, so every
 * millisecond above the fastest one is scheduling delay, a GC pause, or a sibling
 * Vitest worker holding the CPU -- never the algorithm. Taking the median of raw
 * samples does not remove that: `pnpm test` runs this file alongside 27 others on a
 * pool of workers, and under that load the median of every sample more than doubled
 * and tripped a gate with 2x headroom, while the same code measured 3.8 ms when the
 * file ran alone. The minimum per subject is the closest estimate of the cost a
 * user's idle browser pays.
 *
 * Taking the median ACROSS subjects afterwards is what keeps the test honest: it
 * still asks "what does a typical keystroke cost", so one query that got genuinely
 * slower still moves the number, and a global minimum -- which would just report the
 * single cheapest query -- would not.
 */

import fs from "node:fs";
import path from "node:path";
import { beforeAll, describe, expect, it, vi } from "vitest";

import type { Index, IndexEntry } from "../types/index.js";
import type { Obtain } from "../types/obtain.js";
import type { Shard } from "../types/shard.js";
import type { RenderContext } from "../render/context.js";
import { renderEntity } from "../render/entity.js";
import { type Corpus, buildCorpus, search } from "../search/matcher.js";

// Product budgets and gating thresholds
const PRODUCT_KEYSTROKE_BUDGET_MS = 16;
const GATE_KEYSTROKE_THRESHOLD_MS = 35;

const PRODUCT_RENDER_BUDGET_MS = 100;
const GATE_RENDER_THRESHOLD_MS = 180;

// Written straight to stdout rather than through `console.log`. Vitest
// intercepts console output and, under the default reporter that `pnpm test`
// and CI both use, drops it for a passing test -- so a `console.log` here
// prints the figure only when the gate has already failed, which is the one
// run where the number is least useful. `process.stdout.write` bypasses the
// interception, so every run reports what it measured.
function reportBudget(line: string): void {
  process.stdout.write(`${line}\n`);
}

/** Return the smallest value, or 0 for an empty list. */
function fastest(values: number[]): number {
  let best = Number.POSITIVE_INFINITY;
  for (const value of values) {
    if (value < best) best = value;
  }
  return Number.isFinite(best) ? best : 0;
}

function computeMedian(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  const midVal = sorted[mid];
  if (midVal === undefined) return 0;
  if (sorted.length % 2 !== 0) {
    return midVal;
  }
  const prevVal = sorted[mid - 1];
  if (prevVal === undefined) return midVal;
  return (prevVal + midVal) / 2;
}

describe("Performance budgets: 16 ms keystroke and 100 ms window render", () => {
  let realIndex: Index;
  let corpus: Corpus;
  let idMap: Map<string, IndexEntry>;
  let nameMap: Map<string, IndexEntry>;
  let shardsByName: Map<string, Shard>;
  let obtainGraph: Obtain;
  let ctx: RenderContext;

  beforeAll(() => {
    const root = process.cwd();
    const indexPath = path.resolve(root, "data/dist/index.json");
    realIndex = JSON.parse(fs.readFileSync(indexPath, "utf-8")) as Index;
    corpus = buildCorpus(realIndex);

    idMap = new Map();
    nameMap = new Map();
    for (const entry of realIndex.entities) {
      idMap.set(entry.id, entry);
      if (!nameMap.has(entry.n.toLowerCase())) {
        nameMap.set(entry.n.toLowerCase(), entry);
      }
    }

    const obtainPath = path.resolve(root, "data/dist/obtain.json");
    obtainGraph = JSON.parse(fs.readFileSync(obtainPath, "utf-8")) as Obtain;

    // Load all entity shards into memory
    shardsByName = new Map();
    const entitiesDir = path.resolve(root, "data/dist/entities");
    for (const fileName of fs.readdirSync(entitiesDir)) {
      if (fileName.endsWith(".json")) {
        const shardName = fileName.replace(".json", "");
        const raw = fs.readFileSync(path.join(entitiesDir, fileName), "utf-8");
        shardsByName.set(shardName, JSON.parse(raw) as Shard);
      }
    }

    ctx = {
      openRef: vi.fn(),
      lookup: (id: string) => {
        return (
          idMap.get(id) ??
          nameMap.get(id.toLowerCase()) ??
          idMap.get(`minecraft:${id.toLowerCase().replace(/\s+/g, "_")}`) ??
          null
        );
      },
    };

    // Mock fetch to serve real data from memory without network latency
    vi.stubGlobal("fetch", (input: string | URL | Request) => {
      const urlStr =
        typeof input === "string" ? input : input instanceof URL ? input.href : input.url;

      if (urlStr.includes("data/obtain.json")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(obtainGraph),
        });
      }
      const match = /data\/entities\/([a-zA-Z0-9_-]+)\.json/.exec(urlStr);
      if (match && match[1]) {
        const shard = shardsByName.get(match[1]);
        if (shard) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: () => Promise.resolve(shard),
          });
        }
      }
      return Promise.resolve({
        ok: false,
        status: 404,
        json: () => Promise.resolve({}),
      });
    });
  });

  // An explicit timeout with room to spare. The measurement is cheap, but the
  // loop runs while 27 other test files compete for the same worker pool, and a
  // gate that reports 2 ms and then fails on Vitest's 5 s default is a flake
  // that says nothing about the product.
  it(
    "enforces keystroke matching budget (16 ms product budget, 35 ms gate)",
    { timeout: 30_000 },
    () => {
      // Keystroke sequence simulating real user searches
      const querySequences = [
        "d",
        "di",
        "dia",
        "diam",
        "diamo",
        "diamon",
        "diamond",
        "diamond sword",
        "c",
        "cr",
        "cre",
        "cree",
        "creep",
        "creeper",
        "g",
        "go",
        "gol",
        "gold",
        "golden",
        "golden apple",
        "b",
        "bl",
        "bla",
        "blas",
        "blast furnace",
        "z",
        "zo",
        "zom",
        "zomb",
        "zombie",
        "o",
        "oa",
        "oak",
        "oak planks",
        "p",
        "po",
        "pot",
        "potato",
        "m",
        "mu",
        "mus",
        "music disc",
      ];

      // Warm up
      for (const q of querySequences.slice(0, 10)) {
        search(corpus, q);
      }

      // Eight passes, not twenty. A minimum converges on the uncontended cost in a
      // handful of passes, where a median of raw samples needed many to be stable.
      const ITERATIONS = 8;
      const perQuery = new Map<string, number[]>();

      for (let iter = 0; iter < ITERATIONS; iter++) {
        for (const query of querySequences) {
          const start = performance.now();
          search(corpus, query);
          const end = performance.now();
          const samples = perQuery.get(query) ?? [];
          samples.push(end - start);
          perQuery.set(query, samples);
        }
      }

      const durations = [...perQuery.values()].map(fastest);
      const median = computeMedian(durations);
      reportBudget(
        `[Budget] Matcher keystroke latency median: ${median.toFixed(3)} ms ` +
          `across ${String(durations.length)} distinct keystrokes ` +
          `(Product budget: ${String(PRODUCT_KEYSTROKE_BUDGET_MS)} ms, Gate threshold: ${String(GATE_KEYSTROKE_THRESHOLD_MS)} ms)`,
      );

      expect(median).toBeLessThan(GATE_KEYSTROKE_THRESHOLD_MS);
    },
  );

  it(
    "enforces rendered window budget (100 ms product budget, 180 ms gate)",
    { timeout: 30_000 },
    async () => {
      // Representative set of diverse entities across kinds
      const targetIds = [
        "minecraft:diamond_sword",
        "minecraft:zombie",
        "minecraft:oak_planks",
        "minecraft:golden_apple",
        "minecraft:creeper",
        "minecraft:sharpness",
      ];

      const entries = targetIds
        .map((id) => idMap.get(id))
        .filter((e): e is IndexEntry => e !== undefined);

      expect(entries.length).toBe(targetIds.length);

      // Warm-up render
      const warmupContainer = document.createElement("div");
      const firstEntry = entries[0];
      expect(firstEntry).toBeDefined();
      if (firstEntry) {
        renderEntity(warmupContainer, firstEntry, ctx);
      }
      // Allow microtasks and any asynchronous obtain-tree loads to settle
      await new Promise((resolve) => setTimeout(resolve, 20));

      const ITERATIONS = 10;
      const perEntity = new Map<string, number[]>();

      for (let iter = 0; iter < ITERATIONS; iter++) {
        for (const entry of entries) {
          const container = document.createElement("div");
          const start = performance.now();

          renderEntity(container, entry, ctx);
          // Wait for asynchronous obtain tree and shard attachment to settle
          await new Promise((resolve) => setTimeout(resolve, 0));

          const end = performance.now();
          const samples = perEntity.get(entry.id) ?? [];
          samples.push(end - start);
          perEntity.set(entry.id, samples);
        }
      }

      const durations = [...perEntity.values()].map(fastest);
      const median = computeMedian(durations);
      reportBudget(
        `[Budget] Window render latency median: ${median.toFixed(3)} ms ` +
          `across ${String(durations.length)} distinct entities ` +
          `(Product budget: ${String(PRODUCT_RENDER_BUDGET_MS)} ms, Gate threshold: ${String(GATE_RENDER_THRESHOLD_MS)} ms)`,
      );

      expect(median).toBeLessThan(GATE_RENDER_THRESHOLD_MS);
    },
  );
});
