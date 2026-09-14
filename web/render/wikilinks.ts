import type { RenderContext } from "./context.js";
import { createIconElement } from "./icon.js";

/**
 * Matches one `[[Target|Label]]` or `[[Label]]` wikilink.
 *
 * The pipeline keeps this markup in prose that names another entity, rather
 * than flattening it to plain text, so a renderer can turn it into a real link.
 * Decision 13: a name printed as plain text is a dead end where a jump should be.
 */
const WIKI_LINK_PATTERN = /\[\[(?:([^|\]]+)\|)?([^\]]+)\]\]/g;

/**
 * Resolves a wiki link target (e.g. "Parrot", "Sculk Sensor") to an IndexEntry.
 *
 * Tries the display name first, then the registry ID the name implies. A target
 * that resolves to neither is not an error: the wiki links plenty of pages this
 * build holds no entity for ("walking", "difficulty"), and those stay plain text.
 */
function resolveWikiLink(target: string, ctx: RenderContext) {
  const direct = ctx.lookup(target);
  if (direct) {
    return direct;
  }
  const namespaced = `minecraft:${target.toLowerCase().replace(/\s+/g, "_")}`;
  return ctx.lookup(namespaced);
}

function createEntityLink(
  id: string,
  icon: string | undefined,
  label: string,
  ctx: RenderContext,
  rarity?: string,
) {
  const link = document.createElement("a");
  link.href = "#";
  // `entity-link-prose` drops the chip padding that the standalone form carries.
  // Inside a sentence that padding reads as a space, so `[[parrot]]s` came out
  // as "parrot s" and `[[Bogged]].` as "Bogged ."
  link.className = "entity-link entity-link-prose";
  link.setAttribute("role", "button");
  link.dataset["id"] = id;

  link.append(createIconElement(icon));

  const labelSpan = document.createElement("span");
  labelSpan.className = "entity-name";
  if (rarity) {
    labelSpan.classList.add(`rarity-${rarity}`);
  }
  labelSpan.textContent = label;
  link.append(labelSpan);

  link.addEventListener("click", (e) => {
    e.preventDefault();
    ctx.openRef(id);
  });

  link.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      ctx.openRef(id);
    }
  });

  return link;
}

/**
 * Appends `rawText` to `host`, turning every `[[Target|Label]]` it holds into a
 * real entity link where the target resolves, and into plain text where it does not.
 *
 * Shared by every section whose prose carries wikilinks, so the parsing rule
 * lives in one place rather than once per renderer.
 */
export function appendWikiText(host: HTMLElement, rawText: string, ctx: RenderContext): void {
  WIKI_LINK_PATTERN.lastIndex = 0;

  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = WIKI_LINK_PATTERN.exec(rawText)) !== null) {
    if (match.index > lastIndex) {
      host.append(document.createTextNode(rawText.slice(lastIndex, match.index)));
    }

    const rawLabel = match[2] ?? "";
    const target = match[1] ? match[1].trim() : rawLabel.trim();
    const label = rawLabel.trim();

    const entry = resolveWikiLink(target, ctx);
    if (entry) {
      host.append(createEntityLink(entry.id, entry.i, label, ctx, entry.r));
    } else {
      host.append(document.createTextNode(label));
    }

    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < rawText.length) {
    host.append(document.createTextNode(rawText.slice(lastIndex)));
  }
}
