import type { DropTable, Ratio } from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { entityLink } from "../link.js";

function formatRatioPercentage(ratio: Ratio): string {
  if (ratio.denominator === 0) {
    return "0%";
  }
  const pct = (ratio.numerator / ratio.denominator) * 100;
  if (pct % 1 === 0) {
    return `${pct.toString()}%`;
  }
  const rounded = Math.round(pct * 10) / 10;
  return `${rounded.toString()}%`;
}

function cleanWikitext(text: string): string {
  return text.replace(/\[\[(?:[^|\]]*\|)?([^\]]+)\]\]/g, "$1");
}

/**
 * Renders a DropTable section:
 * - One row per item, four columns for looting 0 through 3
 * - A drop that always happens shows quantityText; a chance drop shows dropChance as a percentage
 * - Drops collapse past 6 rows with a "Show all N" button
 */
export function renderDropTable(section: DropTable, ctx: RenderContext): HTMLElement | null {
  if (!section.drops || section.drops.length === 0) {
    return null;
  }

  const container = document.createElement("section");
  container.className = "entity-section drop-table-section";

  const title = document.createElement("h3");
  title.className = "section-title";
  title.textContent = "Drops";
  container.append(title);

  const tableWrapper = document.createElement("div");
  tableWrapper.className = "table-wrapper";

  const table = document.createElement("table");
  table.className = "data-table drop-table";

  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");

  const headers = ["Item", "Looting 0", "Looting I", "Looting II", "Looting III"];
  for (const text of headers) {
    const th = document.createElement("th");
    th.textContent = text;
    headerRow.append(th);
  }
  thead.append(headerRow);
  table.append(thead);

  const tbody = document.createElement("tbody");
  const COLLAPSE_THRESHOLD = 6;
  const rows: HTMLTableRowElement[] = [];

  for (const [i, drop] of section.drops.entries()) {
    const tr = document.createElement("tr");
    if (i >= COLLAPSE_THRESHOLD) {
      tr.classList.add("is-collapsed-row");
    }

    // Item column
    const itemTd = document.createElement("td");
    itemTd.className = "item-cell";
    if (drop.itemRef) {
      itemTd.append(entityLink(drop.itemRef, ctx));
    } else {
      const nameSpan = document.createElement("span");
      nameSpan.className = "entity-name";
      nameSpan.textContent = drop.item;
      itemTd.append(nameSpan);
    }

    if (drop.notes && drop.notes.length > 0) {
      for (const note of drop.notes) {
        const noteEl = document.createElement("div");
        noteEl.className = "drop-note";
        noteEl.textContent = cleanWikitext(note.content);
        itemTd.append(noteEl);
      }
    }
    tr.append(itemTd);

    // Looting 0..3 columns
    for (let lvl = 0; lvl <= 3; lvl++) {
      const td = document.createElement("td");
      td.className = "looting-cell";

      const lootingDrop = drop.byLootingLevel?.find((l) => l.lootingLevel === lvl);
      if (lootingDrop) {
        // Show the figure the reader came for. A drop that can yield more than
        // one item is a question of how many, so print the quantity; a drop
        // capped at one is a question of whether, so print the chance. A
        // certain drop prints its quantity either way. The other figure stays
        // in the cell's title attribute.
        const always =
          lootingDrop.dropChance.numerator === lootingDrop.dropChance.denominator &&
          lootingDrop.dropChance.denominator > 0;

        if (always || lootingDrop.maximum > 1) {
          td.textContent = lootingDrop.quantityText;
        } else {
          td.textContent = formatRatioPercentage(lootingDrop.dropChance);
        }
        td.title = `${lootingDrop.quantityText}, ${formatRatioPercentage(lootingDrop.dropChance)} chance (avg ${lootingDrop.average.numerator.toString()}/${lootingDrop.average.denominator.toString()})`;
      } else {
        td.textContent = "—";
      }
      tr.append(td);
    }

    tbody.append(tr);
    rows.push(tr);
  }

  table.append(tbody);
  tableWrapper.append(table);
  container.append(tableWrapper);

  // Collapse past threshold
  if (section.drops.length > COLLAPSE_THRESHOLD) {
    let expanded = false;
    const totalDrops = section.drops.length;
    const toggleBtn = document.createElement("button");
    toggleBtn.type = "button";
    toggleBtn.className = "show-more-btn";
    toggleBtn.textContent = `Show all ${totalDrops.toString()}`;

    toggleBtn.addEventListener("click", () => {
      expanded = !expanded;
      for (let i = COLLAPSE_THRESHOLD; i < rows.length; i++) {
        const row = rows[i];
        if (row) {
          if (expanded) {
            row.classList.remove("is-collapsed-row");
          } else {
            row.classList.add("is-collapsed-row");
          }
        }
      }
      toggleBtn.textContent = expanded ? "Show less" : `Show all ${totalDrops.toString()}`;
    });

    container.append(toggleBtn);
  }

  return container;
}
