import type { BiomeInfo, BiomeSpawnEntry, NoisePlacement } from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { entityLink, formatQuantityRange } from "../link.js";

const DIMENSION_NAMES: Record<string, string> = {
  overworld: "Overworld",
  nether: "The Nether",
  the_end: "The End",
  end: "The End",
};

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

function formatDimension(dim: string): string {
  return DIMENSION_NAMES[dim.toLowerCase()] ?? dim;
}

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
 * - Climate details grid (Dimension, Temperature, Downfall, Precipitation)
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

  // Dimension. Omitted rather than guessed when no dimension tag claims the biome,
  // which in 26.2 is The Void alone.
  if (section.dimension) {
    const dimVal = row("Dimension:", grid);
    dimVal.textContent = formatDimension(section.dimension);
  }

  // Temperature
  const tempVal = row("Temperature:", grid);
  if (section.temperatureModifier && section.temperatureModifier !== "none") {
    tempVal.textContent = `${section.temperature.toString()} (${section.temperatureModifier})`;
  } else {
    tempVal.textContent = section.temperature.toString();
  }

  // Downfall
  const downfallVal = row("Downfall:", grid);
  downfallVal.textContent = section.downfall.toString();

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
    caption.textContent =
      "Noise generator climate parameters, distinct from the temperature and downfall properties above.";
    worldgenContainer.append(caption);

    // Group memberships (compact parameter chips)
    const groupPlacements = section.noisePlacements.filter((p) => p.route === "group");
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

      worldgenContainer.append(groupsContainer);
    }

    // Inland surface table (direct inland or group terrain)
    const inlandPlacements = section.noisePlacements.filter(
      (p) => p.route === "direct_inland" || p.route === "group_terrain",
    );
    if (inlandPlacements.length > 0) {
      if (groupPlacements.length > 0) {
        const terrainTitle = document.createElement("h4");
        terrainTitle.className = "biome-noise-subtitle";
        terrainTitle.textContent = "Terrain Placement";
        worldgenContainer.append(terrainTitle);
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

      worldgenContainer.append(renderWorldgenTable(headers, rows));
    }

    // Depth table (cave biomes)
    const depthPlacements = section.noisePlacements.filter((p) => p.route === "depth");
    if (depthPlacements.length > 0) {
      const headers = ["Depth", "Additional Requirement"];
      const rows = depthPlacements.map((p) => [p.depth ?? "—", p.additionalRequirement ?? "—"]);
      worldgenContainer.append(renderWorldgenTable(headers, rows));
    }

    // Non-inland table (oceans and mushroom fields)
    const nonInlandPlacements = section.noisePlacements.filter((p) => p.route === "non_inland");
    if (nonInlandPlacements.length > 0) {
      const headers = ["Continentalness", "Temperature Level"];
      const rows = nonInlandPlacements.map((p) => [p.continentalness ?? "—", p.temperature ?? "—"]);
      worldgenContainer.append(renderWorldgenTable(headers, rows));
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
