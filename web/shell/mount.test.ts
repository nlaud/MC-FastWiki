import { beforeEach, describe, expect, it } from "vitest";

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
    ],
  };

  beforeEach(() => {
    document.body.replaceChildren();
    root = document.createElement("div");
    root.id = "app";
    document.body.append(root);
  });

  it("mounts search input and results list into root", () => {
    mount(root, buildCorpus(mockIndex));

    const input = root.querySelector<HTMLInputElement>("input.search-input");
    const list = root.querySelector<HTMLUListElement>("ul.search-results");

    expect(input).not.toBeNull();
    expect(list).not.toBeNull();
    expect(input?.placeholder).toBe("Search Minecraft Java...");
  });

  it("populates search results as user types", async () => {
    const corpus = buildCorpus(mockIndex);
    mount(root, corpus);

    const input = root.querySelector<HTMLInputElement>("input.search-input");
    const list = root.querySelector<HTMLUListElement>("ul.search-results");
    if (input === null || list === null) {
      throw new Error("Missing search input or results list");
    }

    input.value = "gapple";
    input.dispatchEvent(new Event("input"));

    // Flush microtasks
    await Promise.resolve();

    const items = list.querySelectorAll("li.search-result-item");
    expect(items).toHaveLength(1);
    expect(items[0]?.textContent).toBe("Golden Apple");
    expect((items[0] as HTMLElement | undefined)?.dataset["id"]).toBe("minecraft:golden_apple");
    expect((items[0] as HTMLElement | undefined)?.dataset["kind"]).toBe("item");
  });

  it("clears results when query is emptied", async () => {
    const corpus = buildCorpus(mockIndex);
    mount(root, corpus);

    const input = root.querySelector<HTMLInputElement>("input.search-input");
    const list = root.querySelector<HTMLUListElement>("ul.search-results");
    if (input === null || list === null) {
      throw new Error("Missing search input or results list");
    }

    input.value = "villager";
    input.dispatchEvent(new Event("input"));
    await Promise.resolve();
    expect(list.children).toHaveLength(1);

    input.value = "";
    input.dispatchEvent(new Event("input"));
    await Promise.resolve();
    expect(list.children).toHaveLength(0);
  });
});
