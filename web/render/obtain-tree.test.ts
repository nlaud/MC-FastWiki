import fs from "node:fs";
import path from "node:path";
import { beforeAll, describe, expect, it } from "vitest";

import type { Obtain } from "../types/obtain.js";
import { buildObtainTree, expandStub, isOreSmelt } from "./obtain-tree.js";

describe("obtain-tree workstation tree rules", () => {
  let graph: Obtain;

  beforeAll(() => {
    const obtainPath = path.resolve(import.meta.dirname, "../../data/dist/obtain.json");
    const raw = fs.readFileSync(obtainPath, "utf-8");
    graph = JSON.parse(raw) as Obtain;
  });

  describe("depth-aware filtering", () => {
    it("keeps manipulation at root and retains raw acquisition in rawProducers", () => {
      const tree = buildObtainTree("minecraft:iron_pickaxe", graph);
      expect(tree.root.producers.length).toBeGreaterThan(0);
      // All root tree producers must be manipulation (crafting, smelting, etc.)
      for (const p of tree.root.producers) {
        expect(["crafting", "smelting", "brewing", "filling"]).toContain(p.method);
      }

      // Raw acquisition producers are preserved on tree.rawProducers
      expect(tree.rawProducers).toBeDefined();
      const rawChestLoot = tree.rawProducers?.filter((p) => p.m === "chest_loot");
      expect(rawChestLoot?.length).toBeGreaterThan(0);
    });

    it("drops acquisition producers below root so sub-items become leaves", () => {
      const tree = buildObtainTree("minecraft:stick", graph);
      // Under stick, bamboo has block_drop, mob_drop, chest_loot in raw data,
      // but in tree as sub-item, those are dropped.
      const bambooProducer = tree.root.producers.find((p) =>
        p.inputs.some((i) => i.item === "minecraft:bamboo"),
      );
      if (bambooProducer) {
        const bambooInput = bambooProducer.inputs.find((i) => i.item === "minecraft:bamboo");
        expect(bambooInput?.node?.producers).toHaveLength(0);
      }
    });
  });

  describe("ore-smelt suppression", () => {
    it("isOreSmelt correctly identifies ore blocks, raw metals, and ancient debris", () => {
      // Suppressed
      expect(isOreSmelt("minecraft:iron_ore")).toBe(true);
      expect(isOreSmelt("minecraft:deepslate_iron_ore")).toBe(true);
      expect(isOreSmelt("minecraft:copper_ore")).toBe(true);
      expect(isOreSmelt("minecraft:raw_iron")).toBe(true);
      expect(isOreSmelt("minecraft:raw_gold")).toBe(true);
      expect(isOreSmelt("minecraft:ancient_debris")).toBe(true);

      // Not suppressed (food, stone, glass, charcoal, bricks)
      expect(isOreSmelt("minecraft:potato")).toBe(false);
      expect(isOreSmelt("minecraft:beef")).toBe(false);
      expect(isOreSmelt("minecraft:sand")).toBe(false);
      expect(isOreSmelt("minecraft:cobblestone")).toBe(false);
      expect(isOreSmelt("minecraft:clay_ball")).toBe(false);
      expect(isOreSmelt("minecraft:oak_log")).toBe(false);
    });

    it("suppresses ore smelting for sub-items (depth >= 1)", () => {
      // At root, iron_ingot DOES have smelting producers
      const rootTree = buildObtainTree("minecraft:iron_ingot", graph);
      const rootSmelts = rootTree.root.producers.filter((p) => p.method === "smelting");
      expect(rootSmelts.length).toBeGreaterThan(0);

      // Under iron_pickaxe, iron_ingot as sub-item has ore-smelting suppressed
      const pickaxeTree = buildObtainTree("minecraft:iron_pickaxe", graph);
      const ironInput = pickaxeTree.root.producers[0]?.inputs.find(
        (i) => i.item === "minecraft:iron_ingot",
      );
      expect(ironInput?.node).toBeDefined();
      const subSmelts = ironInput?.node?.producers.filter((p) => p.method === "smelting") ?? [];
      expect(subSmelts).toHaveLength(0);
    });
  });

  describe("cooking station compression", () => {
    it("collapses multiple cooking stations with same inputs into one producer", () => {
      const tree = buildObtainTree("minecraft:iron_ingot", graph);
      const rawIronSmelt = tree.root.producers.find(
        (p) => p.method === "smelting" && p.inputs.some((i) => i.item === "minecraft:raw_iron"),
      );
      expect(rawIronSmelt).toBeDefined();
      // Should have both blast furnace and furnace in stations
      expect(rawIronSmelt?.stations).toBeDefined();
      expect(rawIronSmelt?.stations).toContain("furnace");
      expect(rawIronSmelt?.stations).toContain("blast_furnace");
      // Station chip order prioritises furnace, blast_furnace, smoker, campfire
      expect(rawIronSmelt?.stations?.[0]).toBe("furnace");
      expect(rawIronSmelt?.stations?.[1]).toBe("blast_furnace");
    });
  });

  describe("grid propagation", () => {
    it("propagates shaped crafting recipe pattern and dimensions", () => {
      const tree = buildObtainTree("minecraft:iron_pickaxe", graph);
      const craftingProducer = tree.root.producers.find((p) => p.method === "crafting");
      expect(craftingProducer).toBeDefined();
      expect(craftingProducer?.grid_width).toBe(3);
      expect(craftingProducer?.grid_height).toBe(3);
      expect(craftingProducer?.grid).toEqual([1, 1, 1, null, 0, null, null, 0, null]);
    });
  });

  describe("cycles, depth-capping, and expandStub", () => {
    it("drops cycles without infinite recursion (iron ingot <-> nugget)", () => {
      const tree = buildObtainTree("minecraft:iron_ingot", graph);
      expect(tree.root.producers.length).toBeGreaterThan(0);
      const nuggetProducer = tree.root.producers.find((p) =>
        p.inputs.some((i) => i.item === "minecraft:iron_nugget"),
      );
      expect(nuggetProducer).toBeDefined();
      if (!nuggetProducer) throw new Error("Expected nuggetProducer");
      const nuggetInput = nuggetProducer.inputs.find((i) => i.item === "minecraft:iron_nugget");
      expect(nuggetInput?.node).toBeDefined();
      // Nugget node under iron_ingot should have its iron_ingot producer dropped (cycle)
      const cyclicProducer = nuggetInput?.node?.producers.find((p) =>
        p.inputs.some((i) => i.item === "minecraft:iron_ingot"),
      );
      expect(cyclicProducer).toBeUndefined();
    });

    it("caps depth at maxDepth creating expandable stubs", () => {
      const tree = buildObtainTree("minecraft:chiseled_resin_bricks", graph, {
        maxDepth: 1,
      });
      expect(tree.root.expandable).toBe(false);
      expect(tree.root.producers.length).toBeGreaterThan(0);
      const firstInput = tree.root.producers[0]?.inputs[0];
      expect(firstInput?.node?.expandable).toBe(true);
      expect(firstInput?.node?.producers).toHaveLength(0);
    });

    it("expandStub continues walk carrying ancestors for cycle prevention", () => {
      const tree = buildObtainTree("minecraft:chiseled_resin_bricks", graph, {
        maxDepth: 1,
      });
      const stubInput = tree.root.producers[0]?.inputs[0];
      expect(stubInput?.node?.expandable).toBe(true);
      const stubItemId = stubInput?.item;
      expect(stubItemId).toBeDefined();
      if (!stubItemId) throw new Error("Expected stubItemId");

      const expandedNode = expandStub(stubItemId, graph, ["minecraft:chiseled_resin_bricks"]);
      expect(expandedNode.expandable).toBe(false);
      expect(expandedNode.producers.length).toBeGreaterThan(0);
    });
  });
});
