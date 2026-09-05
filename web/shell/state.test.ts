import { describe, expect, it } from "vitest";

import type { IndexEntry } from "../types/index.js";
import {
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

const makeEntry = (id: string, name: string): IndexEntry => ({
  id,
  n: name,
  k: "mob",
  a: [],
  s: "mob-0",
});

describe("state", () => {
  it("initializes with empty state and bar visible", () => {
    const s = createInitialState();
    expect(s.query).toBe("");
    expect(s.results).toEqual([]);
    expect(s.selectedIndex).toBe(-1);
    expect(s.windows).toEqual([]);
    expect(s.focusOrder).toEqual([]);
    expect(s.isHelpOpen).toBe(false);
    expect(isBarVisible(s)).toBe(true);
    expect(getFocusedSlot(s)).toBeNull();
  });

  describe("query and selection", () => {
    it("selects first result by default on new result set", () => {
      const e1 = makeEntry("minecraft:creeper", "Creeper");
      const e2 = makeEntry("minecraft:zombie", "Zombie");
      const s = setQuery(createInitialState(), "cr", [e1, e2]);

      expect(s.query).toBe("cr");
      expect(s.results).toHaveLength(2);
      expect(s.selectedIndex).toBe(0);
      expect(getSelectedResult(s)).toBe(e1);
    });

    it("sets selectedIndex to -1 when result set is empty", () => {
      const s = setQuery(createInitialState(), "unknown", []);
      expect(s.selectedIndex).toBe(-1);
      expect(getSelectedResult(s)).toBeNull();
    });

    it("wraps selection at both ends", () => {
      const e1 = makeEntry("1", "One");
      const e2 = makeEntry("2", "Two");
      const e3 = makeEntry("3", "Three");
      let s = setQuery(createInitialState(), "num", [e1, e2, e3]);
      expect(s.selectedIndex).toBe(0);

      // Wrap backward from 0 -> 2 (last)
      s = moveSelection(s, -1);
      expect(s.selectedIndex).toBe(2);

      // Wrap forward from 2 -> 0 (first)
      s = moveSelection(s, 1);
      expect(s.selectedIndex).toBe(0);

      // Move forward 0 -> 1
      s = moveSelection(s, 1);
      expect(s.selectedIndex).toBe(1);
    });

    it("clears query and resets selection", () => {
      const e1 = makeEntry("1", "One");
      let s = setQuery(createInitialState(), "1", [e1]);
      s = clearQuery(s);
      expect(s.query).toBe("");
      expect(s.results).toEqual([]);
      expect(s.selectedIndex).toBe(-1);
    });
  });

  describe("windows, slots, and eviction order", () => {
    const e1 = makeEntry("1", "One");
    const e2 = makeEntry("2", "Two");
    const e3 = makeEntry("3", "Three");
    const e4 = makeEntry("4", "Four");
    const e5 = makeEntry("5", "Five");
    const e6 = makeEntry("6", "Six");
    const e7 = makeEntry("7", "Seven");
    const e8 = makeEntry("8", "Eight");
    const e9 = makeEntry("9", "Nine");

    it("assigns lowest free slot as windows open and updates focusOrder", () => {
      let s = createInitialState();
      s = openWindow(s, e1);
      expect(s.windows).toHaveLength(1);
      expect(s.windows[0]?.slot).toBe(0);
      expect(s.focusOrder).toEqual([0]);
      expect(isBarVisible(s)).toBe(true);

      s = openWindow(s, e2);
      expect(s.windows).toHaveLength(2);
      expect(s.windows[1]?.slot).toBe(1);
      expect(s.focusOrder).toEqual([1, 0]);

      s = openWindow(s, e3);
      s = openWindow(s, e4);
      s = openWindow(s, e5);
      s = openWindow(s, e6);
      s = openWindow(s, e7);
      expect(s.windows).toHaveLength(7);
      expect(isBarVisible(s)).toBe(true);

      s = openWindow(s, e8);
      expect(s.windows).toHaveLength(8);
      expect(s.windows[7]?.slot).toBe(7);
      expect(s.focusOrder).toEqual([7, 6, 5, 4, 3, 2, 1, 0]);
      expect(isBarVisible(s)).toBe(false); // Hidden at exactly 8
    });

    it("reuses lowest free slot after an inner slot is closed", () => {
      let s = createInitialState();
      s = openWindow(s, e1); // slot 0
      s = openWindow(s, e2); // slot 1
      s = openWindow(s, e3); // slot 2

      // Close slot 1
      s = closeWindow(s, 1);
      expect(s.windows.map((w) => w.slot)).toEqual([0, 2]);
      expect(s.focusOrder).toEqual([2, 0]);

      // Open new window -> lowest free slot is 1
      s = openWindow(s, e4);
      expect(s.windows.map((w) => w.slot)).toEqual([0, 2, 1]);
      expect(s.focusOrder).toEqual([1, 2, 0]);
    });

    it("evicts the least-recently-focused slot when opening at eight windows (D2)", () => {
      let s = createInitialState();
      s = openWindow(s, e1);
      s = openWindow(s, e2);
      s = openWindow(s, e3);
      s = openWindow(s, e4);
      s = openWindow(s, e5);
      s = openWindow(s, e6);
      s = openWindow(s, e7);
      s = openWindow(s, e8);

      // Focus sequence: focus slot 0, then focus slot 2
      s = focusWindow(s, 0);
      s = focusWindow(s, 2);

      expect(s.focusOrder[0]).toBe(2);
      expect(s.focusOrder[1]).toBe(0);
      const leastRecentlyFocused = s.focusOrder[s.focusOrder.length - 1];
      expect(leastRecentlyFocused).toBe(1);

      // Opening a 9th window must evict slot 1 and place it at the front.
      s = openWindow(s, e9);
      expect(s.windows).toHaveLength(8);
      const replacedWindow = s.windows.find((w) => w.slot === 1);
      expect(replacedWindow?.entry).toBe(e9);
      expect(s.focusOrder[0]).toBe(1);
    });

    it("restores bar visibility when closing from 8 to 7 windows", () => {
      let s = createInitialState();
      s = openWindow(s, e1);
      s = openWindow(s, e2);
      s = openWindow(s, e3);
      s = openWindow(s, e4);
      s = openWindow(s, e5);
      s = openWindow(s, e6);
      s = openWindow(s, e7);
      s = openWindow(s, e8);
      expect(isBarVisible(s)).toBe(false);

      s = closeWindow(s, 7);
      expect(isBarVisible(s)).toBe(true);
      expect(s.windows).toHaveLength(7);
    });

    it("focusNextWindow cycles occupied slots in ascending order", () => {
      let s = createInitialState();
      s = openWindow(s, e1); // slot 0
      s = openWindow(s, e2); // slot 1
      s = openWindow(s, e3); // slot 2
      // slots are [0, 1, 2], current focused is 2
      expect(getFocusedSlot(s)).toBe(2);

      s = focusNextWindow(s);
      expect(getFocusedSlot(s)).toBe(0);

      s = focusNextWindow(s);
      expect(getFocusedSlot(s)).toBe(1);

      s = focusNextWindow(s);
      expect(getFocusedSlot(s)).toBe(2);
    });
  });

  describe("help overlay", () => {
    it("toggles and closes help overlay state", () => {
      let s = createInitialState();
      expect(s.isHelpOpen).toBe(false);

      s = toggleHelp(s);
      expect(s.isHelpOpen).toBe(true);

      s = toggleHelp(s);
      expect(s.isHelpOpen).toBe(false);

      s = toggleHelp(s);
      expect(s.isHelpOpen).toBe(true);

      s = closeHelp(s);
      expect(s.isHelpOpen).toBe(false);
    });
  });
});
