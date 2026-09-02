// Generated from pipeline/schema/obtain.schema.json. Do not edit.
//
// Run `pnpm schema:types` after a change to that schema. `pnpm build` runs
// the same command, and `pnpm test` fails when this file is out of date.

/**
 * A namespaced identifier. Vanilla content uses the `minecraft` namespace. Mirrors `entity.schema.json`'s `$defs.entityId` exactly; the definition is copied rather than referenced across files, per this directory's self-containment rule in `pipeline/schema/__init__.py`.
 *
 * This interface was referenced by `Obtain`'s JSON-Schema
 * via the `definition` "entityId".
 */
export type EntityId = string;
/**
 * How one producer turns its inputs into its output. Mirrors `pipeline.obtain.producer.ObtainMethod` exactly -- there is no separate member for stonecutting or smithing, both of which are crafting-like and are told apart by `st` (station) rather than by their own method member. `filling` is the world interaction that produces a water bottle from a glass bottle: no recipe or loot table produces one, and without it every potion tree stops one step above the glass bottle.
 *
 * This interface was referenced by `Obtain`'s JSON-Schema
 * via the `definition` "obtainMethod".
 */
export type ObtainMethod =
  "crafting" | "smelting" | "brewing" | "filling" | "mob_loot" | "chest_loot" | "trade" | "block_drop";

/**
 * data/dist/obtain.json, the flat producer graph the web app assembles into an item's obtain tree at render time. `pipeline.emit.obtain` writes this file from a `pipeline.obtain.producer.ProducerIndex`, and `pipeline.obtain.tree.build_obtain_tree` is the reference implementation of the walk a renderer performs against it -- see that module's own docstring for the four rules the walk applies (cycle handling, memoization, a depth cap, and repeated-subtree collapse). The pipeline used to materialise a depth-capped tree into every entity shard instead; measured against the real 26.2 data, that cost 73.8 MB raw and 4.1 MB gzipped for strictly less depth than this file carries at 1.05 MB raw and 0.07 MB gzipped, because the same subtrees were being duplicated into hundreds of shards. Every key of a producer or an input is short, the same convention `index.schema.json`'s `indexEntry` uses, because this file carries every producer this build knows about with no depth cap -- each short key's own description below names the long field it stands for.
 */
export interface Obtain {
  /**
   * The version of this contract. The web app refuses data that carries another number. Raise it whenever a schema change breaks an older reader.
   */
  schemaVersion: 1;
  /**
   * Every producer this build found, keyed by the item id it produces. A key with no entry in this map has no known producer at all -- see `pipeline.cli.build.ObtainReport.items_with_no_producer` for the build-time accounting of that gap.
   */
  producers: {
    [k: string]: ObtainProducer[];
  };
}
/**
 * One way to produce an item, mirroring `pipeline.obtain.producer.Producer`. Carries no field naming what it produces -- that is the item id it sits under in `producers` above.
 *
 * This interface was referenced by `Obtain`'s JSON-Schema
 * via the `definition` "obtainProducer".
 */
export interface ObtainProducer {
  /**
   * Long form: method.
   */
  m: "crafting" | "smelting" | "brewing" | "filling" | "mob_loot" | "chest_loot" | "trade" | "block_drop";
  /**
   * Long form: count. How many of the output item this producer yields at once. Mirrors `pipeline.obtain.producer.ProducerOutput.count`.
   */
  c?: number;
  /**
   * Long form: sourceId. Where this producer came from -- a recipe path, a loot table path, a brewing rule's own description -- so a report can point at the exact upstream row a bad producer traces back to.
   */
  src: string;
  /**
   * Long form: station. The block or entity the player uses, where one applies: "furnace", "blast_furnace", "smoker", "campfire", "stonecutter", "smithing_table", "brewing_stand". Absent when no station applies.
   */
  st?: string;
  /**
   * Long form: note. A qualifier a renderer should show but that changes no other field's shape: "requires silk touch", "requires looting".
   */
  nt?: string;
  /**
   * Long form: inputs. Every ingredient slot this producer consumes, in producer-declaration order.
   */
  in?: ObtainProducerInput[];
}
/**
 * One ingredient slot of an `obtainProducer`, mirroring `pipeline.obtain.producer.ProducerInput`. Exactly one of `i` (item) or `t` (tag) is present: a plain item names `i` and leaves `t` and `mb` (members) absent; a tag names `t` and `mb`, and leaves `i` absent; the untagged-alternatives-list shape `pipeline.obtain.recipes` produces sets `i` to the alphabetically-first alternative and still carries the full sorted list in `mb`.
 *
 * This interface was referenced by `Obtain`'s JSON-Schema
 * via the `definition` "obtainProducerInput".
 */
export interface ObtainProducerInput {
  /**
   * A namespaced identifier. Vanilla content uses the `minecraft` namespace. Mirrors `entity.schema.json`'s `$defs.entityId` exactly; the definition is copied rather than referenced across files, per this directory's self-containment rule in `pipeline/schema/__init__.py`.
   */
  i?: string;
  /**
   * Long form: tag. Present for a tag input. Absent otherwise.
   */
  t?: string;
  /**
   * Long form: count. How many of this input one use of the producer consumes.
   */
  c?: number;
  /**
   * Long form: members. What `t` resolved to, for a tag input, or the full sorted alternatives list, for an untagged alternatives-list input. Empty for a plain item input.
   */
  mb?: EntityId[];
}
