import type { RenderContext } from "../context.js";
import { createIconElement } from "../icon.js";
import { entityLink } from "../link.js";
import type { TreeInput } from "../obtain-tree.js";
import { potionIconKey, potionName } from "../potion-icon.js";
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

/**
 * Title Cases a registry id for display: `minecraft:lava_bucket` -> `Lava Bucket`.
 *
 * Exported because three station modules needed the same fallback name and each
 * had grown its own byte-identical copy.
 */
export function humaniseId(id: string): string {
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
 * Opens a modal dialog listing all candidate items for a multi-member slot.
 * Every member is rendered as an entity link allowing the user to view or navigate to it.
 */
export function openSlotMemberList(
  title: string,
  items: string[],
  ctx: RenderContext,
  returnFocusEl?: HTMLElement,
): HTMLElement {
  const backdrop = document.createElement("div");
  backdrop.className = "slot-list-backdrop";
  backdrop.setAttribute("role", "dialog");
  backdrop.setAttribute("aria-modal", "true");
  backdrop.setAttribute("aria-label", title);

  const panel = document.createElement("div");
  panel.className = "slot-list-panel";

  const header = document.createElement("div");
  header.className = "slot-list-header";

  const h2 = document.createElement("h2");
  h2.className = "slot-list-title";
  h2.textContent = title;

  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "slot-list-close-btn";
  closeBtn.setAttribute("aria-label", "Close alternatives list");
  closeBtn.textContent = "×";

  const close = (): void => {
    backdrop.remove();
    document.removeEventListener("keydown", onKeyDown);
    if (returnFocusEl && typeof returnFocusEl.focus === "function") {
      returnFocusEl.focus();
    }
  };

  const onKeyDown = (e: KeyboardEvent): void => {
    if (e.key === "Escape") {
      e.stopPropagation();
      close();
    }
  };

  closeBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    close();
  });

  header.append(h2, closeBtn);

  const content = document.createElement("div");
  content.className = "slot-list-content";

  for (const item of items) {
    const entry = ctx.lookup(item);
    const displayName = entry?.n ?? potionName(item) ?? humaniseId(item);
    const link = entityLink({ id: item, name: displayName }, ctx);
    link.addEventListener("click", () => {
      close();
    });
    link.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        close();
      }
    });
    content.append(link);
  }

  panel.append(header, content);
  backdrop.append(panel);

  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) {
      close();
    }
  });

  document.addEventListener("keydown", onKeyDown);
  document.body.append(backdrop);
  if (typeof closeBtn.focus === "function") {
    closeBtn.focus();
  }

  return backdrop;
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
      const icon = createIconElement(iconKey, { size: 32, allowUpscale: true });
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
      const affordance = candidateItems.length > 1 ? ` (${candidateItems.length.toString()})` : "";
      slotEl.title = `${displayName}${affordance}`;
    }
    slotEl.setAttribute("aria-label", slotEl.title);
  };

  if (candidateItems.length > 0) {
    const initialItem = candidateItems[0];
    if (initialItem) {
      updateItemDisplay(initialItem);
    }

    const step = (delta: number): void => {
      currentItemIndex = (currentItemIndex + delta + candidateItems.length) % candidateItems.length;
      const currentItem = candidateItems[currentItemIndex];
      if (currentItem) {
        updateItemDisplay(currentItem);
      }
    };

    // Subscribe to cycling if there are multiple candidate items
    if (candidateItems.length > 1) {
      slotEl.classList.add("is-cycling");
      slotEl.setAttribute("aria-haspopup", "dialog");
      subscribeTicker((tick) => {
        currentItemIndex = tick % candidateItems.length;
        const currentItem = candidateItems[currentItemIndex];
        if (currentItem) {
          updateItemDisplay(currentItem);
        }
      });

      // Visible next control for mouse users to step forward through alternatives
      const nextBtn = document.createElement("button");
      nextBtn.type = "button";
      nextBtn.className = "slot-step-next";
      nextBtn.setAttribute("aria-label", "Next alternative");
      nextBtn.textContent = "›";
      nextBtn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        step(1);
      });
      slotEl.append(nextBtn);
    }

    slotEl.tabIndex = 0;
    slotEl.setAttribute("role", "button");

    const modalTitle = tagLabel
      ? `${tagLabel} (${candidateItems.length.toString()})`
      : `Alternatives (${candidateItems.length.toString()})`;

    const activateSlot = (e: Event): void => {
      e.preventDefault();
      if (candidateItems.length > 1) {
        openSlotMemberList(modalTitle, candidateItems, ctx, slotEl);
      } else {
        const currentItem = candidateItems[0];
        if (currentItem) {
          ctx.openRef(currentItem);
        }
      }
    };

    slotEl.addEventListener("click", activateSlot);
    slotEl.addEventListener("keydown", (e) => {
      if (candidateItems.length > 1) {
        if (e.key === "ArrowLeft") {
          e.preventDefault();
          e.stopPropagation();
          step(-1);
          return;
        }
        if (e.key === "ArrowRight") {
          e.preventDefault();
          e.stopPropagation();
          step(1);
          return;
        }
      }
      if (e.key === "Enter" || e.key === " ") {
        activateSlot(e);
      }
    });
  } else if (tagLabel) {
    // Tag with no resolved members
    const textFallback = document.createElement("span");
    textFallback.className = "slot-fallback-text";
    textFallback.textContent = tagLabel;
    contentContainer.append(textFallback);
    slotEl.title = tagLabel;
    slotEl.setAttribute("aria-label", tagLabel);
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
