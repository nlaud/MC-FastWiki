import type { Entity, RecipeTree, TradeTable } from "../../types/entity.js";
import type { IndexEntry } from "../../types/index.js";
import type { Obtain, ObtainProducer } from "../../types/obtain.js";
import { loadObtain } from "../../search/load.js";
import type { RenderContext } from "../context.js";
import { entityLink } from "../link.js";
import {
  type ObtainNode,
  type TreeInput,
  expandStub,
  isAcquisition,
  isOreSmelt,
  nodeDepth,
  sortStations,
  truncateNode,
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
 * What one attempt *is*, per method, for the "per attempt" half of the odds.
 *
 * The payload deliberately carries no noun for this -- `pa` is a bare
 * expected-count and the method already says what was attempted, so the
 * vocabulary lives here rather than being written once per producer into
 * every shard. A method absent from this map renders its rate without a
 * denominator instead of guessing a noun for it.
 */
const ATTEMPT_NOUN: Readonly<Record<string, string>> = {
  chest_loot: "chest",
  block_drop: "block",
  mob_loot: "kill",
  fishing: "catch",
  bartering: "gold",
  brushing: "brush",
  shearing: "shear",
  harvesting: "harvest",
  gift: "gift",
};

/**
 * Formats one producer's odds for display, or returns null when it has none.
 *
 * Three separate answers, because a player mid-match asks three different
 * questions: how likely is it, how many do I get, and how many should I
 * expect per try. The payload keeps them unrounded so this is the only place
 * that decides precision.
 *
 * Each of the three drops out on its own when it carries no information, and
 * a producer whose three all drop out renders no odds at all.
 *
 * - A chance of exactly 1 never renders as "100%". A producer that always
 *   fires says nothing by saying so.
 * - A count renders only as a range, or as a fixed stack above one.
 * - A rate drops out when the drop is both certain and fixed, because it can
 *   only restate the count. Breaking one cobblestone gives one cobblestone,
 *   and "1.0 per block" beside it is noise. A certain drop of a *range* keeps
 *   its rate, because the mean of that range is a real answer.
 */
export function formatOdds(
  producer: ObtainProducer,
): { chance: string | null; count: string | null; rate: string | null } | null {
  const { ch, cx, pa } = producer;
  if (ch === undefined || cx === undefined) {
    return null;
  }
  const low = producer.c ?? 1;
  const certain = ch >= 1;
  const fixed = low === cx;
  // Below 0.1% would render as "0.0%", which reads as impossible rather than
  // rare, so anything that small gets an explicit floor instead.
  const chance = certain ? null : ch < 0.001 ? "<0.1%" : `${(ch * 100).toFixed(ch < 0.1 ? 1 : 0)}%`;
  const count = !fixed ? `${low.toString()}-${cx.toString()}` : low > 1 ? low.toString() : null;
  const noun = ATTEMPT_NOUN[producer.m];
  const rate =
    pa === undefined || (certain && fixed)
      ? null
      : `${pa < 0.1 ? pa.toFixed(2) : pa.toFixed(1)}${noun ? ` per ${noun}` : ""}`;
  if (chance === null && count === null && rate === null) {
    return null;
  }
  return { chance, count, rate };
}

/**
 * Finds the mob a drop table is named after, never the item that shares its id.
 *
 * A mob and an item can hold the same registry id: the chicken mob and the raw
 * chicken item are both `minecraft:chicken`, as are cod, salmon and rabbit.
 * The build settles that collision by enumerating such a mob under an
 * `entity_type/` path and leaving the bare id to the item, so a lookup of the
 * bare id alone returned "Raw Chicken" for four mobs and linked the Feather
 * page's drop row to a food item.
 *
 * Two steps, in this order:
 *
 * 1. The `entity_type/` path, which only ever names an entity.
 * 2. The bare id, accepted only when the entry it finds really is a mob or an
 *    entity. Most mobs have no colliding item and are enumerated bare.
 *
 * A name that reaches neither returns null, and the caller prints plain text
 * rather than a wrong link. Four April Fools mobs land there today, and that
 * is the right answer for a mob this build does not enumerate.
 */
function lookupMob(mobName: string, ctx: RenderContext): IndexEntry | null {
  const path = mobName.toLowerCase().replace(/\s+/g, "_");
  const qualified = ctx.lookup(`minecraft:entity_type/${path}`);
  if (qualified) {
    return qualified;
  }
  const bare = ctx.lookup(`minecraft:${path}`);
  return bare && (bare.k === "mob" || bare.k === "entity") ? bare : null;
}

/**
 * Appends one producer's odds to a Sources row, when it has any.
 *
 * Every group in the panel builds its own row element -- block drops lead
 * with a block link, mob drops with "Dropped by", the rest with a curated
 * label -- so the odds attach through one function rather than being written
 * into each branch, which is what keeps a chest, a kill, and a barter
 * formatted identically.
 */
function appendOdds(li: HTMLElement, producer: ObtainProducer): void {
  const odds = formatOdds(producer);
  if (!odds) {
    return;
  }
  const oddsEl = document.createElement("span");
  oddsEl.className = "sources-odds";
  for (const [part, partClass] of [
    [odds.chance, "sources-odds-chance"],
    [odds.count, "sources-odds-count"],
    [odds.rate, "sources-odds-rate"],
  ] as const) {
    if (!part) continue;
    const partEl = document.createElement("span");
    partEl.className = partClass;
    partEl.textContent = part;
    oddsEl.append(partEl);
  }
  li.append(oddsEl);
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
  const afterPrefix = sourceId.includes("loot_table/")
    ? (sourceId.split("loot_table/")[1] ?? sourceId)
    : sourceId;
  const parts = afterPrefix.split("/");
  const leaf = parts.length > 1 ? parts.slice(1).join(" ") : (parts[0] ?? afterPrefix);
  const cleaned = leaf.replace(/\.json$/, "").replace(/[_/]+/g, " ");
  return titleCase(cleaned);
}

export const getSourceLabel = getChestSourceLabel;

/**
 * The documented display order of acquisition groups in the Sources panel.
 */
export const SOURCE_GROUP_ORDER: readonly {
  method: string;
  title: string;
  groupClass: string;
}[] = [
  { method: "chest_loot", title: "Chest Loot", groupClass: "sources-chest-group" },
  { method: "world_generation", title: "Natural Generation", groupClass: "sources-worldgen-group" },
  { method: "brushing", title: "Brushing", groupClass: "sources-brushing-group" },
  { method: "fishing", title: "Fishing", groupClass: "sources-fishing-group" },
  { method: "bartering", title: "Bartering", groupClass: "sources-bartering-group" },
  { method: "gift", title: "Gifts & Growth", groupClass: "sources-gift-group" },
  { method: "shearing", title: "Shearing", groupClass: "sources-shearing-group" },
  { method: "harvesting", title: "Harvesting", groupClass: "sources-harvesting-group" },
  { method: "smelting", title: "Smelting", groupClass: "sources-smelt-group" },
  { method: "block_drop", title: "Block Drops", groupClass: "sources-block-group" },
  { method: "mob_loot", title: "Mob Drops", groupClass: "sources-mob-group" },
  { method: "trade", title: "Villager Trades", groupClass: "sources-trade-group" },
];

interface SourcesData {
  producersByMethod: Map<string, ObtainProducer[]>;
  oreSmelts: ObtainProducer[];
  tradeTableSection?: TradeTable | undefined;
  sourcesMap?:
    | Record<
        string,
        { s?: string; c?: string; structure?: string; container?: string; ref?: string }
      >
    | undefined;
}

function renderSourcesPanel(data: SourcesData, ctx: RenderContext): HTMLElement | null {
  const hasSmelts = data.oreSmelts.length > 0;
  const hasTradeTable = Boolean(data.tradeTableSection);
  const hasAnyProducer = Array.from(data.producersByMethod.values()).some(
    (list) => list.length > 0,
  );

  if (!hasSmelts && !hasTradeTable && !hasAnyProducer) {
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

  for (const groupConfig of SOURCE_GROUP_ORDER) {
    if (groupConfig.method === "smelting") {
      if (data.oreSmelts.length > 0) {
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

        panelEl.append(renderGroup(groupConfig.title, smeltItems, groupConfig.groupClass));
      }
    } else if (groupConfig.method === "block_drop") {
      const blockDrops = data.producersByMethod.get("block_drop") ?? [];
      if (blockDrops.length > 0) {
        const blockItems = blockDrops.map((p) => {
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
          appendOdds(li, p);
          if (p.nt) {
            const noteBadge = document.createElement("span");
            noteBadge.className = "sources-note-badge";
            noteBadge.textContent = p.nt;
            li.append(noteBadge);
          }
          return li;
        });
        panelEl.append(renderGroup(groupConfig.title, blockItems, groupConfig.groupClass));
      }
    } else if (groupConfig.method === "mob_loot") {
      const mobDrops = data.producersByMethod.get("mob_loot") ?? [];
      if (mobDrops.length > 0) {
        const mobItems = mobDrops.map((p) => {
          const li = document.createElement("li");
          li.className = "sources-item sources-mob-item";

          const lead = document.createElement("span");
          lead.className = "sources-mob-label";
          lead.textContent = "Dropped by";
          li.append(lead);

          const mobName = p.src.replace(/^droptable\//, "").trim();
          const entry = mobName ? lookupMob(mobName, ctx) : null;

          if (entry) {
            li.append(entityLink({ id: entry.id, name: entry.n }, ctx));
          } else if (mobName) {
            const plain = document.createElement("span");
            plain.className = "sources-mob-name";
            plain.textContent = mobName;
            li.append(plain);
          }
          appendOdds(li, p);
          return li;
        });
        panelEl.append(renderGroup(groupConfig.title, mobItems, groupConfig.groupClass));
      }
    } else if (groupConfig.method === "trade") {
      const tradeProducers = data.producersByMethod.get("trade") ?? [];
      if (data.tradeTableSection || tradeProducers.length > 0) {
        const tradeGroup = document.createElement("div");
        tradeGroup.className = `sources-group ${groupConfig.groupClass}`;

        const subtitle = document.createElement("h5");
        subtitle.className = "sources-group-title";
        subtitle.textContent = groupConfig.title;
        tradeGroup.append(subtitle);

        if (data.tradeTableSection) {
          const tradeEl = renderTradeTable(data.tradeTableSection, ctx, { withoutTitle: true });
          if (tradeEl) {
            tradeGroup.append(tradeEl);
          }
        } else {
          const tradeList = document.createElement("ul");
          tradeList.className = "sources-list";
          for (const p of tradeProducers) {
            const li = document.createElement("li");
            li.className = "sources-item sources-trade-item";
            li.textContent = p.nt ?? p.src;
            tradeList.append(li);
          }
          tradeGroup.append(tradeList);
        }
        panelEl.append(tradeGroup);
      }
    } else {
      const producers = data.producersByMethod.get(groupConfig.method) ?? [];
      if (producers.length > 0) {
        const items = producers.map((p) => {
          const li = document.createElement("li");
          const itemClass =
            groupConfig.method === "chest_loot"
              ? "sources-chest-item"
              : `sources-${groupConfig.method}-item`;
          li.className = `sources-item ${itemClass}`;
          const label = document.createElement("span");
          const labelClass =
            groupConfig.method === "chest_loot"
              ? "sources-chest-label"
              : `sources-${groupConfig.method}-label`;
          label.className = `sources-source-label ${labelClass}`;
          const labelText = getChestSourceLabel(p.src, data.sourcesMap);

          // Link the label when the curated row names one entity or block a
          // page exists for -- the piglin you barter with, the sheep you
          // shear. `entityLink` falls back to plain text when the id is not in
          // the search index, so a ref naming something unshipped degrades to
          // exactly what this rendered before rather than to a dead link.
          const ref = data.sourcesMap?.[p.src]?.ref;
          const refEntry = ref ? ctx.lookup(ref) : null;
          if (ref && refEntry) {
            label.append(entityLink({ id: ref, name: labelText }, ctx));
          } else {
            label.textContent = labelText;
          }
          li.append(label);
          appendOdds(li, p);

          if (p.nt) {
            const noteBadge = document.createElement("span");
            noteBadge.className = "sources-note-badge";
            noteBadge.textContent = p.nt;
            li.append(noteBadge);
          }
          return li;
        });
        panelEl.append(renderGroup(groupConfig.title, items, groupConfig.groupClass));
      }
    }
  }

  return panelEl;
}

/**
 * How many alternatives are worth walking to find the shallowest shape.
 *
 * Past this, every alternative is drawn as a bare card instead. A tag that
 * large is a list of interchangeable materials rather than a branch worth
 * following, and walking all of them on first paint would cost more than the
 * shape it buys.
 */
const EAGER_MEMBER_LIMIT = 16;

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
 * the same member list, so they cannot drift apart.
 *
 * ## One shape for every alternative
 *
 * The alternatives on a slot rarely have subtrees of matching depth. A Golden
 * Helmet is a leaf, because the walk has already passed Gold Ingot and will not
 * loop back through it, while a Golden Axe still carries a stick branch. Drawn
 * as they come, the tree gained and lost a whole level roughly once a second
 * and everything below it jumped.
 *
 * So the alternatives are walked up front, the shallowest one decides the
 * shape, and the rest are truncated to match -- a deeper alternative gives up
 * the levels the shallowest was never going to show anyway. That is why these
 * subtrees are built eagerly rather than on the tick that needs them: the
 * shallowest cannot be known without seeing all of them. The walks are bounded
 * by the same depth cap as the rest of the tree, and past `EAGER_MEMBER_LIMIT`
 * members the shape is flattened to a leaf outright rather than walking a very
 * large tag.
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

  const built = new Map<string, ObtainNode>();
  for (const memberId of members) {
    if (members.length > EAGER_MEMBER_LIMIT) {
      break;
    }
    if (memberId === input.item) {
      built.set(memberId, baseNode);
      continue;
    }
    try {
      built.set(memberId, expandStub(memberId, graph, ancestors));
    } catch {
      // A member the graph cannot walk simply has no subtree to show.
    }
  }

  // The shallowest alternative sets the shape the whole cycle holds.
  const shape =
    built.size > 0 ? Math.min(...[...built.values()].map((node) => nodeDepth(node))) : 0;

  const shaped = new Map<string, ObtainNode>();
  for (const [memberId, node] of built) {
    shaped.set(memberId, truncateNode(node, shape));
  }

  const showMember = (memberId: string): void => {
    const childNode = shaped.get(memberId) ??
      // Past the eager limit every alternative is drawn as a bare card, which
      // is the one shape they are all guaranteed to share.
      { item: memberId, producers: [], expandable: false, back_reference: null };
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
  const producersByMethod = new Map<string, ObtainProducer[]>();
  for (const p of rawProducers) {
    const list = producersByMethod.get(p.m) ?? [];
    list.push(p);
    producersByMethod.set(p.m, list);
  }

  const oreSmelts = (producersByMethod.get("smelting") ?? []).filter((p) => {
    const inputId = p.in?.[0]?.i ?? p.in?.[0]?.t;
    return Boolean(inputId && isOreSmelt(inputId));
  });

  // A TradeTable means two different things depending on whose page carries
  // it, and only one of them belongs under "Obtaining".
  //
  // On an item or block page it lists the trades that GIVE this thing, which is
  // a way of getting it, so the Sources panel embeds it and groups it by the
  // profession selling it.
  //
  // On a seller's own page -- the 13 professions, and the wandering trader,
  // which is a mob because the `villager_profession` registry does not list it
  // -- the same section lists what that seller OFFERS. Embedding it here would
  // answer "how do I obtain a wandering trader" with the trader's own shop, and
  // would print all 97 rows a second time directly below the Trades section
  // that already showed them.
  const isSellerPage = entity?.kind === "profession" || entity?.kind === "mob";
  const tradeTableSection = isSellerPage
    ? undefined
    : entity?.sections.find((s): s is TradeTable => s.type === "TradeTable");

  const hasTreeContent = rootNode.producers.length > 0;
  const fallbackGraph = section.graph ?? { schemaVersion: 1, producers: {} };
  const hasSourcesContent =
    rawProducers.some((p) => isAcquisition(fallbackGraph, p)) || Boolean(tradeTableSection);

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
        producersByMethod,
        oreSmelts,
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
