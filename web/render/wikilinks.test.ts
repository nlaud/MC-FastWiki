import { describe, expect, it, vi } from "vitest";
import type { IndexEntry } from "../types/index.js";
import type { RenderContext } from "./context.js";
import { appendWikiText } from "./wikilinks.js";

const ENTRIES: IndexEntry[] = [
  { id: "minecraft:witch", n: "Witch", k: "mob", a: [], i: "EntitySprite:witch" },
  { id: "minecraft:shipwreck", n: "Shipwreck", k: "block", a: [], i: "InvSprite:Shipwreck" },
] as unknown as IndexEntry[];

function makeContext(): RenderContext & { openRef: ReturnType<typeof vi.fn> } {
  const byId = new Map(ENTRIES.map((e) => [e.id, e]));
  const byName = new Map(ENTRIES.map((e) => [e.n.toLowerCase(), e]));
  const openRef = vi.fn();
  return {
    openRef,
    lookup: (id: string) =>
      byId.get(id) ??
      byName.get(id.toLowerCase()) ??
      byId.get(`minecraft:${id.toLowerCase().replace(/\s+/g, "_")}`) ??
      null,
  };
}

function render(raw: string) {
  const ctx = makeContext();
  const host = document.createElement("p");
  appendWikiText(host, raw, ctx);
  return { host, ctx };
}

describe("appendWikiText", () => {
  it("turns a wikilink whose target resolves into a real entity link", () => {
    const { host } = render("[[Witch|Witches]] drink this potion.");

    const link = host.querySelector<HTMLAnchorElement>("a.entity-link");
    expect(link).not.toBeNull();
    expect(link?.dataset["id"]).toBe("minecraft:witch");
    // The label the wiki chose, not the page title.
    expect(link?.querySelector(".entity-name")?.textContent).toBe("Witches");
    expect(host.textContent).toContain("drink this potion.");
  });

  it("resolves a bare wikilink through the display name", () => {
    const { host } = render("Found in [[Shipwreck]] chests.");

    const link = host.querySelector<HTMLAnchorElement>("a.entity-link");
    expect(link?.dataset["id"]).toBe("minecraft:shipwreck");
  });

  it("prints an unresolvable target as plain text rather than a dead link", () => {
    // The wiki links plenty of pages this build holds no entity for.
    const { host } = render("increases speed while [[walking]] or [[sprinting]].");

    expect(host.querySelector("a")).toBeNull();
    expect(host.textContent).toBe("increases speed while walking or sprinting.");
  });

  it("keeps the text around and between links", () => {
    const { host } = render("A [[Witch|Witches]] B [[Shipwreck]] C");

    expect(host.textContent).toBe("A Witches B Shipwreck C");
    expect(host.querySelectorAll("a.entity-link")).toHaveLength(2);
  });

  it("opens the entity when the link is clicked", () => {
    const { host, ctx } = render("[[Witch|Witches]]");

    host.querySelector<HTMLAnchorElement>("a.entity-link")?.click();
    expect(ctx.openRef).toHaveBeenCalledWith("minecraft:witch");
  });

  it("passes plain prose through untouched", () => {
    const { host } = render("Replenishes when in range.");

    expect(host.textContent).toBe("Replenishes when in range.");
    expect(host.querySelector("a")).toBeNull();
  });

  it("starts each call from the beginning of the text", () => {
    // The pattern is module-level and stateful, so a second call must not
    // resume from where the first one stopped.
    const first = render("[[Witch|Witches]] one");
    const second = render("[[Witch|Witches]] two");

    expect(first.host.querySelectorAll("a.entity-link")).toHaveLength(1);
    expect(second.host.querySelectorAll("a.entity-link")).toHaveLength(1);
  });
});
