import type {
  AdvancementInfo,
  DropTable,
  Section,
  SpawnInfo,
  StatBlock,
  TradeTable,
} from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { renderAdvancementInfo } from "./advancement-info.js";
import { renderDropTable } from "./drop-table.js";
import { renderSpawnInfo } from "./spawn-info.js";
import { renderStatBlock } from "./stat-block.js";
import { renderTradeTable } from "./trade-table.js";

export type SectionRenderer = (section: Section, ctx: RenderContext) => HTMLElement | null;

export const RENDERERS: Record<string, SectionRenderer> = {
  StatBlock: (s, ctx) => renderStatBlock(s as StatBlock, ctx),
  DropTable: (s, ctx) => renderDropTable(s as DropTable, ctx),
  SpawnInfo: (s, ctx) => renderSpawnInfo(s as SpawnInfo, ctx),
  TradeTable: (s, ctx) => renderTradeTable(s as TradeTable, ctx),
  AdvancementInfo: (s, ctx) => renderAdvancementInfo(s as AdvancementInfo, ctx),
};

/**
 * Renders a single section using the registered section renderers.
 * Returns null if the section type is unknown or has no renderer implemented yet.
 */
export function renderSection(section: Section, ctx: RenderContext): HTMLElement | null {
  const renderer = RENDERERS[section.type];
  if (!renderer) {
    return null;
  }
  return renderer(section, ctx);
}
