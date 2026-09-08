import { describe, expect, it } from "vitest";

import { ENCHANTMENT_FALLBACK_ICON, entryIconKey } from "./entry-icon.js";

describe("entryIconKey", () => {
  it("returns the entry's own icon when it has one", () => {
    expect(entryIconKey({ i: "InvSprite:Diamond Pickaxe", k: "item" })).toBe(
      "InvSprite:Diamond Pickaxe",
    );
  });

  it("draws the Enchanted Book frame for an enchantment with no icon", () => {
    expect(entryIconKey({ k: "enchantment" })).toBe(ENCHANTMENT_FALLBACK_ICON);
  });

  it("never overrides an enchantment that does resolve an icon of its own", () => {
    expect(entryIconKey({ i: "InvSprite:Something", k: "enchantment" })).toBe(
      "InvSprite:Something",
    );
  });

  it("leaves every other kind without an icon undrawn rather than borrowing one", () => {
    // A missing item or block icon is a real gap the pipeline reports. Filling
    // it in here would hide that gap behind a wrong picture.
    for (const kind of ["item", "block", "mob", "effect", "biome"] as const) {
      expect(entryIconKey({ k: kind })).toBeUndefined();
    }
  });
});
