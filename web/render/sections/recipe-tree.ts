import type { Entity, RecipeTree, TradeTable } from "../../types/entity.js";
import type { ObtainProducer } from "../../types/obtain.js";
import { loadObtain } from "../../search/load.js";
import type { RenderContext } from "../context.js";
import { entityLink } from "../link.js";
import { type ObtainNode, type TreeInput, expandStub } from "../obtain-tree.js";
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
  blockDrops: ObtainProducer[];
  mobDrops: ObtainProducer[];
  tradeProducers: ObtainProducer[];
  tradeTableSection?: TradeTable | undefined;
  sourcesMap?:
    Record<string, { s?: string; c?: string; structure?: string; container?: string }> | undefined;
}

function renderSourcesPanel(data: SourcesData, ctx: RenderContext): HTMLElement | null {
  const hasChest = data.chestLoot.length > 0;
  const hasBlocks = data.blockDrops.length > 0;
  const hasMobs = data.mobDrops.length > 0;
  const hasTrades = Boolean(data.tradeTableSection) || data.tradeProducers.length > 0;

  if (!hasChest && !hasBlocks && !hasMobs && !hasTrades) {
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

  // 2. Block Drops
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

  // 3. Mob Drops
  if (hasMobs) {
    const mobItems = data.mobDrops.map((p) => {
      const li = document.createElement("li");
      li.className = "sources-item sources-mob-item";
      const text = p.nt ?? p.src.replace(/^droptable\//, "Dropped by ");
      const span = document.createElement("span");
      span.className = "sources-mob-label";
      span.textContent = text;
      li.append(span);
      return li;
    });
    panelEl.append(renderGroup("Mob Drops", mobItems, "sources-mob-group"));
  }

  // 4. Trades
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

function renderTreeNode(node: ObtainNode, ctx: RenderContext, ancestors: string[]): HTMLElement {
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
          const expandedEl = renderTreeNode(expanded, ctx, [...ancestors, targetId]);
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
    const leafCard = renderLeafCard(node.item, ctx, { isRaw: node.is_raw });
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
        const nextAncestors = input.item ? [...ancestors, input.item] : ancestors;
        const childNodeEl = renderTreeNode(input.node, ctx, nextAncestors);
        branchEl.append(childNodeEl);
        childrenContainer.append(branchEl);
      }
    } else {
      childrenContainer.hidden = true;
    }
  };

  updateCardAndChildren();
  return nodeContainer;
}

export interface RecipeTreeSectionData extends RecipeTree {
  rawProducers?: ObtainProducer[] | undefined;
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
  const blockDrops = rawProducers.filter((p) => p.m === "block_drop");
  const mobDrops = rawProducers.filter((p) => p.m === "mob_loot");
  const tradeProducers = rawProducers.filter((p) => p.m === "trade");

  const tradeTableSection = entity?.sections.find((s): s is TradeTable => s.type === "TradeTable");

  const hasTreeContent = rootNode.producers.length > 0;
  const hasSourcesContent =
    chestLoot.length > 0 ||
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

  // Left pane: Workstation Tree
  const treePaneEl = document.createElement("div");
  treePaneEl.className = "obtaining-tree-pane";

  const rootItemId = rootNode.item;
  const treeRootEl = renderTreeNode(rootNode, ctx, [rootItemId]);
  treePaneEl.append(treeRootEl);
  shellEl.append(treePaneEl);

  // Right pane: Sources panel
  if (hasSourcesContent) {
    const sourcesPaneEl = renderSourcesPanel(
      {
        chestLoot,
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
