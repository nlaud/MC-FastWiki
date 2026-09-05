import type { Entity, RecipeTree, TradeTable } from "../../types/entity.js";
import type { Obtain, ObtainProducer } from "../../types/obtain.js";
import { loadObtain } from "../../search/load.js";
import type { RenderContext } from "../context.js";
import { entityLink } from "../link.js";
import {
  type ObtainNode,
  type TreeInput,
  expandStub,
  isOreSmelt,
  sortStations,
} from "../obtain-tree.js";
import { subscribeTicker } from "../station/ticker.js";
import { renderLeafCard, renderStationCard } from "../station/index.js";
import { renderTradeTable } from "./trade-table.js";

function titleCase(str: string): string {
  return str
    .split(/\s+/)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(" ");
}

function humaniseId(id: string): string {
  const bare = id.replace(/^[a-z0-9_-]+:/, "");
  return bare
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/**
 * Returns a human-readable Title Case label for a chest loot source.
 * Uses curated structure/container mapping when available.
 */
export function getChestSourceLabel(
  sourceId: string,
  sources?: Record<string, { s?: string; c?: string; structure?: string; container?: string }>,
): string {
  const curated = sources?.[sourceId];
  if (curated) {
    const struct = curated.structure ?? curated.s;
    const cont = curated.container ?? curated.c;
    if (struct && cont) {
      return struct === cont ? struct : `${struct} - ${cont}`;
    }
  }

  // Fallback: Title Case from path
  const afterChests = sourceId.split("chests/").pop() ?? sourceId;
  const cleaned = afterChests.replace(/\.json$/, "").replace(/[_/]+/g, " ");
  return titleCase(cleaned);
}

interface SourcesData {
  chestLoot: ObtainProducer[];
  oreSmelts: ObtainProducer[];
  blockDrops: ObtainProducer[];
  mobDrops: ObtainProducer[];
  tradeProducers: ObtainProducer[];
  tradeTableSection?: TradeTable | undefined;
  sourcesMap?:
    Record<string, { s?: string; c?: string; structure?: string; container?: string }> | undefined;
}

function renderSourcesPanel(data: SourcesData, ctx: RenderContext): HTMLElement | null {
  const hasChest = data.chestLoot.length > 0;
  const hasOreSmelts = data.oreSmelts.length > 0;
  const hasBlocks = data.blockDrops.length > 0;
  const hasMobs = data.mobDrops.length > 0;
  const hasTrades = Boolean(data.tradeTableSection) || data.tradeProducers.length > 0;

  if (!hasChest && !hasOreSmelts && !hasBlocks && !hasMobs && !hasTrades) {
    return null;
  }

  const panelEl = document.createElement("div");
  panelEl.className = "obtaining-sources-pane";

  const panelTitle = document.createElement("h4");
  panelTitle.className = "sources-pane-title";
  panelTitle.textContent = "Sources";
  panelEl.append(panelTitle);

  const INITIAL_LIMIT = 3;

  function renderGroup(title: string, items: HTMLElement[], groupClass: string): HTMLElement {
    const groupEl = document.createElement("div");
    groupEl.className = `sources-group ${groupClass}`;

    const subtitle = document.createElement("h5");
    subtitle.className = "sources-group-title";
    subtitle.textContent = title;
    groupEl.append(subtitle);

    const listEl = document.createElement("ul");
    listEl.className = "sources-list";

    const initial = items.slice(0, INITIAL_LIMIT);
    for (const item of initial) {
      listEl.append(item);
    }
    groupEl.append(listEl);

    if (items.length > INITIAL_LIMIT) {
      const overflow = items.slice(INITIAL_LIMIT);
      const overflowContainer = document.createElement("ul");
      overflowContainer.className = "sources-list sources-overflow";
      overflowContainer.hidden = true;
      groupEl.append(overflowContainer);

      const toggleBtn = document.createElement("button");
      toggleBtn.type = "button";
      toggleBtn.className = "sources-more-button";
      const remaining = overflow.length;
      const showText = `Show ${remaining.toString()} more ${title.toLowerCase()}...`;
      toggleBtn.textContent = showText;

      let built = false;
      toggleBtn.addEventListener("click", () => {
        if (!built) {
          for (const item of overflow) {
            overflowContainer.append(item);
          }
          built = true;
        }
        overflowContainer.hidden = !overflowContainer.hidden;
        toggleBtn.textContent = overflowContainer.hidden
          ? showText
          : `Show fewer ${title.toLowerCase()}`;
      });

      groupEl.append(toggleBtn);
    }

    return groupEl;
  }

  // 1. Chest Loot
  if (hasChest) {
    const chestItems = data.chestLoot.map((p) => {
      const li = document.createElement("li");
      li.className = "sources-item sources-chest-item";
      const label = document.createElement("span");
      label.className = "sources-chest-label";
      label.textContent = getChestSourceLabel(p.src, data.sourcesMap);
      li.append(label);
      return li;
    });
    panelEl.append(renderGroup("Chest Loot", chestItems, "sources-chest-group"));
  }

  // 2. Smelting an ore into this material.
  //
  // This is the one acquisition route that is also a recipe, so it earns a
  // group of its own rather than a line of prose: a reader on the Diamond page
  // wants to see that Diamond Ore smelts into it, next to the chests it turns
  // up in. Below the root it never appears at all -- see `isAcquisition`.
  if (hasOreSmelts) {
    // One row per ore, not per station. Diamond is smelted from two ores at two
    // stations, which arrives here as four producers and reads as four separate
    // facts unless the stations are gathered back onto the ore they belong to.
    const byOre = new Map<string, Set<string>>();
    for (const p of data.oreSmelts) {
      const inputId = p.in?.[0]?.i;
      if (!inputId) {
        continue;
      }
      const stations = byOre.get(inputId) ?? new Set<string>();
      if (p.st) {
        stations.add(p.st);
      }
      byOre.set(inputId, stations);
    }

    const smeltItems = [...byOre.entries()].map(([inputId, stations]) => {
      const li = document.createElement("li");
      li.className = "sources-item sources-smelt-item";

      const entry = ctx.lookup(inputId);
      li.append(entityLink({ id: inputId, name: entry?.n ?? humaniseId(inputId) }, ctx));

      for (const station of sortStations([...stations])) {
        const stationBadge = document.createElement("span");
        stationBadge.className = "sources-note-badge";
        stationBadge.textContent = humaniseId(station);
        li.append(stationBadge);
      }
      return li;
    });
    panelEl.append(renderGroup("Smelting", smeltItems, "sources-smelt-group"));
  }

  // 3. Block Drops
  if (hasBlocks) {
    const blockItems = data.blockDrops.map((p) => {
      const li = document.createElement("li");
      li.className = "sources-item sources-block-item";
      const blockInput = p.in?.[0];
      const blockId = blockInput?.i;
      if (blockId) {
        const entry = ctx.lookup(blockId);
        const link = entityLink(
          {
            id: blockId,
            name: entry?.n ?? humaniseId(blockId),
          },
          ctx,
        );
        li.append(link);
      }
      if (p.nt) {
        const noteBadge = document.createElement("span");
        noteBadge.className = "sources-note-badge";
        noteBadge.textContent = p.nt;
        li.append(noteBadge);
      }
      return li;
    });
    panelEl.append(renderGroup("Block Drops", blockItems, "sources-block-group"));
  }

  // 4. Mob Drops
  if (hasMobs) {
    const mobItems = data.mobDrops.map((p) => {
      const li = document.createElement("li");
      li.className = "sources-item sources-mob-item";

      const lead = document.createElement("span");
      lead.className = "sources-mob-label";
      lead.textContent = "Dropped by";
      li.append(lead);

      // `src` is `droptable/<Mob display name>`, and `nt` repeats it as
      // "dropped by <Mob>". The name is the only handle on the mob either field
      // gives, so the id is rebuilt from it and only becomes a link once the
      // index confirms it resolves -- a mob whose page does not exist stays as
      // plain text rather than becoming a dead link.
      const mobName = p.src.replace(/^droptable\//, "").trim();
      const mobId = `minecraft:${mobName.toLowerCase().replace(/\s+/g, "_")}`;
      const entry = mobName ? ctx.lookup(mobId) : null;

      if (entry) {
        li.append(entityLink({ id: mobId, name: entry.n }, ctx));
      } else if (mobName) {
        const plain = document.createElement("span");
        plain.className = "sources-mob-name";
        plain.textContent = mobName;
        li.append(plain);
      }
      return li;
    });
    panelEl.append(renderGroup("Mob Drops", mobItems, "sources-mob-group"));
  }

  // 5. Trades
  if (hasTrades) {
    const tradeGroup = document.createElement("div");
    tradeGroup.className = "sources-group sources-trade-group";

    const subtitle = document.createElement("h5");
    subtitle.className = "sources-group-title";
    subtitle.textContent = "Villager Trades";
    tradeGroup.append(subtitle);

    if (data.tradeTableSection) {
      const tradeEl = renderTradeTable(data.tradeTableSection, ctx, { withoutTitle: true });
      if (tradeEl) {
        tradeGroup.append(tradeEl);
      }
    } else {
      const tradeList = document.createElement("ul");
      tradeList.className = "sources-list";
      for (const p of data.tradeProducers) {
        const li = document.createElement("li");
        li.className = "sources-item sources-trade-item";
        li.textContent = p.nt ?? p.src;
        tradeList.append(li);
      }
      tradeGroup.append(tradeList);
    }
    panelEl.append(tradeGroup);
  }

  return panelEl;
}

/**
 * Draws one child branch, and keeps it in step with its parent slot's cycle.
 *
 * A tag ingredient such as `#minecraft:planks` is drawn as one slot that cycles
 * through the twelve planks it resolves to, but the branch under that slot was
 * built once, from the tag's representative member. So the slot advanced to
 * Spruce Planks while the branch below it still read "Oak Planks, from Oak Log"
 * -- the logs never changed with the planks, which is exactly what a reader
 * notices first.
 *
 * Both sides now advance off the same shared ticker with the same modulo over
 * the same member list, so they cannot drift apart. Subtrees are built on the
 * tick that first needs them and cached from then on, so cycling a twelve-member
 * tag costs twelve walks spread over twelve seconds rather than twelve walks up
 * front, and a member nobody ever sees is never walked at all.
 */
function renderBranch(
  branchEl: HTMLElement,
  input: TreeInput,
  ctx: RenderContext,
  ancestors: string[],
  graph: Obtain | null,
): void {
  const draw = (childNode: ObtainNode, itemId: string | null): void => {
    const nextAncestors = itemId ? [...ancestors, itemId] : ancestors;
    branchEl.replaceChildren(renderTreeNode(childNode, ctx, nextAncestors, graph));
  };

  const baseNode = input.node;
  if (!baseNode) {
    return;
  }

  const members = input.members;
  if (!graph || members.length < 2) {
    draw(baseNode, input.item);
    return;
  }

  const cache = new Map<string, ObtainNode>();
  if (input.item) {
    cache.set(input.item, baseNode);
  }

  const showMember = (memberId: string): void => {
    let childNode = cache.get(memberId);
    if (!childNode) {
      try {
        childNode = expandStub(memberId, graph, ancestors);
      } catch {
        return;
      }
      cache.set(memberId, childNode);
    }
    draw(childNode, memberId);
  };

  const first = members[0];
  showMember(first ?? input.item ?? "");

  subscribeTicker((tick) => {
    const memberId = members[tick % members.length];
    if (memberId) {
      showMember(memberId);
    }
  });
}

function renderTreeNode(
  node: ObtainNode,
  ctx: RenderContext,
  ancestors: string[],
  graph: Obtain | null,
): HTMLElement {
  const nodeContainer = document.createElement("div");
  nodeContainer.className = "tree-node";

  const cardWrapper = document.createElement("div");
  cardWrapper.className = "tree-node-card";
  nodeContainer.append(cardWrapper);

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
          const targetId = node.item;
          const expanded = expandStub(targetId, graph, ancestors);
          const expandedEl = renderTreeNode(expanded, ctx, [...ancestors, targetId], graph);
          nodeContainer.replaceWith(expandedEl);
        } catch {
          expandBtn.textContent = "Failed to expand";
        }
      })();
    });

    stubContainer.append(expandBtn);
    cardWrapper.append(stubContainer);
    return nodeContainer;
  }

  if (backRef) {
    const refSpan = document.createElement("span");
    refSpan.className = "tree-back-reference";
    refSpan.textContent = "(shown above)";
    refSpan.title = backRef;
    cardWrapper.append(refSpan);
    return nodeContainer;
  }

  if (node.producers.length === 0) {
    // Leaf node: item with no manipulation producers
    const leafCard = renderLeafCard(node.item, ctx);
    cardWrapper.append(leafCard);
    return nodeContainer;
  }

  // Node with 1 or more producers
  let activeIndex = 0;
  const childrenContainer = document.createElement("div");
  childrenContainer.className = "tree-children";
  nodeContainer.append(childrenContainer);

  const updateCardAndChildren = (): void => {
    cardWrapper.replaceChildren();
    childrenContainer.replaceChildren();

    const activeProducer = node.producers[activeIndex];
    if (!activeProducer) return;

    const card = renderStationCard(activeProducer, node.item, ctx, {
      activeProducerIndex: activeIndex,
      totalProducers: node.producers.length,
      onSelectProducer: (newIdx) => {
        activeIndex = newIdx;
        updateCardAndChildren();
      },
    });
    cardWrapper.append(card);

    // Build children branches for active producer
    const childInputs = activeProducer.inputs.filter((i: TreeInput) => i.node !== null);
    if (childInputs.length > 0) {
      childrenContainer.hidden = false;
      for (const input of childInputs) {
        if (!input.node) continue;
        const branchEl = document.createElement("div");
        branchEl.className = "tree-branch";
        childrenContainer.append(branchEl);
        renderBranch(branchEl, input, ctx, ancestors, graph);
      }
      markRows(childrenContainer);
    } else {
      childrenContainer.hidden = true;
    }
  };

  updateCardAndChildren();
  return nodeContainer;
}

/**
 * Marks the first and last branch on each line of a layer.
 *
 * The sibling bar is drawn in CSS as one segment per branch: the branch at the
 * start of a line draws only its right half and the one at the end only its
 * left, so the bar runs centre to centre and no further. That needs to know
 * where each line begins and ends, and CSS has no selector for "first on its
 * line" -- `:first-child` is per-container, so once a layer wrapped it marked
 * one branch out of the whole layer and every line after the first got a bar
 * running off both ends.
 *
 * Grouping by `offsetTop` is the whole measurement: one read per branch, redone
 * only when the layer actually changes size. A line holding a single branch
 * needs no bar at all.
 */
function markRows(container: HTMLElement): void {
  const apply = (): void => {
    const branches = [...container.children] as HTMLElement[];
    if (branches.length === 0) {
      return;
    }

    const rows = new Map<number, HTMLElement[]>();
    for (const branch of branches) {
      const row = rows.get(branch.offsetTop) ?? [];
      row.push(branch);
      rows.set(branch.offsetTop, row);
    }

    for (const row of rows.values()) {
      const last = row.length - 1;
      row.forEach((branch, index) => {
        branch.classList.toggle("is-row-single", row.length === 1);
        branch.classList.toggle("is-row-start", row.length > 1 && index === 0);
        branch.classList.toggle("is-row-end", row.length > 1 && index === last);
      });
    }
  };

  apply();

  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(apply).observe(container);
  }
}

export interface RecipeTreeSectionData extends RecipeTree {
  rawProducers?: ObtainProducer[] | undefined;
  /**
   * The whole producer graph, so a cycling tag branch can walk a member the
   * pre-built tree never visited. See `renderBranch`.
   */
  graph?: Obtain | undefined;
  sources?:
    Record<string, { s?: string; c?: string; structure?: string; container?: string }> | undefined;
}

/**
 * Renders an Obtaining section:
 * - Title "Obtaining"
 * - Two-pane Obtaining shell:
 *   - Left pane (.obtaining-tree-pane): Centered tree of workstation GUI cards with pure CSS connector lines.
 *   - Right pane (.obtaining-sources-pane): Flat list of root acquisition sources (chest loot, block drops, mob drops, villager trades).
 */
export function renderRecipeTree(
  section: RecipeTreeSectionData,
  ctx: RenderContext,
  entity?: Entity,
): HTMLElement | null {
  const rootNode = section.root as unknown as ObtainNode;

  // Collect raw acquisition producers for the root item
  const rawProducers = section.rawProducers ?? [];
  const chestLoot = rawProducers.filter((p) => p.m === "chest_loot");
  const oreSmelts = rawProducers.filter((p) => {
    if (p.m !== "smelting") {
      return false;
    }
    const inputId = p.in?.[0]?.i ?? p.in?.[0]?.t;
    return Boolean(inputId && isOreSmelt(inputId));
  });
  const blockDrops = rawProducers.filter((p) => p.m === "block_drop");
  const mobDrops = rawProducers.filter((p) => p.m === "mob_loot");
  const tradeProducers = rawProducers.filter((p) => p.m === "trade");

  const tradeTableSection = entity?.sections.find((s): s is TradeTable => s.type === "TradeTable");

  const hasTreeContent = rootNode.producers.length > 0;
  const hasSourcesContent =
    chestLoot.length > 0 ||
    oreSmelts.length > 0 ||
    blockDrops.length > 0 ||
    mobDrops.length > 0 ||
    tradeProducers.length > 0 ||
    Boolean(tradeTableSection);

  // If there's neither manipulation tree content nor acquisition sources:
  if (!hasTreeContent && !hasSourcesContent) {
    return null;
  }

  const container = document.createElement("section");
  container.className = "entity-section recipe-tree-section";

  const title = document.createElement("h3");
  title.className = "section-title";
  title.textContent = "Obtaining";
  container.append(title);

  const shellEl = document.createElement("div");
  shellEl.className = "obtaining-shell";

  // Left pane: Workstation Tree.
  //
  // Only when there is a tree to draw. Honeycomb comes out of a chest and out
  // of nothing else, so every producer it has is acquisition; drawing the pane
  // anyway left a lone root card standing on its own with no branch under it,
  // which reads as a broken tree rather than as "there is no recipe".
  if (hasTreeContent) {
    const treePaneEl = document.createElement("div");
    treePaneEl.className = "obtaining-tree-pane";

    const rootItemId = rootNode.item;
    const treeRootEl = renderTreeNode(rootNode, ctx, [rootItemId], section.graph ?? null);
    treePaneEl.append(treeRootEl);
    shellEl.append(treePaneEl);
  } else {
    shellEl.classList.add("is-sources-only");
  }

  // Right pane: Sources panel
  if (hasSourcesContent) {
    const sourcesPaneEl = renderSourcesPanel(
      {
        chestLoot,
        oreSmelts,
        blockDrops,
        mobDrops,
        tradeProducers,
        tradeTableSection,
        sourcesMap: section.sources,
      },
      ctx,
    );
    if (sourcesPaneEl) {
      shellEl.append(sourcesPaneEl);
    }
  }

  container.append(shellEl);
  return container;
}
