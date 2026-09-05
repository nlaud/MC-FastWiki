import type { HarvestInfo, HarvestTier, HarvestTool } from "../../types/entity.js";
import type { RenderContext } from "../context.js";

const TOOL_NAMES: Record<HarvestTool, string> = {
  pickaxe: "Pickaxe",
  axe: "Axe",
  shovel: "Shovel",
  hoe: "Hoe",
};

const TIER_NAMES: Record<HarvestTier, string> = {
  wooden: "Wooden",
  stone: "Stone",
  iron: "Iron",
  diamond: "Diamond",
};

/**
 * Renders a HarvestInfo section:
 * - Title "Harvest"
 * - Tool(s) required to break the block
 * - Minimum tier required for drops
 * - Whether the block drops when broken without the tool
 */
export function renderHarvestInfo(section: HarvestInfo, _ctx: RenderContext): HTMLElement {
  const container = document.createElement("section");
  container.className = "entity-section harvest-info-section";

  const title = document.createElement("h3");
  title.className = "section-title";
  title.textContent = "Harvest";
  container.append(title);

  const grid = document.createElement("div");
  grid.className = "harvest-details-grid";

  // Tool row
  if (section.tools.length > 0) {
    const toolRow = document.createElement("div");
    toolRow.className = "harvest-row";

    const label = document.createElement("span");
    label.className = "harvest-label";
    label.textContent = section.tools.length === 1 ? "Tool" : "Tools";

    const value = document.createElement("span");
    value.className = "harvest-value";
    value.textContent = section.tools.map((t) => TOOL_NAMES[t]).join(", ");

    toolRow.append(label, value);
    grid.append(toolRow);
  }

  // Tier row
  const tierRow = document.createElement("div");
  tierRow.className = "harvest-row";

  const tierLabel = document.createElement("span");
  tierLabel.className = "harvest-label";
  tierLabel.textContent = "Minimum Tier";

  const tierValue = document.createElement("span");
  tierValue.className = "harvest-value";
  const tierName = TIER_NAMES[section.tier];
  tierValue.textContent = section.tier === "wooden" ? `${tierName} (any)` : tierName;

  tierRow.append(tierLabel, tierValue);
  grid.append(tierRow);

  // Drops without tool row
  const dropsRow = document.createElement("div");
  dropsRow.className = "harvest-row";

  const dropsLabel = document.createElement("span");
  dropsLabel.className = "harvest-label";
  dropsLabel.textContent = "Drops without tool";

  const dropsValue = document.createElement("span");
  dropsValue.className = `harvest-badge ${section.dropsWithoutTool ? "badge-yes" : "badge-no"}`;
  dropsValue.textContent = section.dropsWithoutTool ? "Yes" : "No";

  dropsRow.append(dropsLabel, dropsValue);
  grid.append(dropsRow);

  container.append(grid);
  return container;
}
