import type { RenderContext } from "../context.js";
import type { TreeProducer } from "../obtain-tree.js";
import { renderSlot } from "./slot.js";

const STATION_DISPLAY_NAMES: Record<string, string> = {
  furnace: "Furnace",
  blast_furnace: "Blast Furnace",
  smoker: "Smoker",
  campfire: "Campfire",
};

/**
 * Renders a Smelting workstation card.
 * - One card per distinct (input, output) smelt.
 * - Chips name only the stations that actually accept this smelt (no struck-through chips).
 * - Input slot, animated/styled flame, fuel slot, arrow, and result slot with count badge.
 */
export function renderFurnaceCard(
  producer: TreeProducer,
  resultItem: string,
  ctx: RenderContext,
): HTMLElement {
  const cardEl = document.createElement("div");
  cardEl.className = "station-card station-furnace";

  // Station chips: render only the applicable stations
  const stations =
    producer.stations && producer.stations.length > 0
      ? producer.stations
      : producer.station
        ? [producer.station]
        : ["furnace"];

  const chipsContainer = document.createElement("div");
  chipsContainer.className = "station-chips";
  for (const station of stations) {
    const chip = document.createElement("span");
    chip.className = `station-chip station-chip-${station}`;
    chip.textContent = STATION_DISPLAY_NAMES[station] ?? station;
    chipsContainer.append(chip);
  }
  cardEl.append(chipsContainer);

  const bodyEl = document.createElement("div");
  bodyEl.className = "station-body furnace-body";

  // Left column: input slot, flame, fuel slot
  const leftCol = document.createElement("div");
  leftCol.className = "furnace-column";

  const inputTarget = producer.inputs[0] ?? null;
  const inputSlot = renderSlot(inputTarget, ctx, { role: "input" });
  leftCol.append(inputSlot);

  const flameEl = document.createElement("div");
  flameEl.className = "station-flame";
  flameEl.setAttribute("aria-hidden", "true");
  flameEl.textContent = "🔥";
  leftCol.append(flameEl);

  // Fuel slot
  const fuelSlot = renderSlot("minecraft:coal", ctx, { role: "fuel" });
  fuelSlot.classList.add("slot-fuel");
  leftCol.append(fuelSlot);

  bodyEl.append(leftCol);

  // Arrow
  const arrowEl = document.createElement("div");
  arrowEl.className = "station-arrow";
  arrowEl.textContent = "→";
  bodyEl.append(arrowEl);

  // Result slot
  const resultSlot = renderSlot(resultItem, ctx, {
    count: producer.count,
    isResult: true,
  });
  bodyEl.append(resultSlot);

  cardEl.append(bodyEl);
  return cardEl;
}
