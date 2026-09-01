// Generated from pipeline/schema/shard.schema.json. Do not edit.
//
// Run `pnpm schema:types` after a change to that schema. `pnpm build` runs
// the same command, and `pnpm test` fails when this file is out of date.

/**
 * One file under data/dist/entities/, named `<kind>-<n>.json` by `pipeline.emit.shard.assign_shards` -- `item-0.json`, `mob-3.json`. Holds a contiguous, id-sorted slice of one entity kind, at most `pipeline.emit.shard.DEFAULT_SHARD_SIZE` entities long. `schemaVersion` is carried here, on every shard, and not only on manifest.json, because Phase 10 caches shard payloads in IndexedDB: a cached shard can outlive the build that wrote it, sitting in a browser's storage across a Minecraft version bump that changed this contract, and a per-file version is what lets that stale copy be recognised and refetched without also reading the manifest that wrote the newer one.
 */
export interface Shard {
  /**
   * The version of this contract. A reader that finds a number it does not recognise must refuse the cached copy and refetch, rather than render a shape it was not written to understand.
   */
  schemaVersion: 1;
  /**
   * The entities this shard carries, sorted by `id` -- the same order `index.json`'s `s` field implies a client can rely on when it wants a stable position inside the file.
   *
   * @minItems 1
   */
  entities: [Entity, ...Entity[]];
}
/**
 * One entity, typed loosely here on purpose. `entity.schema.json` is the one authoritative contract for this shape; duplicating its closed, field-by-field definition into a second file would drift the moment one copy changed and the other did not, which is exactly the failure this directory's self-containment rule in `pipeline/schema/__init__.py` cannot itself prevent across two independent files. This definition exists only so `entities` above has something to point `$ref` at. `additionalProperties: true` keeps the generated TypeScript an open bag -- see `scripts/generate-schema-types.js`'s own comment on why an explicit `true` here, rather than the generator's stricter default, is what produces an index signature instead of an empty object type.
 *
 * This interface was referenced by `Shard`'s JSON-Schema
 * via the `definition` "entity".
 */
export interface Entity {
  [k: string]: unknown;
}
