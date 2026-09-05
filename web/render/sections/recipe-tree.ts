import type { RecipeTree } from "../../types/entity.js";
import { loadObtain } from "../../search/load.js";
import type { RenderContext } from "../context.js";
import { entityLink } from "../link.js";
import { type ObtainNode, type TreeInput, type TreeProducer, expandStub } from "../obtain-tree.js";

const METHOD_LABELS: Record<string, string> = {
  crafting: "Crafting",
  smelting: "Smelting",
  brewing: "Brewing",
  filling: "Filling",
  mob_loot: "Mob Drop",
  chest_loot: "Chest Loot",
  trade: "Trading",
  block_drop: "Block Drop",
};

/**
 * The order the method groups are drawn in, most actionable first.
 *
 * This is a rendering order only. The walk itself keeps the graph's own
 * `(method, output id, source_id)` sort, which `pipeline.obtain.producer.
 * ProducerIndex.from_producers` fixes and the acceptance fixture pins, so
 * reordering here changes what a player reads without changing the tree
 * either implementation builds.
 *
 * The graph's order is alphabetical by method, which puts `chest_loot` above
 * `crafting` -- so an item you simply craft led with a list of chests that
 * might happen to contain one. A player mid-match wants the thing they can
 * act on: make it, then cook it, then break or kill something for it, and
 * only then the places it might be lying around. A method absent from this
 * list sorts last, in the graph's order, rather than being dropped.
 */
const METHOD_ORDER: readonly string[] = [
  "crafting",
  "smelting",
  "brewing",
  "filling",
  "block_drop",
  "mob_loot",
  "trade",
  "chest_loot",
];

function methodRank(method: string): number {
  const rank = METHOD_ORDER.indexOf(method);
  return rank === -1 ? METHOD_ORDER.length : rank;
}

const STATION_LABELS: Record<string, string> = {
  furnace: "Furnace",
  blast_furnace: "Blast Furnace",
  smoker: "Smoker",
  campfire: "Campfire",
  stonecutter: "Stonecutter",
  smithing_table: "Smithing Table",
  brewing_stand: "Brewing Stand",
};

function humanise(str: string): string {
  return str.replace(/^minecraft:/, "").replace(/_/g, " ");
}

/**
 * Names where a producer that consumes nothing actually comes from.
 *
 * A chest loot producer has no inputs, so without this its row is the bare
 * word "Chest Loot" repeated once per chest -- which tells a player nothing.
 * `source_id` is the only field carrying the answer, as the loot table path
 * `loot_table/chests/abandoned_mineshaft.json`, so the basename is the chest.
 *
 * Only chest loot is read this way. A mob drop and a trade already carry a
 * readable `note` ("dropped by Evoker", "Farmer, Apprentice"), and a block
 * drop names its block in the input beside it, so reading the path for those
 * would repeat what the row already says.
 */
function sourceLabel(producer: TreeProducer): string | null {
  if (producer.method !== "chest_loot") {
    return null;
  }

  // Everything below `chests/`, not just the basename. Half the chest tables
  // (27 of the 54 in 26.2) sit one directory deeper, where the basename alone
  // is meaningless on its own: `chests/trial_chambers/intersection.json` reads
  // as "intersection" without the directory that says what it is an
  // intersection of.
  const afterChests = producer.source_id.split("chests/").pop();
  if (!afterChests) {
    return null;
  }

  const segments = afterChests.replace(/\.json$/, "").split("/");
  // `village/village_armorer` would otherwise read "village village armorer".
  // A segment whose successor already names it adds nothing.
  const kept = segments.filter((segment, index) => {
    const next = segments[index + 1];
    return next === undefined || !next.startsWith(`${segment}_`);
  });

  const label = humanise(kept.join(" "));
  return label.length > 0 ? label : null;
}

function renderInput(input: TreeInput, ctx: RenderContext, ancestors: string[]): HTMLElement {
  const itemEl = document.createElement("li");
  itemEl.className = "tree-input-item";

  const headEl = document.createElement("div");
  headEl.className = "tree-input-head";

  if (input.count > 1) {
    const countEl = document.createElement("span");
    countEl.className = "tree-input-count";
    countEl.textContent = `${input.count.toString()}×`;
    headEl.append(countEl);
  }

  if (input.tag) {
    const tagSpan = document.createElement("span");
    tagSpan.className = "tree-tag-badge";
    tagSpan.textContent = `#${humanise(input.tag)}`;
    headEl.append(tagSpan);

    if (input.members.length > 0) {
      const membersSpan = document.createElement("span");
      membersSpan.className = "tree-members-count";
      membersSpan.textContent = ` (${input.members.length.toString()})`;
      headEl.append(membersSpan);
    }
  } else if (input.item) {
    const entry = ctx.lookup(input.item);
    const linkEl = entityLink(
      {
        id: input.item,
        name: entry?.n ?? humanise(input.label),
      },
      ctx,
    );
    headEl.append(linkEl);
  } else {
    const labelSpan = document.createElement("span");
    labelSpan.className = "entity-plain";
    labelSpan.textContent = input.label;
    headEl.append(labelSpan);
  }

  itemEl.append(headEl);

  // Child node
  if (input.node) {
    const node = input.node;
    const backRef =
      node.back_reference ?? (node as unknown as { backReference?: string }).backReference;

    if (node.expandable) {
      const stubContainer = document.createElement("div");
      stubContainer.className = "tree-stub";

      const expandBtn = document.createElement("button");
      expandBtn.type = "button";
      expandBtn.className = "tree-expand-stub-btn";
      expandBtn.textContent = "Expand...";

      expandBtn.addEventListener("click", () => {
        void (async () => {
          expandBtn.disabled = true;
          expandBtn.textContent = "Loading...";
          try {
            const graph = await loadObtain();
            const targetId = input.item ?? node.item;
            const expanded = expandStub(targetId, graph, ancestors);
            const expandedEl = renderNode(expanded, ctx, [...ancestors, targetId]);
            stubContainer.replaceWith(expandedEl);
          } catch {
            expandBtn.textContent = "Failed to expand";
          }
        })();
      });

      stubContainer.append(expandBtn);
      itemEl.append(stubContainer);
    } else if (backRef) {
      // Rule 4 collapsed a repeated subtree to the node path where it was
      // first drawn. That path is an addressing detail of the walk, not
      // something a player can act on, so the chip reads as the plain fact it
      // stands for and the path stays on `title` for anyone debugging a tree.
      const refSpan = document.createElement("span");
      refSpan.className = "tree-back-reference";
      refSpan.textContent = "(shown above)";
      refSpan.title = backRef;
      headEl.append(refSpan);
    } else if (node.producers.length > 0) {
      const nextAncestors = input.item ? [...ancestors, input.item] : ancestors;
      const childNodeEl = renderNode(node, ctx, nextAncestors);
      itemEl.append(childNodeEl);
    }
  }

  return itemEl;
}

function renderProducer(
  producer: TreeProducer,
  ctx: RenderContext,
  ancestors: string[],
): HTMLElement {
  const row = document.createElement("div");
  row.className = "tree-producer-row";

  const header = document.createElement("div");
  header.className = "tree-producer-header";

  // No method badge: every row sits under a heading naming its own method
  // already, so a badge here only repeats the line above it.
  const source = sourceLabel(producer);
  if (source) {
    const sourceEl = document.createElement("span");
    sourceEl.className = "tree-source-label";
    sourceEl.textContent = source;
    header.append(sourceEl);
  }

  if (producer.station) {
    const stationBadge = document.createElement("span");
    stationBadge.className = "station-badge";
    stationBadge.textContent = STATION_LABELS[producer.station] ?? humanise(producer.station);
    header.append(stationBadge);
  }

  if (producer.note) {
    const noteBadge = document.createElement("span");
    noteBadge.className = "note-badge";
    noteBadge.textContent = producer.note;
    header.append(noteBadge);
  }

  row.append(header);

  if (producer.inputs.length > 0) {
    const inputsList = document.createElement("ul");
    inputsList.className = "tree-inputs-list";
    for (const input of producer.inputs) {
      inputsList.append(renderInput(input, ctx, ancestors));
    }
    row.append(inputsList);
  }

  return row;
}

function renderNode(node: ObtainNode, ctx: RenderContext, ancestors: string[]): HTMLElement {
  const nodeContainer = document.createElement("div");
  nodeContainer.className = "tree-node";

  const producers = node.producers;
  if (producers.length === 0) {
    return nodeContainer;
  }

  // Group by method, preserving order of first appearance
  const groups = new Map<string, TreeProducer[]>();
  for (const producer of producers) {
    const group = groups.get(producer.method);
    if (group) {
      group.push(producer);
    } else {
      groups.set(producer.method, [producer]);
    }
  }

  const orderedGroups = [...groups.entries()].sort(
    ([left], [right]) => methodRank(left) - methodRank(right),
  );

  for (const [method, groupProducers] of orderedGroups) {
    const groupEl = document.createElement("div");
    groupEl.className = "tree-method-group";

    const titleEl = document.createElement("h4");
    titleEl.className = `tree-method-title method-${method}`;
    titleEl.textContent = METHOD_LABELS[method] ?? method;
    groupEl.append(titleEl);

    // Render up to 3 producers initially
    const initialProducers = groupProducers.slice(0, 3);
    for (const producer of initialProducers) {
      groupEl.append(renderProducer(producer, ctx, ancestors));
    }

    // Overflow beyond 3 behind a control that builds it on first use.
    //
    // Building the overflow eagerly and hiding it with `display: none` costs
    // the whole subtree of every hidden producer, at every level of the walk,
    // for rows nobody has asked to see. Measured on `minecraft:emerald`, that
    // was 883 of 932 producer rows and 8,507 DOM nodes in one window. The cap
    // exists to bound what the page builds, so the rows have to not exist
    // until the reader opens them.
    if (groupProducers.length > 3) {
      const overflowProducers = groupProducers.slice(3);
      const overflowEl = document.createElement("div");
      overflowEl.className = "tree-group-overflow";
      overflowEl.hidden = true;
      groupEl.append(overflowEl);

      const toggleBtn = document.createElement("button");
      toggleBtn.type = "button";
      toggleBtn.className = "tree-more-button";
      const remainingCount = overflowProducers.length;
      const methodLabel = (METHOD_LABELS[method] ?? method).toLowerCase();
      const showText = `Show ${remainingCount.toString()} more ${methodLabel}...`;
      toggleBtn.textContent = showText;

      let built = false;
      toggleBtn.addEventListener("click", () => {
        if (!built) {
          for (const producer of overflowProducers) {
            overflowEl.append(renderProducer(producer, ctx, ancestors));
          }
          built = true;
        }
        overflowEl.hidden = !overflowEl.hidden;
        toggleBtn.textContent = overflowEl.hidden ? showText : `Show fewer ${methodLabel}`;
      });

      groupEl.append(toggleBtn);
    }

    nodeContainer.append(groupEl);
  }

  return nodeContainer;
}

/**
 * Renders an obtaining tree section:
 * - Title "Obtaining"
 * - Producers grouped by method
 * - Max 3 producers per group visible by default, rest behind expand control
 * - Inputs rendered as entityLinks or tag references
 * - Nested nodes indented under their respective inputs
 * - Stubs expandable on click
 */
export function renderRecipeTree(section: RecipeTree, ctx: RenderContext): HTMLElement | null {
  const rootNode = section.root as unknown as ObtainNode;
  if (rootNode.producers.length === 0) {
    return null;
  }

  const container = document.createElement("section");
  container.className = "entity-section recipe-tree-section";

  const title = document.createElement("h3");
  title.className = "section-title";
  title.textContent = "Obtaining";
  container.append(title);

  const rootItemId = rootNode.item;

  const treeEl = renderNode(rootNode, ctx, [rootItemId]);
  container.append(treeEl);

  return container;
}
