import type { ChestLoot } from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { entityLink, formatQuantityRange } from "../link.js";

function formatChance(chance: number): string {
  const pct = chance * 100;
  if (pct >= 100) {
    return "100%";
  }
  if (pct < 0.1) {
    return "<0.1%";
  }
  if (pct % 1 === 0) {
    return `${pct.toString()}%`;
  }
  return `${pct.toFixed(1)}%`;
}

/**
 * Renders a ChestLoot section:
 * - Table per container
 * - Sorted by chance descending
 * - Container label heading
 * - Item link, chance percentage, stack range
 * - Omits section if no containers exist
 */
export function renderChestLoot(section: ChestLoot, ctx: RenderContext): HTMLElement | null {
  if (section.containers.length === 0) {
    return null;
  }

  const container = document.createElement("section");
  container.className = "entity-section chest-loot-section";

  const title = document.createElement("h3");
  title.className = "section-title";
  title.textContent = "Chest Loot";
  container.append(title);

  for (const c of section.containers) {
    if (c.items.length === 0) {
      continue;
    }

    const group = document.createElement("div");
    group.className = "chest-container-group";

    const label = document.createElement("h4");
    label.className = "chest-container-label";
    label.textContent = c.label;
    group.append(label);

    const tableWrapper = document.createElement("div");
    tableWrapper.className = "table-wrapper";

    const table = document.createElement("table");
    table.className = "data-table chest-loot-table";

    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");

    for (const heading of ["Item", "Chance", "Stack Size"]) {
      const th = document.createElement("th");
      th.textContent = heading;
      headerRow.append(th);
    }
    thead.append(headerRow);
    table.append(thead);

    const tbody = document.createElement("tbody");
    const sortedItems = [...c.items].sort((a, b) => b.chance - a.chance);

    for (const item of sortedItems) {
      const tr = document.createElement("tr");

      const itemTd = document.createElement("td");
      itemTd.className = "item-cell";
      itemTd.append(entityLink(item.item, ctx));
      tr.append(itemTd);

      const chanceTd = document.createElement("td");
      chanceTd.className = "chance-cell";
      chanceTd.textContent = formatChance(item.chance);
      tr.append(chanceTd);

      const stackTd = document.createElement("td");
      stackTd.className = "stack-cell";
      stackTd.textContent = formatQuantityRange(item.stackRange);
      tr.append(stackTd);

      tbody.append(tr);
    }

    table.append(tbody);
    tableWrapper.append(table);
    group.append(tableWrapper);
    container.append(group);
  }

  if (container.children.length <= 1) {
    return null;
  }

  return container;
}
