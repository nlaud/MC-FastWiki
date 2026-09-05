import type { RenderContext } from "../context.js";
import type { TreeProducer } from "../obtain-tree.js";
import { renderSlot } from "./slot.js";

/**
 * Renders a Stonecutter workstation card.
 * - Chips indicate the Stonecutter station.
 * - Single input slot -> arrow -> result slot with count badge.
 */
export function renderStonecutterCard(
  producer: TreeProducer,
  resultItem: string,
  ctx: RenderContext,
): HTMLElement {
  const cardEl = document.createElement("div");
  cardEl.className = "station-card station-stonecutter";

  const chipsContainer = document.createElement("div");
  chipsContainer.className = "station-chips";
  const chip = document.createElement("span");
  chip.className = "station-chip station-chip-stonecutter";
  chip.textContent = "Stonecutter";
  chipsContainer.append(chip);
  cardEl.append(chipsContainer);

  const bodyEl = document.createElement("div");
  bodyEl.className = "station-body stonecutter-body";

  const inputTarget = producer.inputs[0] ?? null;
  const inputSlot = renderSlot(inputTarget, ctx, { role: "input" });
  bodyEl.append(inputSlot);

  const arrowEl = document.createElement("div");
  arrowEl.className = "station-arrow";
  arrowEl.textContent = "→";
  bodyEl.append(arrowEl);

  const resultSlot = renderSlot(resultItem, ctx, {
    count: producer.count,
    isResult: true,
  });
  bodyEl.append(resultSlot);

  cardEl.append(bodyEl);
  return cardEl;
}
