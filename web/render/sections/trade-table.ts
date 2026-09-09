import type { TradeTable } from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { entityLink } from "../link.js";

/**
 * The display rank of a trade level, mirroring `LEVEL_ORDER` in
 * `pipeline/enrich/trade.py`.
 *
 * `level` names two different ladders. Villagers climb Novice through Master.
 * The wandering trader has Ordinary, Special and Purchase instead, and that is
 * the order the wiki presents them in, not alphabetical order. Listing only the
 * five villager levels here left the trader's three to fall through to the
 * `?? 99` default and sort by name, which put Purchase above Special and
 * silently disagreed with the pipeline that had already ranked them.
 *
 * An unknown level still sorts after every known one rather than being dropped,
 * for the reason `level_rank` gives: a level this project has not seen is a new
 * label, not a reason to lose a trade.
 */
const LEVEL_ORDER: Record<string, number> = {
  Novice: 1,
  Apprentice: 2,
  Journeyman: 3,
  Expert: 4,
  Master: 5,
  Ordinary: 6,
  Special: 7,
  Purchase: 8,
};

interface TradeItem {
  trade: NonNullable<TradeTable["trades"]>[number];
  globalIndex: number;
}

export interface TradeTableOptions {
  withoutTitle?: boolean;
  groupByLevelOnly?: boolean;
}

/**
 * Renders a TradeTable section:
 * - When groupByLevelOnly is true (professions): grouped by level (Novice through Master) with h4 level headings, no row collapse.
 * - Otherwise (items / mobs): grouped by profession, then by level in game order (Novice through Master), collapsing past 6 rows.
 * - Wanted and given items link through their ref.
 * - Profession headers link through professionRef if present.
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

  if (options.groupByLevelOnly) {
    const byLevel = new Map<string, TradeTable["trades"]>();
    for (const trade of section.trades) {
      const list = byLevel.get(trade.level) ?? [];
      list.push(trade);
      byLevel.set(trade.level, list);
    }

    const sortedLevels = Array.from(byLevel.keys()).sort((a, b) => {
      const ordA = LEVEL_ORDER[a] ?? 99;
      const ordB = LEVEL_ORDER[b] ?? 99;
      if (ordA !== ordB) {
        return ordA - ordB;
      }
      return a.localeCompare(b);
    });

    const groupsContainer = document.createElement("div");
    groupsContainer.className = "trade-groups trade-level-groups";

    for (const level of sortedLevels) {
      const items = byLevel.get(level);
      if (!items || items.length === 0) {
        continue;
      }

      const levelGroup = document.createElement("div");
      levelGroup.className = "trade-level-group";

      const levelHeader = document.createElement("h4");
      levelHeader.className = "trade-level-title";
      levelHeader.textContent = level;
      levelGroup.append(levelHeader);

      const table = document.createElement("table");
      table.className = "data-table trade-table";

      const thead = document.createElement("thead");
      const headerRow = document.createElement("tr");
      for (const h of ["Wanted", "", "Given", "Chance"]) {
        const th = document.createElement("th");
        th.textContent = h;
        headerRow.append(th);
      }
      thead.append(headerRow);
      table.append(thead);

      const tbody = document.createElement("tbody");
      for (const trade of items) {
        const tr = document.createElement("tr");

        // Wanted items
        const wantedTd = document.createElement("td");
        wantedTd.className = "trade-wanted-cell";
        if (trade.wanted && trade.wanted.length > 0) {
          for (const [i, wantedItem] of trade.wanted.entries()) {
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
        givenTd.append(entityLink(trade.given, ctx));
        tr.append(givenTd);

        // Chance
        const chanceTd = document.createElement("td");
        chanceTd.className = "trade-chance-cell";
        chanceTd.textContent = trade.javaProbability?.text ?? "—";
        tr.append(chanceTd);

        tbody.append(tr);
      }

      table.append(tbody);
      levelGroup.append(table);
      groupsContainer.append(levelGroup);
    }

    container.append(groupsContainer);
    return container;
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
    const profRef = items[0]?.trade.professionRef;
    if (profRef) {
      profHeader.append(entityLink(profRef, ctx));
    } else {
      profHeader.textContent = profession;
    }
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
