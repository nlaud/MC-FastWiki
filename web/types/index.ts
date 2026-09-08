// Generated from pipeline/schema/index.schema.json. Do not edit.
//
// Run `pnpm schema:types` after a change to that schema. `pnpm build` runs
// the same command, and `pnpm test` fails when this file is out of date.

/**
 * A namespaced identifier. Vanilla content uses the `minecraft` namespace. A collection page uses the `collection` namespace. A display name is never a key. Mirrors `entity.schema.json`'s `$defs.entityId` exactly; the definition is copied rather than referenced across files, per this directory's self-containment rule in `pipeline/schema/__init__.py`.
 *
 * This interface was referenced by `Index`'s JSON-Schema
 * via the `definition` "entityId".
 */
export type EntityId = string;
/**
 * The discriminator of the Entity model. Mirrors `entity.schema.json`'s `$defs.entityKind` exactly, copied for the same self-containment reason as `entityId` above.
 *
 * This interface was referenced by `Index`'s JSON-Schema
 * via the `definition` "entityKind".
 */
export type EntityKind =
  | "mob"
  | "item"
  | "block"
  | "effect"
  | "advancement"
  | "enchantment"
  | "structure"
  | "biome"
  | "collection"
  | "entity"
  | "profession";

/**
 * data/dist/index.json, the whole Phase 4 search payload: one entry per searchable entity, sorted by `id`. Every key of an entry is short -- see `$defs.indexEntry` -- because this payload repeats them roughly 5,000 times and Phase 4 budgets 16 ms per keystroke against the whole file once it is loaded. `pipeline.emit.search_index` writes this file from the shard assignment `pipeline.emit.shard` already built, so the `s` field of every entry names a shard this same build also wrote.
 */
export interface Index {
  /**
   * The version of this contract. The web app refuses data that carries another number. Raise it whenever a schema change breaks an older reader.
   */
  schemaVersion: 1;
  /**
   * Every searchable entity of this build, sorted by `id`.
   *
   * @minItems 1
   */
  entities: [IndexEntry, ...IndexEntry[]];
}
/**
 * One entity's search row. `id` is spelled out because it is also the shard's own join key; every other key is short, and each one's own description below names the long field it stands for.
 *
 * This interface was referenced by `Index`'s JSON-Schema
 * via the `definition` "indexEntry".
 */
export interface IndexEntry {
  id: EntityId;
  /**
   * Long form: `name`. The display name. Search shows this text, and no key uses it.
   */
  n: string;
  /**
   * Long form: `kind`. Selects which renderer opens the entity once its shard has loaded.
   */
  k:
    | "mob"
    | "item"
    | "block"
    | "effect"
    | "advancement"
    | "enchantment"
    | "structure"
    | "biome"
    | "collection"
    | "entity"
    | "profession";
  /**
   * Long form: `aliases`. Every extra search term of this entity, in the order `pipeline.normalize.aliases.generate_aliases` produced them. May be empty.
   */
  a: string[];
  /**
   * Long form: `shard`. The name of the file under data/dist/entities/ that holds this entity's full record, without its `.json` suffix -- `item-3`, not `item-3.json`. The pipeline decides how entities are chunked into shards; the web app looks this value up rather than recomputing the chunking rule itself, which is what lets that rule change on a later build without a coordinated change to the web app's code.
   */
  s: string;
  /**
   * Long form: `icon`. The sprite key in the atlas coordinate map. Absent, not null, when the entity has no icon -- see `entity.schema.json`'s own `icon` field for why a missing one is a reported gap rather than a fabricated placeholder.
   */
  i?: string;
}
