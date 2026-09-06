import type { TradeTable } from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { entityLink } from "../link.js";

const LEVEL_ORDER: Record<string, number> = {
  Novice: 1,
  Apprentice: 2,
  Journeyman: 3,
  Expert: 4,
  Master: 5,
};

interface TradeItem {
  trade: NonNullable<TradeTable["trades"]>[number];
  globalIndex: number;
}

export interface TradeTableOptions {
  withoutTitle?: boolean;
}

/**
 * Renders a TradeTable section:
 * - Grouped by profession, then by level in game order (Novice through Master)
 * - Wanted and given items link through their ref
 * - Collapses past 6 rows with a "Show all N trades" button
 */
export function renderTradeTable(
  section: TradeTable,
  ctx: RenderContext,
  options: TradeTableOptions = {},
): HTMLElement | null {
  if (!section.trades || section.trades.length === 0) {
    return null;
  }

  const container = document.createElement(options.withoutTitle ? "div" : "section");
  container.className = options.withoutTitle
    ? "trade-table-embedded"
    : "entity-section trade-table-section";

  if (!options.withoutTitle) {
    const title = document.createElement("h3");
    title.className = "section-title";
    title.textContent = "Trades";
    container.append(title);
  }

  // Group by profession, then sort by level
  const byProfession = new Map<string, TradeItem[]>();
  let globalIndex = 0;

  for (const trade of section.trades) {
    const list = byProfession.get(trade.profession) ?? [];
    list.push({ trade, globalIndex: globalIndex++ });
    byProfession.set(trade.profession, list);
  }

  const sortedProfessions = Array.from(byProfession.keys()).sort();
  const COLLAPSE_THRESHOLD = 6;
  const collapsibleRows: HTMLElement[] = [];
  const collapsibleGroups: HTMLElement[] = [];

  const groupsContainer = document.createElement("div");
  groupsContainer.className = "trade-groups";

  for (const profession of sortedProfessions) {
    const items = byProfession.get(profession);
    if (!items) {
      continue;
    }
    items.sort((a, b) => {
      const ordA = LEVEL_ORDER[a.trade.level] ?? 99;
      const ordB = LEVEL_ORDER[b.trade.level] ?? 99;
      if (ordA !== ordB) {
        return ordA - ordB;
      }
      return a.trade.level.localeCompare(b.trade.level);
    });

    const profGroup = document.createElement("div");
    profGroup.className = "trade-profession-group";

    // If all items in this group are past threshold, collapse the group
    const allCollapsed = items.every((item) => item.globalIndex >= COLLAPSE_THRESHOLD);
    if (allCollapsed) {
      profGroup.classList.add("is-collapsed-group");
      collapsibleGroups.push(profGroup);
    }

    const profHeader = document.createElement("h4");
    profHeader.className = "trade-profession-title";
    profHeader.textContent = profession;
    profGroup.append(profHeader);

    const table = document.createElement("table");
    table.className = "data-table trade-table";

    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");
    for (const h of ["Level", "Wanted", "", "Given", "Chance"]) {
      const th = document.createElement("th");
      th.textContent = h;
      headerRow.append(th);
    }
    thead.append(headerRow);
    table.append(thead);

    const tbody = document.createElement("tbody");

    for (const item of items) {
      const tr = document.createElement("tr");
      if (item.globalIndex >= COLLAPSE_THRESHOLD) {
        tr.classList.add("is-collapsed-row");
        collapsibleRows.push(tr);
      }

      // Level
      const levelTd = document.createElement("td");
      levelTd.className = "trade-level-cell";
      levelTd.textContent = item.trade.level;
      tr.append(levelTd);

      // Wanted items
      const wantedTd = document.createElement("td");
      wantedTd.className = "trade-wanted-cell";
      if (item.trade.wanted && item.trade.wanted.length > 0) {
        for (const [i, wantedItem] of item.trade.wanted.entries()) {
          if (i > 0) {
            const plus = document.createElement("span");
            plus.className = "trade-plus";
            plus.textContent = " + ";
            wantedTd.append(plus);
          }
          wantedTd.append(entityLink(wantedItem, ctx));
        }
      } else {
        wantedTd.textContent = "—";
      }
      tr.append(wantedTd);

      // Arrow
      const arrowTd = document.createElement("td");
      arrowTd.className = "trade-arrow-cell";
      arrowTd.textContent = "→";
      tr.append(arrowTd);

      // Given item
      const givenTd = document.createElement("td");
      givenTd.className = "trade-given-cell";
      givenTd.append(entityLink(item.trade.given, ctx));
      tr.append(givenTd);

      // Chance
      const chanceTd = document.createElement("td");
      chanceTd.className = "trade-chance-cell";
      chanceTd.textContent = item.trade.javaProbability?.text ?? "—";
      tr.append(chanceTd);

      tbody.append(tr);
    }

    table.append(tbody);
    profGroup.append(table);
    groupsContainer.append(profGroup);
  }

  container.append(groupsContainer);

  if (section.trades.length > COLLAPSE_THRESHOLD) {
    let expanded = false;
    const totalTrades = section.trades.length;
    const toggleBtn = document.createElement("button");
    toggleBtn.type = "button";
    toggleBtn.className = "show-more-btn";
    toggleBtn.textContent = `Show all ${totalTrades.toString()} trades`;

    toggleBtn.addEventListener("click", () => {
      expanded = !expanded;
      for (const row of collapsibleRows) {
        if (expanded) {
          row.classList.remove("is-collapsed-row");
        } else {
          row.classList.add("is-collapsed-row");
        }
      }
      for (const group of collapsibleGroups) {
        if (expanded) {
          group.classList.remove("is-collapsed-group");
        } else {
          group.classList.add("is-collapsed-group");
        }
      }
      toggleBtn.textContent = expanded ? "Show less" : `Show all ${totalTrades.toString()} trades`;
    });

    container.append(toggleBtn);
  }

  return container;
}
