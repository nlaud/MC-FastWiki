import type { IndexEntry } from "../types/index.js";

export interface WindowState {
  slot: number;
  entry: IndexEntry;
}

export interface ShellState {
  query: string;
  results: IndexEntry[];
  selectedIndex: number;
  windows: WindowState[];
  focusOrder: number[];
  isHelpOpen: boolean;
}

export function createInitialState(): ShellState {
  return {
    query: "",
    results: [],
    selectedIndex: -1,
    windows: [],
    focusOrder: [],
    isHelpOpen: false,
  };
}

export function setQuery(state: ShellState, query: string, results: IndexEntry[]): ShellState {
  return {
    ...state,
    query,
    results,
    selectedIndex: results.length > 0 ? 0 : -1,
  };
}

export function moveSelection(state: ShellState, delta: 1 | -1): ShellState {
  if (state.results.length === 0) {
    return { ...state, selectedIndex: -1 };
  }

  const count = state.results.length;
  const current = state.selectedIndex < 0 ? 0 : state.selectedIndex;
  const next = (current + delta + count) % count;

  return {
    ...state,
    selectedIndex: next,
  };
}

export function clearQuery(state: ShellState): ShellState {
  return {
    ...state,
    query: "",
    results: [],
    selectedIndex: -1,
  };
}

export const MAX_WINDOWS = 8;

export function getLowestFreeSlot(occupiedSlots: number[]): number | null {
  for (let slot = 0; slot < MAX_WINDOWS; slot++) {
    if (!occupiedSlots.includes(slot)) {
      return slot;
    }
  }
  return null;
}

export function openWindow(state: ShellState, entry: IndexEntry): ShellState {
  const occupied = state.windows.map((w) => w.slot);

  if (occupied.length < MAX_WINDOWS) {
    const slot = getLowestFreeSlot(occupied);
    if (slot === null) {
      return state;
    }
    const newWindow: WindowState = { slot, entry };
    return {
      ...state,
      query: "",
      results: [],
      selectedIndex: -1,
      windows: [...state.windows, newWindow],
      focusOrder: [slot, ...state.focusOrder.filter((s) => s !== slot)],
    };
  }

  // MAX_WINDOWS are open: evict the least-recently-focused slot (back of focusOrder).
  const evictedSlot = state.focusOrder[state.focusOrder.length - 1];
  if (evictedSlot === undefined) {
    return state;
  }
  const nextWindows = state.windows.map((w) =>
    w.slot === evictedSlot ? { slot: evictedSlot, entry } : w,
  );

  return {
    ...state,
    query: "",
    results: [],
    selectedIndex: -1,
    windows: nextWindows,
    focusOrder: [evictedSlot, ...state.focusOrder.filter((s) => s !== evictedSlot)],
  };
}

export function closeWindow(state: ShellState, slot: number): ShellState {
  const nextWindows = state.windows.filter((w) => w.slot !== slot);
  const nextFocusOrder = state.focusOrder.filter((s) => s !== slot);

  return {
    ...state,
    windows: nextWindows,
    focusOrder: nextFocusOrder,
  };
}

export function focusWindow(state: ShellState, slot: number): ShellState {
  if (!state.windows.some((w) => w.slot === slot)) {
    return state;
  }

  return {
    ...state,
    focusOrder: [slot, ...state.focusOrder.filter((s) => s !== slot)],
  };
}

export function focusNextWindow(state: ShellState): ShellState {
  if (state.windows.length === 0) {
    return state;
  }

  const occupiedSlots = state.windows.map((w) => w.slot).sort((a, b) => a - b);
  const currentSlot = state.focusOrder[0];
  const currentIndex = currentSlot !== undefined ? occupiedSlots.indexOf(currentSlot) : -1;

  const nextIndex = currentIndex === -1 ? 0 : (currentIndex + 1) % occupiedSlots.length;
  const nextSlot = occupiedSlots[nextIndex];
  if (nextSlot === undefined) {
    return state;
  }

  return focusWindow(state, nextSlot);
}

export function toggleHelp(state: ShellState): ShellState {
  return {
    ...state,
    isHelpOpen: !state.isHelpOpen,
  };
}

export function closeHelp(state: ShellState): ShellState {
  return {
    ...state,
    isHelpOpen: false,
  };
}

export function isBarVisible(state: ShellState): boolean {
  return state.windows.length < MAX_WINDOWS;
}

export function getFocusedSlot(state: ShellState): number | null {
  const slot = state.focusOrder[0];
  return slot !== undefined ? slot : null;
}

export function getSelectedResult(state: ShellState): IndexEntry | null {
  if (state.selectedIndex >= 0 && state.selectedIndex < state.results.length) {
    const entry = state.results[state.selectedIndex];
    return entry ?? null;
  }
  return null;
}
