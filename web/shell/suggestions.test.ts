import { describe, expect, it, vi } from "vitest";

import type { IndexEntry } from "../types/index.js";
import { renderSuggestions } from "./suggestions.js";

function entry(id: string, name: string): IndexEntry {
  return { id, n: name, k: "item", a: [], s: "item-0" };
}

const results: IndexEntry[] = [
  entry("minecraft:diamond", "Diamond"),
  entry("minecraft:diamond_axe", "Diamond Axe"),
  entry("minecraft:diamond_hoe", "Diamond Hoe"),
];

describe("renderSuggestions", () => {
  it("renders one option per result and marks only the selected one", () => {
    const container = document.createElement("div");

    renderSuggestions(container, { results, selectedIndex: 1, onSelect: () => undefined });

    const items = container.querySelectorAll(".suggestion-item");
    expect(items).toHaveLength(3);
    expect(items[1]?.getAttribute("aria-selected")).toBe("true");
    expect(items[0]?.getAttribute("aria-selected")).toBe("false");
    expect(items[2]?.getAttribute("aria-selected")).toBe("false");
  });

  it("hides the container when there is nothing to show", () => {
    const container = document.createElement("div");

    renderSuggestions(container, { results: [], selectedIndex: -1, onSelect: () => undefined });

    expect(container.style.display).toBe("none");
    expect(container.querySelectorAll(".suggestion-item")).toHaveLength(0);
  });

  // The list caps its height and scrolls. Without this, moving the selection
  // past the fold with Up/Down left the selected row outside the visible box,
  // so Enter opened an entity the user could not see. Observed in Chrome: the
  // tenth result of `diamond` stayed at scrollTop 0 and out of view.
  // jsdom implements no layout, so the call itself is what can be asserted.
  it("scrolls the selected option into view, and only that one", () => {
    const container = document.createElement("div");
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;

    renderSuggestions(container, { results, selectedIndex: 2, onSelect: () => undefined });

    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest" });
  });

  it("scrolls nothing into view when no option is selected", () => {
    const container = document.createElement("div");
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;

    renderSuggestions(container, { results, selectedIndex: -1, onSelect: () => undefined });

    expect(scrollIntoView).not.toHaveBeenCalled();
  });

  it("applies rarity classes to suggestion-name when entry declares rarity", () => {
    const container = document.createElement("div");
    const testResults: IndexEntry[] = [
      { id: "minecraft:apple", n: "Apple", k: "item", a: [], s: "item-0" },
      { id: "minecraft:golden_apple", n: "Golden Apple", k: "item", a: [], s: "item-0", r: "rare" },
      { id: "minecraft:mace", n: "Mace", k: "item", a: [], s: "item-0", r: "epic" },
    ];

    renderSuggestions(container, {
      results: testResults,
      selectedIndex: 0,
      onSelect: () => undefined,
    });

    const names = container.querySelectorAll(".suggestion-name");
    expect(names[0]?.classList.contains("rarity-rare")).toBe(false);
    expect(names[1]?.classList.contains("rarity-rare")).toBe(true);
    expect(names[2]?.classList.contains("rarity-epic")).toBe(true);
  });
});
