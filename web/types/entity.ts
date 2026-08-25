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
  "mob" | "item" | "block" | "effect" | "advancement" | "enchantment" | "structure" | "biome" | "collection";
/**
 * The tier that produced one field. A is vanilla game data from mcmeta. B is the Minecraft Wiki. C is a curated override. A later tier wins.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "sourceTier".
 */
export type SourceTier = "A" | "B" | "C";
/**
 * One render block. The `type` field selects the renderer. Phase 3 replaces the open payload of each member with real fields.
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
   * The source wiki page. The license is CC BY-NC-SA 3.0, so the user interface shows this link as a visible credit. Every entity carries one, because an entity that shows wiki text without a link to it breaks the license. The host is fixed too: the project reads minecraft.wiki and never Fandom, so the site keeps one scraper and one attribution obligation.
   */
  wikiUrl: string;
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
 * Named numbers of an entity. Health and damage of a mob are two examples. The payload of this section arrives in Phase 3.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "statBlock".
 */
export interface StatBlock {
  type: "StatBlock";
  [k: string]: unknown;
}
/**
 * Where the entity spawns, and under which conditions. The payload of this section arrives in Phase 3.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "spawnInfo".
 */
export interface SpawnInfo {
  type: "SpawnInfo";
  [k: string]: unknown;
}
/**
 * What the entity drops, per looting level. The payload of this section arrives in Phase 3.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "dropTable".
 */
export interface DropTable {
  type: "DropTable";
  [k: string]: unknown;
}
/**
 * The obtain tree of an item. Brewing is a node of this tree. The payload of this section arrives in Phase 3.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "recipeTree".
 */
export interface RecipeTree {
  type: "RecipeTree";
  [k: string]: unknown;
}
/**
 * Every acquisition path that the wiki Obtaining section lists. The payload of this section arrives in Phase 3.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "obtainList".
 */
export interface ObtainList {
  type: "ObtainList";
  [k: string]: unknown;
}
/**
 * The items that breed a mob, and the result. The payload of this section arrives in Phase 3.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "breedingInfo".
 */
export interface BreedingInfo {
  type: "BreedingInfo";
  [k: string]: unknown;
}
/**
 * Every source of a status effect. The payload of this section arrives in Phase 3.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "effectSources".
 */
export interface EffectSources {
  type: "EffectSources";
  [k: string]: unknown;
}
/**
 * How the player earns an advancement, and the parent chain. The payload of this section arrives in Phase 3.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "advancementInfo".
 */
export interface AdvancementInfo {
  type: "AdvancementInfo";
  [k: string]: unknown;
}
/**
 * Villager trades, grouped by profession and level. The payload of this section arrives in Phase 3.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "tradeTable".
 */
export interface TradeTable {
  type: "TradeTable";
  [k: string]: unknown;
}
/**
 * The chest loot tables that hold the item. The payload of this section arrives in Phase 3.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "chestLoot".
 */
export interface ChestLoot {
  type: "ChestLoot";
  [k: string]: unknown;
}
/**
 * Levels, applicable items, costs, and the exclusive set. The payload of this section arrives in Phase 3.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "enchantInfo".
 */
export interface EnchantInfo {
  type: "EnchantInfo";
  [k: string]: unknown;
}
/**
 * Where a block, a structure, or a biome generates. The payload of this section arrives in Phase 3.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "generationInfo".
 */
export interface GenerationInfo {
  type: "GenerationInfo";
  [k: string]: unknown;
}
/**
 * A plain list of links to other entities. The payload of this section arrives in Phase 3.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "linkList".
 */
export interface LinkList {
  type: "LinkList";
  [k: string]: unknown;
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
