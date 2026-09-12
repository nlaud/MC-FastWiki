import { describe, expect, it, vi } from "vitest";
import type { CollectionTree } from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { renderCollectionTree } from "./collection-tree.js";

describe("renderCollectionTree", () => {
  const ctx: RenderContext = {
    openRef: vi.fn(),
    lookup: (id: string) => ({
      id,
      n: id.split(":")[1]?.replace(/_/g, " ") ?? id,
      k: "advancement" as const,
      a: [],
      s: "advancement-0",
    }),
  };

  it("returns null for an empty members list", () => {
    const section: CollectionTree = {
      type: "CollectionTree",
      members: [],
    };
    expect(renderCollectionTree(section, ctx)).toBeNull();
  });

  it("renders a tree section with title and indented rows", () => {
    const section: CollectionTree = {
      type: "CollectionTree",
      title: "Minecraft",
      members: [
        { ref: { id: "minecraft:story/root", name: "Minecraft" }, depth: 0 },
        { ref: { id: "minecraft:story/mine_stone", name: "Stone Age" }, depth: 1 },
        { ref: { id: "minecraft:story/upgrade_tools", name: "Getting an Upgrade" }, depth: 2 },
      ],
    };

    const el = renderCollectionTree(section, ctx);
    expect(el).not.toBeNull();
    expect(el?.className).toContain("collection-tree-section");

    const title = el?.querySelector(".section-title");
    expect(title?.textContent).toBe("Minecraft");

    const list = el?.querySelector(".collection-tree-items");
    expect(list).not.toBeNull();

    const rows = el?.querySelectorAll<HTMLElement>(".collection-tree-row");
    expect(rows?.length).toBe(3);

    expect(rows?.[0]?.style.getPropertyValue("--depth")).toBe("0");
    expect(rows?.[1]?.style.getPropertyValue("--depth")).toBe("1");
    expect(rows?.[2]?.style.getPropertyValue("--depth")).toBe("2");

    const links = el?.querySelectorAll("a.entity-link");
    expect(links?.length).toBe(3);
    expect(links?.[0]?.getAttribute("data-id")).toBe("minecraft:story/root");
    expect(links?.[1]?.getAttribute("data-id")).toBe("minecraft:story/mine_stone");
    expect(links?.[2]?.getAttribute("data-id")).toBe("minecraft:story/upgrade_tools");
  });

  it("omits the title when none is set", () => {
    const section: CollectionTree = {
      type: "CollectionTree",
      members: [{ ref: { id: "minecraft:story/root", name: "Minecraft" }, depth: 0 }],
    };

    const el = renderCollectionTree(section, ctx);
    expect(el).not.toBeNull();
    expect(el?.querySelector(".section-title")).toBeNull();
  });
});
