import type { EffectLink, EffectSource, EffectSources } from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { entityLink } from "../link.js";

function renderSourceItem(source: EffectSource, ctx: RenderContext): HTMLElement {
  const container = document.createElement("span");
  container.className = "effect-source-name-cell";

  if (source.ref) {
    container.append(entityLink(source.ref, ctx));
  } else {
    const plain = document.createElement("span");
    plain.className = "entity-plain";
    const nameSpan = document.createElement("span");
    nameSpan.className = "entity-name";
    nameSpan.textContent = source.name;
    plain.append(nameSpan);
    container.append(plain);
  }

  if (source.qualifier) {
    const qual = document.createElement("span");
    qual.className = "effect-source-qualifier";
    qual.textContent = source.qualifier;
    container.append(qual);
  }

  return container;
}

function renderRemover(link: EffectLink, ctx: RenderContext): HTMLElement {
  if (link.ref) {
    return entityLink(link.ref, ctx);
  }
  const plain = document.createElement("span");
  plain.className = "entity-plain";
  const nameSpan = document.createElement("span");
  nameSpan.className = "entity-name";
  nameSpan.textContent = link.name;
  plain.append(nameSpan);
  return plain;
}

export function renderEffectSources(section: EffectSources, ctx: RenderContext): HTMLElement {
  const container = document.createElement("section");
  container.className = "entity-section effect-sources-section";

  // Header with title and category badge
  const header = document.createElement("div");
  header.className = "effect-header";

  const title = document.createElement("h3");
  title.className = "section-title";
  title.textContent = "Effect Sources";

  const badge = document.createElement("span");
  badge.className = `effect-category-badge category-${section.category}`;
  badge.textContent = section.category;

  header.append(title, badge);
  container.append(header);

  // Behaviour prose if present
  if (section.behaviour) {
    const behaviourP = document.createElement("p");
    behaviourP.className = "effect-behaviour";
    behaviourP.textContent = section.behaviour;
    container.append(behaviourP);
  }

  // Removed by row if present
  if (section.removedBy.length > 0) {
    const removedByDiv = document.createElement("div");
    removedByDiv.className = "effect-removed-by";

    const label = document.createElement("span");
    label.className = "effect-removed-by-label";
    label.textContent = "Removed by:";
    removedByDiv.append(label);

    for (const remover of section.removedBy) {
      removedByDiv.append(renderRemover(remover, ctx));
    }
    container.append(removedByDiv);
  }

  // Sources table if present
  if (section.sources.length > 0) {
    const tableWrapper = document.createElement("div");
    tableWrapper.className = "effect-sources-container";

    const table = document.createElement("table");
    table.className = "effect-sources-table";

    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");

    const thSource = document.createElement("th");
    thSource.textContent = "Source";

    const thPotency = document.createElement("th");
    thPotency.textContent = "Potency";

    const thLength = document.createElement("th");
    thLength.textContent = "Duration";

    const thNotes = document.createElement("th");
    thNotes.textContent = "Notes";

    headerRow.append(thSource, thPotency, thLength, thNotes);
    thead.append(headerRow);
    table.append(thead);

    const tbody = document.createElement("tbody");
    for (const src of section.sources) {
      const row = document.createElement("tr");

      const tdSource = document.createElement("td");
      tdSource.append(renderSourceItem(src, ctx));

      const tdPotency = document.createElement("td");
      tdPotency.className = "effect-source-potency";
      tdPotency.textContent = src.potency ?? "—";

      const tdLength = document.createElement("td");
      tdLength.className = "effect-source-length";
      tdLength.textContent = src.length ?? "—";

      const tdNotes = document.createElement("td");
      tdNotes.className = "effect-source-notes";
      tdNotes.textContent = src.note ?? "—";

      row.append(tdSource, tdPotency, tdLength, tdNotes);
      tbody.append(row);
    }

    table.append(tbody);
    tableWrapper.append(table);
    container.append(tableWrapper);
  }

  return container;
}
