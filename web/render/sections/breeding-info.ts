import type { BreedingInfo, BreedingItem } from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { entityLink } from "../link.js";

function renderBreedingItem(item: BreedingItem, ctx: RenderContext): HTMLElement {
  if (item.ref) {
    return entityLink(item.ref, ctx);
  }
  const plain = document.createElement("span");
  plain.className = "entity-plain";
  const nameSpan = document.createElement("span");
  nameSpan.className = "entity-name";
  nameSpan.textContent = item.name;
  plain.append(nameSpan);
  return plain;
}

/**
 * Formats a duration in seconds the way the wiki states it: whole minutes
 * where the value divides evenly, seconds otherwise.
 */
function formatDuration(seconds: number): string {
  if (seconds >= 60 && seconds % 60 === 0) {
    const minutes = seconds / 60;
    return `${minutes.toString()} ${minutes === 1 ? "minute" : "minutes"}`;
  }
  return `${seconds.toString()} ${seconds === 1 ? "second" : "seconds"}`;
}

/**
 * Renders a BreedingInfo section:
 * - Title "Breeding"
 * - Optional "Requires Taming" badge
 * - Cooldown and baby growth time, both read from the section
 * - Food items as entity links or plain text
 * - Taming items if present
 */
export function renderBreedingInfo(section: BreedingInfo, ctx: RenderContext): HTMLElement | null {
  if (section.items.length === 0) {
    return null;
  }

  const container = document.createElement("section");
  container.className = "entity-section breeding-info-section";

  const header = document.createElement("div");
  header.className = "breeding-header";

  const title = document.createElement("h3");
  title.className = "section-title";
  title.textContent = "Breeding";
  header.append(title);

  if (section.requiresTaming) {
    const tamingBadge = document.createElement("span");
    tamingBadge.className = "stat-badge";
    tamingBadge.textContent = "Requires Taming";
    header.append(tamingBadge);
  }

  container.append(header);

  const timing = document.createElement("div");
  timing.className = "breeding-timing";

  const cooldown = document.createElement("span");
  cooldown.className = "timing-item";
  const cdLabel = document.createElement("strong");
  cdLabel.textContent = "Cooldown: ";
  cooldown.append(cdLabel, document.createTextNode(formatDuration(section.cooldownSeconds)));
  timing.append(cooldown);

  const babyGrowth = document.createElement("span");
  babyGrowth.className = "timing-item";
  const growthLabel = document.createElement("strong");
  growthLabel.textContent = "Baby Growth: ";
  babyGrowth.append(
    growthLabel,
    document.createTextNode(formatDuration(section.babyGrowthSeconds)),
  );
  timing.append(babyGrowth);

  container.append(timing);

  // Food items
  const foodGroup = document.createElement("div");
  foodGroup.className = "breeding-group";

  const foodTitle = document.createElement("h4");
  foodTitle.className = "breeding-subtitle";
  foodTitle.textContent = "Food";
  foodGroup.append(foodTitle);

  const foodItems = document.createElement("div");
  foodItems.className = "breeding-items";
  for (const item of section.items) {
    foodItems.append(renderBreedingItem(item, ctx));
  }
  foodGroup.append(foodItems);
  container.append(foodGroup);

  // Taming items (only rendered when non-empty)
  if (section.tamingItems.length > 0) {
    const tamingGroup = document.createElement("div");
    tamingGroup.className = "breeding-group taming-group";

    const tamingTitle = document.createElement("h4");
    tamingTitle.className = "breeding-subtitle";
    tamingTitle.textContent = "Taming";
    tamingGroup.append(tamingTitle);

    const tamingItemsEl = document.createElement("div");
    tamingItemsEl.className = "taming-items";
    for (const item of section.tamingItems) {
      tamingItemsEl.append(renderBreedingItem(item, ctx));
    }
    tamingGroup.append(tamingItemsEl);
    container.append(tamingGroup);
  }

  return container;
}
