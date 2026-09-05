import type { RenderContext } from "../context.js";
import { createIconElement } from "../icon.js";

function humaniseId(id: string): string {
  const bare = id.replace(/^[a-z0-9_-]+:/, "");
  return bare
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/**
 * Renders a Leaf node card for an item the tree does not walk any further.
 * - Item icon + linked readable name.
 * - Quiet 'Raw material' note, but only when `isRaw` says the graph knows of no
 *   producer at all for this item. A leaf reached because the depth-1 filter or
 *   cycle detection removed every producer is still a crafted item, and calling
 *   it a raw material is a claim the tree has not checked -- Block of Iron under
 *   Iron Ingot is the case that caught this.
 * - No station, no branch, no children.
 */
export function renderLeafCard(
  itemId: string,
  ctx: RenderContext,
  options: { isRaw?: boolean } = {},
): HTMLElement {
  const cardEl = document.createElement("div");
  cardEl.className = "station-card station-leaf";
  cardEl.tabIndex = 0;
  cardEl.setAttribute("role", "button");

  const entry = ctx.lookup(itemId);
  const displayName = entry?.n ?? humaniseId(itemId);

  const bodyEl = document.createElement("div");
  bodyEl.className = "station-body leaf-body";

  if (entry?.i) {
    const icon = createIconElement(entry.i, { size: 18 });
    bodyEl.append(icon);
  }

  const nameEl = document.createElement("span");
  nameEl.className = "leaf-name";
  nameEl.textContent = displayName;
  bodyEl.append(nameEl);

  if (options.isRaw ?? false) {
    const badgeEl = document.createElement("span");
    badgeEl.className = "leaf-badge";
    badgeEl.textContent = "Raw material";
    bodyEl.append(badgeEl);
  }

  cardEl.append(bodyEl);

  const openLeaf = (e: Event): void => {
    e.preventDefault();
    ctx.openRef(itemId);
  };

  cardEl.addEventListener("click", openLeaf);
  cardEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      openLeaf(e);
    }
  });

  return cardEl;
}
