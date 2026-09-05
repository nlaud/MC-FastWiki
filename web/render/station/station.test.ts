import { beforeEach, describe, expect, it, vi } from "vitest";
import type { RenderContext } from "../context.js";
import type { TreeProducer } from "../obtain-tree.js";
import {
  advanceTickerForTesting,
  humaniseTag,
  renderBrewingCard,
  renderCraftingCard,
  renderFurnaceCard,
  renderLeafCard,
  renderSlot,
  renderSmithingCard,
  renderStationCard,
  renderStonecutterCard,
  resetTickerForTesting,
} from "./index.js";

function createMockContext(): RenderContext {
  return {
    openRef: vi.fn(),
    lookup: (id: string) => {
      if (id === "minecraft:iron_ingot")
        return { id, n: "Iron Ingot", s: "items", i: "item/iron_ingot", k: "item" as const, a: [] };
      if (id === "minecraft:stick")
        return { id, n: "Stick", s: "items", i: "item/stick", k: "item" as const, a: [] };
      if (id === "minecraft:oak_planks")
        return { id, n: "Oak Planks", s: "items", i: "item/oak_planks", k: "item" as const, a: [] };
      if (id === "minecraft:birch_planks")
        return {
          id,
          n: "Birch Planks",
          s: "items",
          i: "item/birch_planks",
          k: "item" as const,
          a: [],
        };
      if (id === "minecraft:coal")
        return { id, n: "Coal", s: "items", i: "item/coal", k: "item" as const, a: [] };
      if (id === "minecraft:raw_iron")
        return { id, n: "Raw Iron", s: "items", i: "item/raw_iron", k: "item" as const, a: [] };
      if (id === "minecraft:iron_pickaxe")
        return {
          id,
          n: "Iron Pickaxe",
          s: "items",
          i: "item/iron_pickaxe",
          k: "item" as const,
          a: [],
        };
      return null;
    },
  };
}

describe("StationSlot", () => {
  beforeEach(() => {
    resetTickerForTesting();
  });

  it("humanises tag without '#' prefix and in Title Case", () => {
    expect(humaniseTag("#minecraft:planks")).toBe("Planks");
    expect(humaniseTag("#iron_tool_materials")).toBe("Iron Tool Materials");
    expect(humaniseTag("#minecraft:wooden_slabs")).toBe("Wooden Slabs");
  });

  it("renders empty slot with is-empty class", () => {
    const ctx = createMockContext();
    const slot = renderSlot(null, ctx);
    expect(slot.classList.contains("station-slot")).toBe(true);
    expect(slot.classList.contains("is-empty")).toBe(true);
  });

  it("renders item slot with count badge when count > 1", () => {
    const ctx = createMockContext();
    const slot = renderSlot("minecraft:iron_ingot", ctx, { count: 3 });
    expect(slot.classList.contains("is-empty")).toBe(false);
    const badge = slot.querySelector(".slot-count");
    expect(badge?.textContent).toBe("3");
  });

  it("cycles candidate items for tags with members using ticker", () => {
    const ctx = createMockContext();
    const slot = renderSlot(
      {
        label: "Planks",
        item: "minecraft:oak_planks",
        tag: "#minecraft:planks",
        count: 1,
        members: ["minecraft:oak_planks", "minecraft:birch_planks"],
        node: null,
      },
      ctx,
    );

    expect(slot.classList.contains("is-cycling")).toBe(true);
    expect(slot.title).toContain("Planks (2): Oak Planks");

    // Advance ticker
    advanceTickerForTesting();
    expect(slot.title).toContain("Planks (2): Birch Planks");

    // Advance ticker again to wrap around
    advanceTickerForTesting();
    expect(slot.title).toContain("Planks (2): Oak Planks");
  });

  it("falls back to readable text when atlas sprite is missing", () => {
    const ctx = createMockContext();
    const slot = renderSlot("minecraft:unknown_material", ctx);
    const fallback = slot.querySelector(".slot-fallback-text");
    expect(fallback?.textContent).toBe("Unknown Material");
  });
});

describe("CraftingCard", () => {
  it("renders true 3x3 pattern according to shaped recipe grid", () => {
    const ctx = createMockContext();
    // Iron pickaxe: row 0: [iron, iron, iron], row 1: [null, stick, null], row 2: [null, stick, null]
    // inputs: [stick (idx 0), iron_ingot (idx 1)]
    // grid: [1, 1, 1, null, 0, null, null, 0, null]
    const producer: TreeProducer = {
      method: "crafting",
      station: null,
      note: null,
      source_id: "minecraft:iron_pickaxe",
      count: 1,
      grid: [1, 1, 1, null, 0, null, null, 0, null],
      grid_width: 3,
      grid_height: 3,
      inputs: [
        {
          label: "minecraft:stick",
          item: "minecraft:stick",
          tag: null,
          count: 2,
          members: [],
          node: null,
        },
        {
          label: "minecraft:iron_ingot",
          item: "minecraft:iron_ingot",
          tag: null,
          count: 3,
          members: [],
          node: null,
        },
      ],
    };

    const card = renderCraftingCard(producer, "minecraft:iron_pickaxe", ctx);
    expect(card.classList.contains("station-crafting")).toBe(true);

    const slots = Array.from(card.querySelectorAll(".crafting-grid .station-slot"));
    expect(slots.length).toBe(9);

    // Row 0 slots should not be empty (iron ingot)
    expect(slots[0]?.classList.contains("is-empty")).toBe(false);
    expect(slots[1]?.classList.contains("is-empty")).toBe(false);
    expect(slots[2]?.classList.contains("is-empty")).toBe(false);

    // Row 1: empty, stick, empty
    expect(slots[3]?.classList.contains("is-empty")).toBe(true);
    expect(slots[4]?.classList.contains("is-empty")).toBe(false);
    expect(slots[5]?.classList.contains("is-empty")).toBe(true);

    // Row 2: empty, stick, empty
    expect(slots[6]?.classList.contains("is-empty")).toBe(true);
    expect(slots[7]?.classList.contains("is-empty")).toBe(false);
    expect(slots[8]?.classList.contains("is-empty")).toBe(true);

    // Arrow and result slot
    expect(card.querySelector(".station-arrow")?.textContent).toBe("→");
    const resultSlot = card.querySelector(".slot-result");
    expect(resultSlot).not.toBeNull();
  });

  it("fills shapeless recipe left-to-right when grid is absent", () => {
    const ctx = createMockContext();
    const producer: TreeProducer = {
      method: "crafting",
      station: null,
      note: null,
      source_id: "shapeless_test",
      count: 1,
      inputs: [
        {
          label: "minecraft:oak_planks",
          item: "minecraft:oak_planks",
          tag: null,
          count: 2,
          members: [],
          node: null,
        },
      ],
    };

    const card = renderCraftingCard(producer, "minecraft:stick", ctx);
    const slots = Array.from(card.querySelectorAll(".crafting-grid .station-slot"));
    expect(slots.length).toBe(9);
    // 2 units fill slots 0 and 1
    expect(slots[0]?.classList.contains("is-empty")).toBe(false);
    expect(slots[1]?.classList.contains("is-empty")).toBe(false);
    expect(slots[2]?.classList.contains("is-empty")).toBe(true);
  });
});

describe("FurnaceCard", () => {
  it("renders only applicable stations with no struck-through chips", () => {
    const ctx = createMockContext();
    const producer: TreeProducer = {
      method: "smelting",
      station: "furnace",
      stations: ["blast_furnace", "furnace"],
      note: null,
      source_id: "iron_ingot_smelt",
      count: 1,
      inputs: [
        {
          label: "minecraft:raw_iron",
          item: "minecraft:raw_iron",
          tag: null,
          count: 1,
          members: [],
          node: null,
        },
      ],
    };

    const card = renderFurnaceCard(producer, "minecraft:iron_ingot", ctx);
    const chips = Array.from(card.querySelectorAll(".station-chip")).map((c) => c.textContent);
    expect(chips).toEqual(["Blast Furnace", "Furnace"]);
    // Smoker and campfire should NOT appear
    expect(chips).not.toContain("Smoker");
    expect(chips).not.toContain("Campfire");

    // Flame and fuel slot exist
    expect(card.querySelector(".station-flame")?.textContent).toBe("🔥");
    expect(card.querySelector(".slot-fuel")).not.toBeNull();
  });
});

describe("StonecutterCard", () => {
  it("renders stonecutter card with input, arrow, and result slot", () => {
    const ctx = createMockContext();
    const producer: TreeProducer = {
      method: "crafting",
      station: "stonecutter",
      note: null,
      source_id: "stonecutter_test",
      count: 1,
      inputs: [
        {
          label: "minecraft:stone",
          item: "minecraft:stone",
          tag: null,
          count: 1,
          members: [],
          node: null,
        },
      ],
    };

    const card = renderStonecutterCard(producer, "minecraft:stone_stairs", ctx);
    expect(card.classList.contains("station-stonecutter")).toBe(true);
    expect(card.querySelector(".station-chip")?.textContent).toBe("Stonecutter");
    expect(card.querySelector(".station-arrow")?.textContent).toBe("→");
  });
});

describe("SmithingCard", () => {
  it("renders template, base, and addition slots", () => {
    const ctx = createMockContext();
    const producer: TreeProducer = {
      method: "crafting",
      station: "smithing_table",
      note: null,
      source_id: "smithing_test",
      count: 1,
      inputs: [
        {
          label: "minecraft:netherite_upgrade_smithing_template",
          item: "minecraft:netherite_upgrade_smithing_template",
          tag: null,
          count: 1,
          members: [],
          node: null,
        },
        {
          label: "minecraft:diamond_pickaxe",
          item: "minecraft:diamond_pickaxe",
          tag: null,
          count: 1,
          members: [],
          node: null,
        },
        {
          label: "minecraft:netherite_ingot",
          item: "minecraft:netherite_ingot",
          tag: null,
          count: 1,
          members: [],
          node: null,
        },
      ],
    };

    const card = renderSmithingCard(producer, "minecraft:netherite_pickaxe", ctx);
    expect(card.classList.contains("station-smithing")).toBe(true);
    expect(card.querySelector('[data-slot-role="template"]')).not.toBeNull();
    expect(card.querySelector('[data-slot-role="base"]')).not.toBeNull();
    expect(card.querySelector('[data-slot-role="addition"]')).not.toBeNull();
  });
});

describe("BrewingCard", () => {
  it("renders ingredient slot and 3 bottle slots", () => {
    const ctx = createMockContext();
    const producer: TreeProducer = {
      method: "brewing",
      station: "brewing_stand",
      note: null,
      source_id: "brewing_test",
      count: 1,
      inputs: [
        {
          label: "minecraft:nether_wart",
          item: "minecraft:nether_wart",
          tag: null,
          count: 1,
          members: [],
          node: null,
        },
        {
          label: "minecraft:potion/water",
          item: "minecraft:potion/water",
          tag: null,
          count: 1,
          members: [],
          node: null,
        },
      ],
    };

    const card = renderBrewingCard(producer, "minecraft:potion/awkward", ctx);
    expect(card.classList.contains("station-brewing")).toBe(true);
    expect(card.querySelector('[data-slot-role="ingredient"]')).not.toBeNull();
    const bottles = card.querySelectorAll('[data-slot-role="bottle"]');
    expect(bottles.length).toBe(3);
  });
});

describe("LeafCard", () => {
  it("renders raw material badge and links to item", () => {
    const ctx = createMockContext();
    const card = renderLeafCard("minecraft:raw_iron", ctx, { isRaw: true });
    expect(card.classList.contains("station-leaf")).toBe(true);
    expect(card.querySelector(".leaf-name")?.textContent).toBe("Raw Iron");
    expect(card.querySelector(".leaf-badge")?.textContent).toBe("Raw material");

    card.click();
    expect(ctx.openRef).toHaveBeenCalledWith("minecraft:raw_iron");
  });

  // Block of Iron is crafted from nine ingots. It only reaches a leaf under
  // Iron Ingot because cycle detection removed its one producer, so the tree
  // has not established that it is a raw material and must not say so.
  it("omits the raw material badge for an item whose producers were filtered away", () => {
    const ctx = createMockContext();
    const card = renderLeafCard("minecraft:iron_block", ctx, { isRaw: false });
    expect(card.querySelector(".leaf-name")?.textContent).toBe("Iron Block");
    expect(card.querySelector(".leaf-badge")).toBeNull();
  });
});

describe("StationPagination", () => {
  it("renders pagination dots when totalProducers > 1 and handles selection", () => {
    const ctx = createMockContext();
    const producer: TreeProducer = {
      method: "crafting",
      station: null,
      note: null,
      source_id: "test",
      count: 1,
      inputs: [],
    };

    const onSelect = vi.fn();
    const card = renderStationCard(producer, "minecraft:stick", ctx, {
      activeProducerIndex: 0,
      totalProducers: 3,
      onSelectProducer: onSelect,
    });

    const dots = card.querySelectorAll<HTMLButtonElement>(".station-dot");
    expect(dots.length).toBe(3);
    expect(dots[0]?.classList.contains("is-active")).toBe(true);
    expect(dots[1]?.classList.contains("is-active")).toBe(false);

    dots[1]?.click();
    expect(onSelect).toHaveBeenCalledWith(1);
  });
});
