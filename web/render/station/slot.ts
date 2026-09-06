import type { RenderContext } from "../context.js";
import { createIconElement } from "../icon.js";
import type { TreeInput } from "../obtain-tree.js";
import { potionIconKey, potionName } from "./potion-icon.js";
import { subscribeTicker } from "./ticker.js";

/**
 * Formats a Minecraft tag id into plain readable Title Case words without '#'.
 * E.g. '#minecraft:planks' -> 'Planks', '#iron_tool_materials' -> 'Iron Tool Materials'.
 */
export function humaniseTag(tag: string): string {
  const bare = tag.replace(/^#/, "").replace(/^[a-z0-9_-]+:/, "");
  return bare
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function humaniseId(id: string): string {
  const bare = id.replace(/^[a-z0-9_-]+:/, "");
  return bare
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export interface SlotOptions {
  count?: number;
  role?: string;
  isResult?: boolean;
}

/**
 * Renders a single workstation GUI slot.
 * - Empty slots render as '.station-slot.is-empty'.
 * - Item slots render an entity icon, count badge, and handle navigation via ctx.openRef.
 * - Tag or multi-member slots cycle through members using the shared ticker.
 * - Items without an icon sprite fall back to readable text rather than an empty box.
 */
export function renderSlot(
  target: TreeInput | string | null,
  ctx: RenderContext,
  options: SlotOptions = {},
): HTMLElement {
  const slotEl = document.createElement("div");
  slotEl.className = "station-slot";
  if (options.isResult) {
    slotEl.classList.add("slot-result");
  }
  if (options.role) {
    slotEl.dataset["slotRole"] = options.role;
  }

  if (target === null) {
    slotEl.classList.add("is-empty");
    return slotEl;
  }

  const isInputObj = typeof target !== "string";
  const itemId = isInputObj ? target.item : target;
  const tag = isInputObj ? target.tag : null;
  const members = isInputObj ? target.members : [];
  const count = options.count ?? (isInputObj ? target.count : 1);

  // If we have a tag with members, or untagged alternatives list:
  const candidateItems = members.length > 0 ? members : itemId ? [itemId] : [];
  const tagLabel = tag ? humaniseTag(tag) : null;

  let currentItemIndex = 0;

  const contentContainer = document.createElement("div");
  contentContainer.className = "slot-content";
  slotEl.append(contentContainer);

  const updateItemDisplay = (item: string): void => {
    contentContainer.replaceChildren();
    const entry = ctx.lookup(item);
    // A brewed potion is in the index by name but carries no icon: the atlas has
    // no frame for `minecraft:potion/regeneration`. So the fallback keys off the
    // missing icon, not a missing entry, and the index's own name still wins.
    const displayName = entry?.n ?? potionName(item) ?? humaniseId(item);
    const iconKey = entry?.i ?? potionIconKey(item);

    if (iconKey) {
      const icon = createIconElement(iconKey, { size: 16 });
      contentContainer.append(icon);
    } else {
      // Fallback for items with no sprite in the atlas
      const textFallback = document.createElement("span");
      textFallback.className = "slot-fallback-text";
      textFallback.textContent = displayName;
      contentContainer.append(textFallback);
    }

    if (tagLabel) {
      const affordance = candidateItems.length > 1 ? ` (${candidateItems.length.toString()})` : "";
      slotEl.title = `${tagLabel}${affordance}: ${displayName}`;
    } else {
      slotEl.title = displayName;
    }
  };

  if (candidateItems.length > 0) {
    const initialItem = candidateItems[0];
    if (initialItem) {
      updateItemDisplay(initialItem);
    }

    // Subscribe to cycling if there are multiple candidate items
    if (candidateItems.length > 1) {
      slotEl.classList.add("is-cycling");
      subscribeTicker((tick) => {
        currentItemIndex = tick % candidateItems.length;
        const currentItem = candidateItems[currentItemIndex];
        if (currentItem) {
          updateItemDisplay(currentItem);
        }
      });
    }

    slotEl.tabIndex = 0;
    slotEl.setAttribute("role", "button");

    const openCurrent = (e: Event): void => {
      e.preventDefault();
      const currentItem = candidateItems[currentItemIndex] ?? candidateItems[0];
      if (currentItem) {
        ctx.openRef(currentItem);
      }
    };

    slotEl.addEventListener("click", openCurrent);
    slotEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        openCurrent(e);
      }
    });
  } else if (tagLabel) {
    // Tag with no resolved members
    const textFallback = document.createElement("span");
    textFallback.className = "slot-fallback-text";
    textFallback.textContent = tagLabel;
    contentContainer.append(textFallback);
    slotEl.title = tagLabel;
  }

  // Count badge
  if (count > 1) {
    const countBadge = document.createElement("span");
    countBadge.className = "slot-count";
    countBadge.textContent = count.toString();
    slotEl.append(countBadge);
  }

  return slotEl;
}
