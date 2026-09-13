import type { CollectionMembers } from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { entityLink, proseEntityLink } from "../link.js";

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
        const colRefs = member.refs?.[col.key];
        if (colRefs && colRefs.length > 0) {
          td.classList.add("has-refs");
          // `proseEntityLink`, not `entityLink`, and on every link rather than
          // only the ones a comma follows. The standalone link's horizontal
          // padding reads as a word space before punctuation, which rendered
          // the Coast trim's cell as `Shipwreck , Beached Shipwreck`. Applying
          // it to single-ref cells too keeps one column's links on one left
          // edge; padding only the rows that happen to hold one ref would
          // indent them 4px past the rest of the column.
          colRefs.forEach((ref, index) => {
            if (index > 0) {
              td.append(", ");
            }
            td.append(proseEntityLink(ref, ctx));
          });
        } else {
          const val = member.values?.[col.key];
          if (val !== undefined && val !== "") {
            td.textContent = val;
          }
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
