// Generated from pipeline/schema/entity.schema.json. Do not edit.
//
// Run `pnpm schema:types` after a change to that schema. `pnpm build` runs
// the same command, and `pnpm test` fails when this file is out of date.

/**
 * A namespaced identifier. Vanilla content uses the `minecraft` namespace. A collection page uses the `collection` namespace. A display name is never a key.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "entityId".
 */
export type EntityId = string;
/**
 * The discriminator of the Entity model. It selects the renderer.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "entityKind".
 */
export type EntityKind =
  "mob" | "item" | "block" | "effect" | "advancement" | "enchantment" | "structure" | "biome" | "collection" | "entity";
/**
 * The tier that produced one field. A is vanilla game data from mcmeta. B is the Minecraft Wiki. C is a curated override. A later tier wins.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "sourceTier".
 */
export type SourceTier = "A" | "B" | "C";
/**
 * One render block. The `type` field selects the renderer. Six members -- `statBlock`, `spawnInfo`, `dropTable`, `recipeTree`, `tradeTable`, `advancementInfo` -- carry real, closed fields. The other seven are still open payloads; each one's own description names the later phase that fills it in.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "section".
 */
export type Section =
  | StatBlock
  | SpawnInfo
  | DropTable
  | RecipeTree
  | ObtainList
  | BreedingInfo
  | EffectSources
  | AdvancementInfo
  | TradeTable
  | ChestLoot
  | EnchantInfo
  | GenerationInfo
  | LinkList;

/**
 * One searchable thing. Every entity of the site uses this shape, and the `kind` field selects the renderer. The pipeline writes these objects into the sharded entity JSON.
 */
export interface Entity {
  id: EntityId;
  kind: EntityKind;
  /**
   * The display name. Search shows this text, and no key uses it.
   */
  name: string;
  /**
   * Every extra search term of this entity. The list holds identifier segments, community shorthand, and curated extras. Search matches these as well as the name.
   */
  aliases: string[];
  /**
   * The sprite key in the atlas coordinate map. A missing icon is a broken join between the wiki and the registry, so the build reports it.
   */
  icon?: string;
  /**
   * The intro text of the wiki page, as plain text.
   */
  blurb?: string;
  /**
   * The source wiki page. The license is CC BY-NC-SA 3.0, so the user interface shows this link as a visible credit. Required whenever this entity carries wiki-authored content -- a `blurb` or any section -- per the `if`/`then` conditional below, because showing wiki text without a link to it breaks the license. An `icon` alone does not require it: the sprites are Mojang's textures that the wiki hosts rather than authored, per Decision 3 of TODO.md. Optional otherwise: registry IDs the wiki has no page for at all cannot carry this field and must not be forced to invent one. The host is fixed too: the project reads minecraft.wiki and never Fandom, so the site keeps one scraper and one attribution obligation.
   */
  wikiUrl?: string;
  /**
   * The tier that produced each field of this entity. The key is the field name. Wrong data is traceable to its source through this map.
   */
  sourceTiers: {
    [k: string]: SourceTier;
  };
  /**
   * The render blocks of this entity, in render order.
   */
  sections: Section[];
}
/**
 * Named numbers of an entity, mirroring `pipeline.enrich.infobox.EntityInfobox`. `speed` and `knockbackResistance` are carried here but deliberately not rendered, per `TODO.md` Phase 6 -- they are stored so a later renderer can use them without a pipeline change, not because today's renderer shows them.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "statBlock".
 */
export interface StatBlock {
  type: "StatBlock";
  health?: LabelledValue[];
  damage?: {
    labels: string[];
    difficulties: string[];
    value: Measure;
  }[];
  armor?: LabelledValue[];
  size?: {
    labels: string[];
    height: number;
    width: number;
  }[];
  behavior?: LabelledText[];
  mobType?: string[];
  /**
   * Stored and never rendered. See this section's own description.
   */
  speed?: LabelledText[];
  /**
   * Stored and never rendered. See this section's own description.
   */
  knockbackResistance?: LabelledText[];
}
/**
 * A `measure` the infobox parser read for a labelled variant of a mob, such as 'Large' or 'Baby'. `statBlock` reuses this one shape for `health` and `armor` rather than declaring the same two fields twice.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "labelledValue".
 */
export interface LabelledValue {
  labels: string[];
  value: Measure;
}
/**
 * A number, or a span of them, mirroring `pipeline.enrich.infobox.Measure`. A fixed value is a measure whose `minimum` equals its `maximum` -- every plain `{{hp|N}}` on the wiki produces one of these; a two-template line such as an Iron Golem's damage range produces one whose ends differ.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "measure".
 */
export interface Measure {
  minimum: number;
  maximum: number;
}
/**
 * A field the infobox parser read as plain text rather than a number, labelled by whichever heading or trailing parenthetical governed the line it came from. `statBlock` reuses this one shape for `behavior`, `speed`, and `knockbackResistance` rather than declaring the same two fields three times.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "labelledText".
 */
export interface LabelledText {
  labels: string[];
  text: string;
}
/**
 * Where the entity spawns, and under which conditions, mirroring `pipeline.enrich.spawn_table.SpawnIndex.by_mob`. One entry per biome the wiki records a Java spawn weight for.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "spawnInfo".
 */
export interface SpawnInfo {
  type: "SpawnInfo";
  entries?: {
    biome: string;
    biomeRef?: EntityRef;
    category: string;
    weight: number;
    totalWeight: number;
    groupSize: IntegerRange;
    note?: string;
    noteName?: string;
  }[];
}
/**
 * A cross-reference to another entity. A renderer never prints an entity name as plain text. It prints this object as a link that opens a new window.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "entityRef".
 */
export interface EntityRef {
  id: EntityId;
  /**
   * The display name of the target, at the time of the build.
   */
  name: string;
}
/**
 * A whole number, or a span of them, mirroring `pipeline.enrich.IntegerRange`. A wiki table cell such as a spawn group size or a trade quantity can print a single figure or a range, and this one shape covers both without a second field to check.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "integerRange".
 */
export interface IntegerRange {
  minimum: number;
  maximum: number;
}
/**
 * What the entity drops, per looting level, mirroring `pipeline.enrich.droptable.DropIndex.by_mob`. Java only, per non-negotiable 1 of CLAUDE.md.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "dropTable".
 */
export interface DropTable {
  type: "DropTable";
  drops?: {
    item: string;
    itemRef?: EntityRef;
    notes?: {
      name?: string;
      content: string;
    }[];
    byLootingLevel?: LootingDrop[];
  }[];
}
/**
 * What one mob drops of one item at one looting level, mirroring `pipeline.enrich.droptable.LootingDrop`. `distribution` is a JSON array of `{count, chance}` pairs sorted by `count`, rather than an object keyed by the count as the Python model's `Mapping[int, Ratio]` is: a JSON object key must be a string, and a numeric-looking string key such as `"10"` is exactly the kind of value that sorts wrong the moment something reads it as text instead of as a number. An array carries the same information with no such trap.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "lootingDrop".
 */
export interface LootingDrop {
  lootingLevel: number;
  minimum: number;
  maximum: number;
  average: Ratio;
  dropChance: Ratio;
  quantityText: string;
  distribution?: {
    count: number;
    chance: Ratio;
  }[];
}
/**
 * An exact fraction, mirroring `pipeline.enrich.droptable.Ratio`. Kept as a numerator and a denominator, rather than a single float, because that is how the wiki states a drop chance or an average, and rounding it once here would be a loss no later stage could see or undo.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "ratio".
 */
export interface Ratio {
  numerator: number;
  denominator: number;
}
/**
 * The obtain tree of an item, rooted at `root`. Brewing is a node of this tree, mirroring `pipeline.obtain.tree.ObtainTree`. No build stage writes one of these into a shard: the pipeline ships the flat producer graph at data/dist/obtain.json instead, and the web app assembles this exact shape from that graph at render time, using `pipeline.obtain.tree.build_obtain_tree` as the reference implementation of the walk. Measured against the real 26.2 data, materialising this shape into every shard cost 73.8 MB raw and 4.1 MB gzipped at a depth cap of 4, against 1.05 MB raw and 0.07 MB gzipped for the graph with no depth cap at all -- and the graph's deepest real chain is 15 levels, past any depth-4 cap the materialised tree ever reached. This definition stays fully specified, and stays a member of the section union below, because the web app's generated TypeScript still needs to describe the shape a renderer assembles.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "recipeTree".
 */
export interface RecipeTree {
  type: "RecipeTree";
  root: RecipeTreeNode;
}
/**
 * One item of the obtain tree, mirroring `pipeline.obtain.tree.ObtainNode`. See `recipeTree`'s own description for why no build stage writes this shape any more; a renderer assembles it from data/dist/obtain.json instead. `expandable` marks a depth-cap stub: the web app continues the walk by opening `item`'s own entity shard. `backReference` marks a repeated-subtree collapse: the path of the node where this same subtree was first rendered in this tree.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "recipeTreeNode".
 */
export interface RecipeTreeNode {
  item: EntityRef;
  producers?: RecipeTreeProducer[];
  expandable?: boolean;
  backReference?: string;
}
/**
 * One way to get a node's item, mirroring `pipeline.obtain.producer.Producer`. See `recipeTree`'s own description for why no build stage writes this shape any more; a renderer assembles it from data/dist/obtain.json instead.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "recipeTreeProducer".
 */
export interface RecipeTreeProducer {
  method: string;
  station?: string;
  note?: string;
  sourceId: string;
  inputs?: RecipeTreeInput[];
}
/**
 * One ingredient slot of a `recipeTreeProducer`, mirroring `pipeline.obtain.tree.TreeInput`. See `recipeTree`'s own description for why no build stage writes this shape any more; a renderer assembles it from data/dist/obtain.json instead. `item` is present for a plain item input and absent for a tag input; `tag` is present for a tag input and absent otherwise. `node` is the recursive expansion of `item`, absent for a tag input, an untagged alternatives list (`members` still carries the full list), or a cycle-dropped repeat.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "recipeTreeInput".
 */
export interface RecipeTreeInput {
  label: string;
  item?: EntityRef;
  tag?: string;
  count?: number;
  members?: string[];
  node?: RecipeTreeNode;
}
/**
 * Every acquisition path that the wiki Obtaining section lists. The payload of this section arrives in Phase 6b, scraped from the wiki's own Obtaining section.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "obtainList".
 */
export interface ObtainList {
  type: "ObtainList";
  [k: string]: unknown;
}
/**
 * The items that breed a mob, and the result. The payload of this section arrives in Phase 6.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "breedingInfo".
 */
export interface BreedingInfo {
  type: "BreedingInfo";
  [k: string]: unknown;
}
/**
 * Every source of a status effect. The payload of this section arrives in Phase 6.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "effectSources".
 */
export interface EffectSources {
  type: "EffectSources";
  [k: string]: unknown;
}
/**
 * How the player earns an advancement, and the parent chain, mirroring `pipeline.enrich.advancement.WikiAdvancement`.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "advancementInfo".
 */
export interface AdvancementInfo {
  type: "AdvancementInfo";
  internalId: string;
  title: string;
  description?: string;
  gameDescription?: string;
  parent?: EntityRef;
  parentTitle?: string;
  children?: EntityRef[];
  experience?: number;
  reward?: string;
  background?: string;
}
/**
 * Villager and wandering trader trades, grouped by profession and level, mirroring `pipeline.enrich.trade.TradeIndex`. `professionRef` is expected to stay absent for now: villager profession entities arrive in Phase 6c, so there is nothing yet for the merge to link a profession name to. Only the Java probability is carried into `javaProbability`; `bedrock_probability` is dropped upstream in `pipeline.enrich.trade`, per non-negotiable 1 of CLAUDE.md.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "tradeTable".
 */
export interface TradeTable {
  type: "TradeTable";
  trades?: {
    profession: string;
    professionRef?: EntityRef;
    level: string;
    wanted?: ItemAmount[];
    given: ItemAmount;
    javaProbability?: {
      text: string;
      low: number;
      high: number;
    };
    maxTrades?: IntegerRange;
    villagerXp?: number;
    priceMultiplier?: number;
  }[];
}
/**
 * One item and how many, the shape a wiki drop or a trade side reduces to. Tier B tables are keyed by the wiki's own display name, not by registry ID, so `name` is always present. Where the merge can resolve that name to a registry ID it fills `ref`, and a renderer prints it as a link; where it cannot, `ref` is absent and the renderer prints `name` as plain text. `TODO.md`'s Phase 6 lint pass exists to flag exactly that absence on a name the merge already knows is an entity, so a renderer is never allowed to quietly print a link-worthy name as text.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "itemAmount".
 */
export interface ItemAmount {
  name: string;
  ref?: EntityRef;
  quantity: IntegerRange;
  note?: string;
}
/**
 * The chest loot tables that hold the item. The payload of this section arrives in Phase 6c.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "chestLoot".
 */
export interface ChestLoot {
  type: "ChestLoot";
  [k: string]: unknown;
}
/**
 * Levels, applicable items, costs, and the exclusive set. The payload of this section arrives in Phase 6c.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "enchantInfo".
 */
export interface EnchantInfo {
  type: "EnchantInfo";
  [k: string]: unknown;
}
/**
 * Where a block, a structure, or a biome generates. The payload of this section arrives in Phase 6c.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "generationInfo".
 */
export interface GenerationInfo {
  type: "GenerationInfo";
  [k: string]: unknown;
}
/**
 * A plain list of links to other entities. The payload of this section arrives in Phase 6.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "linkList".
 */
export interface LinkList {
  type: "LinkList";
  [k: string]: unknown;
}
