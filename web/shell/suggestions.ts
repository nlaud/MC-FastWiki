import { createIconElement } from "../render/icon.js";
import { entryIconKey } from "../render/entry-icon.js";
import type { IndexEntry } from "../types/index.js";

export interface SuggestionsProps {
  results: IndexEntry[];
  selectedIndex: number;
  onSelect: (entry: IndexEntry) => void;
}

export function renderSuggestions(container: HTMLElement, props: SuggestionsProps): void {
  container.replaceChildren();

  if (props.results.length === 0) {
    container.style.display = "none";
    return;
  }

  container.style.display = "flex";
  container.setAttribute("role", "listbox");
  container.id = "suggestions-list";

  for (const [index, entry] of props.results.entries()) {
    const isSelected = index === props.selectedIndex;

    const item = document.createElement("div");
    item.className = "suggestion-item";
    if (isSelected) {
      item.classList.add("is-selected");
    }
    item.setAttribute("role", "option");
    item.id = `suggestion-${entry.id}`;
    item.setAttribute("aria-selected", isSelected ? "true" : "false");

    const left = document.createElement("div");
    left.className = "suggestion-left";

    const icon = createIconElement(entryIconKey(entry));
    const name = document.createElement("span");
    name.className = "suggestion-name";
    name.textContent = entry.n;
    left.append(icon, name);

    const kind = document.createElement("span");
    kind.className = "suggestion-kind";
    kind.textContent = entry.k;

    item.append(left, kind);

    item.addEventListener("click", (e) => {
      e.stopPropagation();
      props.onSelect(entry);
    });

    container.append(item);

    // The list caps its height and scrolls, so a selection moved past the fold
    // with Up/Down would otherwise sit outside the visible box and Enter would
    // open an entity the user cannot see. `nearest` scrolls only when the item
    // is actually out of view, so it never fights a selection already visible.
    // Guarded because jsdom does not implement scrollIntoView.
    if (isSelected && typeof item.scrollIntoView === "function") {
      item.scrollIntoView({ block: "nearest" });
    }
  }
}
