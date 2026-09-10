import type { BiomeInfo, BiomeSpawnEntry, EntityRef, NoisePlacement } from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { entityLink, formatQuantityRange } from "../link.js";

/* The bare noun, for use inside a sentence. "The Nether" is the right label for a
   standalone field value, and the wrong one mid-sentence: interpolating it produced
   "Plus 5 common The Nether blocks". These names carry no article so a sentence can
   supply its own. */
const DIMENSION_NOUNS: Record<string, string> = {
  overworld: "Overworld",
  nether: "Nether",
  the_end: "End",
  end: "End",
};

function dimensionNoun(dim: string): string {
  return DIMENSION_NOUNS[dim.toLowerCase()] ?? dim;
}

function titleCaseWords(value: string): string {
  return value
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function cleanWikitext(text: string): string {
  return text.replace(/\[\[(?:[^|\]]*\|)?([^\]]+)\]\]/g, "$1").replace(/'{2,5}/g, "");
}

/* The seven continentalness bands the World generation prose lists, in order.
   `continentalnessBands` indexes into this, so ocean-side and inland placements
   share one axis instead of each restarting at zero. */
const CONTINENTALNESS_BAND_NAMES = [
  "Mushroom fields",
  "Deep ocean",
  "Ocean",
  "Coast",
  "Near-inland",
  "Mid-inland",
  "Far-inland",
];

const TEMPERATURE_LEVEL_COUNT = 5;
const HUMIDITY_LEVEL_COUNT = 5;
const EROSION_LEVEL_COUNT = 7;

/** Collapse sorted integers into contiguous [start, end] runs. */
function contiguousRuns(levels: number[]): [number, number][] {
  const runs: [number, number][] = [];
  for (const level of levels) {
    const last = runs.at(-1);
    if (last && level === last[1] + 1) {
      last[1] = level;
    } else {
      runs.push([level, level]);
    }
  }
  return runs;
}

/** The distinct levels a set of placements names for one parameter, sorted. */
function collectLevels(
  placements: NoisePlacement[],
  pick: (p: NoisePlacement) => number[] | undefined,
): number[] {
  const seen = new Set<number>();
  for (const placement of placements) {
    for (const level of pick(placement) ?? []) seen.add(level);
  }
  return [...seen].sort((a, b) => a - b);
}

/* The exact ranges live only in the display strings the pipeline formatted, and
   re-parsing those to recover a number is what `temperatureLevels` and its
   siblings exist to avoid. So the tooltip reuses the whole string rather than
   picking it apart. */
function collectDisplay(
  placements: NoisePlacement[],
  pick: (p: NoisePlacement) => string | undefined,
): string {
  const seen = new Set<string>();
  for (const placement of placements) {
    const value = pick(placement);
    if (value) seen.add(value);
  }
  return [...seen].join("   ");
}

function formatLevelSpan(levels: number[], prefix: string): string {
  if (levels.length === 0) return "—";
  return contiguousRuns(levels)
    .map(([start, end]) =>
      start === end
        ? `${prefix}=${start.toString()}`
        : `${prefix}=${start.toString()}–${end.toString()}`,
    )
    .join(", ");
}

function formatBandSpan(bands: number[]): string {
  if (bands.length === 0) return "—";
  return contiguousRuns(bands)
    .map(([start, end]) => {
      const startName = CONTINENTALNESS_BAND_NAMES[start] ?? String(start);
      if (start === end) return startName;
      const endName = CONTINENTALNESS_BAND_NAMES[end] ?? String(end);
      return `${startName} to ${endName}`;
    })
    .join(", ");
}

/**
 * One labelled axis: the parameter name, the two ends of its scale in plain
 * words, a track of segments with the matching ones filled, and the level
 * itself. The exact numeric range hangs off the value as a tooltip.
 */
function renderNoiseAxis(opts: {
  name: string;
  lowLabel: string;
  highLabel: string;
  count: number;
  active: number[];
  valueText: string;
  tooltip: string;
}): HTMLElement {
  const axis = document.createElement("div");
  axis.className = "noise-axis";

  const nameEl = document.createElement("span");
  nameEl.className = "noise-axis-name";
  nameEl.textContent = opts.name;

  const lowEl = document.createElement("span");
  lowEl.className = "noise-axis-end";
  lowEl.textContent = opts.lowLabel;

  const track = document.createElement("span");
  track.className = "noise-axis-track";
  const activeSet = new Set(opts.active);
  for (let i = 0; i < opts.count; i++) {
    const seg = document.createElement("span");
    seg.className = activeSet.has(i) ? "noise-axis-seg is-on" : "noise-axis-seg";
    seg.title = `Level ${i.toString()}`;
    track.append(seg);
  }

  const highEl = document.createElement("span");
  highEl.className = "noise-axis-end";
  highEl.textContent = opts.highLabel;

  const valueEl = document.createElement("span");
  valueEl.className = "noise-axis-value";
  valueEl.textContent = opts.valueText;
  if (opts.tooltip) valueEl.title = opts.tooltip;

  axis.append(nameEl, lowEl, track, highEl, valueEl);
  return axis;
}

function row(label: string, parent: HTMLElement): HTMLElement {
  const line = document.createElement("div");
  line.className = "biome-row";
  const key = document.createElement("span");
  key.className = "biome-label";
  key.textContent = label;
  const value = document.createElement("span");
  value.className = "biome-value";
  line.append(key, value);
  parent.append(line);
  return value;
}

function renderWorldgenTable(headers: string[], rows: (HTMLElement | string)[][]): HTMLElement {
  const tableWrapper = document.createElement("div");
  tableWrapper.className = "table-wrapper";

  const table = document.createElement("table");
  table.className = "data-table biome-noise-table";

  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  for (const h of headers) {
    const th = document.createElement("th");
    th.textContent = h;
    headerRow.append(th);
  }
  thead.append(headerRow);
  table.append(thead);

  const tbody = document.createElement("tbody");
  for (const rowData of rows) {
    const tr = document.createElement("tr");
    for (const cellData of rowData) {
      const td = document.createElement("td");
      if (typeof cellData === "string") {
        td.textContent = cellData;
      } else {
        td.append(cellData);
      }
      tr.append(td);
    }
    tbody.append(tr);
  }
  table.append(tbody);
  tableWrapper.append(table);
  return tableWrapper;
}

/**
 * Renders a BiomeInfo section:
 * - Climate details grid (Precipitation)
 * - World generation noise climate rules (for Overworld biomes)
 * - Mob spawns table grouped by category, with group size, weight, share %, and condition notes
 * - Generating blocks list with common dimension blocks count
 */
export function renderBiomeInfo(section: BiomeInfo, ctx: RenderContext): HTMLElement | null {
  const container = document.createElement("section");
  container.className = "entity-section biome-info-section";

  // 1. Climate
  const climateContainer = document.createElement("div");
  climateContainer.className = "biome-climate-container";

  const climateTitle = document.createElement("h3");
  climateTitle.className = "section-title";
  climateTitle.textContent = "Climate";
  climateContainer.append(climateTitle);

  const grid = document.createElement("div");
  grid.className = "biome-climate-grid";

  // Dimension, temperature and downfall are deliberately not rendered here.
  // `dimension` still gates the World Generation block below and still names the
  // dimension in the generating-blocks note, so the field is read, just not
  // printed as a row of its own.

  // Precipitation
  const precipVal = row("Precipitation:", grid);
  precipVal.textContent = titleCaseWords(section.precipitation);

  climateContainer.append(grid);
  container.append(climateContainer);

  // 2. World Generation
  if (
    section.dimension?.toLowerCase() === "overworld" &&
    section.noisePlacements &&
    section.noisePlacements.length > 0
  ) {
    const worldgenContainer = document.createElement("div");
    worldgenContainer.className = "biome-worldgen-container";

    const worldgenTitle = document.createElement("h3");
    worldgenTitle.className = "section-title";
    worldgenTitle.textContent = "World Generation";
    worldgenContainer.append(worldgenTitle);

    const caption = document.createElement("p");
    caption.className = "biome-worldgen-caption";
    caption.textContent = "Where the world generator places this biome.";
    worldgenContainer.append(caption);

    const allPlacements = section.noisePlacements;
    const groupPlacements = allPlacements.filter((p) => p.route === "group");

    // --- The summary: where this biome sits on each axis -------------------
    //
    // Aggregated over every placement, because a biome reached by more than one
    // route is present at every level any of them names. Jungle is a middle, a
    // plateau and a shattered biome, and the axes state the union.
    const tLevels = collectLevels(allPlacements, (p) => p.temperatureLevels);
    const hLevels = collectLevels(allPlacements, (p) => p.humidityLevels);
    const eLevels = collectLevels(allPlacements, (p) => p.erosionLevels);
    const cBands = collectLevels(allPlacements, (p) => p.continentalnessBands);

    const axes = document.createElement("div");
    axes.className = "biome-noise-axes";
    let axisCount = 0;

    if (tLevels.length > 0) {
      axes.append(
        renderNoiseAxis({
          name: "Temperature",
          lowLabel: "cold",
          highLabel: "hot",
          count: TEMPERATURE_LEVEL_COUNT,
          active: tLevels,
          valueText: formatLevelSpan(tLevels, "T"),
          tooltip: collectDisplay(allPlacements, (p) => p.temperature),
        }),
      );
      axisCount++;
    }
    if (hLevels.length > 0) {
      axes.append(
        renderNoiseAxis({
          name: "Humidity",
          lowLabel: "dry",
          highLabel: "wet",
          count: HUMIDITY_LEVEL_COUNT,
          active: hLevels,
          valueText: formatLevelSpan(hLevels, "H"),
          tooltip: collectDisplay(allPlacements, (p) => p.humidity),
        }),
      );
      axisCount++;
    }
    if (cBands.length > 0) {
      axes.append(
        renderNoiseAxis({
          name: "Continentalness",
          lowLabel: "ocean",
          highLabel: "inland",
          count: CONTINENTALNESS_BAND_NAMES.length,
          active: cBands,
          valueText: formatBandSpan(cBands),
          tooltip: collectDisplay(allPlacements, (p) => p.continentalness),
        }),
      );
      axisCount++;
    }
    if (eLevels.length > 0) {
      // Low erosion is hilly and high erosion is flat, so the axis reads left to
      // right the same way the level numbers climb.
      axes.append(
        renderNoiseAxis({
          name: "Erosion",
          lowLabel: "hilly",
          highLabel: "flat",
          count: EROSION_LEVEL_COUNT,
          active: eLevels,
          valueText: formatLevelSpan(eLevels, "E"),
          tooltip: collectDisplay(allPlacements, (p) => p.erosion),
        }),
      );
      axisCount++;
    }
    if (axisCount > 0) worldgenContainer.append(axes);

    // --- Depth, stated in a line rather than a one-row table ---------------
    const depthPlacements = allPlacements.filter((p) => p.route === "depth");
    for (const p of depthPlacements) {
      const line = document.createElement("p");
      line.className = "biome-noise-depth";
      const requirement =
        p.additionalRequirement && p.additionalRequirement !== "N/A"
          ? `, where ${p.additionalRequirement}`
          : "";
      line.textContent = `Underground: generates at depth ${p.depth ?? "—"}${requirement}.`;
      worldgenContainer.append(line);
    }

    // --- Variants: the biome the same cell gives when weirdness flips ------
    const variants = new Map<string, { ref: EntityRef; condition: string | undefined }>();
    for (const p of allPlacements) {
      if (!p.sibling) continue;
      if (!variants.has(p.sibling.id)) {
        variants.set(p.sibling.id, { ref: p.sibling, condition: p.weirdness });
      }
    }
    if (variants.size > 0) {
      const variantsEl = document.createElement("div");
      variantsEl.className = "biome-noise-variants";

      const label = document.createElement("span");
      label.className = "biome-noise-variants-label";
      label.textContent = variants.size === 1 ? "Variant here:" : "Variants here:";
      variantsEl.append(label);

      for (const { ref, condition } of variants.values()) {
        const item = document.createElement("span");
        item.className = "biome-noise-variant";
        item.append(entityLink(ref, ctx));
        // Our own rule carries one side of weirdness, so the variant is the
        // other side. Stated only when the source gave us a side to flip.
        if (condition === "W<0" || condition === "W>0") {
          const note = document.createElement("span");
          note.className = "biome-noise-variant-note";
          note.textContent = condition === "W<0" ? " (weirdness above 0)" : " (weirdness below 0)";
          item.append(note);
        }
        variantsEl.append(item);
      }
      worldgenContainer.append(variantsEl);
    }

    // --- Which groups place it, named but not linked -----------------------
    const groupNames = [...new Set(groupPlacements.map((p) => p.group).filter(Boolean))];
    if (groupNames.length > 0) {
      const placedAs = document.createElement("p");
      placedAs.className = "biome-noise-placed-as";
      placedAs.textContent = `Placed as: ${groupNames.join(", ").toLowerCase()}.`;
      worldgenContainer.append(placedAs);
    }

    // --- Everything exact, behind one disclosure ---------------------------
    const detailPlacements = allPlacements.filter((p) => p.route !== "depth");
    const details = document.createElement("details");
    details.className = "biome-noise-detail";
    const summary = document.createElement("summary");
    summary.textContent = `Exact noise values and terrain cells (${detailPlacements.length.toString()})`;
    details.append(summary);

    const detailBody = document.createElement("div");
    detailBody.className = "biome-noise-detail-body";

    // Group memberships (compact parameter chips)
    if (groupPlacements.length > 0) {
      const byGroup = new Map<string, NoisePlacement[]>();
      for (const p of groupPlacements) {
        const gName = p.group ?? "Group";
        const list = byGroup.get(gName) ?? [];
        list.push(p);
        byGroup.set(gName, list);
      }

      const groupsContainer = document.createElement("div");
      groupsContainer.className = "biome-noise-groups";

      for (const [groupName, placements] of byGroup.entries()) {
        const groupEl = document.createElement("div");
        groupEl.className = "biome-noise-group";

        const headerEl = document.createElement("div");
        headerEl.className = "biome-noise-group-title";
        headerEl.textContent = groupName;
        groupEl.append(headerEl);

        const chipsEl = document.createElement("div");
        chipsEl.className = "biome-noise-chips";

        for (const p of placements) {
          const chip = document.createElement("div");
          chip.className = "biome-noise-chip";

          const parts: string[] = [];
          if (p.temperature) parts.push(p.temperature);
          if (p.humidity) parts.push(p.humidity);
          if (p.weirdness) parts.push(p.weirdness);
          if (p.condition) parts.push(p.condition);

          chip.textContent = parts.length > 0 ? parts.join(", ") : "—";

          if (p.sibling) {
            const sibWrapper = document.createElement("span");
            sibWrapper.className = "biome-noise-sibling";
            sibWrapper.append(" (sibling: ", entityLink(p.sibling, ctx), ")");
            chip.append(sibWrapper);
          }

          chipsEl.append(chip);
        }

        groupEl.append(chipsEl);
        groupsContainer.append(groupEl);
      }

      detailBody.append(groupsContainer);
    }

    // Inland surface table (direct inland or group terrain)
    const inlandPlacements = allPlacements.filter(
      (p) => p.route === "direct_inland" || p.route === "group_terrain",
    );
    if (inlandPlacements.length > 0) {
      if (groupPlacements.length > 0) {
        const terrainTitle = document.createElement("h4");
        terrainTitle.className = "biome-noise-subtitle";
        terrainTitle.textContent = "Terrain Placement";
        detailBody.append(terrainTitle);
      }

      const hasGroup = inlandPlacements.some((p) => Boolean(p.group));
      const hasCondition = inlandPlacements.some((p) => Boolean(p.condition));
      const hasSibling = inlandPlacements.some((p) => Boolean(p.sibling));

      const headers = ["Erosion", "PV", "Continentalness"];
      let noteCol: "both" | "group" | "condition" | "none" = "none";
      if (hasGroup && hasCondition) {
        headers.push("Group / Condition");
        noteCol = "both";
      } else if (hasGroup) {
        headers.push("Group");
        noteCol = "group";
      } else if (hasCondition) {
        headers.push("Condition");
        noteCol = "condition";
      }

      if (hasSibling) {
        headers.push("Sibling");
      }

      const rows: (HTMLElement | string)[][] = [];
      for (const p of inlandPlacements) {
        const rowData: (HTMLElement | string)[] = [
          p.erosion ?? "—",
          p.pv ?? "—",
          p.continentalness ?? "—",
        ];

        if (noteCol === "both") {
          if (p.group && p.condition) {
            rowData.push(`${p.group} (${p.condition})`);
          } else {
            rowData.push(p.group ?? p.condition ?? "—");
          }
        } else if (noteCol === "group") {
          rowData.push(p.group ?? "—");
        } else if (noteCol === "condition") {
          rowData.push(p.condition ?? "—");
        }

        if (hasSibling) {
          if (p.sibling) {
            rowData.push(entityLink(p.sibling, ctx));
          } else {
            rowData.push("—");
          }
        }

        rows.push(rowData);
      }

      detailBody.append(renderWorldgenTable(headers, rows));
    }

    // Non-inland table (oceans and mushroom fields)
    const nonInlandPlacements = allPlacements.filter((p) => p.route === "non_inland");
    if (nonInlandPlacements.length > 0) {
      const headers = ["Continentalness", "Temperature Level"];
      const rows = nonInlandPlacements.map((p) => [p.continentalness ?? "—", p.temperature ?? "—"]);
      detailBody.append(renderWorldgenTable(headers, rows));
    }

    // A biome placed only by depth has nothing left for the disclosure, and an
    // empty one that opens onto nothing is worse than no disclosure at all.
    if (detailPlacements.length > 0) {
      details.append(detailBody);
      worldgenContainer.append(details);
    }

    container.append(worldgenContainer);
  }

  // 2. Mob Spawns
  if (section.spawns && section.spawns.length > 0) {
    const spawnsContainer = document.createElement("div");
    spawnsContainer.className = "biome-spawns-container";

    const spawnsTitle = document.createElement("h3");
    spawnsTitle.className = "section-title";
    spawnsTitle.textContent = "Mob Spawns";
    spawnsContainer.append(spawnsTitle);

    // Group by category
    const byCategory = new Map<string, BiomeSpawnEntry[]>();
    for (const spawn of section.spawns) {
      const list = byCategory.get(spawn.category) ?? [];
      list.push(spawn);
      byCategory.set(spawn.category, list);
    }

    const groupsContainer = document.createElement("div");
    groupsContainer.className = "biome-spawn-groups";

    for (const [category, categorySpawns] of byCategory.entries()) {
      const catGroup = document.createElement("div");
      catGroup.className = "biome-spawn-group";

      const catHeader = document.createElement("h4");
      catHeader.className = "biome-category-title";
      catHeader.textContent = titleCaseWords(category);
      catGroup.append(catHeader);

      const tableWrapper = document.createElement("div");
      tableWrapper.className = "table-wrapper";

      const table = document.createElement("table");
      table.className = "data-table biome-spawns-table";

      const thead = document.createElement("thead");
      const headerRow = document.createElement("tr");

      for (const heading of ["Mob", "Group Size", "Weight", "Share"]) {
        const th = document.createElement("th");
        th.textContent = heading;
        headerRow.append(th);
      }
      thead.append(headerRow);
      table.append(thead);

      const tbody = document.createElement("tbody");

      for (const spawn of categorySpawns) {
        const tr = document.createElement("tr");

        const mobTd = document.createElement("td");
        mobTd.className = "mob-cell";
        mobTd.append(entityLink(spawn.mob, ctx));

        if (spawn.note) {
          const noteEl = document.createElement("div");
          noteEl.className = "biome-spawn-note";
          noteEl.textContent = cleanWikitext(spawn.note);
          mobTd.append(noteEl);
        }
        tr.append(mobTd);

        const groupTd = document.createElement("td");
        groupTd.className = "group-cell";
        groupTd.textContent = formatQuantityRange(spawn.groupSize);
        tr.append(groupTd);

        const weightTd = document.createElement("td");
        weightTd.className = "weight-cell";
        weightTd.textContent = spawn.weight.toString();
        tr.append(weightTd);

        const shareTd = document.createElement("td");
        shareTd.className = "share-cell";
        shareTd.textContent =
          spawn.totalWeight > 0 ? `${((spawn.weight / spawn.totalWeight) * 100).toFixed(1)}%` : "—";
        tr.append(shareTd);

        tbody.append(tr);
      }

      table.append(tbody);
      tableWrapper.append(table);
      catGroup.append(tableWrapper);
      groupsContainer.append(catGroup);
    }

    spawnsContainer.append(groupsContainer);
    container.append(spawnsContainer);
  }

  // 3. Generating Blocks
  const hasSpecificBlocks = Boolean(section.blocks && section.blocks.length > 0);
  const commonCount = section.commonBlocksCount ?? 0;
  const hasBlocks = hasSpecificBlocks || commonCount > 0;

  if (hasBlocks) {
    const blocksContainer = document.createElement("div");
    blocksContainer.className = "biome-blocks-container";

    const blocksTitle = document.createElement("h3");
    blocksTitle.className = "section-title";
    blocksTitle.textContent = "Generating Blocks";
    blocksContainer.append(blocksTitle);

    if (hasSpecificBlocks && section.blocks) {
      const list = document.createElement("div");
      list.className = "biome-blocks-list";
      for (const block of section.blocks) {
        list.append(entityLink(block, ctx));
      }
      blocksContainer.append(list);
    }

    // The note names the dimension whose common blocks it is counting, so it needs
    // one. A biome in no dimension tag has no dimension-wide set and so has a count
    // of zero; the explicit check states that pairing rather than relying on it.
    if (commonCount > 0 && section.dimension) {
      const commonNote = document.createElement("p");
      commonNote.className = "biome-common-blocks";
      commonNote.textContent = `Plus ${commonCount.toString()} more blocks common to every ${dimensionNoun(section.dimension)} biome.`;
      blocksContainer.append(commonNote);
    }

    container.append(blocksContainer);
  }

  return container;
}
