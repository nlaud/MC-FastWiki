import type {
  EntityRef,
  HarvestDrop,
  HarvestInfo,
  HarvestTier,
  HarvestTool,
  ItemAmount,
} from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { entityLink } from "../link.js";

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
 * Turns one drop into the target `entityLink` wants.
 *
 * A count of 1 stays an `EntityRef`, because `entityLink` prints every
 * `ItemAmount` quantity it is given and a leading "1" on every single-item
 * drop is noise. Anything above 1 becomes an `ItemAmount` so the count picks
 * up the same `.item-quantity` styling every other section's quantities have.
 */
function dropTarget(drop: HarvestDrop): EntityRef | ItemAmount {
  const ref: EntityRef = { id: drop.id, name: drop.name ?? drop.id };
  const count = drop.count ?? 1;
  if (count === 1) {
    return ref;
  }
  return { name: ref.name, ref, quantity: { minimum: count, maximum: count } };
}

/**
 * Renders one drop as a link, tagged with a "requires silk touch" or "requires shears"
 * badge when gated.
 */
function renderDrop(drop: HarvestDrop, ctx: RenderContext): HTMLElement {
  const link = entityLink(dropTarget(drop), ctx);
  if (!drop.gate) {
    return link;
  }

  const wrapper = document.createElement("span");
  wrapper.className = "harvest-drop";
  const badge = document.createElement("span");
  badge.className = "sources-note-badge";
  badge.textContent = drop.gate === "silk_touch" ? "requires silk touch" : "requires shears";
  wrapper.append(link, badge);
  return wrapper;
}

/**
 * Renders a HarvestInfo section:
 * - Title "Harvest"
 * - Tool(s) required to break the block
 * - Minimum tier required for drops
 * - Whether the block drops when broken without the tool
 * - Items dropped when broken, silk-touch drops badged as such
 */
export function renderHarvestInfo(section: HarvestInfo, ctx: RenderContext): HTMLElement {
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
  const dropsWithoutToolRow = document.createElement("div");
  dropsWithoutToolRow.className = "harvest-row";

  const dropsWithoutToolLabel = document.createElement("span");
  dropsWithoutToolLabel.className = "harvest-label";
  dropsWithoutToolLabel.textContent = "Drops without tool";

  const dropsWithoutToolValue = document.createElement("span");
  dropsWithoutToolValue.className = `harvest-badge ${section.dropsWithoutTool ? "badge-yes" : "badge-no"}`;
  dropsWithoutToolValue.textContent = section.dropsWithoutTool ? "Yes" : "No";

  dropsWithoutToolRow.append(dropsWithoutToolLabel, dropsWithoutToolValue);
  grid.append(dropsWithoutToolRow);

  // Block drops row
  const drops = section.drops ?? [];
  if (drops.length > 0) {
    const dropsRow = document.createElement("div");
    dropsRow.className = "harvest-row";

    const dropsLabel = document.createElement("span");
    dropsLabel.className = "harvest-label";
    dropsLabel.textContent = "Drops";

    const dropsValue = document.createElement("span");
    dropsValue.className = "harvest-value harvest-drops";

    // Gated drops (silk touch, shears) sort last, so the drop a player gets by
    // simply breaking the block reads first.
    const ordered = [...drops].sort(
      (a, b) => Number(a.gate !== undefined) - Number(b.gate !== undefined),
    );
    for (const drop of ordered) {
      dropsValue.append(renderDrop(drop, ctx));
    }

    dropsRow.append(dropsLabel, dropsValue);
    grid.append(dropsRow);
  }

  container.append(grid);
  return container;
}
