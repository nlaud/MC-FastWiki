import fs from "node:fs";
import path from "node:path";
import { beforeAll, describe, expect, it } from "vitest";

import acceptanceFixture from "../../tests/fixtures/obtain_tree_acceptance.json";
import type { Obtain } from "../types/obtain.js";
import { type ObtainTree, buildObtainTree, expandStub } from "./obtain-tree.js";

describe("obtain-tree acceptance fixture", () => {
  let graph: Obtain;

  beforeAll(() => {
    const obtainPath = path.resolve(import.meta.dirname, "../../data/dist/obtain.json");
    const raw = fs.readFileSync(obtainPath, "utf-8");
    graph = JSON.parse(raw) as Obtain;
  });

  it.each(Object.keys(acceptanceFixture))(
    "reproduces identical acceptance tree for %s",
    (itemId) => {
      const expected = (acceptanceFixture as Record<string, ObtainTree>)[itemId];
      const actual = buildObtainTree(itemId, graph);
      expect(actual).toEqual(expected);
    },
  );
});

describe("obtain-tree rules and expandStub", () => {
  let graph: Obtain;

  beforeAll(() => {
    const obtainPath = path.resolve(import.meta.dirname, "../../data/dist/obtain.json");
    const raw = fs.readFileSync(obtainPath, "utf-8");
    graph = JSON.parse(raw) as Obtain;
  });

  it("drops cycles without infinite recursion (iron ingot <-> nugget)", () => {
    const tree = buildObtainTree("minecraft:iron_ingot", graph);
    expect(tree.root.producers.length).toBeGreaterThan(0);
    // Finds nugget producer
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
    // Resin bricks chain: chiseled_resin_bricks -> resin_brick_slab -> resin_bricks -> resin_clump
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
