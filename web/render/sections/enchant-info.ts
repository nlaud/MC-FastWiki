import type { ApplicableItems, EnchantInfo } from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { entityLink, proseEntityLink } from "../link.js";

const ROMAN_NUMERALS: Record<number, string> = {
  1: "I",
  2: "II",
  3: "III",
  4: "IV",
  5: "V",
};

const RARITY_NAMES: Record<string, string> = {
  common: "Common",
  uncommon: "Uncommon",
  rare: "Rare",
  very_rare: "Very Rare",
};

const SLOT_NAMES: Record<string, string> = {
  mainhand: "Main hand",
  offhand: "Off hand",
  head: "Head",
  armor: "Armor",
  feet: "Feet",
  legs: "Legs",
  hand: "Hand",
  any: "Any",
};

function row(label: string, grid: HTMLElement): HTMLElement {
  const line = document.createElement("div");
  line.className = "enchant-row";
  const key = document.createElement("span");
  key.className = "enchant-label";
  key.textContent = label;
  const value = document.createElement("span");
  value.className = "enchant-value";
  line.append(key, value);
  grid.append(line);
  return value;
}

/**
 * Turns a tag path into a label a player reads.
 *
 * `supportedItems.group` carries the tag the data file names, such as
 * `enchantable/mining_loot`. That is the provenance, not a label -- a slash and
 * an underscore in the middle of a sentence is a data path that leaked onto the
 * screen. Only the last segment names the group, and spelling it in words is
 * enough: "Mining loot", "Sharp weapon", "Foot armor".
 */
function groupLabel(group: string): string {
  const lastSegment = group.slice(group.lastIndexOf("/") + 1);
  const spelled = lastSegment.replace(/_/g, " ");
  return spelled.charAt(0).toUpperCase() + spelled.slice(1);
}

/**
 * Renders one applicability group as its label and every item link under it.
 *
 * Every item is drawn, with no disclosure to open first. The set reaches 92
 * items for Curse of Vanishing, so the row is long -- but a link the reader can
 * see is a jump they can take, and a click that only reveals the links is a
 * step between the question and the answer.
 */
function renderApplicableItems(app: ApplicableItems, ctx: RenderContext): HTMLElement {
  const container = document.createElement("div");
  container.className = "enchant-applicable";

  const heading = document.createElement("span");
  heading.className = "enchant-items-group";
  const countStr = app.items.length === 1 ? "1 item" : `${app.items.length.toString()} items`;
  heading.textContent = `${groupLabel(app.group)} (${countStr})`;
  container.append(heading);

  const list = document.createElement("div");
  list.className = "enchant-items-list";
  for (const item of app.items) {
    list.append(entityLink(item, ctx));
  }
  container.append(list);
  return container;
}

/**
 * Renders an EnchantInfo section with max level, rarity, anvil cost,
 * equipment slots, modified enchantment level range, exclusive set,
 * and applicable item groups.
 */
export function renderEnchantInfo(section: EnchantInfo, ctx: RenderContext): HTMLElement {
  const container = document.createElement("section");
  container.className = "entity-section enchant-info-section";

  const title = document.createElement("h3");
  title.className = "section-title";
  title.textContent = "Enchantment";
  container.append(title);

  const grid = document.createElement("div");
  grid.className = "enchant-details-grid";

  // Max level
  const maxLvlValue = row("Max level", grid);
  const roman = ROMAN_NUMERALS[section.maxLevel] ?? section.maxLevel.toString();
  maxLvlValue.textContent =
    section.maxLevel === 1 ? "I" : `${roman} (${section.maxLevel.toString()})`;

  // Rarity
  const rarityValue = row("Rarity", grid);
  rarityValue.textContent = RARITY_NAMES[section.rarity] ?? section.rarity;

  // Anvil cost
  const anvilValue = row("Anvil cost", grid);
  anvilValue.textContent = section.anvilCost.toString();

  // Equipment slots
  if (section.slots.length > 0) {
    const slotsValue = row(section.slots.length === 1 ? "Slot" : "Slots", grid);
    slotsValue.textContent = section.slots.map((s) => SLOT_NAMES[s] ?? s).join(", ");
  }

  // Modified enchantment level range
  const costValue = row("Modified enchantment level", grid);
  const firstRange = section.costRanges[0];
  if (section.costRanges.length === 1 && firstRange) {
    costValue.textContent = `${firstRange.minimum.toString()}–${firstRange.maximum.toString()}`;
  } else {
    costValue.textContent = section.costRanges
      .map((r, i) => {
        const romanLvl = ROMAN_NUMERALS[i + 1] ?? (i + 1).toString();
        return `${romanLvl}: ${r.minimum.toString()}–${r.maximum.toString()}`;
      })
      .join(", ");
  }

  // Incompatible enchantments
  if (section.exclusiveSet.length > 0) {
    const conflictValue = row("Incompatible with", grid);
    const conflictsContainer = document.createElement("span");
    conflictsContainer.className = "enchant-conflicts";
    let first = true;
    for (const conflict of section.exclusiveSet) {
      if (!first) {
        conflictsContainer.append(document.createTextNode(", "));
      }
      first = false;
      conflictsContainer.append(proseEntityLink(conflict, ctx));
    }
    conflictValue.append(conflictsContainer);
  }

  // Applicability rows: separate primary/supported when primaryItems is present,
  // otherwise single row
  if (section.primaryItems) {
    const primaryVal = row("Primary items", grid);
    primaryVal.append(renderApplicableItems(section.primaryItems, ctx));

    const supportedVal = row("Supported items", grid);
    supportedVal.append(renderApplicableItems(section.supportedItems, ctx));
  } else {
    const applicableVal = row("Applicable items", grid);
    applicableVal.append(renderApplicableItems(section.supportedItems, ctx));
  }

  // Classification badges (treasure, curse, non-tradeable)
  if (section.treasure || section.curse || !section.tradeable) {
    const flagsVal = row("Properties", grid);
    const flagsContainer = document.createElement("span");
    flagsContainer.className = "enchant-flags";
    if (section.treasure) {
      const badge = document.createElement("span");
      badge.className = "enchant-badge badge-treasure";
      badge.textContent = "Treasure";
      flagsContainer.append(badge);
    }
    if (section.curse) {
      const badge = document.createElement("span");
      badge.className = "enchant-badge badge-curse";
      badge.textContent = "Curse";
      flagsContainer.append(badge);
    }
    if (!section.tradeable) {
      const badge = document.createElement("span");
      badge.className = "enchant-badge badge-untradeable";
      badge.textContent = "Not tradeable";
      flagsContainer.append(badge);
    }
    flagsVal.append(flagsContainer);
  }

  container.append(grid);
  return container;
}
