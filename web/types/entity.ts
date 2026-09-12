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
 * The tier that produced one field. A is vanilla game data from mcmeta. B is the Minecraft Wiki. C is a curated override. A later tier wins.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "sourceTier".
 */
export type SourceTier = "A" | "B" | "C";
/**
 * One render block. The `type` field selects the renderer. Seven members -- `statBlock`, `spawnInfo`, `dropTable`, `recipeTree`, `tradeTable`, `advancementInfo`, `breedingInfo` -- plus `foodInfo`, `harvestInfo`, `generationInfo`, and `enchantInfo` carry real, closed fields. The other three (`obtainList`, `chestLoot`, `linkList`) are still open payloads; each one's own description names the later phase that fills it in.
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
  | FoodInfo
  | HarvestInfo
  | EffectSources
  | AdvancementInfo
  | TradeTable
  | ChestLoot
  | EnchantInfo
  | GenerationInfo
  | LinkList
  | CollectionMembers
  | CollectionTree
  | ProfessionInfo
  | StructureInfo
  | BiomeInfo
  | CompostInfo
  | FuelInfo;
/**
 * The tool that breaks a block, from the mineable tags.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "harvestTool".
 */
export type HarvestTool = "pickaxe" | "axe" | "shovel" | "hoe";
/**
 * The material floor of the tool, from the needs_<material>_tool tags.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "harvestTier".
 */
export type HarvestTier = "wooden" | "stone" | "iron" | "diamond";
/**
 * The special requirement to drop an item, e.g. Silk Touch or shears.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "harvestGate".
 */
export type HarvestGate = "silk_touch" | "shears";
/**
 * Rarity of an enchantment derived from its weight.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "enchantRarity".
 */
export type EnchantRarity = "common" | "uncommon" | "rare" | "very_rare";
/**
 * Equipment slot where an enchantment is active.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "enchantSlot".
 */
export type EnchantSlot = "any" | "armor" | "feet" | "hand" | "head" | "legs" | "mainhand" | "offhand";
/**
 * Placement configuration for a structure set.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "structurePlacement".
 */
export type StructurePlacement = RandomSpreadPlacement | ConcentricRingsPlacement;

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
    biomeRef: EntityRef;
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
 * The items that breed a mob, its taming requirements, and its timings in seconds.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "breedingInfo".
 */
export interface BreedingInfo {
  type: "BreedingInfo";
  items: BreedingItem[];
  requiresTaming: boolean;
  tamingItems: BreedingItem[];
  /**
   * Seconds before a bred pair can be fed again.
   */
  cooldownSeconds: number;
  /**
   * Seconds for a baby of this mob to grow up, unaccelerated.
   */
  babyGrowthSeconds: number;
}
/**
 * One breeding or taming item, following the name/ref pattern. When ref is absent or unresolvable, the renderer prints name as plain text.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "breedingItem".
 */
export interface BreedingItem {
  name: string;
  ref?: EntityRef;
}
/**
 * What eating an item restores, and what else it does, from the minecraft:food and minecraft:consumable components. nutrition and saturation are absent together for an item that is consumable without being food, such as the milk bucket; a renderer reads that pair to choose between a Food heading and a Consuming one.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "foodInfo".
 */
export interface FoodInfo {
  type: "FoodInfo";
  /**
   * Hunger points restored, out of a full bar of 20. Two points are one shank.
   */
  nutrition?: number;
  /**
   * Saturation restored, rounded to two decimal places by the extract because the source carries float32 noise.
   */
  saturation?: number;
  /**
   * Whether the item can be eaten on a full hunger bar.
   */
  canAlwaysEat: boolean;
  effects: FoodEffect[];
  /**
   * Status effects this item cures, from a remove_effects consume effect.
   */
  removes: EffectLink[];
  /**
   * Whether consuming this removes every active status effect, as the milk bucket does.
   */
  clearsAllEffects: boolean;
  /**
   * Whether consuming this teleports the player, as the chorus fruit does.
   */
  teleportsRandomly: boolean;
}
/**
 * One status effect that eating an item applies. durationTicks is raw game ticks and level is 1-based, so Regeneration II is level 2; the renderer formats both. probability is the chance of the whole apply_effects group the source put this effect in.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "foodEffect".
 */
export interface FoodEffect {
  name: string;
  ref?: EntityRef;
  /**
   * How long the effect lasts, in game ticks. 20 ticks is one second.
   */
  durationTicks: number;
  /**
   * The level shown on screen, counting from 1. One higher than the amplifier the vanilla component carries.
   */
  level: number;
  /**
   * The chance the effect lands, from just above 0 to 1. Only three items in 26.2 carry one below 1.
   */
  probability: number;
}
/**
 * One status effect a food section names, following the name/ref pattern. When ref is absent or unresolvable, the renderer prints name as plain text.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "effectLink".
 */
export interface EffectLink {
  name: string;
  ref?: EntityRef;
}
/**
 * What tool and tier are needed to harvest a block, from the vanilla block tags. tools lists the mineable tools in HarvestTool order. tier is the material floor. dropsWithoutTool indicates whether the block drops itself when broken without the right tool.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "harvestInfo".
 */
export interface HarvestInfo {
  type: "HarvestInfo";
  tools: HarvestTool[];
  tier: HarvestTier;
  /**
   * Whether the block drops itself when broken without the required tool.
   */
  dropsWithoutTool: boolean;
  /**
   * Items dropped when the block is harvested, including standard and silk touch drops.
   */
  drops?: HarvestDrop[];
}
/**
 * An item dropped when this block is broken.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "harvestDrop".
 */
export interface HarvestDrop {
  id: string;
  name?: string;
  count?: number;
  gate?: HarvestGate;
}
/**
 * Every source of a status effect, its category, and what it does.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "effectSources".
 */
export interface EffectSources {
  type: "EffectSources";
  category: "positive" | "negative" | "neutral";
  behaviour?: string;
  sources: EffectSource[];
  removedBy: EffectLink[];
}
/**
 * One source that grants or inflicts a status effect.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "effectSource".
 */
export interface EffectSource {
  name: string;
  ref?: EntityRef;
  qualifier?: string;
  potency?: string;
  length?: string;
  note?: string;
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
 * Villager and wandering trader trades, grouped by profession and level, mirroring `pipeline.enrich.trade.TradeIndex`. Only the Java probability is carried into `javaProbability`; `bedrock_probability` is dropped upstream in `pipeline.enrich.trade`, per non-negotiable 1 of CLAUDE.md.
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
 * The loot tables and containers that generate inside a structure.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "chestLoot".
 */
export interface ChestLoot {
  type: "ChestLoot";
  containers: ChestLootContainer[];
}
/**
 * One container (chest, barrel, dispenser, pot, vault) within a structure.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "chestLootContainer".
 */
export interface ChestLootContainer {
  label: string;
  items: ChestLootItem[];
}
/**
 * One item appearing in a chest or container table.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "chestLootItem".
 */
export interface ChestLootItem {
  item: EntityRef;
  chance: number;
  stackRange: IntegerRange;
}
/**
 * Levels, applicable items, costs, and the exclusive set.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "enchantInfo".
 */
export interface EnchantInfo {
  type: "EnchantInfo";
  /**
   * Maximum level of the enchantment (1 to 5).
   */
  maxLevel: number;
  /**
   * Weight of the enchantment in the table selection pool (10, 5, 2, 1).
   */
  weight: number;
  rarity: EnchantRarity;
  /**
   * Base anvil modification cost multiplier (1, 2, 4, 8).
   */
  anvilCost: number;
  /**
   * Equipment slots where this enchantment applies.
   */
  slots: EnchantSlot[];
  /**
   * Modified enchantment level ranges for each level from 1 to maxLevel.
   */
  costRanges: IntegerRange[];
  supportedItems: ApplicableItems;
  primaryItems?: ApplicableItems;
  /**
   * Enchantments that cannot be combined with this one.
   */
  exclusiveSet: EntityRef[];
  /**
   * Whether this is a treasure enchantment, unavailable in the enchanting table.
   */
  treasure: boolean;
  /**
   * Whether this enchantment is a curse.
   */
  curse: boolean;
  /**
   * Whether this enchantment can be traded from librarians.
   */
  tradeable: boolean;
}
/**
 * The group of items an enchantment can be applied to.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "applicableItems".
 */
export interface ApplicableItems {
  /**
   * The item tag or group name.
   */
  group: string;
  /**
   * Every item accepted by this group.
   */
  items: EntityRef[];
}
/**
 * Where a block, a structure, or a biome generates. Carries one scope per dimension the block generates in, because the band, the attempt count and the biome list are all facts about one dimension: gravel and the two mushrooms generate in the overworld and the nether at once.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "generationInfo".
 */
export interface GenerationInfo {
  type: "GenerationInfo";
  /**
   * One entry per dimension this block generates in, ordered overworld, nether, end.
   */
  scopes: GenerationScope[];
}
/**
 * How one block generates in one dimension.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "generationScope".
 */
export interface GenerationScope {
  /**
   * The dimension these facts describe.
   */
  dimension: "overworld" | "nether" | "end";
  /**
   * Lowest Y level where this block generates in this dimension, clipped to the dimension's build range. Absent when every vein is placed on a surface heightmap, which states no band.
   */
  minY?: number;
  /**
   * Highest Y level where this block generates in this dimension. Absent under the same rule as minY.
   */
  maxY?: number;
  /**
   * Y level with the highest density, taken from the declared trapezoid rather than the clipped band. Absent when the distribution is uniform, or when the veins that have a peak disagree or do not cover the whole band.
   */
  densestY?: number;
  /**
   * Whether every vein of this scope is placed on a surface heightmap rather than in a height band.
   */
  surfaceOnly?: boolean;
  /**
   * Placement attempts per chunk, summed over the veins that state one. Absent where no vein states a per-chunk count: a count that runs after the position modifier is patch density, not an attempt rate, and a noise-driven count is no fixed number at all.
   */
  attemptsPerChunk?: number;
  /**
   * Number of biomes of this dimension the block generates in.
   */
  biomeCount: number;
  /**
   * Whether this block generates in every biome of this dimension, measured against the dimension's own biome tag.
   */
  allBiomesOfDimension: boolean;
  /**
   * Biomes of this dimension where this block generates. Empty when allBiomesOfDimension is true.
   */
  biomes: EntityRef[];
  /**
   * The individual placed features that generate this block in this dimension.
   */
  veins: VeinInfo[];
}
/**
 * One placed feature's contribution to a block's generation in one dimension.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "veinInfo".
 */
export interface VeinInfo {
  /**
   * The namespaced ID of the placed feature.
   */
  feature: string;
  /**
   * Lowest Y level for this feature, clipped to the dimension's build range. Absent together with maxY when the feature is placed on a surface heightmap.
   */
  minY?: number;
  /**
   * Highest Y level for this feature. Absent under the same rule as minY.
   */
  maxY?: number;
  /**
   * Whether this feature is placed on a surface heightmap rather than in a height band.
   */
  surface?: boolean;
  /**
   * Y level of highest density for trapezoid distributions.
   */
  densestY?: number;
  /**
   * Attempts per chunk. Absent where the placement states no per-chunk count.
   */
  tries?: number;
  /**
   * 1-in-N chance per chunk, if rarity-filtered.
   */
  chunkChance?: number;
  /**
   * Maximum blocks per vein, if configured.
   */
  veinSize?: number;
}
/**
 * A plain list of links to other entities.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "linkList".
 */
export interface LinkList {
  type: "LinkList";
  title?: string;
  links: EntityRef[];
}
/**
 * The member list of a collection page. With columns it renders as a table; with none it renders a flat link row.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "collectionMembers".
 */
export interface CollectionMembers {
  type: "CollectionMembers";
  title?: string;
  columns?: MemberColumn[];
  members?: CollectionMember[];
}
/**
 * One column header in a collection member table.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "memberColumn".
 */
export interface MemberColumn {
  key: string;
  label: string;
}
/**
 * One row in a collection member table. Values are pre-formatted strings.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "collectionMember".
 */
export interface CollectionMember {
  ref: EntityRef;
  values?: {
    [k: string]: string;
  };
}
/**
 * One group of a tree-shaped collection, in depth-first order.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "collectionTree".
 */
export interface CollectionTree {
  type: "CollectionTree";
  title?: string;
  members?: CollectionTreeMember[];
}
/**
 * One row of a tree-shaped collection. Depth is the distance from the group root.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "collectionTreeMember".
 */
export interface CollectionTreeMember {
  ref: EntityRef;
  depth: number;
}
/**
 * Villager profession details: workstation block and trade count.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "professionInfo".
 */
export interface ProfessionInfo {
  type: "ProfessionInfo";
  workstation?: EntityRef;
  tradeCount: number;
}
/**
 * Where and how a structure generates, its siblings, mob spawns, and suppressed spawns.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "structureInfo".
 */
export interface StructureInfo {
  type: "StructureInfo";
  dimension: "overworld" | "nether" | "end";
  step: string;
  biomes: EntityRef[];
  placement: StructurePlacement;
  siblings: StructureSibling[];
  spawns: StructureSpawnEntry[];
  suppressedSpawns: string[];
}
/**
 * Placement across the world with spacing and separation.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "randomSpreadPlacement".
 */
export interface RandomSpreadPlacement {
  type: "minecraft:random_spread";
  spacing: number;
  separation: number;
  spreadType?: string;
  frequency?: number;
  frequencyReductionMethod?: string;
  exclusionZone?: ExclusionZone;
  salt?: number;
}
/**
 * An area around another structure set where this structure cannot place.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "exclusionZone".
 */
export interface ExclusionZone {
  otherSet: string;
  chunkCount: number;
}
/**
 * Placement in concentric rings around the world origin (e.g. Strongholds).
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "concentricRingsPlacement".
 */
export interface ConcentricRingsPlacement {
  type: "minecraft:concentric_rings";
  count: number;
  distance: number;
  spread: number;
  preferredBiomes: string;
  salt?: number;
}
/**
 * Another structure belonging to the same structure set, with its relative weight.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "structureSibling".
 */
export interface StructureSibling {
  structure: EntityRef;
  weight: number;
}
/**
 * One mob spawn override inside a structure bounding box.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "structureSpawnEntry".
 */
export interface StructureSpawnEntry {
  category: string;
  mob: EntityRef;
  groupSize: IntegerRange;
  weight: number;
}
/**
 * Climate, mob spawns, and generating blocks of a biome.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "biomeInfo".
 */
export interface BiomeInfo {
  type: "BiomeInfo";
  dimension?: "overworld" | "nether" | "end";
  temperature: number;
  temperatureModifier?: string;
  downfall: number;
  hasPrecipitation: boolean;
  precipitation: "rain" | "snow" | "none";
  creatureSpawnProbability?: number;
  spawnCosts?: {
    [k: string]: {
      [k: string]: number;
    };
  };
  spawns?: BiomeSpawnEntry[];
  blocks?: EntityRef[];
  commonBlocksCount?: number;
  noisePlacements?: NoisePlacement[];
}
/**
 * One mob spawning in a biome, at a given weight and group size.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "biomeSpawnEntry".
 */
export interface BiomeSpawnEntry {
  category: string;
  mob: EntityRef;
  groupSize: IntegerRange;
  weight: number;
  totalWeight: number;
  note?: string;
  noteName?: string;
}
/**
 * One noise climate placement rule for an Overworld biome, sourced from World generation § Biomes -> Overworld.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "noisePlacement".
 */
export interface NoisePlacement {
  route: "depth" | "non_inland" | "direct_inland" | "group" | "group_terrain";
  group?: string;
  temperature?: string;
  humidity?: string;
  continentalness?: string;
  erosion?: string;
  weirdness?: string;
  pv?: string;
  depth?: string;
  additionalRequirement?: string;
  condition?: string;
  sibling?: EntityRef;
  /**
   * Temperature levels this rule applies at, 0 (coldest) to 4 (hottest). The same fact as `temperature`, as integers, so a renderer can plot the axis without re-parsing the display string.
   */
  temperatureLevels?: number[];
  /**
   * Humidity levels this rule applies at, 0 (driest) to 4 (wettest).
   */
  humidityLevels?: number[];
  /**
   * Erosion levels this rule applies at, 0 to 6. Low erosion is hilly terrain and high erosion is flat, per the World generation prose.
   */
  erosionLevels?: number[];
  /**
   * Continentalness bands this rule applies at, indexing all seven bands the prose lists: 0 Mushroom fields, 1 Deep ocean, 2 Ocean, 3 Coast, 4 Near-inland, 5 Mid-inland, 6 Far-inland. One absolute axis is shared by ocean-side and inland rules.
   */
  continentalnessBands?: number[];
  /**
   * Peaks-and-valleys band name with no numeric range attached, such as `High` or `High~Peaks`.
   */
  pvBand?: string;
}
/**
 * Composting chance when placed in a composter.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "compostInfo".
 */
export interface CompostInfo {
  type: "CompostInfo";
  /**
   * Composting chance in percent, from 1 to 100.
   */
  chance: number;
}
/**
 * Furnace burn time in game ticks.
 *
 * This interface was referenced by `Entity`'s JSON-Schema
 * via the `definition` "fuelInfo".
 */
export interface FuelInfo {
  type: "FuelInfo";
  /**
   * Furnace burn time in game ticks. 20 ticks is one second, 200 ticks is one smelting operation.
   */
  burnTime: number;
}
