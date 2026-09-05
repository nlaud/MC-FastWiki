import { MAX_WINDOWS } from "./state.js";

export interface SearchBarCallbacks {
  onInput: (value: string) => void;
  onClear?: () => void;
}

export interface SearchBarElements {
  container: HTMLElement;
  wrapper: HTMLElement;
  suggestionsContainer: HTMLElement;
  input: HTMLInputElement;
  hint: HTMLElement;
}

export function createSearchBar(callbacks: SearchBarCallbacks): SearchBarElements {
  const container = document.createElement("div");
  container.className = "search-bar-container";

  const suggestionsContainer = document.createElement("div");
  suggestionsContainer.className = "search-suggestions-container";
  suggestionsContainer.style.display = "none";

  const barWrapper = document.createElement("div");
  barWrapper.className = "search-input-wrapper";

  const input = document.createElement("input");
  input.type = "text";
  input.className = "search-input";
  input.placeholder = "Search Minecraft Java...";
  input.setAttribute("aria-label", "Search Minecraft Java");
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-expanded", "false");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-controls", "suggestions-list");

  input.addEventListener("input", () => {
    callbacks.onInput(input.value);
  });

  barWrapper.append(input);

  const hint = document.createElement("div");
  hint.className = "search-max-hint";
  hint.textContent = `Maximum ${MAX_WINDOWS.toString()} windows open. Press Alt+W to close active window, or F1 for help.`;
  hint.style.display = "none";

  container.append(suggestionsContainer, barWrapper, hint);

  return {
    container,
    wrapper: barWrapper,
    suggestionsContainer,
    input,
    hint,
  };
}

export function updateSearchBarVisibility(elements: SearchBarElements, windowCount: number): void {
  if (windowCount >= MAX_WINDOWS) {
    elements.wrapper.style.display = "none";
    elements.suggestionsContainer.style.display = "none";
    elements.hint.style.display = "block";
  } else {
    elements.wrapper.style.display = "block";
    elements.hint.style.display = "none";
  }
}
