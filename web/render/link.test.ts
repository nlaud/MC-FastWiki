import { describe, expect, it, vi } from "vitest";
import type { IndexEntry } from "../types/index.js";
import type { RenderContext } from "./context.js";
import { entityLink } from "./link.js";

describe("entityLink rule", () => {
  const mockAppleEntry: IndexEntry = {
    id: "minecraft:apple",
    n: "Apple",
    k: "item",
    a: [],
    s: "item-0",
    i: "InvSprite:Apple",
  };

  const mockIndex = new Map<string, IndexEntry>([["minecraft:apple", mockAppleEntry]]);

  const createMockContext = (): RenderContext => ({
    openRef: vi.fn(),
    lookup: (id: string) => mockIndex.get(id) ?? null,
  });

  it("renders an EntityRef as a link when resolvable in the index", () => {
    const ctx = createMockContext();
    const el = entityLink({ id: "minecraft:apple", name: "Apple" }, ctx);

    expect(el.tagName).toBe("A");
    expect(el.classList.contains("entity-link")).toBe(true);
    expect(el.getAttribute("role")).toBe("button");
    expect(el.dataset["id"]).toBe("minecraft:apple");
    expect(el.querySelector(".entity-name")?.textContent).toBe("Apple");
    expect(el.querySelector(".entity-icon")).not.toBeNull();

    // Clicking invokes openRef
    el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    expect(ctx.openRef).toHaveBeenCalledWith("minecraft:apple");
  });

  it("renders an ItemAmount carrying a resolvable ref as a link with quantity", () => {
    const ctx = createMockContext();
    const el = entityLink(
      {
        name: "Apple",
        ref: { id: "minecraft:apple", name: "Apple" },
        quantity: { minimum: 4, maximum: 4 },
      },
      ctx,
    );

    expect(el.tagName).toBe("A");
    expect(el.classList.contains("entity-link")).toBe(true);
    expect(el.querySelector(".item-quantity")?.textContent).toBe("4 ");
    expect(el.querySelector(".entity-name")?.textContent).toBe("Apple");
  });

  it("asserts the converse: a present resolvable ref is never printed as plain text", () => {
    const ctx = createMockContext();

    // Plain EntityRef
    const refEl = entityLink({ id: "minecraft:apple", name: "Apple" }, ctx);
    expect(refEl.tagName).toBe("A");
    expect(refEl.classList.contains("entity-plain")).toBe(false);

    // ItemAmount with ref
    const itemEl = entityLink(
      {
        name: "Apple",
        ref: { id: "minecraft:apple", name: "Apple" },
        quantity: { minimum: 1, maximum: 1 },
      },
      ctx,
    );
    expect(itemEl.tagName).toBe("A");
    expect(itemEl.classList.contains("entity-plain")).toBe(false);
  });

  it("prints an ItemAmount whose ref is absent as plain text", () => {
    const ctx = createMockContext();
    const el = entityLink(
      {
        name: "Mystery Berry",
        quantity: { minimum: 2, maximum: 5 },
      },
      ctx,
    );

    expect(el.tagName).toBe("SPAN");
    expect(el.classList.contains("entity-plain")).toBe(true);
    expect(el.querySelector("a")).toBeNull();
    expect(el.textContent).toContain("2–5");
    expect(el.textContent).toContain("Mystery Berry");
  });

  it("degrades to plain text when a ref ID does not resolve in the index", () => {
    const ctx = createMockContext();
    const el = entityLink({ id: "minecraft:unindexed_thing", name: "Unindexed" }, ctx);

    expect(el.tagName).toBe("SPAN");
    expect(el.classList.contains("entity-plain")).toBe(true);
    expect(el.textContent).toBe("Unindexed");
  });

  it("applies rarity classes to entity-name when the target index entry declares rarity", () => {
    const beaconEntry: IndexEntry = {
      id: "minecraft:beacon",
      n: "Beacon",
      k: "block",
      a: [],
      s: "block-0",
      r: "rare",
    };
    mockIndex.set("minecraft:beacon", beaconEntry);

    const ctx = createMockContext();
    const appleEl = entityLink({ id: "minecraft:apple", name: "Apple" }, ctx);
    const appleName = appleEl.querySelector(".entity-name");
    expect(appleName?.classList.contains("rarity-rare")).toBe(false);
    expect(appleName?.classList.contains("rarity-uncommon")).toBe(false);
    expect(appleName?.classList.contains("rarity-epic")).toBe(false);

    const beaconEl = entityLink({ id: "minecraft:beacon", name: "Beacon" }, ctx);
    const beaconName = beaconEl.querySelector(".entity-name");
    expect(beaconName?.classList.contains("rarity-rare")).toBe(true);
  });
});
