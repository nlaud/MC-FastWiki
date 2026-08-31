import { describe, expect, it } from "vitest";

import type { Entity, EntityRef, Section } from "./web/types/entity.js";
import type { Manifest } from "./web/types/manifest.js";

// `/pipeline/schema` is the contract between the Python pipeline and the web
// app. `pnpm schema:types` turns those JSON Schema files into the types that
// this file imports, and the generated files stay in Git so a reviewer reads
// the current contract.
//
// These cases are type assertions first. Each one fails the type check when a
// schema change removes a field or renames a type, which is the half of the
// contract that a runtime assertion cannot reach. The `pnpm test` script runs
// `pnpm schema:check` in front of vitest, so a stale generated file fails
// before these cases run.

describe("generated schema types", () => {
  it("describe an entity of the shape that CLAUDE.md names", () => {
    const ref: EntityRef = { id: "minecraft:cave", name: "Cave" };
    const section: Section = { type: "LinkList", links: [ref] };
    const creeper: Entity = {
      id: "minecraft:creeper",
      kind: "mob",
      name: "Creeper",
      aliases: ["creeper", "creep"],
      icon: "EntitySprite creeper",
      blurb: "A creeper is a hostile mob.",
      wikiUrl: "https://minecraft.wiki/w/Creeper",
      sourceTiers: { name: "A", blurb: "B" },
      sections: [section],
    };

    // Decision D1: `wikiUrl` is required exactly when `sourceTiers` names
    // Tier B for some field, not unconditionally -- the unreleased
    // `poplar_*` registry IDs have no wiki page at all, so an unconditional
    // requirement would make them impossible to represent. A JSON Schema
    // `if`/`then` conditional cannot be expressed as a TypeScript conditional
    // type by this generator, so `wikiUrl` types as optional here for every
    // entity; the obligation the CC BY-NC-SA 3.0 license actually imposes is
    // enforced at build time instead, by `Entity`'s own validator in
    // `pipeline.normalize.entity`. This creeper carries Tier B provenance
    // (`blurb: "B"`), so the value is present at runtime even though the
    // type alone does not guarantee it.
    const credit = creeper.wikiUrl;

    expect(creeper.sections[0]?.type).toBe("LinkList");
    expect(creeper.sourceTiers["blurb"]).toBe("B");
    expect(credit).toContain("minecraft.wiki");
  });

  it("allows wikiUrl to be omitted for an entity with no Tier B provenance", () => {
    // The other half of decision D1: the `poplar_*` set carries only Tier A
    // provenance and no wiki page, so it must type-check with `wikiUrl`
    // absent entirely, not merely set to `undefined`.
    const poplarBoat: Entity = {
      id: "minecraft:poplar_boat",
      kind: "item",
      name: "Poplar Boat",
      aliases: ["poplar_boat"],
      sourceTiers: { name: "A" },
      sections: [],
    };

    expect(poplarBoat.wikiUrl).toBeUndefined();
  });

  it("describe a build manifest", () => {
    const manifest: Manifest = {
      schemaVersion: 1,
      minecraftVersion: "26.2",
      mcmetaRef: "26.2-data",
      pipelineVersion: "0.1.0",
      builtAt: "2026-08-24T21:00:00Z",
    };

    expect(manifest.schemaVersion).toBe(1);
  });
});
