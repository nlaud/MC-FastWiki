import type { RenderContext } from "../context.js";
import { createIconElement } from "../icon.js";
import { potionIconKey, potionName } from "./potion-icon.js";
import { humaniseId } from "./slot.js";

/**
 * Renders a Leaf node card for an item the tree does not walk any further.
 * - Item icon + linked readable name.
 * - No station, no branch, no children, and no badge: a card with nothing under
 *   it already says the branch ends, so labelling it as well was noise on every
 *   leaf of every tree.
 */
export function renderLeafCard(itemId: string, ctx: RenderContext): HTMLElement {
  const cardEl = document.createElement("div");
  cardEl.className = "station-card station-leaf";
  cardEl.tabIndex = 0;
  cardEl.setAttribute("role", "button");

  const entry = ctx.lookup(itemId);
  const displayName = entry?.n ?? potionName(itemId) ?? humaniseId(itemId);

  const bodyEl = document.createElement("div");
  bodyEl.className = "station-body leaf-body";

  const iconKey = entry?.i ?? potionIconKey(itemId);
  if (iconKey) {
    const icon = createIconElement(iconKey, { size: 18 });
    bodyEl.append(icon);
  }

  const nameEl = document.createElement("span");
  nameEl.className = "leaf-name";
  nameEl.textContent = displayName;
  bodyEl.append(nameEl);

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
