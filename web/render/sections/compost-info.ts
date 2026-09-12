import type { CompostInfo } from "../../types/entity.js";
import type { RenderContext } from "../context.js";

/**
 * Renders the composting chance for an item placed in a composter.
 */
export function renderCompostInfo(section: CompostInfo, _ctx: RenderContext): HTMLElement | null {
  const container = document.createElement("section");
  container.className = "entity-section compost-info-section";

  const title = document.createElement("h3");
  title.className = "section-title";
  title.textContent = "Composting";
  container.append(title);

  const box = document.createElement("div");
  box.className = "compost-box";

  const metric = document.createElement("div");
  metric.className = "compost-metric";

  const chanceValue = document.createElement("span");
  chanceValue.className = "compost-chance-value";
  chanceValue.textContent = `${section.chance.toString()}%`;

  const chanceLabel = document.createElement("span");
  chanceLabel.className = "compost-chance-label";
  chanceLabel.textContent = "chance to add a layer";

  metric.append(chanceValue, chanceLabel);
  box.append(metric);
  container.append(box);

  return container;
}
