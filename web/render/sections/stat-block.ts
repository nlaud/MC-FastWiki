import type { Measure, StatBlock } from "../../types/entity.js";
import type { RenderContext } from "../context.js";

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
 * Renders a StatBlock section:
 * - HP, damage per difficulty, and armor as badges
 * - behavior and mobType as hostile/passive/neutral signal
 * - size when present
 * - speed and knockbackResistance stay unrendered
 * - labelled variants such as leaders and Baby render beside the base value
 */
export function renderStatBlock(section: StatBlock, _ctx: RenderContext): HTMLElement | null {
  const container = document.createElement("section");
  container.className = "entity-section stat-block";

  const badges = document.createElement("div");
  badges.className = "stat-badges";

  let hasContent = false;

  // Behavior signal
  if (section.behavior && section.behavior.length > 0) {
    for (const b of section.behavior) {
      const badge = document.createElement("span");
      const norm = b.text.toLowerCase();
      badge.className = `stat-badge stat-behavior is-${norm}`;
      const labelSuffix = b.labels.length > 0 ? ` (${b.labels.join(", ")})` : "";
      badge.textContent = `${b.text}${labelSuffix}`;
      badges.append(badge);
      hasContent = true;
    }
  }

  // Mob type
  if (section.mobType && section.mobType.length > 0) {
    for (const mt of section.mobType) {
      const badge = document.createElement("span");
      badge.className = "stat-badge stat-mob-type";
      badge.textContent = mt;
      badges.append(badge);
      hasContent = true;
    }
  }

  // Health (HP)
  if (section.health && section.health.length > 0) {
    for (const h of section.health) {
      const badge = document.createElement("span");
      badge.className = "stat-badge stat-health";
      const labelSuffix = h.labels.length > 0 ? ` (${h.labels.join(", ")})` : "";
      badge.textContent = `${formatMeasure(h.value)} HP${labelSuffix}`;
      badges.append(badge);
      hasContent = true;
    }
  }

  // Armor
  if (section.armor && section.armor.length > 0) {
    for (const a of section.armor) {
      if (a.value.maximum > 0) {
        const badge = document.createElement("span");
        badge.className = "stat-badge stat-armor";
        const labelSuffix = a.labels.length > 0 ? ` (${a.labels.join(", ")})` : "";
        badge.textContent = `${formatMeasure(a.value)} Armor${labelSuffix}`;
        badges.append(badge);
        hasContent = true;
      }
    }
  }

  // Damage
  if (section.damage && section.damage.length > 0) {
    for (const d of section.damage) {
      const badge = document.createElement("span");
      badge.className = "stat-badge stat-damage";

      const diffStr =
        d.difficulties.length > 0
          ? d.difficulties.map((diff) => diff.charAt(0).toUpperCase() + diff.slice(1)).join("/")
          : null;

      const labels = d.labels.map(cleanWikiTemplates).filter((l) => l.length > 0);
      const labelSuffix = labels.length > 0 ? ` (${labels.join(", ")})` : "";

      if (diffStr) {
        badge.textContent = `${diffStr}: ${formatMeasure(d.value)} dmg${labelSuffix}`;
      } else {
        badge.textContent = `${formatMeasure(d.value)} dmg${labelSuffix}`;
      }
      badges.append(badge);
      hasContent = true;
    }
  }

  // Size
  if (section.size && section.size.length > 0) {
    for (const s of section.size) {
      const badge = document.createElement("span");
      badge.className = "stat-badge stat-size";
      const labelSuffix = s.labels.length > 0 ? ` (${s.labels.join(", ")})` : "";
      badge.textContent = `Size: ${s.width.toString()} × ${s.height.toString()}m${labelSuffix}`;
      badges.append(badge);
      hasContent = true;
    }
  }

  if (!hasContent) {
    return null;
  }

  container.append(badges);
  return container;
}
