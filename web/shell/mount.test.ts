import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildCorpus } from "../search/matcher.js";
import type { Index } from "../types/index.js";
import { mount } from "./mount.js";

describe("mount", () => {
  let root: HTMLElement;

  const mockIndex: Index = {
    schemaVersion: 1,
    entities: [
      { id: "minecraft:villager", n: "Villager", k: "mob", a: [], s: "mob-0" },
      { id: "minecraft:golden_apple", n: "Golden Apple", k: "item", a: ["gapple"], s: "item-0" },
      { id: "minecraft:diamond", n: "Diamond", k: "item", a: [], s: "item-0" },
      { id: "minecraft:creeper", n: "Creeper", k: "mob", a: [], s: "mob-0" },
      { id: "minecraft:iron_ingot", n: "Iron Ingot", k: "item", a: [], s: "item-0" },
      { id: "minecraft:emerald", n: "Emerald", k: "item", a: [], s: "item-0" },
      { id: "minecraft:coal", n: "Coal", k: "item", a: [], s: "item-0" },
      { id: "minecraft:stick", n: "Stick", k: "item", a: [], s: "item-0" },
    ],
  };

  const mockShardMob0 = {
    schemaVersion: 1,
    entities: [
      {
        id: "minecraft:villager",
        kind: "mob",
        name: "Villager",
        blurb: "A passive NPC.",
        wikiUrl: "https://minecraft.wiki/w/Villager",
      },
      {
        id: "minecraft:creeper",
        kind: "mob",
        name: "Creeper",
        blurb: "A common hostile mob.",
        wikiUrl: "https://minecraft.wiki/w/Creeper",
        sections: [
          {
            type: "DropTable",
            drops: [
              {
                item: "Iron Ingot",
                itemRef: { id: "minecraft:iron_ingot", name: "Iron Ingot" },
                byLootingLevel: [
                  {
                    lootingLevel: 0,
                    minimum: 1,
                    maximum: 1,
                    average: { numerator: 1, denominator: 1 },
                    dropChance: { numerator: 1, denominator: 1 },
                    quantityText: "1",
                  },
                ],
              },
            ],
          },
        ],
      },
    ],
  };

  const mockShardItem0 = {
    schemaVersion: 1,
    entities: [
      {
        id: "minecraft:golden_apple",
        kind: "item",
        name: "Golden Apple",
        blurb: "A beneficial food item.",
        wikiUrl: "https://minecraft.wiki/w/Golden_Apple",
      },
      {
        id: "minecraft:diamond",
        kind: "item",
        name: "Diamond",
        blurb: "A precious mineral.",
        wikiUrl: "https://minecraft.wiki/w/Diamond",
      },
      {
        id: "minecraft:iron_ingot",
        kind: "item",
        name: "Iron Ingot",
        blurb: "A versatile metal.",
        wikiUrl: "https://minecraft.wiki/w/Iron_Ingot",
      },
      {
        id: "minecraft:emerald",
        kind: "item",
        name: "Emerald",
        blurb: "A green gem.",
      },
      {
        id: "minecraft:coal",
        kind: "item",
        name: "Coal",
        blurb: "A fuel mineral.",
      },
      {
        id: "minecraft:stick",
        kind: "item",
        name: "Stick",
        blurb: "A wooden stick.",
      },
    ],
  };

  beforeEach(() => {
    vi.restoreAllMocks();
    document.body.replaceChildren();
    HTMLElement.prototype.scrollBy = vi.fn();
    root = document.createElement("div");
    root.id = "app";
    document.body.append(root);

    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("mob-0")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(mockShardMob0),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(mockShardItem0),
      });
    });
  });

  it("mounts containers into root and autofocuses input", () => {
    mount(root, buildCorpus(mockIndex));

    const input = root.querySelector<HTMLInputElement>("input.search-input");
    const windowsRoot = root.querySelector("#windows-root");
    const searchRoot = root.querySelector("#search-root");
    const helpRoot = root.querySelector("#help-root");

    expect(input).not.toBeNull();
    expect(windowsRoot).not.toBeNull();
    expect(searchRoot).not.toBeNull();
    expect(helpRoot).not.toBeNull();
    expect(document.activeElement).toBe(input);
  });

  it("populates search suggestions with first item selected by default", async () => {
    const corpus = buildCorpus(mockIndex);
    mount(root, corpus);

    const input = root.querySelector<HTMLInputElement>("input.search-input");
    if (!input) throw new Error("Missing input");
    input.value = "gapple";
    input.dispatchEvent(new Event("input"));

    await Promise.resolve();

    const items = root.querySelectorAll(".suggestion-item");
    expect(items).toHaveLength(1);
    expect(items[0]?.textContent).toContain("Golden Apple");
    expect(items[0]?.classList.contains("is-selected")).toBe(true);
    expect(input.getAttribute("aria-expanded")).toBe("true");
  });

  it("supports Up/Down arrow selection movement", async () => {
    const corpus = buildCorpus(mockIndex);
    mount(root, corpus);

    const input = root.querySelector<HTMLInputElement>("input.search-input");
    if (!input) throw new Error("Missing input");
    input.value = "e"; // matches multiple entities
    input.dispatchEvent(new Event("input"));

    await Promise.resolve();

    const items = root.querySelectorAll(".suggestion-item");
    expect(items.length).toBeGreaterThan(1);
    expect(items[0]?.classList.contains("is-selected")).toBe(true);

    // Press ArrowDown to move to item 1
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown" }));
    let updatedItems = root.querySelectorAll(".suggestion-item");
    expect(updatedItems[0]?.classList.contains("is-selected")).toBe(false);
    expect(updatedItems[1]?.classList.contains("is-selected")).toBe(true);

    // Press ArrowUp to move back to item 0
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowUp" }));
    updatedItems = root.querySelectorAll(".suggestion-item");
    expect(updatedItems[0]?.classList.contains("is-selected")).toBe(true);

    // Press ArrowUp from 0 to wrap to last item
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowUp" }));
    updatedItems = root.querySelectorAll(".suggestion-item");
    expect(updatedItems[updatedItems.length - 1]?.classList.contains("is-selected")).toBe(true);
  });

  it("opens selected suggestion in a window on Enter and loads shard", async () => {
    const corpus = buildCorpus(mockIndex);
    mount(root, corpus);

    const input = root.querySelector<HTMLInputElement>("input.search-input");
    if (!input) throw new Error("Missing input");
    input.value = "creeper";
    input.dispatchEvent(new Event("input"));

    await Promise.resolve();

    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));

    const windows = root.querySelectorAll(".wiki-window");
    expect(windows).toHaveLength(1);
    expect(windows[0]?.querySelector(".window-title")?.textContent).toBe("Creeper");

    // Flush shard load microtasks
    await new Promise((resolve) => setTimeout(resolve, 20));

    const blurb = windows[0]?.querySelector(".entity-blurb");
    expect(blurb?.textContent).toBe("A common hostile mob.");
    const badge = windows[0]?.querySelector(".entity-kind-badge");
    expect(badge?.textContent).toBe("mob");
  });

  it("hides search bar and shows hint at 8 windows, and restores bar on Alt+W", async () => {
    const corpus = buildCorpus(mockIndex);
    mount(root, corpus);

    const input = root.querySelector<HTMLInputElement>("input.search-input");
    const hint = root.querySelector<HTMLElement>(".search-max-hint");
    if (!input || !hint) throw new Error("Missing input or hint");

    const openItem = async (query: string): Promise<void> => {
      input.value = query;
      input.dispatchEvent(new Event("input"));
      await Promise.resolve();
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
      await Promise.resolve();
    };

    await openItem("villager");
    await openItem("diamond");
    await openItem("creeper");
    await openItem("iron");
    await openItem("golden");
    await openItem("emerald");
    await openItem("coal");
    expect(hint.style.display).toBe("none");

    await openItem("stick");
    expect(root.querySelectorAll(".wiki-window")).toHaveLength(8);
    expect(hint.style.display).toBe("block");
    expect(input.parentElement?.style.display).toBe("none");

    // Close focused window with Alt+W
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "w", altKey: true }));
    expect(root.querySelectorAll(".wiki-window")).toHaveLength(7);
    expect(hint.style.display).toBe("none");
    expect(input.parentElement?.style.display).toBe("block");
    expect(document.activeElement).toBe(input);
  });

  it("scrolls focused window by clientHeight on Shift+ArrowDown", async () => {
    const corpus = buildCorpus(mockIndex);
    mount(root, corpus);

    const input = root.querySelector<HTMLInputElement>("input.search-input");
    if (!input) throw new Error("Missing input");
    input.value = "creeper";
    input.dispatchEvent(new Event("input"));
    await Promise.resolve();
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
    await Promise.resolve();

    const windowBody = root.querySelector<HTMLElement>(".window-body");
    if (!windowBody) throw new Error("Missing window body");

    const scrollByMock = vi.fn();
    windowBody.scrollBy = scrollByMock;
    Object.defineProperty(windowBody, "clientHeight", { value: 600, configurable: true });

    window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", shiftKey: true }));

    expect(scrollByMock).toHaveBeenCalledWith({
      top: 600,
      behavior: "smooth",
    });
  });

  it("toggles help overlay with F1 and dismisses it with Esc", () => {
    mount(root, buildCorpus(mockIndex));

    expect(root.querySelector(".help-backdrop")).toBeNull();

    window.dispatchEvent(new KeyboardEvent("keydown", { key: "F1" }));
    expect(root.querySelector(".help-backdrop")).not.toBeNull();

    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(root.querySelector(".help-backdrop")).toBeNull();
  });

  it("prevents the default insertion when a printable key focuses the bar", () => {
    mount(root, buildCorpus(mockIndex));

    const input = root.querySelector<HTMLInputElement>("input.search-input");
    if (!input) throw new Error("Missing input");
    input.blur();

    // Focus moves to the input during this keydown. Unless the default is
    // prevented, a real browser also performs the keystroke's own insertion
    // against the newly focused field, and the character arrives twice --
    // typing "d" from an unfocused bar produced "dd". jsdom does not perform
    // that default action, so the prevented flag is what this can assert.
    const event = new KeyboardEvent("keydown", { key: "d", cancelable: true });
    window.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(input);
    expect(input.value).toBe("d");
  });

  it("refocuses search input on mouseup when selection is collapsed", () => {
    mount(root, buildCorpus(mockIndex));

    const input = root.querySelector<HTMLInputElement>("input.search-input");
    if (!input) throw new Error("Missing input");
    input.blur();
    expect(document.activeElement).not.toBe(input);

    document.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    expect(document.activeElement).toBe(input);
  });

  it("keeps the bar's focus class through a click inside a window", async () => {
    // The focus-ring bug. Pressing the mouse inside a window moves DOM focus
    // onto that window's article, and the mouseup guard hands it straight back,
    // so a ring bound to `:focus` animated out and in on every click. The class
    // records the shell's intent instead, and an incidental click never
    // changes it -- so the computed style never changes and nothing animates.
    const corpus = buildCorpus(mockIndex);
    mount(root, corpus);

    const input = root.querySelector<HTMLInputElement>("input.search-input");
    if (!input) throw new Error("Missing input");
    input.value = "creeper";
    input.dispatchEvent(new Event("input"));
    await Promise.resolve();
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(input.classList.contains("is-bar-focused")).toBe(true);

    const body = root.querySelector<HTMLElement>(".wiki-window .window-body");
    if (!body) throw new Error("Missing window body");

    // A real browser moves focus to the window article on mousedown. jsdom does
    // not, so the blur is performed here to reproduce what the browser does.
    body.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    input.blur();
    expect(input.classList.contains("is-bar-focused")).toBe(true);

    body.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    expect(input.classList.contains("is-bar-focused")).toBe(true);
    expect(document.activeElement).toBe(input);
  });

  it("drops the bar's focus class when Tab hands the keyboard to a window", async () => {
    const corpus = buildCorpus(mockIndex);
    mount(root, corpus);

    const input = root.querySelector<HTMLInputElement>("input.search-input");
    if (!input) throw new Error("Missing input");
    input.value = "creeper";
    input.dispatchEvent(new Event("input"));
    await Promise.resolve();
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(input.classList.contains("is-bar-focused")).toBe(true);

    // Tab is the one gesture that genuinely gives the keyboard away, so this is
    // the case where the ring is supposed to fade out -- exactly once.
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab" }));
    expect(input.classList.contains("is-bar-focused")).toBe(false);
  });

  it("opens a second window when clicking a rendered entity link", async () => {
    const corpus = buildCorpus(mockIndex);
    mount(root, corpus);

    const input = root.querySelector<HTMLInputElement>("input.search-input");
    if (!input) throw new Error("Missing input");
    input.value = "creeper";
    input.dispatchEvent(new Event("input"));

    await Promise.resolve();
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));

    // Flush shard load microtasks
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(root.querySelectorAll(".wiki-window")).toHaveLength(1);

    // Find rendered link for Iron Ingot in Creeper window
    const link = root.querySelector<HTMLAnchorElement>(".wiki-window .entity-link");
    expect(link).not.toBeNull();
    expect(link?.textContent).toContain("Iron Ingot");

    // Click link to open target entity
    link?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));

    await Promise.resolve();

    const windows = root.querySelectorAll(".wiki-window");
    expect(windows).toHaveLength(2);
    expect(windows[1]?.querySelector(".window-title")?.textContent).toBe("Iron Ingot");
  });
});
