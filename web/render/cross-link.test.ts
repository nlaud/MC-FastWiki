import fs from "node:fs";
import path from "node:path";
import { beforeAll, describe, expect, it } from "vitest";
import type { Entity } from "../types/entity.js";
import type { IndexEntry } from "../types/index.js";
import type { RenderContext } from "./context.js";
import { renderSection } from "./sections/index.js";

interface DiscoveredRef {
  id: string;
  name: string;
  path: string;
}

function collectRefs(obj: unknown, pathStr = ""): DiscoveredRef[] {
  const results: DiscoveredRef[] = [];
  if (!obj || typeof obj !== "object") {
    return results;
  }
  if (Array.isArray(obj)) {
    obj.forEach((item, i) => {
      results.push(...collectRefs(item, `${pathStr}[${i.toString()}]`));
    });
    return results;
  }
  const record = obj as Record<string, unknown>;
  if (
    typeof record["id"] === "string" &&
    record["id"].includes(":") &&
    typeof record["name"] === "string"
  ) {
    results.push({ id: record["id"], name: record["name"], path: pathStr });
  }
  for (const [key, value] of Object.entries(record)) {
    if (key !== "id" && key !== "name") {
      results.push(...collectRefs(value, pathStr ? `${pathStr}.${key}` : key));
    }
  }
  return results;
}

interface MissReport {
  entityId: string;
  entityKind: string;
  sectionType: string;
  refId: string;
  refName: string;
  refPath: string;
}

describe("Lint B: cross-link rendering", () => {
  let indexIds: Set<string>;
  let idMap: Map<string, IndexEntry>;
  let entities: Entity[];
  let ctx: RenderContext;

  beforeAll(() => {
    const indexPath = path.resolve(process.cwd(), "data/dist/index.json");
    const indexData = JSON.parse(fs.readFileSync(indexPath, "utf8")) as {
      entities: IndexEntry[];
    };
    idMap = new Map();
    indexIds = new Set();
    for (const entry of indexData.entities) {
      idMap.set(entry.id, entry);
      indexIds.add(entry.id);
    }

    ctx = {
      openRef: () => {},
      lookup: (id: string) => idMap.get(id) ?? null,
    };

    const shardsDir = path.resolve(process.cwd(), "data/dist/entities");
    const shardFiles = fs.readdirSync(shardsDir).filter((f) => f.endsWith(".json"));
    entities = [];
    for (const file of shardFiles) {
      const content = fs.readFileSync(path.join(shardsDir, file), "utf8");
      const shard = JSON.parse(content) as { entities: Entity[] };
      entities.push(...shard.entities);
    }
  });

  it("reports unrendered cross-references across all entities", () => {
    const misses: MissReport[] = [];
    let totalCheckedRefs = 0;
    let totalSectionsChecked = 0;

    for (const entity of entities) {
      for (const section of entity.sections) {
        // No section type is skipped here. An earlier version skipped TradeTable on any
        // page that was not the seller's own, which suppressed the 170 item and block
        // pages whose trade table was rendering nothing at all -- the exact bug this
        // lint exists to surface. A section a renderer declines to draw is already
        // covered by the `!el` guard below.
        const el = renderSection(section, ctx, entity);
        if (!el) {
          continue;
        }
        totalSectionsChecked++;

        const refs = collectRefs(section);
        const renderedLinks = el.querySelectorAll("a.entity-link");
        const renderedIds = new Set<string>();
        renderedLinks.forEach((link) => {
          const id = (link as HTMLElement).dataset["id"];
          if (id) {
            renderedIds.add(id);
          }
        });

        for (const ref of refs) {
          // Only check refs whose ID exists in the search index
          if (!indexIds.has(ref.id)) {
            continue;
          }

          // Documented exemption: On a seller's own page (profession or wandering trader mob),
          // TradeTable groups by level alone and omits the self-referential profession heading,
          // because linking the reader to the page they are already reading is noise (sections/index.ts:51-57).
          if (
            section.type === "TradeTable" &&
            (entity.kind === "profession" || entity.kind === "mob") &&
            ref.path.endsWith("professionRef") &&
            ref.id === entity.id
          ) {
            continue;
          }

          totalCheckedRefs++;

          if (!renderedIds.has(ref.id)) {
            misses.push({
              entityId: entity.id,
              entityKind: entity.kind,
              sectionType: section.type,
              refId: ref.id,
              refName: ref.name,
              refPath: ref.path,
            });
          }
        }
      }
    }

    expect(totalSectionsChecked).toBeGreaterThan(1000);
    expect(totalCheckedRefs).toBeGreaterThan(7000);
    expect(misses).toEqual([]);
  }, 30_000);

  it("detects when an entity ref is rendered as plain text instead of a link", () => {
    // Given an element where a renderer printed plain text instead of calling entityLink
    const dummyEl = document.createElement("div");
    const plainSpan = document.createElement("span");
    plainSpan.className = "entity-plain";
    plainSpan.textContent = "Diamond";
    dummyEl.append(plainSpan);

    const renderedLinks = dummyEl.querySelectorAll("a.entity-link");
    const renderedIds = new Set<string>();
    renderedLinks.forEach((link) => {
      const id = (link as HTMLElement).dataset["id"];
      if (id) {
        renderedIds.add(id);
      }
    });

    const ref = { id: "minecraft:diamond", name: "Diamond" };
    expect(indexIds.has(ref.id)).toBe(true);
    expect(renderedIds.has(ref.id)).toBe(false);
  });
});
