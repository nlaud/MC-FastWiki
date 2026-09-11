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
});
