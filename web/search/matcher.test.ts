import fs from "node:fs";
import path from "node:path";
import { beforeAll, describe, expect, it } from "vitest";

import acceptanceFixture from "../../tests/fixtures/search_acceptance.json";
import type { Index, IndexEntry } from "../types/index.js";
import { type Corpus, buildCorpus, search } from "./matcher.js";

describe("matcher", () => {
  let realIndex: Index;
  let realCorpus: Corpus;

  beforeAll(() => {
    const indexPath = path.resolve(import.meta.dirname, "../../data/dist/index.json");
    const raw = fs.readFileSync(indexPath, "utf-8");
    realIndex = JSON.parse(raw) as Index;
    realCorpus = buildCorpus(realIndex);
  });

  describe("acceptance table (real index)", () => {
    it.each(acceptanceFixture)('ranks "$expected" first for "$query"', ({ query, expected }) => {
      const results = search(realCorpus, query);
      expect(results.length).toBeGreaterThan(0);
      expect(results[0]?.id).toBe(expected);
    });
  });

  describe("tiers", () => {
    function makeIndex(entries: IndexEntry[]): Corpus {
      return buildCorpus({
        schemaVersion: 1,
        entities: entries as [IndexEntry, ...IndexEntry[]],
      });
    }

    it("Tier 0 (exact match) beats Tier 1 (prefix match)", () => {
      const corpus = makeIndex([
        { id: "test:prefix", n: "Stone Bricks", k: "block", a: [], s: "block-0" },
        { id: "test:exact", n: "Stone", k: "block", a: [], s: "block-0" },
      ]);

      const results = search(corpus, "stone");
      expect(results.map((r) => r.id)).toEqual(["test:exact", "test:prefix"]);
    });

    it("Tier 1 (prefix match) beats Tier 2 (alias contains query)", () => {
      const corpus = makeIndex([
        {
          id: "test:contains",
          n: "Mossy Rock",
          k: "block",
          a: ["mossy cobblestone"],
          s: "block-0",
        },
        { id: "test:prefix", n: "Cobbled Deepslate", k: "block", a: [], s: "block-0" },
      ]);

      const results = search(corpus, "cobb");
      expect(results[0]?.id).toBe("test:prefix");
    });

    it("Tier 2 (alias contains query) beats Tier 3 (fuzzy)", () => {
      const corpus = makeIndex([
        { id: "test:fuzzy", n: "Diamond", k: "item", a: [], s: "item-0" },
        { id: "test:contains", n: "Coal Ore", k: "block", a: ["deepslate coal ore"], s: "block-0" },
      ]);

      const results = search(corpus, "coal");
      expect(results[0]?.id).toBe("test:contains");
    });

    it("Tier 3 (uFuzzy) tolerates single errors (typos)", () => {
      // Transposition
      const diamondResults = search(realCorpus, "dimaond");
      expect(diamondResults[0]?.id).toBe("minecraft:diamond");

      // Substitution
      const blazeResults = search(realCorpus, "blase rod");
      expect(blazeResults[0]?.id).toBe("minecraft:blaze_rod");

      // Transposition / substitution in multi-word term
      const tableResults = search(realCorpus, "enchanting tabel");
      expect(tableResults[0]?.id).toBe("minecraft:enchanting_table");
    });
  });

  describe("tiebreaks", () => {
    function makeIndex(entries: IndexEntry[]): Corpus {
      return buildCorpus({
        schemaVersion: 1,
        entities: entries as [IndexEntry, ...IndexEntry[]],
      });
    }

    it("Tiebreak 1: a name match beats an alias match at the same tier", () => {
      const corpus = makeIndex([
        { id: "test:by_alias", n: "Cobblestone", k: "block", a: ["stone"], s: "block-0" },
        { id: "test:by_name", n: "Stone", k: "block", a: [], s: "block-0" },
      ]);

      const results = search(corpus, "stone");
      expect(results[0]?.id).toBe("test:by_name");
    });

    it("Tiebreak 2: a whole-registry-path alias beats any other alias", () => {
      // `test:target`'s alias IS its registry path, so it is a FULL_PHRASE alias.
      // `test:other_thing` reaches the same tier through a weaker alias. The
      // phrase alias must win even though the other entity's display name is
      // shorter, which is the next tiebreak down.
      const corpus = makeIndex([
        { id: "test:other_thing", n: "Bee", k: "item", a: ["target"], s: "item-0" },
        { id: "test:target", n: "Considerably Longer Name", k: "item", a: ["target"], s: "item-0" },
      ]);

      const results = search(corpus, "target");
      expect(results[0]?.id).toBe("test:target");
    });

    it("does not rank on alias position, which is alphabetical inside a strength band", () => {
      // Regression. `generate_aliases` sorts alphabetically within one strength,
      // so "diamond" lands at alias index 2 for `diamond_axe` (after "axe") and
      // index 1 for `diamond_hoe` (before "hoe"). Ranking on that index made
      // Diamond Ore -- a block -- outrank Diamond Axe for the query "diamond",
      // purely because of how the sibling segment happened to be spelled.
      const results = search(realCorpus, "diamond", 20);
      const ids = results.map((r) => r.id);

      expect(ids[0]).toBe("minecraft:diamond");
      expect(ids.indexOf("minecraft:diamond_axe")).toBeLessThan(
        ids.indexOf("minecraft:diamond_hoe"),
      );
      expect(ids.indexOf("minecraft:diamond_axe")).toBeLessThan(
        ids.indexOf("minecraft:diamond_ore"),
      );
    });

    it("Tiebreak 3: kind priority orders results correctly", () => {
      // mob > item > block > effect > enchantment > biome > structure > collection > advancement > entity
      const corpus = makeIndex([
        { id: "test:adv", n: "Target", k: "advancement", a: [], s: "adv-0" },
        { id: "test:item", n: "Target", k: "item", a: [], s: "item-0" },
        { id: "test:mob", n: "Target", k: "mob", a: [], s: "mob-0" },
        { id: "test:block", n: "Target", k: "block", a: [], s: "block-0" },
      ]);

      const results = search(corpus, "Target");
      expect(results.map((r) => r.id)).toEqual(["test:mob", "test:item", "test:block", "test:adv"]);
    });

    it("surfaces villager mob above villager-adjacent entities", () => {
      const results = search(realCorpus, "villager");
      expect(results[0]?.id).toBe("minecraft:villager");
      expect(results[0]?.k).toBe("mob");
    });

    it("Tiebreak 4: shorter display name beats longer display name", () => {
      const corpus = makeIndex([
        { id: "test:longer", n: "Iron Ingot", k: "item", a: ["metal"], s: "item-0" },
        { id: "test:shorter", n: "Iron", k: "item", a: ["metal"], s: "item-0" },
      ]);

      const results = search(corpus, "metal");
      expect(results.map((r) => r.id)).toEqual(["test:shorter", "test:longer"]);
    });

    it("Tiebreak 5: id alphabetically as final deterministic tiebreak", () => {
      const corpus = makeIndex([
        { id: "minecraft:b_widget", n: "Widget", k: "item", a: [], s: "item-0" },
        { id: "minecraft:a_widget", n: "Widget", k: "item", a: [], s: "item-0" },
      ]);

      const results = search(corpus, "Widget");
      expect(results.map((r) => r.id)).toEqual(["minecraft:a_widget", "minecraft:b_widget"]);
    });
  });

  describe("segment aliases", () => {
    it("golden alone returns every golden item", () => {
      const results = search(realCorpus, "golden", 100);
      const matchedIds = new Set(results.map((r) => r.id));

      expect(matchedIds.has("minecraft:golden_apple")).toBe(true);
      expect(matchedIds.has("minecraft:golden_carrot")).toBe(true);
      expect(matchedIds.has("minecraft:golden_sword")).toBe(true);
      expect(matchedIds.has("minecraft:golden_boots")).toBe(true);
      expect(matchedIds.has("minecraft:enchanted_golden_apple")).toBe(true);
      expect(results.length).toBeGreaterThanOrEqual(10);
    });

    it("does not let a one- or two-character alias match any query containing it", () => {
      // Pins the tier 2 narrowing documented in docs/search.md. The Python
      // reference ranker also accepts an alias *contained by* the query, which
      // over the real index would make `a` (from `adventure/kill_a_mob`) and
      // `on` (from `carrot_on_a_stick`) match almost everything. Measured on the
      // committed index, restoring that clause adds 10 junk results to `diamond`
      // alone, so this asserts the shape of the result rather than one id.
      const results = search(realCorpus, "diamond", 100);
      const matchedIds = new Set(results.map((r) => r.id));

      expect(matchedIds.has("minecraft:diamond")).toBe(true);
      expect(matchedIds.has("minecraft:adventure/kill_a_mob")).toBe(false);
      expect(matchedIds.has("minecraft:carrot_on_a_stick")).toBe(false);
      expect(matchedIds.has("minecraft:husbandry/axolotl_in_a_bucket")).toBe(false);
    });
  });

  describe("edge cases", () => {
    it("returns empty array for empty or whitespace query", () => {
      expect(search(realCorpus, "")).toEqual([]);
      expect(search(realCorpus, "   ")).toEqual([]);
    });

    it("returns empty array for query matching nothing", () => {
      expect(search(realCorpus, "zzzxqj999")).toEqual([]);
    });
  });

  describe("performance budget", () => {
    it("processes a 33-keystroke session with p95 latency under 16 ms", () => {
      // 33 keystrokes across varied queries (prefixes, typos, exact matches)
      const session = [
        "g",
        "go",
        "gol",
        "gold",
        "golde",
        "golden",
        "golden ",
        "golden a",
        "golden ap",
        "golden app",
        "golden appl",
        "golden apple",
        "v",
        "vi",
        "vil",
        "vill",
        "villa",
        "villag",
        "village",
        "villager",
        "d",
        "di",
        "dim",
        "dima",
        "dimao",
        "dimaon",
        "dimaond",
        "w",
        "we",
        "wea",
        "weak",
        "z",
        "1",
      ];
      expect(session).toHaveLength(33);

      // Warm up
      for (const q of session) {
        search(realCorpus, q, 10);
      }

      const timings: number[] = [];
      for (const q of session) {
        const start = performance.now();
        search(realCorpus, q, 10);
        const duration = performance.now() - start;
        timings.push(duration);
      }

      timings.sort((a, b) => a - b);
      const p95Idx = Math.floor(timings.length * 0.95);
      const p95Duration = timings[p95Idx] ?? 0;

      expect(p95Duration).toBeLessThan(16);
    });
  });
});
