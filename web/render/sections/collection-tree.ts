import type { CollectionTree } from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { entityLink } from "../link.js";

/**
 * Renders a CollectionTree section:
 * - Optional title heading (`h3.section-title`).
 * - Flat list of indented member rows (`.collection-tree-items`).
 * - Every member is rendered via `entityLink` in a `.collection-tree-row`.
 * - Indent is driven by `--depth` CSS custom property.
 * - Returns null if members list is empty.
 */
export function renderCollectionTree(
  section: CollectionTree,
  ctx: RenderContext,
): HTMLElement | null {
  const members = section.members ?? [];
  if (members.length === 0) {
    return null;
  }

  const container = document.createElement("section");
  container.className = "entity-section collection-tree-section";

  if (section.title) {
    const title = document.createElement("h3");
    title.className = "section-title";
    title.textContent = section.title;
    container.append(title);
  }

  const list = document.createElement("div");
  list.className = "collection-tree-items";

  for (const member of members) {
    const row = document.createElement("div");
    row.className = "collection-tree-row";
    row.style.setProperty("--depth", String(member.depth));
    row.append(entityLink(member.ref, ctx));
    list.append(row);
  }
  container.append(list);

  return container;
}
