import type {
  AdvancementInfo,
  BreedingInfo,
  DropTable,
  Entity,
  FoodInfo,
  HarvestInfo,
  RecipeTree,
  Section,
  SpawnInfo,
  StatBlock,
} from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { renderAdvancementInfo } from "./advancement-info.js";
import { renderBreedingInfo } from "./breeding-info.js";
import { renderDropTable } from "./drop-table.js";
import { renderFoodInfo } from "./food-info.js";
import { renderHarvestInfo } from "./harvest-info.js";
import { renderRecipeTree } from "./recipe-tree.js";
import { renderSpawnInfo } from "./spawn-info.js";
import { renderStatBlock } from "./stat-block.js";

export type SectionRenderer = (
  section: Section,
  ctx: RenderContext,
  entity?: Entity,
) => HTMLElement | null;

export const RENDERERS: Record<string, SectionRenderer> = {
  StatBlock: (s, ctx) => renderStatBlock(s as StatBlock, ctx),
  DropTable: (s, ctx) => renderDropTable(s as DropTable, ctx),
  SpawnInfo: (s, ctx) => renderSpawnInfo(s as SpawnInfo, ctx),
  TradeTable: () => null, // Standalone TradeTable removed; embedded in RecipeTree Sources
  AdvancementInfo: (s, ctx) => renderAdvancementInfo(s as AdvancementInfo, ctx),
  BreedingInfo: (s, ctx) => renderBreedingInfo(s as BreedingInfo, ctx),
  FoodInfo: (s, ctx) => renderFoodInfo(s as FoodInfo, ctx),
  HarvestInfo: (s, ctx) => renderHarvestInfo(s as HarvestInfo, ctx),
  RecipeTree: (s, ctx, entity) => renderRecipeTree(s as RecipeTree, ctx, entity),
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
