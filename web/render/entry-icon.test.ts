import { describe, expect, it } from "vitest";

import { ENCHANTMENT_FALLBACK_ICON, entryIconKey } from "./entry-icon.js";

describe("entryIconKey", () => {
  it("returns the entry's own icon when it has one", () => {
    expect(
      entryIconKey({ i: "InvSprite:Diamond Pickaxe", id: "minecraft:diamond_pickaxe", k: "item" }),
    ).toBe("InvSprite:Diamond Pickaxe");
  });

  it("draws the Enchanted Book frame for an enchantment with no icon", () => {
    expect(entryIconKey({ id: "minecraft:fortune", k: "enchantment" })).toBe(
      ENCHANTMENT_FALLBACK_ICON,
    );
  });

  it("never overrides an enchantment that does resolve an icon of its own", () => {
    expect(
      entryIconKey({ i: "InvSprite:Something", id: "minecraft:fortune", k: "enchantment" }),
    ).toBe("InvSprite:Something");
  });

  it("leaves every other kind without an icon undrawn rather than borrowing one", () => {
    // A missing item or block icon is a real gap the pipeline reports. Filling
    // it in here would hide that gap behind a wrong picture.
    for (const kind of ["item", "block", "mob", "effect", "biome"] as const) {
      expect(entryIconKey({ id: `minecraft:no_such_${kind}`, k: kind })).toBeUndefined();
    }
  });

  it("resolves an effect-backed potion to its colored effect sprite", () => {
    expect(entryIconKey({ id: "minecraft:potion/swiftness", k: "item" })).toBe(
      "EffectSprite:speed",
    );
  });

  it("resolves an effectless potion to the plain bottle sprite", () => {
    expect(entryIconKey({ id: "minecraft:potion/awkward", k: "item" })).toBe("ItemSprite:potion");
  });

  it("borrows the inventory sprite for Wind Charge entity", () => {
    expect(entryIconKey({ id: "minecraft:breeze_wind_charge", k: "entity" })).toBe(
      "InvSprite:Wind Charge",
    );
  });

  it("keeps Minecart with Monster Spawner and Bucket of Sulfur Cube iconless", () => {
    expect(entryIconKey({ id: "minecraft:spawner_minecart", k: "entity" })).toBeUndefined();
    expect(entryIconKey({ id: "minecraft:sulfur_cube_bucket", k: "item" })).toBeUndefined();
  });
});
