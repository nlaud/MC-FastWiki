import type { ProfessionInfo } from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { entityLink } from "../link.js";

/**
 * Renders a ProfessionInfo section:
 * - Workstation block or item link
 * - Total trade count
 */
export function renderProfessionInfo(
  section: ProfessionInfo,
  ctx: RenderContext,
): HTMLElement | null {
  const container = document.createElement("section");
  container.className = "entity-section profession-info-section";

  // Workstation row
  if (section.workstation) {
    const wsRow = document.createElement("div");
    wsRow.className = "profession-row profession-workstation";

    const label = document.createElement("span");
    label.className = "profession-field-label";
    label.textContent = "Workstation:";

    wsRow.append(label, entityLink(section.workstation, ctx));
    container.append(wsRow);
  }

  // Trade count row
  if (section.tradeCount > 0) {
    const tradesRow = document.createElement("div");
    tradesRow.className = "profession-row profession-trades-count";

    const label = document.createElement("span");
    label.className = "profession-field-label";
    label.textContent = "Trades:";

    const val = document.createElement("span");
    val.className = "profession-field-value";
    val.textContent = `${section.tradeCount.toString()} total trades`;

    tradesRow.append(label, val);
    container.append(tradesRow);
  }

  if (!container.hasChildNodes()) {
    return null;
  }

  return container;
}
