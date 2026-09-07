import type {
  ChestSource,
  Obtain,
  ObtainMethod,
  ObtainProducer,
  ObtainProducerInput,
} from "../types/obtain.js";

export const DEFAULT_MAX_DEPTH = 4;
export const ROOT_PATH = "root";

export const COOKING_STATION_ORDER: readonly string[] = [
  "furnace",
  "blast_furnace",
  "smoker",
  "campfire",
];

export interface TreeInput {
  label: string;
  item: string | null;
  tag: string | null;
  count: number;
  members: string[];
  node: ObtainNode | null;
}

export interface TreeProducer {
  method: ObtainMethod;
  station: string | null;
  stations?: string[];
  note: string | null;
  source_id: string;
  inputs: TreeInput[];
  count: number;
  grid?: (number | null)[] | null;
  grid_width?: number | null;
  grid_height?: number | null;
}

export interface ObtainNode {
  item: string;
  producers: TreeProducer[];
  expandable: boolean;
  back_reference: string | null;
}

export interface ObtainTree {
  root: ObtainNode;
  rawProducers?: ObtainProducer[] | undefined;
  sources?: { [k: string]: ChestSource } | undefined;
}

export interface BuildTreeOptions {
  maxDepth?: number;
}

/**
 * Detects whether a producer is a way of *getting* an item rather than making one.
 *
 * The Sources panel renders exactly this set for the item being looked at, and
 * the tree renders exactly its complement, so both read the same rule from one
 * place instead of keeping two lists that could drift apart.
 */
export function isAcquisition(graph: Obtain, producer: ObtainProducer): boolean {
  if (
    producer.m === "trade" ||
    producer.m === "chest_loot" ||
    producer.m === "block_drop" ||
    producer.m === "mob_loot" ||
    producer.m === "brushing" ||
    producer.m === "harvesting" ||
    producer.m === "shearing" ||
    producer.m === "fishing" ||
    producer.m === "bartering" ||
    producer.m === "gift" ||
    producer.m === "world_generation"
  ) {
    return true;
  }
  if (producer.m === "smelting") {
    const firstInput = producer.in?.[0];
    const inputId = firstInput?.i ?? firstInput?.t;
    return Boolean(inputId && isOreSmelt(inputId));
  }
  return false;
}

/**
 * Detects whether a producer only unpacks a storage block back into the item it
 * was packed from -- Block of Iron into nine Iron Ingots, Block of Redstone into
 * nine Redstone.
 *
 * This is real crafting, and on the item's own page it is a real answer -- so
 * `manipulationProducersOf` keeps it at the root and only suppresses it deeper
 * in a tree, where it is circular: the block is made of the very item it
 * produces, so "first obtain a Block of Iron" sends the reader after nine of
 * the ingots they were trying to make.
 *
 * ## Two tests, because one is not enough
 *
 * The arithmetic finds a round trip: this producer consumes one and yields
 * many, and the thing it consumes has a recipe that consumes many of this and
 * yields one. Packing -- nine Diamonds into a Block of Diamond -- fails it and
 * stays, which is right, because that is the recipe the Block of Diamond page
 * exists to show.
 *
 * What the arithmetic cannot do is tell a Block of Iron from an Iron Ingot.
 * Opening an ingot into nine nuggets is the same shape as opening a block into
 * nine ingots, and it is how a player actually gets nuggets -- there is no
 * other recipe for them. So the input also has to name a block. Measured over
 * the whole 26.2 graph, twenty producers pass the arithmetic: seventeen are
 * storage blocks and the other three are exactly the ingot-into-nugget
 * recipes, so the suffix separates them cleanly with nothing left over.
 */
export function isStorageRoundTrip(
  graph: Obtain,
  outputId: string,
  producer: ObtainProducer,
): boolean {
  if (producer.m !== "crafting") {
    return false;
  }
  const inputs = producer.in ?? [];
  const only = inputs.length === 1 ? inputs[0] : undefined;
  const packedId = only?.i;
  if (!packedId || only.t !== undefined) {
    return false;
  }
  // Consumes one, yields many: the unpacking direction.
  if ((only.c ?? 1) !== 1 || (producer.c ?? 1) <= 1) {
    return false;
  }
  // And what it consumes is a block, not a larger unit of the same item.
  if (!packedId.replace(/^[a-z0-9_-]+:/, "").endsWith("_block")) {
    return false;
  }
  return (graph.producers[packedId] ?? []).some((reverse) => {
    if (reverse.m !== "crafting") {
      return false;
    }
    const reverseInputs = reverse.in ?? [];
    const reverseOnly = reverseInputs.length === 1 ? reverseInputs[0] : undefined;
    return reverseOnly?.i === outputId && (reverseOnly.c ?? 1) > 1;
  });
}

/**
 * Detects whether a producer crafts an ingot from nine nuggets of the same metal
 * -- nine Iron Nuggets into an Iron Ingot, nine Gold Nuggets into a Gold Ingot,
 * nine Copper Nuggets into a Copper Ingot.
 *
 * Like storage block unpacking, this is real crafting on the ingot's own page,
 * but below the root it is circular: nuggets come from ingots, or from smelting
 * tools/gear, so "first obtain nine Iron Nuggets" sends the reader down an
 * absurd detour instead of obtaining ingots from ore smelting.
 */
export function isIngotFromNuggets(
  graph: Obtain,
  outputId: string,
  producer: ObtainProducer,
): boolean {
  if (producer.m !== "crafting") {
    return false;
  }
  const inputs = producer.in ?? [];
  const only = inputs.length === 1 ? inputs[0] : undefined;
  const nuggetId = only?.i;
  if (!nuggetId || only.t !== undefined) {
    return false;
  }
  // Consumes many nuggets, yields one ingot.
  if ((only.c ?? 1) <= 1 || (producer.c ?? 1) !== 1) {
    return false;
  }
  // What it consumes is a nugget.
  if (!nuggetId.replace(/^[a-z0-9_-]+:/, "").endsWith("_nugget")) {
    return false;
  }
  return (graph.producers[nuggetId] ?? []).some((reverse) => {
    if (reverse.m !== "crafting") {
      return false;
    }
    const reverseInputs = reverse.in ?? [];
    const reverseOnly = reverseInputs.length === 1 ? reverseInputs[0] : undefined;
    return reverseOnly?.i === outputId && (reverse.c ?? 1) > 1;
  });
}

/**
 * Detects whether a smelt input represents an ore block, raw metal, or ancient debris.
 *
 * Smelting an ore into its material is how a player *gets* that material out of
 * the world, which puts it with chest loot and block drops rather than with
 * crafting: it belongs in the Sources panel for the item being looked at, and it
 * ends a branch rather than extending one anywhere below the root.
 */
export function isOreSmelt(inputId: string): boolean {
  const name = inputId.replace(/^[a-z0-9_-]+:/, "");
  return name.endsWith("_ore") || name.startsWith("raw_") || name === "ancient_debris";
}

export function sortStations(stations: string[]): string[] {
  return [...stations].sort((a, b) => {
    const idxA = COOKING_STATION_ORDER.indexOf(a);
    const idxB = COOKING_STATION_ORDER.indexOf(b);
    if (idxA !== -1 && idxB !== -1) return idxA - idxB;
    if (idxA !== -1) return -1;
    if (idxB !== -1) return 1;
    return a.localeCompare(b);
  });
}

/**
 * Every producer of `itemId` that the tree draws: manufacturing only.
 *
 * Acquisition -- chest loot, block drops, mob drops, trading, and smelting an
 * ore into its material -- is how a player gets a thing out of the world, not
 * how they build one. All of it goes to the Sources panel for the item being
 * looked at, and none of it extends a branch below the root.
 *
 * Unpacking a storage block and crafting an ingot from nine nuggets are questions
 * of depth rather than of whether they are real. Opening a Block of Iron into nine
 * ingots, or packing nine nuggets into an ingot, are things players do, and they
 * belong on the Iron Ingot page, so at the root they are kept. Below the root
 * they are not: a branch that opens with "first obtain a Block of Iron" or "first
 * obtain nine Iron Nuggets" sends the reader after circular recipes instead of
 * smelting ore.
 *
 * It also never leads. `sortRoundTripsLast` puts storage-block unpacking behind
 * every other way of making the item, so the page opens on nine nuggets
 * becoming an ingot and offers the block as the next option along.
 */
export function isDyeRecipe(producer: ObtainProducer): boolean {
  return producer.src.includes(":dye_") || producer.src.startsWith("dye_");
}

function sortDyeLast(producers: ObtainProducer[]): ObtainProducer[] {
  const hasBaseCraft = producers.some((p) => p.m === "crafting" && !isDyeRecipe(p));
  if (!hasBaseCraft) {
    return producers;
  }
  return [...producers].sort((left, right) => {
    const leftDye = isDyeRecipe(left) ? 1 : 0;
    const rightDye = isDyeRecipe(right) ? 1 : 0;
    return leftDye - rightDye;
  });
}

function manipulationProducersOf(graph: Obtain, itemId: string, isRoot: boolean): ObtainProducer[] {
  const kept = (graph.producers[itemId] ?? []).filter((producer) => {
    if (isAcquisition(graph, producer)) {
      return false;
    }
    return (
      isRoot ||
      (!isStorageRoundTrip(graph, itemId, producer) && !isIngotFromNuggets(graph, itemId, producer))
    );
  });
  return sortRoundTripsLast(graph, itemId, sortDyeLast(kept));
}

/** Orders storage-block unpacking behind every other way of making the item. */
function sortRoundTripsLast(
  graph: Obtain,
  itemId: string,
  producers: ObtainProducer[],
): ObtainProducer[] {
  const roundTrip = new Map(
    producers.map((producer) => [producer, isStorageRoundTrip(graph, itemId, producer)]),
  );
  // Stable: everything else keeps the graph's own order.
  return [...producers].sort(
    (left, right) => Number(roundTrip.get(left) ?? false) - Number(roundTrip.get(right) ?? false),
  );
}

interface CollapsedProducer {
  producer: ObtainProducer;
  stations: string[];
}

/** A producer's identity with input `skip` blanked out, for near-match grouping. */
function producerSignature(producer: ObtainProducer, skip: number): string {
  const inputs = (producer.in ?? []).map((input, index) =>
    index === skip ? "*" : `${input.i ?? ""}|${input.t ?? ""}|${(input.c ?? 1).toString()}`,
  );
  return [
    producer.m,
    producer.st ?? "",
    (producer.c ?? 1).toString(),
    (producer.gw ?? 0).toString(),
    (producer.gh ?? 0).toString(),
    JSON.stringify(producer.g ?? null),
    inputs.join(";"),
  ].join("#");
}

/**
 * Folds recipes that differ in exactly one ingredient into a single card.
 *
 * The game writes "coal or charcoal" as one ingredient sometimes and as two
 * whole recipes other times, and the difference is an encoding detail the
 * reader should never see. Two cards that are pixel-identical apart from one
 * slot read as two things to learn; one card whose slot cycles reads as the one
 * fact it is.
 *
 * The match is exact everywhere else -- same method, station, yield, grid shape
 * and every other ingredient -- so recipes that genuinely differ stay apart and
 * keep their own page behind the dots. Alternatives already collected on a slot
 * (an untagged alternatives list, or the smelting merge above) are carried
 * across rather than dropped, so folding twice cannot lose a member.
 */
function mergeNearIdentical(collapsed: CollapsedProducer[]): CollapsedProducer[] {
  const widest = collapsed.reduce(
    (max, entry) => Math.max(max, (entry.producer.in ?? []).length),
    0,
  );

  let current = collapsed;
  for (let slot = 0; slot < widest; slot++) {
    const buckets = new Map<string, CollapsedProducer[]>();
    const order: string[] = [];

    for (const entry of current) {
      if ((entry.producer.in ?? []).length <= slot) {
        // Cannot differ at a slot it does not have; keep it in a bucket of one.
        const key = `keep:${order.length.toString()}`;
        buckets.set(key, [entry]);
        order.push(key);
        continue;
      }
      const key = producerSignature(entry.producer, slot);
      const bucket = buckets.get(key);
      if (bucket) {
        bucket.push(entry);
      } else {
        buckets.set(key, [entry]);
        order.push(key);
      }
    }

    current = order.map((key) => {
      const bucket = buckets.get(key) ?? [];
      const lead = bucket[0];
      if (!lead || bucket.length === 1) {
        return lead as CollapsedProducer;
      }

      const alternatives: string[] = [];
      for (const entry of bucket) {
        const input = entry.producer.in?.[slot];
        if (!input) {
          continue;
        }
        for (const member of input.mb?.length ? input.mb : input.i ? [input.i] : []) {
          if (!alternatives.includes(member)) {
            alternatives.push(member);
          }
        }
      }

      const leadInputs = [...(lead.producer.in ?? [])];
      const leadInput = leadInputs[slot];
      if (!leadInput || alternatives.length < 2) {
        return lead;
      }
      const first = alternatives[0];
      if (first === undefined) {
        return lead;
      }
      leadInputs[slot] = { ...leadInput, i: first, mb: alternatives };

      return {
        producer: { ...lead.producer, in: leadInputs },
        stations: lead.stations,
      };
    });
  }

  return current;
}

/**
 * Narrows a tag's members to the plain form of each material.
 *
 * `#minecraft:oak_logs` resolves to four blocks -- the log, the six-sided wood,
 * and the stripped version of each -- and all four really do craft into planks.
 * Cycling all four says the same thing four times and, worse, changes what the
 * branch underneath looks like as it goes: an oak log is a leaf, while oak wood
 * is itself crafted from oak logs, so the tree gained and lost a level twice a
 * second. The plain log is the one a player actually has, so it is the one
 * shown; the others are the same material after a step that is not part of
 * getting there.
 *
 * The filter only applies when something survives it, so a tag made entirely of
 * stripped or six-sided blocks keeps all of its members.
 */
export function preferPlainMembers(members: readonly string[]): string[] {
  const plain = members.filter((id) => {
    const name = id.replace(/^[a-z0-9_-]+:/, "");
    return !name.startsWith("stripped_") && !name.endsWith("_wood") && !name.endsWith("_hyphae");
  });
  return plain.length > 0 ? plain : [...members];
}

/** How many levels of producers hang below `node`. A leaf is 0. */
export function nodeDepth(node: ObtainNode): number {
  let deepest = 0;
  for (const producer of node.producers) {
    for (const input of producer.inputs) {
      if (input.node) {
        deepest = Math.max(deepest, 1 + nodeDepth(input.node));
      }
    }
  }
  return deepest;
}

/**
 * Returns `node` with every branch below `limit` levels cut off.
 *
 * Used to hold one shape while a slot cycles. The alternatives on a cycling
 * slot rarely have subtrees of the same depth -- a golden helmet bottoms out at
 * once where a golden axe carries a stick branch under it -- so the tree grew
 * and shrank under the reader with every tick. Truncating each alternative to
 * the shallowest of them keeps the layout still, and what is cut is always the
 * part the shallowest alternative was not going to show anyway.
 */
export function truncateNode(node: ObtainNode, limit: number): ObtainNode {
  if (limit <= 0) {
    return { ...node, producers: [], expandable: false, back_reference: null };
  }
  return {
    ...node,
    producers: node.producers.map((producer) => ({
      ...producer,
      inputs: producer.inputs.map((input) =>
        input.node ? { ...input, node: truncateNode(input.node, limit - 1) } : input,
      ),
    })),
  };
}

function buildTreeInput(
  inputSpec: ObtainProducerInput,
  graph: Obtain,
  maxDepth: number,
  remainingDepth: number,
  path: ReadonlySet<string>,
  firstOccurrence: Map<string, string>,
  nodePath: string,
): [TreeInput, boolean] {
  const count = inputSpec.c ?? 1;
  const members = preferPlainMembers(inputSpec.mb ?? []);

  if (inputSpec.t !== undefined) {
    const label = inputSpec.t;
    let repItem: string | null = null;
    if (members.length > 0) {
      if (members.includes("minecraft:oak_planks")) {
        repItem = "minecraft:oak_planks";
      } else if (members.includes("minecraft:oak_log")) {
        repItem = "minecraft:oak_log";
      } else if (members.includes("minecraft:iron_ingot")) {
        repItem = "minecraft:iron_ingot";
      } else {
        repItem = members[0] ?? null;
      }
    }

    if (!repItem || path.has(repItem) || remainingDepth <= 0) {
      return [
        {
          label,
          item: repItem,
          tag: inputSpec.t,
          count,
          members,
          node: null,
        },
        Boolean(repItem && path.has(repItem)),
      ];
    }

    const childPath = new Set(path);
    childPath.add(repItem);

    const child = buildNode(
      repItem,
      graph,
      maxDepth,
      remainingDepth - 1,
      childPath,
      firstOccurrence,
      nodePath,
      false,
    );

    return [
      {
        label,
        item: repItem,
        tag: inputSpec.t,
        count,
        members,
        node: child,
      },
      false,
    ];
  }

  const itemId = inputSpec.i;
  if (!itemId) {
    throw new Error("ObtainProducerInput has neither tag nor item");
  }

  if (path.has(itemId)) {
    return [
      {
        label: itemId,
        item: itemId,
        tag: null,
        count,
        members: [],
        node: null,
      },
      true,
    ];
  }

  const childPath = new Set(path);
  childPath.add(itemId);

  const child = buildNode(
    itemId,
    graph,
    maxDepth,
    remainingDepth - 1,
    childPath,
    firstOccurrence,
    nodePath,
    false,
  );

  return [
    {
      label: itemId,
      item: itemId,
      tag: null,
      count,
      members,
      node: child,
    },
    false,
  ];
}

function buildNode(
  itemId: string,
  graph: Obtain,
  maxDepth: number,
  remainingDepth: number,
  path: ReadonlySet<string>,
  firstOccurrence: Map<string, string>,
  nodePath: string,
  isRoot = false,
): ObtainNode {
  if (remainingDepth <= 0 && !isRoot) {
    // An "Expand..." control is a promise that there is more tree behind it.
    // At the depth cap that promise is often empty: the item the walk stopped
    // on has no manufacturing producer at all, so expanding it only ever
    // yielded the one bare card the reader could have been shown outright.
    // Where that is the case, show the card and skip the click.
    const hasMore = manipulationProducersOf(graph, itemId, false).length > 0;
    return {
      item: itemId,
      producers: [],
      expandable: hasMore,
      back_reference: null,
    };
  }

  const manipulationProducers = manipulationProducersOf(graph, itemId, isRoot);

  // Collapse a repeated subtree to a pointer at where it was already drawn --
  // but only when there is a subtree to point at.
  //
  // An item with no recipe of its own draws a single card and nothing under it.
  // Replacing that card with "(shown above)" costs the reader the icon and the
  // name and saves nothing, because the thing being deduplicated was one card.
  // Raw materials repeat constantly across a tree, so this was most of the
  // chips on screen.
  const key = `${itemId}:${remainingDepth.toString()}`;
  const earlierPath = firstOccurrence.get(key);
  if (earlierPath !== undefined && manipulationProducers.length > 0) {
    return {
      item: itemId,
      producers: [],
      expandable: false,
      back_reference: earlierPath,
    };
  }
  firstOccurrence.set(key, nodePath);

  // 2. Smelting collapse, across both stations and ingredients.
  //
  // Every smelt that yields this item becomes one card. Two things get gathered
  // onto it, for the same reason: a player reads "smelt something into this" as
  // one fact, and splitting it produces near-identical cards that differ in a
  // detail the card itself already shows.
  //
  //   Stations. Cooked beef comes off a furnace, a smoker and a campfire as
  //   three producers of the same thing; they become three chips on one card.
  //
  //   Ingredients. Several different items can smelt into the same result, and
  //   those become alternatives on the single input slot, which cycles them the
  //   way a `#planks` tag slot cycles its twelve woods. This is the same reading
  //   the graph already applies to an untagged alternatives list.
  //
  // The grouping key is the yield, so a recipe that produces a different number
  // of the item stays a card of its own rather than being folded into one that
  // does not.
  const smeltGroups = new Map<number, ObtainProducer[]>();
  for (const producer of manipulationProducers) {
    if (producer.m === "smelting") {
      const yieldKey = producer.c ?? 1;
      const existing = smeltGroups.get(yieldKey);
      if (existing) {
        existing.push(producer);
      } else {
        smeltGroups.set(yieldKey, [producer]);
      }
    }
  }

  const collapsedProducers: Array<{
    producer: ObtainProducer;
    stations: string[];
  }> = [];

  const handledSmeltYields = new Set<number>();
  for (const producer of manipulationProducers) {
    if (producer.m === "smelting") {
      const yieldKey = producer.c ?? 1;
      if (handledSmeltYields.has(yieldKey)) {
        continue;
      }
      handledSmeltYields.add(yieldKey);
      const group = smeltGroups.get(yieldKey) ?? [producer];

      const stations = sortStations(
        Array.from(new Set(group.map((p) => p.st).filter((s): s is string => Boolean(s)))),
      );

      // Every distinct ingredient across the group, in the graph's own order,
      // folded onto the first producer's single input slot as its members.
      const alternatives: string[] = [];
      let tagged: ObtainProducerInput | null = null;
      for (const member of group) {
        const only = member.in?.[0];
        if (!only) {
          continue;
        }
        if (only.t !== undefined) {
          // A tag ingredient already carries its own member list; it is the
          // richer description, so it wins over a bare item alternative.
          tagged ??= only;
        } else if (only.i && !alternatives.includes(only.i)) {
          alternatives.push(only.i);
        }
      }

      let merged = producer;
      if (tagged) {
        merged = { ...producer, in: [tagged] };
      } else if (alternatives.length > 1) {
        const lead = alternatives[0];
        if (lead) {
          const first = producer.in?.[0];
          merged = {
            ...producer,
            in: [{ ...first, i: lead, mb: alternatives }],
          };
        }
      }

      collapsedProducers.push({
        producer: merged,
        stations,
      });
    } else {
      collapsedProducers.push({
        producer,
        stations: producer.st ? [producer.st] : [],
      });
    }
  }

  const treeProducers: TreeProducer[] = [];

  for (const { producer, stations } of mergeNearIdentical(collapsedProducers)) {
    const rawInputs = producer.in ?? [];
    const repeats = rawInputs.map(
      (inputSpec) => inputSpec.i !== undefined && path.has(inputSpec.i),
    );
    if (rawInputs.length > 0 && repeats.every(Boolean)) {
      continue;
    }

    const producerIndex = treeProducers.length;
    const inputs: TreeInput[] = [];

    // Each alternative recipe gets its own memo table.
    //
    // "(shown above)" is only honest when the reader can see the thing it
    // points at. Only one of a node's producers is on screen at a time -- the
    // others are behind the dots -- so a memo shared across them let a branch
    // of recipe two collapse into a pointer at a node drawn inside recipe one,
    // which is not above it, is not anywhere, and leaves the reader clicking
    // through recipes hunting for a subtree that was never rendered.
    //
    // Scoping the table to the producer keeps the collapse within one visible
    // subtree, where the pointer is true. The cost is bounded: the same item
    // may now be walked once per alternative rather than once per node, under
    // the same depth cap either way.
    const producerOccurrence = new Map(firstOccurrence);

    for (let inputIndex = 0; inputIndex < rawInputs.length; inputIndex++) {
      const inputSpec = rawInputs[inputIndex];
      if (!inputSpec) {
        continue;
      }
      const [treeInput] = buildTreeInput(
        inputSpec,
        graph,
        maxDepth,
        remainingDepth,
        path,
        producerOccurrence,
        `${nodePath}.producers.${producerIndex.toString()}.inputs.${inputIndex.toString()}`,
      );
      inputs.push(treeInput);
    }

    treeProducers.push({
      method: producer.m,
      station: stations[0] ?? producer.st ?? null,
      stations: stations.length > 0 ? stations : producer.st ? [producer.st] : [],
      note: producer.nt ?? null,
      source_id: producer.src,
      inputs,
      count: producer.c ?? 1,
      grid: producer.g ?? null,
      grid_width: producer.gw ?? null,
      grid_height: producer.gh ?? null,
    });
  }

  return {
    item: itemId,
    producers: treeProducers,
    expandable: false,
    back_reference: null,
  };
}

/**
 * Builds the obtain tree of an item under the workstation tree rules:
 * 1. Cycle: drop, do not draw.
 * 2. Memoize on (itemId, remainingDepth), not itemId alone.
 * 3. Depth cap -> expandable stub.
 * 4. Repeated-subtree collapse -> back_reference.
 * 5. Depth-aware filtering (manipulation only, ore smelts suppressed below root).
 * 6. Cooking station collapse into unified cards.
 */
export function buildObtainTree(
  itemId: string,
  graph: Obtain,
  options: BuildTreeOptions = {},
): ObtainTree {
  const maxDepth = options.maxDepth ?? DEFAULT_MAX_DEPTH;
  const path = new Set<string>([itemId]);
  const firstOccurrence = new Map<string, string>();

  return {
    root: buildNode(itemId, graph, maxDepth, maxDepth, path, firstOccurrence, ROOT_PATH, true),
    rawProducers: graph.producers[itemId] ?? [],
    sources: graph.sources,
  };
}

/**
 * Continues a capped walk from an expandable stub as a fresh sub-root.
 * Carries ancestor path so cycle detection (Rule 1) holds across the seam,
 * with its own memo table for the newly expanded subtree.
 */
export function expandStub(
  itemId: string,
  graph: Obtain,
  ancestors: Iterable<string>,
  options: BuildTreeOptions = {},
): ObtainNode {
  const maxDepth = options.maxDepth ?? DEFAULT_MAX_DEPTH;
  const path = new Set<string>(ancestors);
  path.add(itemId);
  const firstOccurrence = new Map<string, string>();

  return buildNode(itemId, graph, maxDepth, maxDepth, path, firstOccurrence, ROOT_PATH, false);
}
