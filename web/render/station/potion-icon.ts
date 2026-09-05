/**
 * Icon keys for the potion ids that no registry entry covers.
 *
 * `pipeline.obtain.brewing` names every brewable potion as `minecraft:potion/
 * <variant>` -- `potion/awkward`, `potion/long_night_vision`,
 * `potion/strong_harming`. Those are not item registry ids, so `index.json` has
 * no entry for them, so a slot found no icon and fell back to printing the name.
 * "Potion Of Strong Regeneration" in a 40px slot is the clipped text this
 * resolves.
 *
 * The answer is the effect sprite rather than a tinted bottle. Every status
 * effect already ships a distinct coloured 18x18 frame in the atlas
 * (`EffectSprite:regeneration`, `EffectSprite:instant-health`, ...), which is
 * both the colour the reader is asking for and a picture that says *which*
 * potion it is -- something a bottle sprite cannot do, and something a colour
 * invented here would only pretend to do. The four potions that confer no
 * effect at all fall back to the plain bottle.
 */

/** Potion variants that carry no status effect, so no effect sprite exists. */
const EFFECTLESS = new Set(["water", "mundane", "thick", "awkward"]);

/**
 * Potion variants whose name differs from the effect id they apply.
 *
 * A Potion of Swiftness grants Speed, a Potion of Healing grants Instant
 * Health, and so on. Verified against the effect frames present in
 * `data/dist/sprites.json`.
 */
const EFFECT_ALIASES: Record<string, string> = {
  swiftness: "speed",
  healing: "instant_health",
  harming: "instant_damage",
  leaping: "jump_boost",
  // A Potion of the Turtle Master applies both Slowness and Resistance.
  // Resistance is the half a player drinks it for.
  turtle_master: "resistance",
};

/** The bottle frame for each potion container, when no effect frame applies. */
const CONTAINER_SPRITES: Record<string, string> = {
  potion: "ItemSprite:potion",
  splash_potion: "ItemSprite:splash-potion",
  lingering_potion: "ItemSprite:lingering-potion",
};

/**
 * Returns an atlas icon key for a `<container>/<variant>` potion id, or null
 * when `id` is not one.
 */
export function potionIconKey(id: string): string | null {
  const bare = id.replace(/^[a-z0-9_-]+:/, "");
  const slash = bare.indexOf("/");
  if (slash === -1) {
    return null;
  }

  const container = bare.slice(0, slash);
  const containerSprite = CONTAINER_SPRITES[container];
  if (!containerSprite) {
    return null;
  }

  // `long_` and `strong_` name the same effect at a different duration or
  // level, and the game draws them with the same icon.
  const variant = bare.slice(slash + 1).replace(/^(long|strong)_/, "");
  if (EFFECTLESS.has(variant)) {
    return containerSprite;
  }

  const effect = EFFECT_ALIASES[variant] ?? variant;
  return `EffectSprite:${effect.replace(/_/g, "-")}`;
}

/** Returns a readable name for a `<container>/<variant>` potion id. */
export function potionName(id: string): string | null {
  const bare = id.replace(/^[a-z0-9_-]+:/, "");
  const slash = bare.indexOf("/");
  if (slash === -1) {
    return null;
  }
  const container = bare.slice(0, slash);
  if (!CONTAINER_SPRITES[container]) {
    return null;
  }

  const words = (text: string): string =>
    text
      .split("_")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");

  const variant = bare.slice(slash + 1);
  const containerLabel = words(container);
  if (variant === "water") {
    return container === "potion" ? "Water Bottle" : `${containerLabel} of Water`;
  }
  return `${containerLabel} of ${words(variant)}`;
}
