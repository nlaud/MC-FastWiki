import type { IndexEntry } from "../types/index.js";

/**
 * The icon key an index entry draws with, after the kind-level fallbacks.
 *
 * Most entries carry their own `i`, resolved by `pipeline.normalize.reconcile`
 * through the wiki's `spritefile` bucket. One kind never can, and this module
 * is where that is answered rather than left blank.
 *
 * ## Why enchantments have no icon of their own
 *
 * An enchantment is not a thing the game draws. It is data on a stack, so it
 * ships no texture and the wiki publishes no sprite for it.
 * `pipeline.normalize.reconcile` records the measurement: 42 of the 43
 * enchantments resolve to nothing under every sprite family this project
 * reads, and the one that did resolve matched an unrelated icon of the same
 * short name by accident. `ICON_RULES["enchantment"]` therefore carries
 * `has_icons=False` and the registry is reported as an exemption. That record
 * is correct and this module does not change it -- no enchantment gains an
 * icon *of its own* here.
 *
 * The wiki does publish a `DungeonsEnchantmentSprite` family, and it is the
 * trap rather than the answer. Those are Minecraft Dungeons artwork for
 * Dungeons' own enchantments. A dozen names collide with Java Edition's --
 * `sharpness`, `protection`, `looting`, `thorns` -- so a join keyed on the
 * name would find a frame for some enchantments and draw another game's art on
 * a Java Edition reference. `pipeline.enrich.sprite.VANILLA_FAMILIES` already
 * excludes every `Dungeons*` family for exactly this reason.
 *
 * ## What is drawn instead
 *
 * The Enchanted Book frame, which is already in the atlas because the item is.
 *
 * This is the fallback `TODO.md`'s Phase 8 potion bullet prescribes for the
 * same shape of problem: "a renderer fallback ... not a new sprite, because the
 * texture really is the same one." It holds more exactly here than it does for
 * potions. Every enchantment genuinely exists in the world as an enchanted
 * book, and the game draws all 43 of them with one identical texture -- there
 * is no per-enchantment art being approximated, because there is no
 * per-enchantment art at all.
 *
 * So this states a kind, not an identity. It tells a reader scanning a mixed
 * suggestion list that the row is an enchantment rather than an item or a
 * block, and it does not pretend to tell Fortune from Efficiency. Picking a
 * representative tool per enchantment -- a diamond pickaxe for Fortune -- would
 * pretend exactly that, by choosing one arbitrary member of a 28-item set, and
 * is the guess Decision 3 forbids.
 */
export const ENCHANTMENT_FALLBACK_ICON = "InvSprite:Enchanted Book";

/**
 * Returns the atlas icon key for `entry`, or `undefined` when it draws none.
 *
 * Call this rather than reading `entry.i` directly anywhere an entry is drawn,
 * so the suggestion list, the window header, and an inline entity link all
 * agree on what an enchantment looks like.
 */
export function entryIconKey(entry: Pick<IndexEntry, "i" | "k">): string | undefined {
  if (entry.i) {
    return entry.i;
  }
  if (entry.k === "enchantment") {
    return ENCHANTMENT_FALLBACK_ICON;
  }
  return undefined;
}
