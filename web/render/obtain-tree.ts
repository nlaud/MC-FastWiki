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
  /**
   * Whether nothing in the graph *makes* this item -- it is only ever gathered.
   *
   * A node can end up with an empty `producers` list for two very different
   * reasons: the item is genuinely raw, or every producer it does have was
   * removed by the depth-1 method filter or by cycle detection. The renderer's
   * "Raw material" badge is a claim about the first case only, and reading it
   * off `producers.length === 0` asserted it for the second case too -- which
   * is how Block of Iron, an item crafted from nine ingots, came to be
   * labelled a raw material under Iron Ingot.
   *
   * "Raw" is the absence of a *manipulation* producer, not the absence of
   * every producer. An oak log is mined and nothing crafts, smelts, brews or
   * fills it into being, so its lone `block_drop` producer leaves it raw. A
   * block of iron has a crafting recipe, so it never is.
   */
  is_raw: boolean;
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
 * Returns whether nothing in the graph makes `itemId` -- see `ObtainNode.is_raw`.
 *
 * Deliberately ignores the depth and cycle state of any particular walk: this
 * is a fact about the item, not about where it happened to land in one tree.
 */
function isRawMaterial(graph: Obtain, itemId: string): boolean {
  const producers = graph.producers[itemId] ?? [];
  return !producers.some(
    (producer) =>
      producer.m === "crafting" ||
      producer.m === "smelting" ||
      producer.m === "brewing" ||
      producer.m === "filling",
  );
}

/**
 * Detects whether a smelt input represents an ore block, raw metal, or ancient debris.
 * Used to suppress ore smelting below the root item in obtain trees.
 */
export function isOreSmelt(inputId: string): boolean {
  const name = inputId.replace(/^[a-z0-9_-]+:/, "");
  return name.endsWith("_ore") || name.startsWith("raw_") || name === "ancient_debris";
}

function sortStations(stations: string[]): string[] {
  return [...stations].sort((a, b) => {
    const idxA = COOKING_STATION_ORDER.indexOf(a);
    const idxB = COOKING_STATION_ORDER.indexOf(b);
    if (idxA !== -1 && idxB !== -1) return idxA - idxB;
    if (idxA !== -1) return -1;
    if (idxB !== -1) return 1;
    return a.localeCompare(b);
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
    return {
      item: itemId,
      producers: [],
      expandable: true,
      back_reference: null,
      is_raw: isRawMaterial(graph, itemId),
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
      is_raw: isRawMaterial(graph, itemId),
    };
  }
  firstOccurrence.set(key, nodePath);

  const rawProducers = graph.producers[itemId] ?? [];

  // 1. Depth-aware filtering:
  // - Root shows manipulation methods (crafting, smelting, brewing, filling).
  //   Acquisition methods (chest_loot, block_drop, mob_loot, trade) go to the Sources panel.
  // - Sub-items (depth >= 1) keep manipulation methods, EXCEPT smelting where input is an ore/raw/ancient debris.
  //   Acquisition methods are dropped so sub-items become leaves.
  const manipulationProducers = rawProducers.filter((producer) => {
    if (
      producer.m === "trade" ||
      producer.m === "chest_loot" ||
      producer.m === "block_drop" ||
      producer.m === "mob_loot"
    ) {
      return false;
    }
    if (producer.m === "smelting" && !isRoot) {
      const firstInput = producer.in?.[0];
      const inputId = firstInput?.i ?? firstInput?.t;
      if (inputId && isOreSmelt(inputId)) {
        return false;
      }
    }
    return true;
  });

  // 2. Cooking station collapse:
  // Smelting producers with the same inputs collapse into one card carrying all applicable stations.
  const smeltGroups = new Map<string, ObtainProducer[]>();
  for (const producer of manipulationProducers) {
    if (producer.m === "smelting") {
      const inputKey = (producer.in ?? [])
        .map((i) => `${i.i ?? ""}:${i.t ?? ""}:${(i.c ?? 1).toString()}`)
        .join(";");
      const existing = smeltGroups.get(inputKey);
      if (existing) {
        existing.push(producer);
      } else {
        smeltGroups.set(inputKey, [producer]);
      }
    }
  }

  const collapsedProducers: Array<{
    producer: ObtainProducer;
    stations: string[];
  }> = [];

  const handledSmeltKeys = new Set<string>();
  for (const producer of manipulationProducers) {
    if (producer.m === "smelting") {
      const inputKey = (producer.in ?? [])
        .map((i) => `${i.i ?? ""}:${i.t ?? ""}:${(i.c ?? 1).toString()}`)
        .join(";");
      if (handledSmeltKeys.has(inputKey)) {
        continue;
      }
      handledSmeltKeys.add(inputKey);
      const group = smeltGroups.get(inputKey) ?? [producer];
      const stations = sortStations(
        Array.from(new Set(group.map((p) => p.st).filter((s): s is string => Boolean(s)))),
      );
      collapsedProducers.push({
        producer,
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
    is_raw: isRawMaterial(graph, itemId),
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
