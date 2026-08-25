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

    // `wikiUrl` is not optional, and the annotation is the assertion: the wiki
    // text is CC BY-NC-SA 3.0, so an entity that carries a blurb and no link to
    // its source page breaks the license. Widen the schema and this line stops
    // compiling, because `string | undefined` does not fit `string`.
    const credit: string = creeper.wikiUrl;

    expect(creeper.sections[0]?.type).toBe("LinkList");
    expect(creeper.sourceTiers["blurb"]).toBe("B");
    expect(credit).toContain("minecraft.wiki");
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
