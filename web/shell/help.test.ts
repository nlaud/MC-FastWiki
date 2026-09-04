import { describe, expect, it, vi } from "vitest";

import { createHelpOverlay } from "./help.js";
import { KEYMAP } from "./keymap.js";

describe("help overlay", () => {
  it("renders every entry from KEYMAP", () => {
    const onClose = vi.fn();
    const overlay = createHelpOverlay(onClose);

    const rows = overlay.querySelectorAll("tr.help-row");
    expect(rows).toHaveLength(KEYMAP.length);

    for (const [i, entry] of KEYMAP.entries()) {
      const row = rows[i];
      if (!row) {
        throw new Error(`Row ${i.toString()} missing in help overlay`);
      }
      expect(row.textContent).toContain(entry.key);
      expect(row.textContent).toContain(entry.does);
      expect(row.textContent).toContain(entry.when);
    }
  });

  it("calls onClose when close button is clicked", () => {
    const onClose = vi.fn();
    const overlay = createHelpOverlay(onClose);

    const btn = overlay.querySelector<HTMLButtonElement>("button.help-close-btn");
    expect(btn).not.toBeNull();
    btn?.click();

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose when clicking the backdrop", () => {
    const onClose = vi.fn();
    const overlay = createHelpOverlay(onClose);

    overlay.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not call onClose when clicking inside the panel", () => {
    const onClose = vi.fn();
    const overlay = createHelpOverlay(onClose);

    const panel = overlay.querySelector(".help-panel");
    panel?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(onClose).not.toHaveBeenCalled();
  });
});
