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
    producer.m === "mob_loot"
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
 * Read as a recipe this is real crafting, which is why the method filter let it
 * through and put "first obtain a Block of Iron" at the head of the Iron Ingot
 * branch. Read as a route it is circular: the block is made of the very item it
 * produces, so it can never be the cheaper way to get one.
 *
 * Only the unpacking direction goes. Packing -- nine Diamonds into a Block of
 * Diamond, nine Nuggets into an Ingot -- is a real thing a player makes, and it
 * is the recipe the Block of Diamond page exists to show. The two directions are
 * told apart by their arithmetic rather than by a list of block names: unpacking
 * consumes one and yields many, packing consumes many and yields one. A storage
 * block added in a later version therefore needs no update here.
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
 * looked at, and none of it extends a branch below the root. Unpacking a
 * storage block is dropped outright: see `isStorageRoundTrip`.
 */
function manipulationProducersOf(graph: Obtain, itemId: string): ObtainProducer[] {
  return (graph.producers[itemId] ?? []).filter((producer) => {
    if (isAcquisition(graph, producer)) {
      return false;
    }
    return !isStorageRoundTrip(graph, itemId, producer);
  });
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
  const members = inputSpec.mb ?? [];

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
    const hasMore = manipulationProducersOf(graph, itemId).length > 0;
    return {
      item: itemId,
      producers: [],
      expandable: hasMore,
      back_reference: null,
    };
  }

  const key = `${itemId}:${remainingDepth.toString()}`;
  const earlierPath = firstOccurrence.get(key);
  if (earlierPath !== undefined) {
    return {
      item: itemId,
      producers: [],
      expandable: false,
      back_reference: earlierPath,
    };
  }
  firstOccurrence.set(key, nodePath);

  const manipulationProducers = manipulationProducersOf(graph, itemId);

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

  for (const { producer, stations } of collapsedProducers) {
    const rawInputs = producer.in ?? [];
    const repeats = rawInputs.map(
      (inputSpec) => inputSpec.i !== undefined && path.has(inputSpec.i),
    );
    if (rawInputs.length > 0 && repeats.every(Boolean)) {
      continue;
    }

    const producerIndex = treeProducers.length;
    const inputs: TreeInput[] = [];

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
        firstOccurrence,
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
