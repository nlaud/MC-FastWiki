import type {
  AdvancementInfo,
  BiomeInfo,
  BreedingInfo,
  ChestLoot,
  CollectionMembers,
  CollectionTree,
  CompostInfo,
  DropTable,
  EffectSources,
  EnchantInfo,
  Entity,
  FoodInfo,
  FuelInfo,
  GenerationInfo,
  HarvestInfo,
  LinkList,
  ProfessionInfo,
  RecipeTree,
  Section,
  SpawnInfo,
  StatBlock,
  StructureInfo,
  TradeTable,
} from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { renderAdvancementInfo } from "./advancement-info.js";
import { renderBiomeInfo } from "./biome-info.js";
import { renderBreedingInfo } from "./breeding-info.js";
import { renderChestLoot } from "./chest-loot.js";
import { renderCollectionMembers } from "./collection-members.js";
import { renderCollectionTree } from "./collection-tree.js";
import { renderCompostInfo } from "./compost-info.js";
import { renderDropTable } from "./drop-table.js";
import { renderEffectSources } from "./effect-sources.js";
import { renderEnchantInfo } from "./enchant-info.js";
import { renderFoodInfo } from "./food-info.js";
import { renderFuelInfo } from "./fuel-info.js";
import { renderGenerationInfo } from "./generation-info.js";
import { renderHarvestInfo } from "./harvest-info.js";
import { renderLinkList } from "./link-list.js";
import { renderProfessionInfo } from "./profession-info.js";
import { renderRecipeTree } from "./recipe-tree.js";
import { renderSpawnInfo } from "./spawn-info.js";
import { renderStatBlock } from "./stat-block.js";
import { renderStructureInfo } from "./structure-info.js";
import { renderTradeTable } from "./trade-table.js";

export type SectionRenderer = (
  section: Section,
  ctx: RenderContext,
  entity?: Entity,
) => HTMLElement | null;

export const RENDERERS: Record<string, SectionRenderer> = {
  StatBlock: (s, ctx) => renderStatBlock(s as StatBlock, ctx),
  DropTable: (s, ctx) => renderDropTable(s as DropTable, ctx),
  SpawnInfo: (s, ctx) => renderSpawnInfo(s as SpawnInfo, ctx),
  // A trade table on the seller's own page groups by level alone: the window
  // title already names the seller, so a group heading would repeat it and,
  // now that the heading carries a ref, would link the reader to the page they
  // are already reading. The two sellers with a page are the 13 professions and
  // the wandering trader, which is a mob because the `villager_profession`
  // registry does not list it. Everywhere else -- an item or block page, which
  // lists what several sellers offer -- the profession grouping is the point.
  TradeTable: (s, ctx, entity) => {
    if (entity?.kind === "profession" || entity?.kind === "mob") {
      return renderTradeTable(s as TradeTable, ctx, { groupByLevelOnly: true });
    }
    // This branch used to `return null`, which contradicted the paragraph above and
    // silently dropped a populated trade table from all 170 item and block pages that
    // carry one -- an Armorer sells a Bell for 36 emeralds, and the Bell page showed
    // nothing. It also defeated half of Phase 6c's "item -> the professions that sell
    // it" cross-link, because every `professionRef` in the section went unrendered.
    // `renderTradeTable` already returns null for an empty trades list, so passing
    // through is safe for a section with nothing in it.
    return renderTradeTable(s as TradeTable, ctx);
  },
  AdvancementInfo: (s, ctx) => renderAdvancementInfo(s as AdvancementInfo, ctx),
  BreedingInfo: (s, ctx) => renderBreedingInfo(s as BreedingInfo, ctx),
  FoodInfo: (s, ctx) => renderFoodInfo(s as FoodInfo, ctx),
  HarvestInfo: (s, ctx) => renderHarvestInfo(s as HarvestInfo, ctx),
  ProfessionInfo: (s, ctx) => renderProfessionInfo(s as ProfessionInfo, ctx),
  RecipeTree: (s, ctx, entity) => renderRecipeTree(s as RecipeTree, ctx, entity),
  EffectSources: (s, ctx) => renderEffectSources(s as EffectSources, ctx),
  GenerationInfo: (s, ctx) => renderGenerationInfo(s as GenerationInfo, ctx),
  EnchantInfo: (s, ctx) => renderEnchantInfo(s as EnchantInfo, ctx),
  ChestLoot: (s, ctx) => renderChestLoot(s as ChestLoot, ctx),
  LinkList: (s, ctx) => renderLinkList(s as LinkList, ctx),
  CollectionMembers: (s, ctx) => renderCollectionMembers(s as CollectionMembers, ctx),
  CollectionTree: (s, ctx) => renderCollectionTree(s as CollectionTree, ctx),
  StructureInfo: (s, ctx) => renderStructureInfo(s as StructureInfo, ctx),
  BiomeInfo: (s, ctx) => renderBiomeInfo(s as BiomeInfo, ctx),
  CompostInfo: (s, ctx) => renderCompostInfo(s as CompostInfo, ctx),
  FuelInfo: (s, ctx) => renderFuelInfo(s as FuelInfo, ctx),
};

/**
 * Renders a single section using the registered section renderers.
 * Returns null if the section type is unknown or has no renderer implemented yet.
 */
export function renderSection(
  section: Section,
  ctx: RenderContext,
  entity?: Entity,
): HTMLElement | null {
  const renderer = RENDERERS[section.type];
  if (!renderer) {
    return null;
  }
  return renderer(section, ctx, entity);
}
