import { describe, expect, it, vi } from "vitest";
import type { CollectionMembers } from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { renderCollectionMembers } from "./collection-members.js";

describe("renderCollectionMembers", () => {
  const ctx: RenderContext = {
    openRef: vi.fn(),
    lookup: (id: string) => ({
      id,
      n: id.split(":")[1]?.replace(/_/g, " ") ?? id,
      k: "item" as const,
      a: [],
      s: "item-0",
    }),
  };

  it("returns null for an empty members list", () => {
    const section: CollectionMembers = {
      type: "CollectionMembers",
      members: [],
    };
    expect(renderCollectionMembers(section, ctx)).toBeNull();
  });

  it("renders a flat link list when no columns are present", () => {
    const section: CollectionMembers = {
      type: "CollectionMembers",
      title: "Undead Mobs",
      columns: [],
      members: [
        { ref: { id: "minecraft:zombie", name: "Zombie" } },
        { ref: { id: "minecraft:skeleton", name: "Skeleton" } },
      ],
    };

    const el = renderCollectionMembers(section, ctx);
    expect(el).not.toBeNull();
    expect(el?.className).toContain("collection-members-section");

    const title = el?.querySelector(".section-title");
    expect(title?.textContent).toBe("Undead Mobs");

    const list = el?.querySelector(".collection-members-items");
    expect(list).not.toBeNull();

    const links = el?.querySelectorAll("a.entity-link");
    expect(links?.length).toBe(2);
    expect(links?.[0]?.getAttribute("data-id")).toBe("minecraft:zombie");
    expect(links?.[1]?.getAttribute("data-id")).toBe("minecraft:skeleton");
  });

  it("renders a table when columns are present", () => {
    const section: CollectionMembers = {
      type: "CollectionMembers",
      columns: [
        { key: "food.nutrition", label: "Hunger" },
        { key: "food.saturation", label: "Saturation" },
      ],
      members: [
        {
          ref: { id: "minecraft:golden_carrot", name: "Golden Carrot" },
          values: {
            "food.nutrition": "6",
            "food.saturation": "14.4",
          },
        },
        {
          ref: { id: "minecraft:apple", name: "Apple" },
          values: {
            "food.nutrition": "4",
            "food.saturation": "2.4",
          },
        },
      ],
    };

    const el = renderCollectionMembers(section, ctx);
    expect(el).not.toBeNull();

    const wrapper = el?.querySelector(".table-wrapper");
    expect(wrapper).not.toBeNull();

    const table = el?.querySelector("table.collection-members-table");
    expect(table).not.toBeNull();

    const headers = table?.querySelectorAll("th");
    expect(headers?.length).toBe(3);
    expect(headers?.[0]?.textContent).toBe("Name");
    expect(headers?.[1]?.textContent).toBe("Hunger");
    expect(headers?.[2]?.textContent).toBe("Saturation");

    const rows = table?.querySelectorAll("tbody tr");
    expect(rows?.length).toBe(2);

    const firstRowCells = rows?.[0]?.querySelectorAll("td");
    expect(firstRowCells?.length).toBe(3);
    expect(firstRowCells?.[0]?.querySelector("a.entity-link")?.getAttribute("data-id")).toBe(
      "minecraft:golden_carrot",
    );
    expect(firstRowCells?.[1]?.textContent).toBe("6");
    expect(firstRowCells?.[2]?.textContent).toBe("14.4");
  });

  it("renders empty cells for missing fact values", () => {
    const section: CollectionMembers = {
      type: "CollectionMembers",
      columns: [
        { key: "food.nutrition", label: "Hunger" },
        { key: "food.saturation", label: "Saturation" },
      ],
      members: [
        {
          ref: { id: "minecraft:cake", name: "Cake" },
          values: {
            "food.nutrition": "2",
          },
        },
      ],
    };

    const el = renderCollectionMembers(section, ctx);
    expect(el).not.toBeNull();

    const row = el?.querySelector("tbody tr");
    const cells = row?.querySelectorAll("td");
    expect(cells?.length).toBe(3);
    expect(cells?.[1]?.textContent).toBe("2");
    expect(cells?.[2]?.textContent).toBe("");
  });

  it("renders armor trims table with Found in column and Tide note", () => {
    const section: CollectionMembers = {
      type: "CollectionMembers",
      columns: [{ key: "obtain.foundIn", label: "Found in" }],
      members: [
        {
          ref: {
            id: "minecraft:bolt_armor_trim_smithing_template",
            name: "Bolt Armor Trim",
          },
          values: {
            "obtain.foundIn": "Trial Chambers",
          },
        },
        {
          ref: {
            id: "minecraft:tide_armor_trim_smithing_template",
            name: "Tide Armor Trim",
          },
          values: {
            "obtain.foundIn": "dropped by Elder Guardian",
          },
        },
      ],
    };

    const el = renderCollectionMembers(section, ctx);
    expect(el).not.toBeNull();
    const rows = el?.querySelectorAll("tbody tr");
    expect(rows?.length).toBe(2);

    const firstRowCells = rows?.[0]?.querySelectorAll("td");
    expect(firstRowCells?.[1]?.textContent).toBe("Trial Chambers");

    const secondRowCells = rows?.[1]?.querySelectorAll("td");
    expect(secondRowCells?.[1]?.textContent).toBe("dropped by Elder Guardian");
  });

  it("renders a column carrying refs on some rows and plain text on others", () => {
    const section: CollectionMembers = {
      type: "CollectionMembers",
      columns: [{ key: "obtain.foundIn", label: "Found in" }],
      members: [
        {
          ref: {
            id: "minecraft:bolt_armor_trim_smithing_template",
            name: "Bolt Armor Trim",
          },
          values: {
            "obtain.foundIn": "Trial Chambers",
          },
          refs: {
            "obtain.foundIn": [{ id: "minecraft:trial_chambers", name: "Trial Chambers" }],
          },
        },
        {
          ref: {
            id: "minecraft:coast_armor_trim_smithing_template",
            name: "Coast Armor Trim",
          },
          values: {
            "obtain.foundIn": "Shipwreck, Beached Shipwreck",
          },
          refs: {
            "obtain.foundIn": [
              { id: "minecraft:shipwreck", name: "Shipwreck" },
              { id: "minecraft:shipwreck_beached", name: "Beached Shipwreck" },
            ],
          },
        },
        {
          ref: {
            id: "minecraft:tide_armor_trim_smithing_template",
            name: "Tide Armor Trim",
          },
          values: {
            "obtain.foundIn": "dropped by Elder Guardian",
          },
        },
      ],
    };

    const el = renderCollectionMembers(section, ctx);
    expect(el).not.toBeNull();
    const rows = el?.querySelectorAll("tbody tr");
    expect(rows?.length).toBe(3);

    // Row 0: Bolt -> single link in fact cell, has-refs class
    const boltCells = rows?.[0]?.querySelectorAll("td");
    const boltFactCell = boltCells?.[1];
    expect(boltFactCell?.className).toContain("has-refs");
    const boltLinks = boltFactCell?.querySelectorAll("a.entity-link");
    expect(boltLinks?.length).toBe(1);
    expect(boltLinks?.[0]?.getAttribute("data-id")).toBe("minecraft:trial_chambers");
    expect(boltFactCell?.textContent).toBe("Trial Chambers");

    // Row 1: Coast -> multi-variant links separated by ", ", has-refs class
    const coastCells = rows?.[1]?.querySelectorAll("td");
    const coastFactCell = coastCells?.[1];
    expect(coastFactCell?.className).toContain("has-refs");
    const coastLinks = coastFactCell?.querySelectorAll("a.entity-link");
    expect(coastLinks?.length).toBe(2);
    expect(coastLinks?.[0]?.getAttribute("data-id")).toBe("minecraft:shipwreck");
    expect(coastLinks?.[1]?.getAttribute("data-id")).toBe("minecraft:shipwreck_beached");
    expect(coastFactCell?.textContent).toBe("Shipwreck, Beached Shipwreck");

    // Every link in a fact cell is a prose link, not a standalone chip. The
    // chip's horizontal padding reads as a word space before the ", ", which
    // rendered this very cell as "Shipwreck , Beached Shipwreck". Single-ref
    // rows carry the class too, so one column keeps one left edge.
    expect(boltLinks?.[0]?.className).toContain("entity-link-prose");
    expect(coastLinks?.[0]?.className).toContain("entity-link-prose");
    expect(coastLinks?.[1]?.className).toContain("entity-link-prose");

    // Row 2: Tide -> plain text, no entity links, no has-refs class
    const tideCells = rows?.[2]?.querySelectorAll("td");
    const tideFactCell = tideCells?.[1];
    expect(tideFactCell?.className).not.toContain("has-refs");
    const tideLinks = tideFactCell?.querySelectorAll("a.entity-link");
    expect(tideLinks?.length).toBe(0);
    expect(tideFactCell?.textContent).toBe("dropped by Elder Guardian");
  });
});
