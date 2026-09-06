import type { RenderContext } from "../context.js";
import type { TreeProducer } from "../obtain-tree.js";
import { renderSlot } from "./slot.js";

/**
 * Renders a Smithing Table workstation card.
 * - Template slot + Base slot + Addition slot -> arrow -> Result slot with count badge.
 * - Station chip indicates Smithing Table.
 */
export function renderSmithingCard(
  producer: TreeProducer,
  resultItem: string,
  ctx: RenderContext,
): HTMLElement {
  const cardEl = document.createElement("div");
  cardEl.className = "station-card station-smithing";

  const chipsContainer = document.createElement("div");
  chipsContainer.className = "station-chips";
  const chip = document.createElement("span");
  chip.className = "station-chip station-chip-smithing";
  chip.textContent = "Smithing Table";
  chipsContainer.append(chip);
  cardEl.append(chipsContainer);

  const bodyEl = document.createElement("div");
  bodyEl.className = "station-body smithing-body";

  const templateInput = producer.inputs[0] ?? null;
  const templateSlot = renderSlot(templateInput, ctx, { role: "template" });
  bodyEl.append(templateSlot);

  const plus1 = document.createElement("div");
  plus1.className = "station-plus";
  plus1.textContent = "+";
  bodyEl.append(plus1);

  const baseInput = producer.inputs[1] ?? null;
  const baseSlot = renderSlot(baseInput, ctx, { role: "base" });
  bodyEl.append(baseSlot);

  const plus2 = document.createElement("div");
  plus2.className = "station-plus";
  plus2.textContent = "+";
  bodyEl.append(plus2);

  const additionInput = producer.inputs[2] ?? null;
  const additionSlot = renderSlot(additionInput, ctx, { role: "addition" });
  bodyEl.append(additionSlot);

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
