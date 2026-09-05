import type { EffectLink, FoodEffect, FoodInfo } from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { createIconElement } from "../icon.js";
import { entityLink } from "../link.js";

/**
 * A full hunger bar: 20 points, drawn as 10 shanks worth 2 points each.
 *
 * No food in the game restores a whole bar, so unlike the health row in
 * `stat-block.ts` this cap is a guard against bad data rather than something a
 * real item reaches. The exact figure always sits in the text beside the icons.
 */
const FULL_BAR_POINTS = 20;

/** Ticks per second. The source counts effect durations in ticks. */
const TICKS_PER_SECOND = 20;

/**
 * The icon keys the atlas packs for the hunger bar.
 *
 * These are real HUD sprites off the wiki, listed in
 * `data/curated/hud-sprites.json` and packed by `pipeline/emit/atlas.py`, not
 * shapes drawn here. `stat-block.ts` hand-draws its hearts in SVG; this section
 * does not, because the sprites exist and a drawing of a shank is a worse
 * answer than the shank.
 */
const SHANK_FULL = "HudSprite:hunger-full";
const SHANK_HALF = "HudSprite:hunger-half";

/**
 * The box a shank is drawn into, in CSS pixels.
 *
 * The frames are 9x9, half the size of every other icon on a page, so at their
 * natural size they read as specks beside a 16px effect icon. 18 is exactly
 * double, so the upscale stays on whole pixels and adds no blur.
 */
const SHANK_SIZE = 18;

/**
 * Roman numerals for effect levels, indexed from level 1.
 *
 * The game shows no potion or food effect above level V, so the table stops
 * where the game does and `formatLevel` falls back to the digits for anything
 * past it rather than pretending to a numeral it cannot build.
 */
const ROMAN = ["", "I", "II", "III", "IV", "V"];

function formatLevel(level: number): string {
  return ROMAN[level] ?? level.toString();
}

/**
 * Formats a tick count the way the game's own HUD does: `m:ss`.
 *
 * Every real food duration divides evenly into seconds, so no rounding rule is
 * needed beyond the floor that a partial tick would hit.
 */
export function formatTicks(ticks: number): string {
  const totalSeconds = Math.floor(ticks / TICKS_PER_SECOND);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes.toString()}:${seconds.toString().padStart(2, "0")}`;
}

/**
 * Draws `points` hunger points as shank sprites: one icon per two points, plus
 * a half shank for an odd point.
 *
 * Every food in 26.2 restores an even number, so the half shank is unreachable
 * from today's data. It is drawn anyway because the sprite exists and the rule
 * is the game's, not this build's.
 */
function appendShanks(group: HTMLElement, points: number): void {
  const drawn = Math.min(Math.max(points, 0), FULL_BAR_POINTS);
  const full = Math.floor(drawn / 2);
  for (let i = 0; i < full; i++) {
    group.append(createIconElement(SHANK_FULL, { size: SHANK_SIZE, allowUpscale: true }));
  }
  if (drawn % 2 !== 0) {
    group.append(createIconElement(SHANK_HALF, { size: SHANK_SIZE, allowUpscale: true }));
  }
}

function renderEffectName(effect: FoodEffect | EffectLink, ctx: RenderContext): HTMLElement {
  if (effect.ref) {
    return entityLink(effect.ref, ctx);
  }
  const plain = document.createElement("span");
  plain.className = "entity-plain";
  const nameSpan = document.createElement("span");
  nameSpan.className = "entity-name";
  nameSpan.textContent = effect.name;
  plain.append(nameSpan);
  return plain;
}

function renderAppliedEffect(effect: FoodEffect, ctx: RenderContext): HTMLElement {
  const row = document.createElement("div");
  row.className = "food-effect-row";

  const link = renderEffectName(effect, ctx);
  // The level rides inside the link text so that "Regeneration II" reads as one
  // name, rather than as a link followed by a loose numeral.
  if (effect.level > 1) {
    const level = document.createElement("span");
    level.className = "food-effect-level";
    level.textContent = ` ${formatLevel(effect.level)}`;
    link.append(level);
  }
  row.append(link);

  const duration = document.createElement("span");
  duration.className = "food-effect-duration";
  duration.textContent = formatTicks(effect.durationTicks);
  row.append(duration);

  // A certain effect says nothing about its chance. Only the three items that
  // are a gamble -- rotten flesh, poisonous potato, raw chicken -- get a figure.
  if (effect.probability < 1) {
    const chance = document.createElement("span");
    chance.className = "food-effect-chance";
    chance.textContent = `${Math.round(effect.probability * 100).toString()}% chance`;
    row.append(chance);
  }

  return row;
}

function renderNoteRow(text: string): HTMLElement {
  const row = document.createElement("div");
  row.className = "food-effect-row";
  const note = document.createElement("span");
  note.className = "food-effect-note";
  note.textContent = text;
  row.append(note);
  return row;
}

/**
 * Renders a FoodInfo section:
 * - Title "Food", or "Consuming" for an item that is consumable without feeding
 * - Hunger points as real shank sprites, plus the exact figure
 * - Saturation as a figure, marked with the Saturation effect sprite
 * - An "Always edible" badge where the item ignores a full hunger bar
 * - One row per status effect, each a link into that effect's own page
 *
 * The heading switches on `nutrition` rather than on a flag, because the
 * pipeline sets `nutrition` and `saturation` together exactly when the item has
 * a `minecraft:food` component. The milk bucket is the one item in 26.2 that
 * reaches the "Consuming" branch.
 */
export function renderFoodInfo(section: FoodInfo, ctx: RenderContext): HTMLElement | null {
  const isFood = section.nutrition !== undefined;
  const hasEffects =
    section.effects.length > 0 ||
    section.removes.length > 0 ||
    section.clearsAllEffects ||
    section.teleportsRandomly;

  if (!isFood && !hasEffects) {
    return null;
  }

  const container = document.createElement("section");
  container.className = "entity-section food-info-section";

  const title = document.createElement("h3");
  title.className = "section-title";
  title.textContent = isFood ? "Food" : "Consuming";
  container.append(title);

  const box = document.createElement("div");
  box.className = "food-box";

  if (isFood) {
    const metric = document.createElement("div");
    metric.className = "food-metric";

    const shanks = document.createElement("span");
    shanks.className = "food-icons";
    appendShanks(shanks, section.nutrition ?? 0);
    metric.append(shanks);

    const hunger = document.createElement("span");
    hunger.className = "food-hunger";
    hunger.textContent = `${(section.nutrition ?? 0).toString()} hunger`;
    metric.append(hunger);

    if (section.saturation !== undefined) {
      // The game draws no saturation meter, and the wiki has no icon for one,
      // so this is the Saturation status effect's own sprite standing in as a
      // label. See `data/curated/hud-sprites.json` for the search that
      // established there is no truer icon to use.
      const saturationIcon = createIconElement("EffectSprite:saturation");
      saturationIcon.classList.add("food-saturation-icon");
      metric.append(saturationIcon);

      const saturation = document.createElement("span");
      saturation.className = "food-saturation";
      saturation.textContent = `${section.saturation.toString()} saturation`;
      metric.append(saturation);
    }

    if (section.canAlwaysEat) {
      const badge = document.createElement("span");
      badge.className = "stat-badge food-always-badge";
      badge.textContent = "Always edible";
      metric.append(badge);
    }

    box.append(metric);
  }

  for (const effect of section.effects) {
    box.append(renderAppliedEffect(effect, ctx));
  }

  for (const removed of section.removes) {
    const row = document.createElement("div");
    row.className = "food-effect-row";
    const label = document.createElement("span");
    label.className = "food-effect-note";
    label.textContent = "Cures";
    row.append(label, renderEffectName(removed, ctx));
    box.append(row);
  }

  if (section.clearsAllEffects) {
    box.append(renderNoteRow("Removes every active status effect."));
  }

  if (section.teleportsRandomly) {
    box.append(renderNoteRow("Teleports you up to 8 blocks."));
  }

  container.append(box);
  return container;
}
