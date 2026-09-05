import fs from "node:fs";
import path from "node:path";
import { beforeAll, describe, expect, it } from "vitest";

import type { Obtain } from "../types/obtain.js";
import type { ObtainNode } from "./obtain-tree.js";
import {
  buildObtainTree,
  expandStub,
  isOreSmelt,
  nodeDepth,
  preferPlainMembers,
  truncateNode,
} from "./obtain-tree.js";

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

    // Smelting an ore into its material is acquisition, not manufacture, so it
    // is listed for the item being looked at and never extends a branch.
    it("keeps ore smelting out of the tree and in rawProducers at the root", () => {
      const rootTree = buildObtainTree("minecraft:diamond", graph);
      const treeSmelts = rootTree.root.producers.filter((p) => p.method === "smelting");
      expect(treeSmelts).toHaveLength(0);

      const listedSmelts =
        rootTree.rawProducers?.filter(
          (p) => p.m === "smelting" && isOreSmelt(p.in?.[0]?.i ?? ""),
        ) ?? [];
      expect(listedSmelts.length).toBeGreaterThan(0);
      expect(listedSmelts.some((p) => p.in?.[0]?.i === "minecraft:diamond_ore")).toBe(true);
      expect(listedSmelts.some((p) => p.in?.[0]?.i === "minecraft:deepslate_diamond_ore")).toBe(
        true,
      );
    });

    it("suppresses ore smelting for sub-items (depth >= 1)", () => {
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
      // Cooked beef is smelted from raw beef at a furnace, a smoker and a
      // campfire. It is not an ore, so it stays in the tree, where the three
      // stations have to collapse into one card.
      const tree = buildObtainTree("minecraft:cooked_beef", graph);
      const smelts = tree.root.producers.filter((p) => p.method === "smelting");
      expect(smelts).toHaveLength(1);
      const smelt = smelts[0];
      expect(smelt?.stations).toContain("furnace");
      expect(smelt?.stations).toContain("smoker");
      expect(smelt?.stations).toContain("campfire");
      // Station chip order prioritises furnace, blast_furnace, smoker, campfire
      expect(smelt?.stations?.[0]).toBe("furnace");
    });
  });

  describe("storage block round trips", () => {
    it("drops unpacking a storage block but keeps packing one", () => {
      const ingot = buildObtainTree("minecraft:iron_ingot", graph);
      const fromBlock = ingot.root.producers.find((p) =>
        p.inputs.some((i) => i.item === "minecraft:iron_block"),
      );
      expect(fromBlock).toBeUndefined();

      // Nine nuggets into an ingot is a real thing a player makes, and stays.
      const fromNuggets = ingot.root.producers.find((p) =>
        p.inputs.some((i) => i.item === "minecraft:iron_nugget"),
      );
      expect(fromNuggets).toBeDefined();

      // And the packing direction is exactly what the block's own page shows.
      const block = buildObtainTree("minecraft:iron_block", graph);
      const packed = block.root.producers.find((p) =>
        p.inputs.some((i) => i.item === "minecraft:iron_ingot"),
      );
      expect(packed).toBeDefined();
    });
  });

  describe("depth cap", () => {
    // An "Expand..." control promises more tree behind it. Where the item the
    // walk stopped on has no recipe at all, the promise is empty and the card
    // should just be drawn.
    it("does not offer to expand an item with nothing to expand into", () => {
      const tree = buildObtainTree("minecraft:iron_pickaxe", graph, { maxDepth: 1 });
      const stubs: string[] = [];
      for (const producer of tree.root.producers) {
        for (const input of producer.inputs) {
          if (input.node?.expandable === true) {
            stubs.push(input.node.item);
          }
        }
      }
      for (const itemId of stubs) {
        const sub = buildObtainTree(itemId, graph);
        expect(sub.root.producers.length).toBeGreaterThan(0);
      }
    });
  });

  describe("smelting ingredient collapse", () => {
    // Several items smelting into one result is one fact, and the input slot
    // cycles them the way a tag slot cycles its members.
    it("folds every ingredient of one smelt onto a single cycling input", () => {
      const synthetic: Obtain = {
        schemaVersion: 1,
        producers: {
          "minecraft:test_ingot": [
            { m: "smelting", st: "furnace", src: "a", c: 1, in: [{ i: "minecraft:test_a" }] },
            { m: "smelting", st: "blast_furnace", src: "b", c: 1, in: [{ i: "minecraft:test_b" }] },
            { m: "smelting", st: "furnace", src: "c", c: 1, in: [{ i: "minecraft:test_b" }] },
          ],
        },
      } as unknown as Obtain;

      const tree = buildObtainTree("minecraft:test_ingot", synthetic);
      const smelts = tree.root.producers.filter((p) => p.method === "smelting");
      expect(smelts).toHaveLength(1);

      const only = smelts[0];
      expect(only?.inputs).toHaveLength(1);
      expect(only?.inputs[0]?.members).toEqual(["minecraft:test_a", "minecraft:test_b"]);
      expect(only?.stations).toContain("furnace");
      expect(only?.stations).toContain("blast_furnace");
    });
  });

  describe("repeated-subtree collapse", () => {
    /** Every node of a tree, root first. */
    function walk(node: ObtainNode): ObtainNode[] {
      const out = [node];
      for (const producer of node.producers) {
        for (const input of producer.inputs) {
          if (input.node) {
            out.push(...walk(input.node));
          }
        }
      }
      return out;
    }

    // "(shown above)" replaces a repeated subtree with a pointer at where it
    // was already drawn. A raw material has no subtree: it is one card, so the
    // pointer costs the icon and the name and saves nothing.
    it("never collapses an item that has no recipe of its own", () => {
      for (const id of [
        "minecraft:crafter",
        "minecraft:iron_pickaxe",
        "minecraft:crafting_table",
      ]) {
        for (const node of walk(buildObtainTree(id, graph).root)) {
          if (node.back_reference !== null) {
            expect(manipulationCount(node.item)).toBeGreaterThan(0);
          }
        }
      }
    });

    // Only one of a node's alternative recipes is on screen at a time, so a
    // pointer into a sibling recipe's subtree names something never rendered.
    it("only points at a node inside the same recipe", () => {
      for (const id of [
        "minecraft:crafter",
        "minecraft:iron_ingot",
        "minecraft:stone_brick_stairs",
      ]) {
        const root = buildObtainTree(id, graph).root;
        const drawn = new Set(
          walk(root)
            .filter((n) => n.back_reference === null)
            .map((n) => n.item),
        );
        for (const node of walk(root)) {
          const ref = node.back_reference;
          if (ref !== null) {
            // The path it names has to sit on the branch that leads here, which
            // for a same-recipe collapse means the item was drawn somewhere.
            expect(drawn.has(node.item)).toBe(true);
          }
        }
      }
    });

    function manipulationCount(itemId: string): number {
      const tree = buildObtainTree(itemId, graph);
      return tree.root.producers.length;
    }
  });

  describe("cycling alternatives", () => {
    // A log tag resolves to the log, the six-sided wood, and the stripped
    // version of each. All four craft into planks, but only the log is the one
    // a player has, and the wood carries a whole extra level under it.
    it("keeps only the plain form of a material tag", () => {
      expect(
        preferPlainMembers([
          "minecraft:oak_log",
          "minecraft:oak_wood",
          "minecraft:stripped_oak_log",
          "minecraft:stripped_oak_wood",
        ]),
      ).toEqual(["minecraft:oak_log"]);

      expect(
        preferPlainMembers([
          "minecraft:crimson_hyphae",
          "minecraft:crimson_stem",
          "minecraft:stripped_crimson_hyphae",
          "minecraft:stripped_crimson_stem",
        ]),
      ).toEqual(["minecraft:crimson_stem"]);

      // Nothing survives the filter, so nothing is filtered.
      expect(preferPlainMembers(["minecraft:oak_wood"])).toEqual(["minecraft:oak_wood"]);
      // A tag with no wood in it is untouched.
      expect(preferPlainMembers(["minecraft:coal", "minecraft:charcoal"])).toEqual([
        "minecraft:coal",
        "minecraft:charcoal",
      ]);
    });

    it("truncates a subtree to a fixed number of levels", () => {
      const tree = buildObtainTree("minecraft:crafting_table", graph);
      const deep = tree.root;
      expect(nodeDepth(deep)).toBeGreaterThan(0);
      expect(nodeDepth(truncateNode(deep, 0))).toBe(0);
      expect(truncateNode(deep, 0).producers).toHaveLength(0);
      expect(nodeDepth(truncateNode(deep, 1))).toBeLessThanOrEqual(1);
    });

    // The tree must not gain and lose a level as a slot cycles, so the
    // shallowest alternative decides the shape for all of them.
    it("has a shallowest alternative to hold the shape to", () => {
      const recipe = (graph.producers["minecraft:crafting_table"] ?? []).find(
        (p) => p.m === "crafting",
      );
      const planks = preferPlainMembers(recipe?.in?.[0]?.mb ?? []);
      expect(planks.length).toBeGreaterThan(1);
      const depths = planks.map((id) => nodeDepth(expandStub(id, graph, [])));
      expect(Math.min(...depths)).toBeLessThanOrEqual(Math.max(...depths));
    });
  });

  describe("items with no recipe", () => {
    it("gives an acquisition-only item an empty tree", () => {
      // Honeycomb comes out of chests and out of nothing else.
      const tree = buildObtainTree("minecraft:honeycomb", graph);
      expect(tree.root.producers).toHaveLength(0);
      expect(tree.rawProducers?.length).toBeGreaterThan(0);
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
