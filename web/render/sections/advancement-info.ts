import type { AdvancementInfo } from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { createIconElement } from "../icon.js";
import { entityLink } from "../link.js";

function cleanHtml(text: string): string {
  return text.replace(/<br\s*\/?>/gi, " ").replace(/<[^>]*>/g, "");
}

/**
 * Resolves a wiki link target (e.g. "Parrot", "Sculk Sensor") to an IndexEntry.
 */
function resolveWikiLink(target: string, ctx: RenderContext) {
  const direct = ctx.lookup(target);
  if (direct) {
    return direct;
  }
  const namespaced = `minecraft:${target.toLowerCase().replace(/\s+/g, "_")}`;
  return ctx.lookup(namespaced);
}

/**
 * Parses in-game description text, converting [[Target|Label]] into real entity links
 * where the target resolves in the index, and plain text otherwise.
 */
function renderParsedDescription(rawText: string, ctx: RenderContext): HTMLElement {
  const p = document.createElement("p");
  p.className = "advancement-description";

  const cleaned = cleanHtml(rawText);
  const WIKI_LINK_REGEX = /\[\[(?:([^|\]]+)\|)?([^\]]+)\]\]/g;

  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = WIKI_LINK_REGEX.exec(cleaned)) !== null) {
    // Text before the match
    if (match.index > lastIndex) {
      p.append(document.createTextNode(cleaned.slice(lastIndex, match.index)));
    }

    const rawLabel = match[2] ?? "";
    const target = match[1] ? match[1].trim() : rawLabel.trim();
    const label = rawLabel.trim();

    const entry = resolveWikiLink(target, ctx);
    if (entry) {
      const link = document.createElement("a");
      link.href = "#";
      link.className = "entity-link";
      link.setAttribute("role", "button");
      link.dataset["id"] = entry.id;

      const icon = createIconElement(entry.i);
      link.append(icon);

      const labelSpan = document.createElement("span");
      labelSpan.className = "entity-name";
      labelSpan.textContent = label;
      link.append(labelSpan);

      link.addEventListener("click", (e) => {
        e.preventDefault();
        ctx.openRef(entry.id);
      });

      link.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          ctx.openRef(entry.id);
        }
      });

      p.append(link);
    } else {
      p.append(document.createTextNode(label));
    }

    lastIndex = match.index + match[0].length;
  }

  // Trailing text
  if (lastIndex < cleaned.length) {
    p.append(document.createTextNode(cleaned.slice(lastIndex)));
  }

  return p;
}

/**
 * Renders an AdvancementInfo section:
 * - Title, parent chain as links, children as links, XP reward
 * - Renders gameDescription only, parsing [[Target|Label]] into real entity links
 * - Does not render description (per Decision 1)
 */
export function renderAdvancementInfo(
  section: AdvancementInfo,
  ctx: RenderContext,
): HTMLElement | null {
  const container = document.createElement("section");
  container.className = "entity-section advancement-info-section";

  // `title` is deliberately not rendered. It equals the entity name for all 126
  // advancements in the build, and the window header already shows that name,
  // so printing it here is the same word twice in a row.

  // Parent chain link
  if (section.parent) {
    const parentRow = document.createElement("div");
    parentRow.className = "advancement-row advancement-parent";

    const label = document.createElement("span");
    label.className = "advancement-field-label";
    label.textContent = "Parent:";
    parentRow.append(label, entityLink(section.parent, ctx));
    container.append(parentRow);
  }

  // Description (gameDescription only)
  if (section.gameDescription) {
    container.append(renderParsedDescription(section.gameDescription, ctx));
  }

  // XP / Reward
  if (section.experience) {
    const rewardRow = document.createElement("div");
    rewardRow.className = "advancement-row advancement-reward";

    const label = document.createElement("span");
    label.className = "advancement-field-label";
    label.textContent = "Reward:";

    const badge = document.createElement("span");
    badge.className = "stat-badge advancement-xp-badge";
    badge.textContent = `+${section.experience.toString()} XP`;

    rewardRow.append(label, badge);
    container.append(rewardRow);
  }

  // Children links
  if (section.children && section.children.length > 0) {
    const childrenRow = document.createElement("div");
    childrenRow.className = "advancement-row advancement-children";

    const label = document.createElement("span");
    label.className = "advancement-field-label";
    label.textContent = "Children:";
    childrenRow.append(label);

    const childrenList = document.createElement("div");
    childrenList.className = "advancement-children-list";
    for (const child of section.children) {
      childrenList.append(entityLink(child, ctx));
    }
    childrenRow.append(childrenList);
    container.append(childrenRow);
  }

  return container;
}
