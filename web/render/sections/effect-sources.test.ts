import fs from "node:fs";
import path from "node:path";
import { beforeAll, describe, expect, it, vi } from "vitest";
import type { EffectSources, Entity } from "../../types/entity.js";
import type { IndexEntry } from "../../types/index.js";
import type { RenderContext } from "../context.js";
import { renderEffectSources } from "./effect-sources.js";

function requireItem<T>(item: T | undefined | null, name: string): T {
  if (item === undefined || item === null) {
    throw new Error(`Expected ${name} to be defined`);
  }
  return item;
}

describe("renderEffectSources", () => {
  let effectsById: Map<string, Entity>;
  let ctx: RenderContext;

  beforeAll(() => {
    const raw = fs.readFileSync(
      path.resolve(process.cwd(), "data/dist/entities/effect-0.json"),
      "utf8",
    );
    const data = JSON.parse(raw) as { entities: Entity[] };
    effectsById = new Map<string, Entity>();
    for (const entity of data.entities) {
      effectsById.set(entity.id, entity);
    }

    const indexRaw = fs.readFileSync(path.resolve(process.cwd(), "data/dist/index.json"), "utf8");
    const index = JSON.parse(indexRaw) as { entities: IndexEntry[] };
    const idMap = new Map<string, IndexEntry>();
    for (const entry of index.entities) {
      idMap.set(entry.id, entry);
    }

    ctx = {
      openRef: vi.fn(),
      lookup: (id: string) => idMap.get(id) ?? null,
    };
  });

  const effectSectionOf = (id: string): EffectSources => {
    const entity = requireItem(effectsById.get(id), id);
    const section = entity.sections.find((s): s is EffectSources => s.type === "EffectSources");
    return requireItem(section, `${id} EffectSources`);
  };

  it("is attached as the first section on effect entities", () => {
    const poison = requireItem(effectsById.get("minecraft:poison"), "Poison");
    expect(poison.sections[0]?.type).toBe("EffectSources");

    const speed = requireItem(effectsById.get("minecraft:speed"), "Speed");
    expect(speed.sections[0]?.type).toBe("EffectSources");
  });

  it("renders Poison with negative category badge, behaviour, removers, and sources table", () => {
    const section = effectSectionOf("minecraft:poison");
    const el = renderEffectSources(section, ctx);

    expect(el.className).toContain("effect-sources-section");
    expect(el.querySelector(".section-title")?.textContent).toBe("Effect Sources");

    const badge = el.querySelector(".effect-category-badge");
    expect(badge?.textContent).toBe("negative");
    expect(badge?.className).toContain("category-negative");

    const behaviour = el.querySelector(".effect-behaviour");
    expect(behaviour?.textContent).toContain("damage");

    // Removed by row
    const removedBy = el.querySelector(".effect-removed-by");
    expect(removedBy?.textContent).toContain("Removed by:");
    const removers = removedBy?.querySelectorAll<HTMLAnchorElement>("a.entity-link");
    expect(removers?.length).toBe(2);
    expect(removers?.[0]?.dataset["id"]).toBe("minecraft:milk_bucket");
    expect(removers?.[1]?.dataset["id"]).toBe("minecraft:honey_bottle");

    // Sources table
    const table = el.querySelector(".effect-sources-table");
    expect(table).not.toBeNull();
    const ths = table?.querySelectorAll("th");
    expect(ths?.length).toBe(4);
    expect(ths?.[0]?.textContent).toBe("Source");
    expect(ths?.[1]?.textContent).toBe("Potency");
    expect(ths?.[2]?.textContent).toBe("Duration");
    expect(ths?.[3]?.textContent).toBe("Notes");

    const rows = table?.querySelectorAll("tbody tr");
    expect(rows && rows.length > 0).toBe(true);

    // First row: Potion of Poison
    const firstRow = rows?.[0];
    const sourceLink = firstRow?.querySelector<HTMLAnchorElement>("a.entity-link");
    expect(sourceLink?.textContent).toContain("Potion of Poison");
    expect(firstRow?.querySelector(".effect-source-potency")?.textContent).toBe("I");
    expect(firstRow?.querySelector(".effect-source-length")?.textContent).toBe("0:45");
    expect(firstRow?.querySelector(".effect-source-notes")?.textContent).toContain("Damage: 36");

    // Check extended potion row has qualifier
    const extendedRow = Array.from(rows ?? []).find((r) =>
      r.querySelector(".effect-source-qualifier")?.textContent.includes("(extended)"),
    );
    expect(extendedRow).toBeDefined();
    expect(extendedRow?.querySelector(".effect-source-length")?.textContent).toBe("1:30");
  });

  it("renders Speed with positive category badge and Milk Bucket remover", () => {
    const section = effectSectionOf("minecraft:speed");
    const el = renderEffectSources(section, ctx);

    const badge = el.querySelector(".effect-category-badge");
    expect(badge?.textContent).toBe("positive");
    expect(badge?.className).toContain("category-positive");

    const removers = el.querySelectorAll(".effect-removed-by a.entity-link");
    expect(removers.length).toBe(1);
    expect(removers[0]?.getAttribute("data-id")).toBe("minecraft:milk_bucket");
  });

  it("renders Bad Luck with Commands as plain text (no EntityRef link)", () => {
    const section = effectSectionOf("minecraft:unluck");
    const el = renderEffectSources(section, ctx);

    const badge = el.querySelector(".effect-category-badge");
    expect(badge?.textContent).toBe("negative");

    const table = el.querySelector(".effect-sources-table");
    const rows = table?.querySelectorAll("tbody tr");
    expect(rows?.length).toBe(1);

    const row = rows?.[0];
    // Commands is plain text, not an entity link
    expect(row?.querySelector("a.entity-link")).toBeNull();
    expect(row?.querySelector(".entity-name")?.textContent).toBe("Commands");
    expect(row?.querySelector(".effect-source-notes")?.textContent).toContain("/effect");
  });

  it("renders minimal EffectSources section without behaviour, removers, or sources", () => {
    const minimal: EffectSources = {
      type: "EffectSources",
      category: "neutral",
      sources: [],
      removedBy: [],
    };
    const el = renderEffectSources(minimal, ctx);

    expect(el.querySelector(".effect-category-badge")?.textContent).toBe("neutral");
    expect(el.querySelector(".effect-behaviour")).toBeNull();
    expect(el.querySelector(".effect-removed-by")).toBeNull();
    expect(el.querySelector(".effect-sources-table")).toBeNull();
  });
});
