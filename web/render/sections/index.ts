import type {
  AdvancementInfo,
  BreedingInfo,
  DropTable,
  EffectSources,
  EnchantInfo,
  Entity,
  FoodInfo,
  GenerationInfo,
  HarvestInfo,
  ProfessionInfo,
  RecipeTree,
  Section,
  SpawnInfo,
  StatBlock,
  TradeTable,
} from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { renderAdvancementInfo } from "./advancement-info.js";
import { renderBreedingInfo } from "./breeding-info.js";
import { renderDropTable } from "./drop-table.js";
import { renderEffectSources } from "./effect-sources.js";
import { renderEnchantInfo } from "./enchant-info.js";
import { renderFoodInfo } from "./food-info.js";
import { renderGenerationInfo } from "./generation-info.js";
import { renderHarvestInfo } from "./harvest-info.js";
import { renderProfessionInfo } from "./profession-info.js";
import { renderRecipeTree } from "./recipe-tree.js";
import { renderSpawnInfo } from "./spawn-info.js";
import { renderStatBlock } from "./stat-block.js";
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
    return null;
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
