import type { Measure, StatBlock } from "../../types/entity.js";
import type { RenderContext } from "../context.js";

const SVG_NS = "http://www.w3.org/2000/svg";

function formatMeasure(m: Measure): string {
  if (m.minimum === m.maximum) {
    return m.minimum.toString();
  }
  return `${m.minimum.toString()}–${m.maximum.toString()}`;
}

function cleanWikiTemplates(text: string): string {
  return text.replace(/\{\{(?:EntityLink|BlockLink|ItemLink)\|([^}|]+)(?:\|[^}]+)?\}\}/g, "$1");
}

/**
 * A player's full bar: 10 icons, each worth 2 points. Health and armour rows
 * both draw at most this many, the way the game's own HUD does.
 */
const FULL_BAR_POINTS = 20;

/**
 * Draws a Minecraft-style meter for `value` into `group`.
 *
 * Icons are drawn from the minimum and capped at a full bar, and a trailing
 * "+" marks whatever the icons do not cover -- a maximum past the cap, or a
 * range wider than its own minimum. Both rows used to draw a single lone icon
 * for anything they could not lay out exactly, which read as a count rather
 * than as a glyph: the Warden's 500 HP showed one heart, weaker on screen than
 * a chicken's four. The exact figure always sits in the text beside the icons.
 */
function appendMeterIcons(
  group: HTMLElement,
  value: Measure,
  createIcon: (type: "full" | "half") => SVGElement,
): void {
  const drawn = Math.min(Math.max(value.minimum, 0), FULL_BAR_POINTS);
  const full = Math.floor(drawn / 2);
  const half = drawn % 2 >= 0.5 ? 1 : 0;

  for (let i = 0; i < full; i++) {
    group.append(createIcon("full"));
  }
  if (half > 0) {
    group.append(createIcon("half"));
  }
  if (value.maximum > drawn) {
    const more = document.createElement("span");
    more.className = "stat-icons-more";
    more.textContent = "+";
    group.append(more);
  }
}

function createHeartIcon(type: "full" | "half"): SVGElement {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 9 9");
  svg.setAttribute("width", "13");
  svg.setAttribute("height", "13");
  svg.setAttribute("class", `stat-icon icon-heart-${type}`);
  svg.setAttribute("aria-hidden", "true");

  if (type === "full") {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute(
      "d",
      "M1 0h2v1H1zm4 0h2v1H5zM0 1h4v1H0zm5 0h4v1H5zM0 2h9v2H0zM1 4h7v1H1zm1 1h5v1H2zm1 1h3v1H3zm1 1h1v1H4z",
    );
    path.setAttribute("fill", "#e53935");

    const highlight = document.createElementNS(SVG_NS, "rect");
    highlight.setAttribute("x", "1");
    highlight.setAttribute("y", "1");
    highlight.setAttribute("width", "1");
    highlight.setAttribute("height", "1");
    highlight.setAttribute("fill", "#ffffff");
    highlight.setAttribute("opacity", "0.8");

    svg.append(path, highlight);
  } else {
    const leftFill = document.createElementNS(SVG_NS, "path");
    leftFill.setAttribute(
      "d",
      "M1 0h2v1H1zM0 1h4v1H0zM0 2h4v2H0zM1 4h3v1H1zm1 1h2v1H2zm1 1h1v1H3z",
    );
    leftFill.setAttribute("fill", "#e53935");

    const highlight = document.createElementNS(SVG_NS, "rect");
    highlight.setAttribute("x", "1");
    highlight.setAttribute("y", "1");
    highlight.setAttribute("width", "1");
    highlight.setAttribute("height", "1");
    highlight.setAttribute("fill", "#ffffff");
    highlight.setAttribute("opacity", "0.8");

    const rightEmpty = document.createElementNS(SVG_NS, "path");
    rightEmpty.setAttribute(
      "d",
      "M5 0h2v1H5zm0 1h4v1H5zm0 1h4v2H5zm0 2h3v1H5zm0 1h2v1H5zm0 1h1v1H5z",
    );
    rightEmpty.setAttribute("fill", "#444444");
    rightEmpty.setAttribute("opacity", "0.4");

    svg.append(leftFill, highlight, rightEmpty);
  }
  return svg;
}

function createArmorIcon(type: "full" | "half"): SVGElement {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 9 9");
  svg.setAttribute("width", "13");
  svg.setAttribute("height", "13");
  svg.setAttribute("class", `stat-icon icon-armor-${type}`);
  svg.setAttribute("aria-hidden", "true");

  if (type === "full") {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute(
      "d",
      "M1 0h2v1H1zm4 0h2v1H5zM0 1h9v3H0zm1 4h7v1H1zm1 1h5v1H2zm1 1h3v1H3zm1 1h1v1H4z",
    );
    path.setAttribute("fill", "#b0bec5");

    const highlight = document.createElementNS(SVG_NS, "rect");
    highlight.setAttribute("x", "1");
    highlight.setAttribute("y", "1");
    highlight.setAttribute("width", "1");
    highlight.setAttribute("height", "2");
    highlight.setAttribute("fill", "#eceff1");

    svg.append(path, highlight);
  } else {
    const leftFill = document.createElementNS(SVG_NS, "path");
    leftFill.setAttribute("d", "M1 0h2v1H1zM0 1h4v3H0zm1 4h3v1H1zm1 1h2v1H2zm1 1h1v1H3z");
    leftFill.setAttribute("fill", "#b0bec5");

    const highlight = document.createElementNS(SVG_NS, "rect");
    highlight.setAttribute("x", "1");
    highlight.setAttribute("y", "1");
    highlight.setAttribute("width", "1");
    highlight.setAttribute("height", "2");
    highlight.setAttribute("fill", "#eceff1");

    const rightEmpty = document.createElementNS(SVG_NS, "path");
    rightEmpty.setAttribute("d", "M5 0h2v1H5zm0 1h4v3H5zm0 3h3v1H5zm0 1h2v1H5zm0 1h1v1H5z");
    rightEmpty.setAttribute("fill", "#444444");
    rightEmpty.setAttribute("opacity", "0.4");

    svg.append(leftFill, highlight, rightEmpty);
  }
  return svg;
}

function createDamageIcon(): SVGElement {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 9 9");
  svg.setAttribute("width", "13");
  svg.setAttribute("height", "13");
  svg.setAttribute("class", "stat-icon icon-damage");
  svg.setAttribute("aria-hidden", "true");

  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute(
    "d",
    "M7 0h2v2H7zm-1 2h2v1H6zm-1 1h2v1H5zm-1 1h2v1H4zm-1 1h2v1H3zm-2 2h1v1H1zm0 1h1v1H1zm-1 1h1v1H0zm3-2h1v1H3zm0-1h1v1H3z",
  );
  path.setAttribute("fill", "#ffb74d");

  svg.append(path);
  return svg;
}

function createSizeIcon(): SVGElement {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 9 9");
  svg.setAttribute("width", "13");
  svg.setAttribute("height", "13");
  svg.setAttribute("class", "stat-icon icon-size");
  svg.setAttribute("aria-hidden", "true");

  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", "M0 0h3v1H1v2H0zm6 0h3v3H8V1H6zM0 6h1v2h2v1H0zm8 0h1v3H6V8h2z");
  path.setAttribute("fill", "#90a4ae");

  svg.append(path);
  return svg;
}

interface FormattedDamage {
  text: string;
}

function formatDamage(damageList: NonNullable<StatBlock["damage"]>): FormattedDamage[] {
  const groups = new Map<string, typeof damageList>();
  for (const d of damageList) {
    const cleaned = d.labels.map(cleanWikiTemplates).filter((l) => l.length > 0);
    const key = cleaned.join(", ");
    const group = groups.get(key) ?? [];
    group.push(d);
    groups.set(key, group);
  }

  const results: FormattedDamage[] = [];

  for (const [labelKey, entries] of groups.entries()) {
    const labelSuffix = labelKey.length > 0 ? ` (${labelKey})` : "";

    const easy = entries.find((e) => e.difficulties.includes("easy"));
    const normal = entries.find((e) => e.difficulties.includes("normal"));
    const hard = entries.find((e) => e.difficulties.includes("hard"));

    if (easy && normal && hard) {
      const eVal = formatMeasure(easy.value);
      const nVal = formatMeasure(normal.value);
      const hVal = formatMeasure(hard.value);

      if (eVal === nVal && nVal === hVal) {
        results.push({ text: `${nVal} dmg${labelSuffix}` });
      } else {
        results.push({ text: `${eVal}/${nVal}/${hVal} dmg${labelSuffix}` });
      }
      continue;
    }

    for (const d of entries) {
      const diffStr =
        d.difficulties.length > 0
          ? d.difficulties.map((diff) => diff.charAt(0).toUpperCase() + diff.slice(1)).join("/")
          : null;

      if (diffStr) {
        results.push({ text: `${diffStr}: ${formatMeasure(d.value)} dmg${labelSuffix}` });
      } else {
        results.push({ text: `${formatMeasure(d.value)} dmg${labelSuffix}` });
      }
    }
  }

  return results;
}

/**
 * Renders a StatBlock section:
 * - HP with visual heart icons and accessibility label
 * - Armor with visual armor icons
 * - Damage per difficulty formatted as 2.5/3/4.5 with damage icon
 * - Size with dimension icon
 * - Behavior and mobType as signals
 * - Speed and knockbackResistance stay unrendered
 */
export function renderStatBlock(section: StatBlock, _ctx: RenderContext): HTMLElement | null {
  const container = document.createElement("section");
  container.className = "entity-section stat-block";

  const tagsRow = document.createElement("div");
  tagsRow.className = "stat-badges stat-tags";

  const visuals = document.createElement("div");
  visuals.className = "stat-visuals";

  let hasContent = false;

  // Behavior signal
  if (section.behavior && section.behavior.length > 0) {
    for (const b of section.behavior) {
      const badge = document.createElement("span");
      const norm = b.text.toLowerCase();
      badge.className = `stat-badge stat-behavior is-${norm}`;
      const labelSuffix = b.labels.length > 0 ? ` (${b.labels.join(", ")})` : "";
      badge.textContent = `${b.text}${labelSuffix}`;
      tagsRow.append(badge);
      hasContent = true;
    }
  }

  // Mob type
  if (section.mobType && section.mobType.length > 0) {
    for (const mt of section.mobType) {
      const badge = document.createElement("span");
      badge.className = "stat-badge stat-mob-type";
      badge.textContent = mt;
      tagsRow.append(badge);
      hasContent = true;
    }
  }

  // Health (HP)
  if (section.health && section.health.length > 0) {
    for (const h of section.health) {
      const row = document.createElement("div");
      row.className = "stat-metric stat-metric-health";

      const iconsGroup = document.createElement("span");
      iconsGroup.className = "stat-icons-group";

      const labelSuffix = h.labels.length > 0 ? ` (${h.labels.join(", ")})` : "";
      const textVal = `${formatMeasure(h.value)} HP${labelSuffix}`;

      appendMeterIcons(iconsGroup, h.value, createHeartIcon);

      const textSpan = document.createElement("span");
      textSpan.className = "stat-label-text";
      textSpan.textContent = textVal;

      row.append(iconsGroup, textSpan);
      visuals.append(row);
      hasContent = true;
    }
  }

  // Armor
  if (section.armor && section.armor.length > 0) {
    for (const a of section.armor) {
      if (a.value.maximum > 0) {
        const row = document.createElement("div");
        row.className = "stat-metric stat-metric-armor";

        const iconsGroup = document.createElement("span");
        iconsGroup.className = "stat-icons-group";

        const labelSuffix = a.labels.length > 0 ? ` (${a.labels.join(", ")})` : "";
        const textVal = `${formatMeasure(a.value)} Armor${labelSuffix}`;

        appendMeterIcons(iconsGroup, a.value, createArmorIcon);

        const textSpan = document.createElement("span");
        textSpan.className = "stat-label-text";
        textSpan.textContent = textVal;

        row.append(iconsGroup, textSpan);
        visuals.append(row);
        hasContent = true;
      }
    }
  }

  // Damage
  if (section.damage && section.damage.length > 0) {
    const formatted = formatDamage(section.damage);
    for (const d of formatted) {
      const row = document.createElement("div");
      row.className = "stat-metric stat-metric-damage";

      const iconsGroup = document.createElement("span");
      iconsGroup.className = "stat-icons-group";
      iconsGroup.append(createDamageIcon());

      const textSpan = document.createElement("span");
      textSpan.className = "stat-label-text";
      textSpan.textContent = d.text;

      row.append(iconsGroup, textSpan);
      visuals.append(row);
      hasContent = true;
    }
  }

  // Size
  if (section.size && section.size.length > 0) {
    for (const s of section.size) {
      const row = document.createElement("div");
      row.className = "stat-metric stat-metric-size";

      const iconsGroup = document.createElement("span");
      iconsGroup.className = "stat-icons-group";
      iconsGroup.append(createSizeIcon());

      const labelSuffix = s.labels.length > 0 ? ` (${s.labels.join(", ")})` : "";
      const textVal = `Size: ${s.width.toString()} × ${s.height.toString()}m${labelSuffix}`;

      const textSpan = document.createElement("span");
      textSpan.className = "stat-label-text";
      textSpan.textContent = textVal;

      row.append(iconsGroup, textSpan);
      visuals.append(row);
      hasContent = true;
    }
  }

  if (!hasContent) {
    return null;
  }

  if (tagsRow.hasChildNodes()) {
    container.append(tagsRow);
  }
  if (visuals.hasChildNodes()) {
    container.append(visuals);
  }

  return container;
}
