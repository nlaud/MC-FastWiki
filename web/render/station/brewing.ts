import type { RenderContext } from "../context.js";
import type { TreeProducer } from "../obtain-tree.js";
import { humaniseId, renderSlot } from "./slot.js";

/**
 * Renders a Brewing Stand workstation card.
 * - Top slot: ingredient (e.g. nether wart, redstone).
 * - Bottom row: three bottle slots showing the precursor potion / base bottle.
 * - Arrow pointing to result potion.
 * - Station chip indicates Brewing Stand.
 */
export function renderBrewingCard(
  producer: TreeProducer,
  resultItem: string,
  ctx: RenderContext,
): HTMLElement {
  const cardEl = document.createElement("div");
  cardEl.className = "station-card station-brewing";

  const chipsContainer = document.createElement("div");
  chipsContainer.className = "station-chips";
  const chip = document.createElement("span");
  chip.className = "station-chip station-chip-brewing";
  chip.textContent = "Brewing Stand";
  chipsContainer.append(chip);
  cardEl.append(chipsContainer);

  const bodyEl = document.createElement("div");
  bodyEl.className = "station-body brewing-body";

  // Stand container: top ingredient slot, stand lines, bottom 3 bottle slots
  const standEl = document.createElement("div");
  standEl.className = "brewing-stand";

  const ingredientInput = producer.inputs[0] ?? null;
  const topSlot = renderSlot(ingredientInput, ctx, { role: "ingredient" });
  topSlot.classList.add("slot-brewing-ingredient");
  standEl.append(topSlot);

  const standPipes = document.createElement("div");
  standPipes.className = "brewing-pipes";
  standPipes.setAttribute("aria-hidden", "true");
  standEl.append(standPipes);

  const bottlesRow = document.createElement("div");
  bottlesRow.className = "brewing-bottles";

  const potionInput = producer.inputs[1] ?? null;
  for (let i = 0; i < 3; i++) {
    const bottleSlot = renderSlot(potionInput, ctx, { role: "bottle" });
    bottleSlot.classList.add("slot-brewing-bottle");
    bottlesRow.append(bottleSlot);
  }
  standEl.append(bottlesRow);

  bodyEl.append(standEl);

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

/**
 * Renders a Filling workstation card (e.g. filling glass bottle from water).
 */
export function renderFillingCard(
  producer: TreeProducer,
  resultItem: string,
  ctx: RenderContext,
): HTMLElement {
  const cardEl = document.createElement("div");
  cardEl.className = "station-card station-filling";

  const chipsContainer = document.createElement("div");
  chipsContainer.className = "station-chips";
  const chip = document.createElement("span");
  chip.className = "station-chip station-chip-filling";
  chip.textContent = producer.station ? humaniseId(producer.station) : "Water Source";
  chipsContainer.append(chip);
  cardEl.append(chipsContainer);

  const bodyEl = document.createElement("div");
  bodyEl.className = "station-body filling-body";

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
