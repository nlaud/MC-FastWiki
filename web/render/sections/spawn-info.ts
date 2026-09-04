import type { SpawnInfo } from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { entityLink } from "../link.js";

/**
 * Renders a SpawnInfo section:
 * - Plain list of linked biome names (not a table)
 * - Sorted by share of totalWeight descending
 * - Collapses past 12 biomes with a "Show all N" button
 */
export function renderSpawnInfo(section: SpawnInfo, ctx: RenderContext): HTMLElement | null {
  if (!section.entries || section.entries.length === 0) {
    return null;
  }

  const container = document.createElement("section");
  container.className = "entity-section spawn-info-section";

  const title = document.createElement("h3");
  title.className = "section-title";
  title.textContent = "Spawn Biomes";
  container.append(title);

  // Sort by share of totalWeight descending
  const sorted = [...section.entries].sort((a, b) => {
    const shareA = a.totalWeight > 0 ? a.weight / a.totalWeight : 0;
    const shareB = b.totalWeight > 0 ? b.weight / b.totalWeight : 0;
    return shareB - shareA;
  });

  const listContainer = document.createElement("div");
  listContainer.className = "spawn-biomes-list";

  const COLLAPSE_THRESHOLD = 12;
  const itemElements: HTMLElement[] = [];

  for (const [i, entry] of sorted.entries()) {
    const itemEl = document.createElement("span");
    itemEl.className = "spawn-biome-item";
    if (i >= COLLAPSE_THRESHOLD) {
      itemEl.classList.add("is-collapsed-item");
    }

    if (entry.biomeRef) {
      itemEl.append(entityLink(entry.biomeRef, ctx));
    } else {
      const nameSpan = document.createElement("span");
      nameSpan.className = "biome-name";
      nameSpan.textContent = entry.biome;
      itemEl.append(nameSpan);
    }

    listContainer.append(itemEl);
    itemElements.push(itemEl);
  }

  container.append(listContainer);

  if (sorted.length > COLLAPSE_THRESHOLD) {
    let expanded = false;
    const toggleBtn = document.createElement("button");
    toggleBtn.type = "button";
    toggleBtn.className = "show-more-btn";
    toggleBtn.textContent = `Show all ${sorted.length.toString()}`;

    toggleBtn.addEventListener("click", () => {
      expanded = !expanded;
      for (let i = COLLAPSE_THRESHOLD; i < itemElements.length; i++) {
        const item = itemElements[i];
        if (item) {
          if (expanded) {
            item.classList.remove("is-collapsed-item");
          } else {
            item.classList.add("is-collapsed-item");
          }
        }
      }
      toggleBtn.textContent = expanded ? "Show less" : `Show all ${sorted.length.toString()}`;
    });

    container.append(toggleBtn);
  }

  return container;
}
