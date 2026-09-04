export interface KeymapEntry {
  key: string;
  does: string;
  when: string;
}

export const KEYMAP: readonly KeymapEntry[] = [
  {
    key: "a-z, 0-9",
    does: "Focus the bar and insert the character",
    when: "Bar visible and unfocused, no modifier held",
  },
  {
    key: "Up / Down",
    does: "Move the suggestion selection, wrapping at both ends",
    when: "Suggestion list is non-empty",
  },
  {
    key: "Up / Down",
    does: "Scroll the focused window",
    when: "Suggestion list is empty",
  },
  {
    key: "Enter",
    does: "Open the selected suggestion in a window",
    when: "A suggestion is selected",
  },
  {
    key: "Esc",
    does: "Clear the query",
    when: "Always, and only this",
  },
  {
    key: "Alt+W",
    does: "Close the focused window",
    when: "A window is open",
  },
  {
    key: "Alt+1 to Alt+4",
    does: "Focus the window in that slot",
    when: "That slot is occupied",
  },
  {
    key: "Tab",
    does: "Focus the next window, wrapping",
    when: "A window is open",
  },
  {
    key: "F1",
    does: "Toggle the keyboard-map overlay",
    when: "Always",
  },
  {
    key: "Esc",
    does: "Dismiss the overlay",
    when: "Overlay is open",
  },
] as const;

export type KeyAction =
  | { type: "FOCUS_INPUT"; char?: string }
  | { type: "MOVE_SELECTION"; delta: 1 | -1 }
  | { type: "SCROLL_WINDOW"; delta: 1 | -1 }
  | { type: "OPEN_SELECTED" }
  | { type: "CLEAR_QUERY" }
  | { type: "CLOSE_FOCUSED_WINDOW" }
  | { type: "FOCUS_SLOT"; slot: number }
  | { type: "FOCUS_NEXT_WINDOW" }
  | { type: "TOGGLE_HELP" }
  | { type: "DISMISS_HELP" };

export interface KeyContext {
  isHelpOpen: boolean;
  barVisible: boolean;
  isInputFocused: boolean;
  hasSuggestions: boolean;
  hasOpenWindows: boolean;
  occupiedSlots: number[];
}

export interface MinimalKeyboardEvent {
  key: string;
  altKey?: boolean;
  ctrlKey?: boolean;
  metaKey?: boolean;
  shiftKey?: boolean;
  isComposing?: boolean;
}

export function dispatchKey(event: MinimalKeyboardEvent, context: KeyContext): KeyAction | null {
  // F1 always toggles help
  if (event.key === "F1") {
    return { type: "TOGGLE_HELP" };
  }

  // Esc closes overlay if open, otherwise clears query
  if (event.key === "Escape") {
    if (context.isHelpOpen) {
      return { type: "DISMISS_HELP" };
    }
    return { type: "CLEAR_QUERY" };
  }

  // If help overlay is open, block all other shortcuts
  if (context.isHelpOpen) {
    return null;
  }

  // Alt combinations
  if (event.altKey && !event.ctrlKey && !event.metaKey) {
    if (event.key === "w" || event.key === "W") {
      if (context.hasOpenWindows) {
        return { type: "CLOSE_FOCUSED_WINDOW" };
      }
      return null;
    }

    if (/^[1-4]$/.test(event.key)) {
      const slot = parseInt(event.key, 10) - 1;
      if (context.occupiedSlots.includes(slot)) {
        return { type: "FOCUS_SLOT", slot };
      }
      return null;
    }
  }

  // Don't intercept browser shortcuts or combinations with Ctrl/Meta/Alt
  if (event.ctrlKey || event.metaKey || event.altKey) {
    return null;
  }

  // Tab moves focus to next window
  if (event.key === "Tab") {
    if (context.hasOpenWindows) {
      return { type: "FOCUS_NEXT_WINDOW" };
    }
    return null;
  }

  // Enter opens selected suggestion
  if (event.key === "Enter") {
    if (context.hasSuggestions) {
      return { type: "OPEN_SELECTED" };
    }
    return null;
  }

  // Up and Down arrows
  if (event.key === "ArrowUp" || event.key === "ArrowDown") {
    const delta: 1 | -1 = event.key === "ArrowDown" ? 1 : -1;
    if (context.hasSuggestions) {
      return { type: "MOVE_SELECTION", delta };
    }
    if (context.hasOpenWindows) {
      return { type: "SCROLL_WINDOW", delta };
    }
    return null;
  }

  // Printable keys autofocus search bar if unfocused and visible
  if (
    context.barVisible &&
    !context.isInputFocused &&
    !event.isComposing &&
    event.key.length === 1
  ) {
    return { type: "FOCUS_INPUT", char: event.key };
  }

  return null;
}
