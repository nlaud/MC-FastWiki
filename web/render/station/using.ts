import type { RenderContext } from "../context.js";
import type { TreeProducer } from "../obtain-tree.js";
import { renderSlot } from "./slot.js";

/**
 * Renders a direct item-usage interaction card (e.g. signing a Book and Quill into a Written Book).
 * - Single input slot.
 * - Arrow pointing to result.
 * - Result slot with count.
 * - Station chip indicating Using.
 */
export function renderUsingCard(
  producer: TreeProducer,
  resultItem: string,
  ctx: RenderContext,
): HTMLElement {
  const cardEl = document.createElement("div");
  cardEl.className = "station-card station-using";

  const chipsContainer = document.createElement("div");
  chipsContainer.className = "station-chips";
  const chip = document.createElement("span");
  chip.className = "station-chip station-chip-using";
  chip.textContent = "Using";
  chipsContainer.append(chip);
  cardEl.append(chipsContainer);

  const bodyEl = document.createElement("div");
  bodyEl.className = "station-body using-body";

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
