import { describe, expect, it } from "vitest";

import { KEYMAP, type KeyContext, dispatchKey } from "./keymap.js";

const defaultContext: KeyContext = {
  isHelpOpen: false,
  barVisible: true,
  isInputFocused: false,
  hasSuggestions: false,
  hasOpenWindows: false,
  occupiedSlots: [],
};

describe("keymap", () => {
  it("exports KEYMAP with all required entries", () => {
    expect(KEYMAP.length).toBeGreaterThanOrEqual(10);
    const keys = KEYMAP.map((k) => k.key);
    expect(keys).toContain("a-z, 0-9");
    expect(keys).toContain("Up / Down");
    expect(keys).toContain("Enter");
    expect(keys).toContain("Esc");
    expect(keys).toContain("Alt+W");
    expect(keys).toContain("Alt+1 to Alt+4");
    expect(keys).toContain("Tab");
    expect(keys).toContain("F1");
  });

  describe("F1", () => {
    it("dispatches TOGGLE_HELP regardless of context", () => {
      expect(dispatchKey({ key: "F1" }, defaultContext)).toEqual({
        type: "TOGGLE_HELP",
      });
      expect(
        dispatchKey({ key: "F1" }, { ...defaultContext, isHelpOpen: true, barVisible: false }),
      ).toEqual({ type: "TOGGLE_HELP" });
    });
  });

  describe("Escape", () => {
    it("dispatches DISMISS_HELP when help overlay is open", () => {
      expect(dispatchKey({ key: "Escape" }, { ...defaultContext, isHelpOpen: true })).toEqual({
        type: "DISMISS_HELP",
      });
    });

    it("dispatches CLEAR_QUERY when help overlay is closed", () => {
      expect(dispatchKey({ key: "Escape" }, { ...defaultContext, isHelpOpen: false })).toEqual({
        type: "CLEAR_QUERY",
      });
    });
  });

  describe("Alt+W", () => {
    it("dispatches CLOSE_FOCUSED_WINDOW when windows are open", () => {
      expect(
        dispatchKey({ key: "w", altKey: true }, { ...defaultContext, hasOpenWindows: true }),
      ).toEqual({ type: "CLOSE_FOCUSED_WINDOW" });

      expect(
        dispatchKey({ key: "W", altKey: true }, { ...defaultContext, hasOpenWindows: true }),
      ).toEqual({ type: "CLOSE_FOCUSED_WINDOW" });
    });

    it("does not dispatch when no window is open", () => {
      expect(
        dispatchKey({ key: "w", altKey: true }, { ...defaultContext, hasOpenWindows: false }),
      ).toBeNull();
    });
  });

  describe("Alt+1 to Alt+4", () => {
    it("dispatches FOCUS_SLOT when the target slot is occupied", () => {
      const ctx: KeyContext = { ...defaultContext, occupiedSlots: [0, 2] };

      expect(dispatchKey({ key: "1", altKey: true }, ctx)).toEqual({
        type: "FOCUS_SLOT",
        slot: 0,
      });
      expect(dispatchKey({ key: "3", altKey: true }, ctx)).toEqual({
        type: "FOCUS_SLOT",
        slot: 2,
      });
    });

    it("ignores Alt+digit when the slot is not occupied", () => {
      const ctx: KeyContext = { ...defaultContext, occupiedSlots: [0] };
      expect(dispatchKey({ key: "2", altKey: true }, ctx)).toBeNull();
      expect(dispatchKey({ key: "4", altKey: true }, ctx)).toBeNull();
    });
  });

  describe("Tab", () => {
    it("dispatches FOCUS_NEXT_WINDOW when windows are open", () => {
      expect(dispatchKey({ key: "Tab" }, { ...defaultContext, hasOpenWindows: true })).toEqual({
        type: "FOCUS_NEXT_WINDOW",
      });
    });

    it("does not dispatch FOCUS_NEXT_WINDOW when no windows are open", () => {
      expect(dispatchKey({ key: "Tab" }, { ...defaultContext, hasOpenWindows: false })).toBeNull();
    });
  });

  describe("Enter", () => {
    it("dispatches OPEN_SELECTED when suggestions are present", () => {
      expect(dispatchKey({ key: "Enter" }, { ...defaultContext, hasSuggestions: true })).toEqual({
        type: "OPEN_SELECTED",
      });
    });

    it("does nothing when suggestions list is empty", () => {
      expect(
        dispatchKey({ key: "Enter" }, { ...defaultContext, hasSuggestions: false }),
      ).toBeNull();
    });
  });

  describe("ArrowUp / ArrowDown", () => {
    it("dispatches MOVE_SELECTION when suggestions list is non-empty", () => {
      const ctx: KeyContext = {
        ...defaultContext,
        hasSuggestions: true,
        hasOpenWindows: true, // Suggestions take priority over scrolling!
      };

      expect(dispatchKey({ key: "ArrowDown" }, ctx)).toEqual({
        type: "MOVE_SELECTION",
        delta: 1,
      });
      expect(dispatchKey({ key: "ArrowUp" }, ctx)).toEqual({
        type: "MOVE_SELECTION",
        delta: -1,
      });
    });

    it("dispatches SCROLL_WINDOW when suggestions are empty and window is open", () => {
      const ctx: KeyContext = {
        ...defaultContext,
        hasSuggestions: false,
        hasOpenWindows: true,
      };

      expect(dispatchKey({ key: "ArrowDown" }, ctx)).toEqual({
        type: "SCROLL_WINDOW",
        delta: 1,
      });
      expect(dispatchKey({ key: "ArrowUp" }, ctx)).toEqual({
        type: "SCROLL_WINDOW",
        delta: -1,
      });
    });

    it("does nothing when suggestions are empty and no window is open", () => {
      const ctx: KeyContext = {
        ...defaultContext,
        hasSuggestions: false,
        hasOpenWindows: false,
      };

      expect(dispatchKey({ key: "ArrowDown" }, ctx)).toBeNull();
      expect(dispatchKey({ key: "ArrowUp" }, ctx)).toBeNull();
    });
  });

  describe("Printable character autofocus", () => {
    it("dispatches FOCUS_INPUT with character when bar is visible and input is not focused", () => {
      expect(
        dispatchKey({ key: "c" }, { ...defaultContext, barVisible: true, isInputFocused: false }),
      ).toEqual({ type: "FOCUS_INPUT", char: "c" });

      expect(
        dispatchKey({ key: "7" }, { ...defaultContext, barVisible: true, isInputFocused: false }),
      ).toEqual({ type: "FOCUS_INPUT", char: "7" });
    });

    it("does not dispatch when bar is hidden at 4 windows", () => {
      expect(
        dispatchKey({ key: "c" }, { ...defaultContext, barVisible: false, isInputFocused: false }),
      ).toBeNull();
    });

    it("does not dispatch when input is already focused (native typing handles it)", () => {
      expect(
        dispatchKey({ key: "c" }, { ...defaultContext, barVisible: true, isInputFocused: true }),
      ).toBeNull();
    });

    it("does not swallow browser shortcuts with Ctrl, Alt, or Meta", () => {
      expect(
        dispatchKey(
          { key: "r", ctrlKey: true },
          { ...defaultContext, barVisible: true, isInputFocused: false },
        ),
      ).toBeNull();

      expect(
        dispatchKey(
          { key: "f", metaKey: true },
          { ...defaultContext, barVisible: true, isInputFocused: false },
        ),
      ).toBeNull();
    });
  });
});
