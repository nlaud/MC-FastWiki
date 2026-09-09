import type { LinkList } from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { entityLink } from "../link.js";

/**
 * Renders a plain list of links to other entities (e.g. structures in a biome).
 */
export function renderLinkList(section: LinkList, ctx: RenderContext): HTMLElement | null {
  if (section.links.length === 0) {
    return null;
  }

  const container = document.createElement("section");
  container.className = "entity-section link-list-section";

  if (section.title) {
    const title = document.createElement("h3");
    title.className = "section-title";
    title.textContent = section.title;
    container.append(title);
  }

  const list = document.createElement("div");
  list.className = "link-list-items";

  for (const link of section.links) {
    list.append(entityLink(link, ctx));
  }

  container.append(list);
  return container;
}
