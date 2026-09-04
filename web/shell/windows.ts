import { createIconElement, renderFallback } from "../render/fallback.js";
import { computeLayout } from "./layout.js";
import type { WindowState } from "./state.js";

export interface WindowCallbacks {
  onClose: (slot: number) => void;
  onFocus: (slot: number) => void;
}

export interface WindowView {
  element: HTMLElement;
  bodyElement: HTMLElement;
  slot: number;
}

export function createWindowElement(
  windowState: WindowState,
  callbacks: WindowCallbacks,
): WindowView {
  const el = document.createElement("article");
  el.className = "wiki-window";
  el.dataset["slot"] = windowState.slot.toString();
  el.tabIndex = 0;
  el.setAttribute(
    "aria-label",
    `${windowState.entry.n} (slot ${(windowState.slot + 1).toString()})`,
  );

  const header = document.createElement("header");
  header.className = "window-header";

  const headerLeft = document.createElement("div");
  headerLeft.className = "window-header-left";

  const icon = createIconElement(windowState.entry.i);
  const title = document.createElement("h2");
  title.className = "window-title";
  title.textContent = windowState.entry.n;

  headerLeft.append(icon, title);

  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "window-close-btn";
  closeBtn.setAttribute("aria-label", "Close window");
  closeBtn.textContent = "×";
  closeBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    callbacks.onClose(windowState.slot);
  });

  header.append(headerLeft, closeBtn);

  const body = document.createElement("div");
  body.className = "window-body";

  el.append(header, body);

  el.addEventListener("mousedown", () => {
    callbacks.onFocus(windowState.slot);
  });

  renderFallback(body, windowState.entry);

  return {
    element: el,
    bodyElement: body,
    slot: windowState.slot,
  };
}

export function syncWindowsLayout(
  container: HTMLElement,
  windows: Map<number, WindowView>,
  focusedSlot: number | null,
): void {
  const occupiedSlots = Array.from(windows.keys());
  const layout = computeLayout(occupiedSlots);

  container.style.gridTemplateColumns = `repeat(${layout.columns.toString()}, 1fr)`;
  container.style.gridTemplateRows = `repeat(${layout.rows.toString()}, 1fr)`;

  for (const [slot, view] of windows.entries()) {
    const cell = layout.slots[slot];
    if (cell) {
      view.element.style.gridColumn = cell.col.toString();
      view.element.style.gridRow = cell.row.toString();
    }
    if (slot === focusedSlot) {
      view.element.classList.add("is-focused");
    } else {
      view.element.classList.remove("is-focused");
    }
  }
}
