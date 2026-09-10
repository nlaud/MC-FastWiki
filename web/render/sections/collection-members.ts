import type { CollectionMembers } from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { entityLink } from "../link.js";

/**
 * Renders a CollectionMembers section:
 * - Table form with columns if `columns` are present and non-empty.
 * - Flat link row if no columns are defined.
 * - Every member is rendered via `entityLink`.
 * - Missing fact values render as empty cells.
 * - Omits section if members list is empty.
 */
export function renderCollectionMembers(
  section: CollectionMembers,
  ctx: RenderContext,
): HTMLElement | null {
  const members = section.members ?? [];
  if (members.length === 0) {
    return null;
  }

  const container = document.createElement("section");
  container.className = "entity-section collection-members-section";

  if (section.title) {
    const title = document.createElement("h3");
    title.className = "section-title";
    title.textContent = section.title;
    container.append(title);
  }

  const columns = section.columns ?? [];
  if (columns.length > 0) {
    const tableWrapper = document.createElement("div");
    tableWrapper.className = "table-wrapper";

    const table = document.createElement("table");
    table.className = "data-table collection-members-table";

    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");

    const thName = document.createElement("th");
    thName.textContent = "Name";
    headerRow.append(thName);

    for (const col of columns) {
      const th = document.createElement("th");
      th.textContent = col.label;
      headerRow.append(th);
    }
    thead.append(headerRow);
    table.append(thead);

    const tbody = document.createElement("tbody");
    for (const member of members) {
      const tr = document.createElement("tr");

      const tdName = document.createElement("td");
      tdName.className = "member-cell";
      tdName.append(entityLink(member.ref, ctx));
      tr.append(tdName);

      for (const col of columns) {
        const td = document.createElement("td");
        td.className = "fact-cell";
        const val = member.values?.[col.key];
        if (val !== undefined && val !== "") {
          td.textContent = val;
        }
        tr.append(td);
      }
      tbody.append(tr);
    }
    table.append(tbody);
    tableWrapper.append(table);
    container.append(tableWrapper);
  } else {
    const list = document.createElement("div");
    list.className = "collection-members-items";

    for (const member of members) {
      list.append(entityLink(member.ref, ctx));
    }
    container.append(list);
  }

  return container;
}
