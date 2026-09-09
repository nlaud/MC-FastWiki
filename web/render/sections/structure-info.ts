import type { StructureInfo, StructurePlacement } from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { entityLink, formatQuantityRange, proseEntityLink } from "../link.js";

const DIMENSION_NAMES: Record<string, string> = {
  overworld: "Overworld",
  nether: "The Nether",
  the_end: "The End",
  end: "The End",
};

function formatDimension(dim: string): string {
  return DIMENSION_NAMES[dim.toLowerCase()] ?? dim;
}

/**
 * Title-cases an underscore-joined data value for display.
 *
 * Every one of these -- a generation step, a spawn category, a suppressed
 * category -- arrives straight from the data pack as `underground_water_
 * creature`. Capitalising only the first letter leaves the underscores on
 * screen, so all three go through here rather than each doing half the job.
 */
function titleCaseWords(value: string): string {
  return value
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function cleanSetName(setName: string): string {
  const bare = setName.startsWith("minecraft:") ? setName.slice("minecraft:".length) : setName;
  if (bare === "villages") {
    return "a Village";
  }
  return titleCaseWords(bare);
}

function formatPlacement(placement: StructurePlacement): {
  main: string;
  exclusion?: string | undefined;
} {
  if (placement.type === "minecraft:random_spread") {
    let percent: string | undefined;
    if (placement.frequency !== undefined) {
      const pct = placement.frequency * 100;
      percent = pct % 1 === 0 ? pct.toString() : pct.toFixed(1);
    }

    // A spacing of 1 with no separation is not a rate. It says the game
    // considers every chunk and lets `frequency` decide, so "Every 1 chunks,
    // at least 0 apart" states a certainty the data denies -- a mineshaft is
    // in 0.4% of chunks, not in all of them. Where the grid says nothing, the
    // frequency is the whole answer and is stated on its own.
    const gridDecidesSomething = placement.spacing > 1 || placement.separation > 0;

    let main: string;
    if (gridDecidesSomething) {
      const unit = placement.spacing === 1 ? "chunk" : "chunks";
      main = `Every ${placement.spacing.toString()} ${unit}, at least ${placement.separation.toString()} apart`;
      if (percent !== undefined) {
        main += ` (in ${percent}% of chunks)`;
      }
    } else if (percent !== undefined) {
      main = `In ${percent}% of chunks`;
    } else {
      main = "Every chunk";
    }

    let exclusion: string | undefined;
    if (placement.exclusionZone) {
      const other = cleanSetName(placement.exclusionZone.otherSet);
      exclusion = `Never within ${placement.exclusionZone.chunkCount.toString()} chunks of ${other}`;
    }
    return { main, exclusion };
  }

  const main = `${placement.count.toString()} in rings ${placement.distance.toString()} chunks apart`;
  return { main };
}

function row(label: string, parent: HTMLElement): HTMLElement {
  const line = document.createElement("div");
  line.className = "structure-row";
  const key = document.createElement("span");
  key.className = "structure-label";
  key.textContent = label;
  const value = document.createElement("span");
  value.className = "structure-value";
  line.append(key, value);
  parent.append(line);
  return value;
}

/**
 * Renders a StructureInfo section:
 * - Dimension, generation step
 * - Biomes (collapsible if > 6)
 * - Placement rules (spacing, separation, frequency, exclusion zone, concentric rings)
 * - Siblings in structure set (with weights)
 * - Mob spawn overrides
 * - Suppressed spawn categories
 */
export function renderStructureInfo(
  section: StructureInfo,
  ctx: RenderContext,
): HTMLElement | null {
  const container = document.createElement("section");
  container.className = "entity-section structure-info-section";

  const title = document.createElement("h3");
  title.className = "section-title";
  title.textContent = "Structure";
  container.append(title);

  const grid = document.createElement("div");
  grid.className = "structure-details-grid";

  // Dimension
  const dimVal = row("Dimension:", grid);
  dimVal.textContent = formatDimension(section.dimension);

  // Step
  const stepVal = row("Step:", grid);
  stepVal.textContent = titleCaseWords(section.step);

  // Placement
  const placementInfo = formatPlacement(section.placement);
  const placeVal = row("Placement:", grid);
  placeVal.textContent = placementInfo.main;

  if (placementInfo.exclusion) {
    const exclVal = row("Exclusion Zone:", grid);
    exclVal.textContent = placementInfo.exclusion;
  }

  // Biomes
  if (section.biomes.length > 0) {
    const biomesVal = row("Biomes:", grid);
    biomesVal.className = "structure-value structure-biomes-value";

    const appendBiomeLinks = (target: HTMLElement): void => {
      let first = true;
      for (const biome of section.biomes) {
        if (!first) {
          target.append(document.createTextNode(", "));
        }
        first = false;
        target.append(proseEntityLink(biome, ctx));
      }
    };

    if (section.biomes.length <= 6) {
      appendBiomeLinks(biomesVal);
    } else {
      const details = document.createElement("details");
      details.className = "structure-biomes-details";
      const summary = document.createElement("summary");
      summary.textContent = `${section.biomes.length.toString()} biomes`;
      details.append(summary);

      const list = document.createElement("div");
      list.className = "structure-biomes-list";
      appendBiomeLinks(list);
      details.append(list);
      biomesVal.append(details);
    }
  }

  // Siblings
  if (section.siblings.length > 1) {
    const sibVal = row("Set Siblings:", grid);
    sibVal.className = "structure-value structure-siblings-value";
    let first = true;
    for (const sib of section.siblings) {
      if (!first) {
        sibVal.append(document.createTextNode(", "));
      }
      first = false;
      sibVal.append(proseEntityLink(sib.structure, ctx));
      const wt = document.createElement("span");
      wt.className = "structure-sibling-weight";
      wt.textContent = ` (weight ${sib.weight.toString()})`;
      sibVal.append(wt);
    }
  }

  // Suppressed spawn categories
  if (section.suppressedSpawns.length > 0) {
    const suppVal = row("Suppressed Spawns:", grid);
    suppVal.textContent = section.suppressedSpawns.map(titleCaseWords).join(", ");
  }

  container.append(grid);

  // Mob spawns table
  if (section.spawns.length > 0) {
    const spawnsContainer = document.createElement("div");
    spawnsContainer.className = "structure-spawns-container";

    const spawnsTitle = document.createElement("h4");
    spawnsTitle.className = "structure-spawns-title";
    spawnsTitle.textContent = "Mob Spawns";
    spawnsContainer.append(spawnsTitle);

    const tableWrapper = document.createElement("div");
    tableWrapper.className = "table-wrapper";

    const table = document.createElement("table");
    table.className = "data-table structure-spawns-table";

    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");

    for (const heading of ["Mob", "Category", "Group Size", "Weight"]) {
      const th = document.createElement("th");
      th.textContent = heading;
      headerRow.append(th);
    }
    thead.append(headerRow);
    table.append(thead);

    const tbody = document.createElement("tbody");

    for (const spawn of section.spawns) {
      const tr = document.createElement("tr");

      const mobTd = document.createElement("td");
      mobTd.className = "mob-cell";
      mobTd.append(entityLink(spawn.mob, ctx));
      tr.append(mobTd);

      const catTd = document.createElement("td");
      catTd.className = "category-cell";
      catTd.textContent = titleCaseWords(spawn.category);
      tr.append(catTd);

      const groupTd = document.createElement("td");
      groupTd.className = "group-cell";
      groupTd.textContent = formatQuantityRange(spawn.groupSize);
      tr.append(groupTd);

      const weightTd = document.createElement("td");
      weightTd.className = "weight-cell";
      weightTd.textContent = spawn.weight.toString();
      tr.append(weightTd);

      tbody.append(tr);
    }

    table.append(tbody);
    tableWrapper.append(table);
    spawnsContainer.append(tableWrapper);
    container.append(spawnsContainer);
  }

  return container;
}
