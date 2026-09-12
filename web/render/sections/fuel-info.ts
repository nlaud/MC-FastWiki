import type { FuelInfo } from "../../types/entity.js";
import type { RenderContext } from "../context.js";

function formatBurnDuration(ticks: number): string {
  if (ticks % 20 === 0) {
    return `${(ticks / 20).toString()}s`;
  }
  const seconds = (ticks / 20).toFixed(2).replace(/\.?0+$/, "");
  return `${seconds}s`;
}

function formatSmeltedCount(ticks: number): string {
  if (ticks % 200 === 0) {
    return (ticks / 200).toString();
  }
  return (ticks / 200).toFixed(2).replace(/\.?0+$/, "");
}

/**
 * Renders furnace fuel duration and smelted item count.
 */
export function renderFuelInfo(section: FuelInfo, _ctx: RenderContext): HTMLElement | null {
  const container = document.createElement("section");
  container.className = "entity-section fuel-info-section";

  const title = document.createElement("h3");
  title.className = "section-title";
  title.textContent = "Furnace Fuel";
  container.append(title);

  const box = document.createElement("div");
  box.className = "fuel-box";

  const durationRow = document.createElement("div");
  durationRow.className = "fuel-metric";

  const durationValue = document.createElement("span");
  durationValue.className = "fuel-burn-duration";
  durationValue.textContent = formatBurnDuration(section.burnTime);

  const durationLabel = document.createElement("span");
  durationLabel.className = "fuel-burn-label";
  durationLabel.textContent = `burn time (${section.burnTime.toLocaleString()} ticks)`;

  durationRow.append(durationValue, durationLabel);

  const smeltRow = document.createElement("div");
  smeltRow.className = "fuel-metric";

  const smeltValue = document.createElement("span");
  smeltValue.className = "fuel-smelt-count";
  smeltValue.textContent = formatSmeltedCount(section.burnTime);

  const smeltLabel = document.createElement("span");
  smeltLabel.className = "fuel-smelt-label";
  const ops = Number(smeltValue.textContent);
  smeltLabel.textContent = ops === 1 ? "item smelted" : "items smelted";

  smeltRow.append(smeltValue, smeltLabel);

  box.append(durationRow, smeltRow);
  container.append(box);

  return container;
}
