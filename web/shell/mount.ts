import type { RenderContext } from "../render/context.js";
import { loadIndex } from "../search/load.js";
import { type Corpus, buildCorpus, search } from "../search/matcher.js";
import type { IndexEntry } from "../types/index.js";
import { createHelpOverlay } from "./help.js";
import { dispatchKey } from "./keymap.js";
import { createSearchBar, updateSearchBarVisibility } from "./searchbar.js";
import {
  MAX_WINDOWS,
  clearQuery,
  closeHelp,
  closeWindow,
  createInitialState,
  focusNextWindow,
  focusWindow,
  getFocusedSlot,
  getSelectedResult,
  isBarVisible,
  moveSelection,
  openWindow,
  setQuery,
  toggleHelp,
} from "./state.js";
import { renderSuggestions } from "./suggestions.js";
import { type WindowView, createWindowElement, syncWindowsLayout } from "./windows.js";

/**
 * Mounts the MC-FastWiki application shell into the given root container.
 */
export function mount(root: HTMLElement, corpusSource?: Promise<Corpus> | Corpus): void {
  let state = createInitialState();
  const windowsMap = new Map<number, WindowView>();

  const windowsContainer = document.createElement("div");
  windowsContainer.className = "windows-container";
  windowsContainer.id = "windows-root";

  const searchContainer = document.createElement("div");
  searchContainer.className = "search-container";
  searchContainer.id = "search-root";

  const helpContainer = document.createElement("div");
  helpContainer.className = "help-container";
  helpContainer.id = "help-root";

  root.replaceChildren(windowsContainer, searchContainer, helpContainer);

  let activeCorpus: Corpus | null =
    corpusSource !== undefined && !(corpusSource instanceof Promise) ? corpusSource : null;

  const corpusPromise: Promise<Corpus> =
    corpusSource instanceof Promise
      ? corpusSource
      : corpusSource !== undefined
        ? Promise.resolve(corpusSource)
        : loadIndex().then(buildCorpus);

  const entryById = new Map<string, IndexEntry>();
  const entryByName = new Map<string, IndexEntry>();

  const populateIndex = (corpus: Corpus): void => {
    for (const entry of corpus.entities) {
      entryById.set(entry.id, entry);
      if (!entryByName.has(entry.n.toLowerCase())) {
        entryByName.set(entry.n.toLowerCase(), entry);
      }
    }
  };

  if (activeCorpus !== null) {
    populateIndex(activeCorpus);
  } else {
    void corpusPromise.then((corpus) => {
      activeCorpus = corpus;
      populateIndex(corpus);
    });
  }

  const renderContext: RenderContext = {
    openRef: (id: string) => {
      const entry = renderContext.lookup(id);
      if (entry) {
        openEntryInWindow(entry);
      }
    },
    lookup: (id: string) => {
      return (
        entryById.get(id) ??
        entryByName.get(id.toLowerCase()) ??
        entryById.get(`minecraft:${id.toLowerCase().replace(/\s+/g, "_")}`) ??
        null
      );
    },
  };

  const performSearch = (query: string): void => {
    if (!activeCorpus) {
      void corpusPromise.then((corpus) => {
        activeCorpus = corpus;
        performSearch(query);
      });
      return;
    }

    if (query.trim() === "") {
      state = clearQuery(state);
      updateSuggestionsUI();
      return;
    }

    const results = search(activeCorpus, query, 10);
    state = setQuery(state, query, results);
    updateSuggestionsUI();
  };

  const updateSuggestionsUI = (): void => {
    renderSuggestions(searchBar.suggestionsContainer, {
      results: state.results,
      selectedIndex: state.selectedIndex,
      onSelect: (entry) => {
        openEntryInWindow(entry);
      },
    });

    const hasResults = state.results.length > 0;
    searchBar.input.setAttribute("aria-expanded", hasResults ? "true" : "false");

    const selected = getSelectedResult(state);
    if (selected) {
      searchBar.input.setAttribute("aria-activedescendant", `suggestion-${selected.id}`);
    } else {
      searchBar.input.removeAttribute("aria-activedescendant");
    }
  };

  const syncLayout = (): void => {
    syncWindowsLayout(windowsContainer, windowsMap, getFocusedSlot(state));
    updateSearchBarVisibility(searchBar, state.windows.length);
  };

  const openEntryInWindow = (entry: IndexEntry): void => {
    state = openWindow(state, entry);

    const focusedSlot = getFocusedSlot(state);
    if (focusedSlot === null) {
      return;
    }

    // If slot was already occupied, remove previous view from DOM
    const existing = windowsMap.get(focusedSlot);
    if (existing) {
      existing.element.remove();
    }

    const currentWindowState = state.windows.find((w) => w.slot === focusedSlot);
    if (!currentWindowState) {
      return;
    }
    const view = createWindowElement(
      currentWindowState,
      {
        onClose: (slot) => {
          closeWindowAtSlot(slot);
        },
        onFocus: (slot) => {
          state = focusWindow(state, slot);
          syncLayout();
        },
      },
      renderContext,
    );

    windowsMap.set(focusedSlot, view);
    windowsContainer.append(view.element);

    syncLayout();

    // Clear search query and hide suggestions
    state = clearQuery(state);
    searchBar.input.value = "";
    updateSuggestionsUI();

    // If bar is still visible, refocus input
    if (isBarVisible(state)) {
      searchBar.input.focus();
    }
  };

  // Tab and Alt+1..4 change which window is logically focused. Without this the
  // ring moved but DOM focus stayed on the search input, so each window's
  // tabIndex was dead weight and assistive technology was never told the focus
  // had moved. preventScroll keeps a focus change from scrolling the canvas.
  const moveDomFocusToFocusedWindow = (): void => {
    const focusedSlot = getFocusedSlot(state);
    if (focusedSlot === null) {
      return;
    }
    windowsMap.get(focusedSlot)?.element.focus({ preventScroll: true });
  };

  const closeWindowAtSlot = (slot: number): void => {
    const wasMax = state.windows.length === MAX_WINDOWS;
    state = closeWindow(state, slot);

    const view = windowsMap.get(slot);
    if (view) {
      view.element.remove();
      windowsMap.delete(slot);
    }

    syncLayout();

    // If closed from MAX_WINDOWS to MAX_WINDOWS - 1, restore focus to search bar
    if (wasMax && isBarVisible(state)) {
      searchBar.input.focus();
    }
  };

  const updateHelpUI = (): void => {
    helpContainer.replaceChildren();
    if (state.isHelpOpen) {
      const overlay = createHelpOverlay(() => {
        state = closeHelp(state);
        updateHelpUI();
      });
      helpContainer.append(overlay);
    }
  };

  const searchBar = createSearchBar({
    onInput: (value) => {
      performSearch(value);
    },
  });

  searchContainer.append(searchBar.container);

  // Autofocus search bar on initial mount
  searchBar.input.focus();

  // Mouseup refocus rule (Guard 1):
  // Refocus on mouseup only when the resulting selection is collapsed
  // and the target is not a link, button, or input.
  document.addEventListener("mouseup", (e) => {
    const selection = window.getSelection();
    if (selection && !selection.isCollapsed) {
      return;
    }

    const target = e.target;
    if (target instanceof Element && target.closest("a, button, input, textarea, select")) {
      return;
    }

    if (isBarVisible(state)) {
      searchBar.input.focus();
    }
  });

  // Global keydown dispatcher
  window.addEventListener("keydown", (e) => {
    const isInputFocused = document.activeElement === searchBar.input;
    const action = dispatchKey(e, {
      isHelpOpen: state.isHelpOpen,
      barVisible: isBarVisible(state),
      isInputFocused,
      hasSuggestions: state.results.length > 0,
      hasOpenWindows: state.windows.length > 0,
      occupiedSlots: state.windows.map((w) => w.slot),
    });

    if (!action) {
      return;
    }

    switch (action.type) {
      case "TOGGLE_HELP": {
        e.preventDefault();
        state = toggleHelp(state);
        updateHelpUI();
        break;
      }
      case "DISMISS_HELP": {
        e.preventDefault();
        state = closeHelp(state);
        updateHelpUI();
        if (isBarVisible(state)) {
          searchBar.input.focus();
        }
        break;
      }
      case "CLEAR_QUERY": {
        e.preventDefault();
        state = clearQuery(state);
        searchBar.input.value = "";
        updateSuggestionsUI();
        break;
      }
      case "MOVE_SELECTION": {
        e.preventDefault();
        state = moveSelection(state, action.delta);
        updateSuggestionsUI();
        break;
      }
      case "SCROLL_WINDOW": {
        e.preventDefault();
        const focusedSlot = getFocusedSlot(state);
        if (focusedSlot !== null) {
          const view = windowsMap.get(focusedSlot);
          if (view) {
            if (typeof view.bodyElement.scrollBy === "function") {
              view.bodyElement.scrollBy({
                top: action.delta * 40,
                behavior: "smooth",
              });
            } else {
              view.bodyElement.scrollTop += action.delta * 40;
            }
          }
        }
        break;
      }
      case "PAGE_SCROLL_WINDOW": {
        e.preventDefault();
        const focusedSlot = getFocusedSlot(state);
        if (focusedSlot !== null) {
          const view = windowsMap.get(focusedSlot);
          if (view) {
            const pageAmount = view.bodyElement.clientHeight || 400;
            if (typeof view.bodyElement.scrollBy === "function") {
              view.bodyElement.scrollBy({
                top: action.delta * pageAmount,
                behavior: "smooth",
              });
            } else {
              view.bodyElement.scrollTop += action.delta * pageAmount;
            }
          }
        }
        break;
      }
      case "OPEN_SELECTED": {
        e.preventDefault();
        const selected = getSelectedResult(state);
        if (selected) {
          openEntryInWindow(selected);
        }
        break;
      }
      case "CLOSE_FOCUSED_WINDOW": {
        e.preventDefault();
        const focusedSlot = getFocusedSlot(state);
        if (focusedSlot !== null) {
          closeWindowAtSlot(focusedSlot);
        }
        break;
      }
      case "FOCUS_SLOT": {
        e.preventDefault();
        state = focusWindow(state, action.slot);
        syncLayout();
        moveDomFocusToFocusedWindow();
        break;
      }
      case "FOCUS_NEXT_WINDOW": {
        e.preventDefault();
        state = focusNextWindow(state);
        syncLayout();
        moveDomFocusToFocusedWindow();
        break;
      }
      case "FOCUS_INPUT": {
        // preventDefault matters here. Focus moves to the input during this
        // keydown, so without it the browser also performs the keystroke's own
        // insertion against the newly focused field and every character typed
        // from an unfocused bar arrives twice ("d" becomes "dd").
        e.preventDefault();
        searchBar.input.focus();
        if (action.char) {
          searchBar.input.value += action.char;
          performSearch(searchBar.input.value);
        }
        break;
      }
    }
  });
}
