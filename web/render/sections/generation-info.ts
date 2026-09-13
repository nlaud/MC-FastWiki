import type { GenerationInfo, GenerationScope, VeinInfo } from "../../types/entity.js";
import type { RenderContext } from "../context.js";
import { proseEntityLink } from "../link.js";

const DIMENSION_NAMES: Record<string, string> = {
  overworld: "Overworld",
  nether: "The Nether",
  the_end: "The End",
  end: "The End",
};

function formatDimension(dim: string): string {
  return DIMENSION_NAMES[dim.toLowerCase()] ?? dim;
}

function cleanFeatureName(feature: string): string {
  const unprefixed = feature.startsWith("minecraft:")
    ? feature.slice("minecraft:".length)
    : feature;
  return unprefixed.replace(/_/g, " ");
}

/**
 * Formats a height band.
 *
 * A feature placed on a surface heightmap states no band at all, so it reads
 * "Surface" rather than borrowing the dimension's build range: a sweet berry
 * bush that claimed "Y -64 to 320" would be naming the whole world for a plant
 * that only ever grows on the ground.
 */
function formatHeight(
  minY: number | undefined,
  maxY: number | undefined,
  surface: boolean,
  densestY?: number,
): string {
  if (minY === undefined || maxY === undefined) {
    return surface ? "Surface" : "—";
  }
  let text = `Y ${minY.toString()} to ${maxY.toString()}`;
  if (densestY !== undefined) {
    text += ` (peak: Y ${densestY.toString()})`;
  }
  return text;
}

function row(label: string, grid: HTMLElement): HTMLElement {
  const line = document.createElement("div");
  line.className = "generation-row";
  const key = document.createElement("span");
  key.className = "generation-label";
  key.textContent = label;
  const value = document.createElement("span");
  value.className = "generation-value";
  line.append(key, value);
  grid.append(line);
  return value;
}

function renderBiomes(scope: GenerationScope, ctx: RenderContext): HTMLElement {
  const container = document.createElement("span");
  container.className = "generation-biomes";

  if (scope.allBiomesOfDimension) {
    container.textContent = `All ${formatDimension(scope.dimension)} biomes (${scope.biomeCount.toString()})`;
    return container;
  }

  if (scope.biomes.length === 0) {
    container.textContent = `${scope.biomeCount.toString()} biomes`;
    return container;
  }

  const appendNames = (target: HTMLElement): void => {
    let first = true;
    for (const biome of scope.biomes) {
      if (!first) {
        target.append(document.createTextNode(", "));
      }
      first = false;
      target.append(proseEntityLink(biome, ctx));
    }
  };

  if (scope.biomes.length <= 6) {
    appendNames(container);
    return container;
  }

  // More than 6 biomes: collapsible details
  const details = document.createElement("details");
  details.className = "generation-biomes-details";
  const summary = document.createElement("summary");
  summary.textContent = `${scope.biomeCount.toString()} biomes`;
  details.append(summary);

  const list = document.createElement("div");
  list.className = "generation-biomes-list";
  appendNames(list);
  details.append(list);
  container.append(details);
  return container;
}

function renderVeinsTable(veins: VeinInfo[]): HTMLElement {
  const table = document.createElement("table");
  table.className = "generation-veins-table";

  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");

  const headers = ["Feature", "Height", "Rate", "Size"];
  for (const h of headers) {
    const th = document.createElement("th");
    th.textContent = h;
    headerRow.append(th);
  }
  thead.append(headerRow);
  table.append(thead);

  const tbody = document.createElement("tbody");
  for (const v of veins) {
    const tr = document.createElement("tr");

    const tdFeature = document.createElement("td");
    tdFeature.className = "vein-feature-name";
    tdFeature.textContent = cleanFeatureName(v.feature);

    const tdHeight = document.createElement("td");
    tdHeight.textContent = formatHeight(v.minY, v.maxY, v.surface ?? false, v.densestY);

    const tdRate = document.createElement("td");
    if (v.tries !== undefined) {
      tdRate.textContent = `${v.tries.toString()} / chunk`;
    } else if (v.chunkChance !== undefined) {
      tdRate.textContent = `1 in ${v.chunkChance.toString()} chunks`;
    } else {
      tdRate.textContent = "—";
    }

    const tdSize = document.createElement("td");
    tdSize.textContent = v.veinSize !== undefined ? `Up to ${v.veinSize.toString()}` : "—";

    tr.append(tdFeature, tdHeight, tdRate, tdSize);
    tbody.append(tr);
  }
  table.append(tbody);
  return table;
}

/**
 * Renders one dimension's worth of generation facts.
 *
 * `showDimensionRow` is false when the dimension already reads as a heading
 * above this block, which is what a block generating in two worlds gets.
 */
function renderScope(
  scope: GenerationScope,
  ctx: RenderContext,
  showDimensionRow: boolean,
): HTMLElement {
  const wrapper = document.createElement("div");
  wrapper.className = "generation-scope";

  if (!showDimensionRow) {
    const heading = document.createElement("h4");
    heading.className = "generation-scope-title";
    heading.textContent = formatDimension(scope.dimension);
    wrapper.append(heading);
  }

  const grid = document.createElement("div");
  grid.className = "generation-details-grid";

  if (showDimensionRow) {
    row("Dimension", grid).textContent = formatDimension(scope.dimension);
  }

  const height = formatHeight(scope.minY, scope.maxY, scope.surfaceOnly ?? false, scope.densestY);
  if (height !== "—") {
    row("Height", grid).textContent = height;
  }

  if (scope.attemptsPerChunk !== undefined) {
    row("Attempts / chunk", grid).textContent = scope.attemptsPerChunk.toString();
  }

  row("Biomes", grid).append(renderBiomes(scope, ctx));

  const firstVein = scope.veins[0];
  if (scope.veins.length === 1 && firstVein?.veinSize !== undefined) {
    row("Vein size", grid).textContent = `Up to ${firstVein.veinSize.toString()} blocks`;
  }

  wrapper.append(grid);

  if (scope.veins.length > 1) {
    const veinsContainer = document.createElement("div");
    veinsContainer.className = "generation-veins-container";

    const veinsHeading = document.createElement("h4");
    veinsHeading.className = "generation-veins-title";
    veinsHeading.textContent = "Veins";
    veinsContainer.append(veinsHeading);

    veinsContainer.append(renderVeinsTable(scope.veins));
    wrapper.append(veinsContainer);
  }

  return wrapper;
}

/**
 * Renders a GenerationInfo section, one block of rows per dimension.
 *
 * Almost every block generates in one dimension and draws one block of rows with
 * a Dimension row at the top. Gravel and the two mushrooms generate in the
 * overworld and the nether at once, and each dimension states its own band,
 * attempt count and biomes, so those draw one titled block each.
 */
export function renderGenerationInfo(section: GenerationInfo, ctx: RenderContext): HTMLElement {
  const container = document.createElement("section");
  container.className = "entity-section generation-info-section";

  const title = document.createElement("h3");
  title.className = "section-title";
  title.textContent = "Generation";
  container.append(title);

  const single = section.scopes.length === 1;
  for (const scope of section.scopes) {
    container.append(renderScope(scope, ctx, single));
  }

  return container;
}
