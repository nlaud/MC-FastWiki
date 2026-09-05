import type { Obtain, ObtainMethod, ObtainProducerInput } from "../types/obtain.js";

export const DEFAULT_MAX_DEPTH = 4;
export const ROOT_PATH = "root";

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
  note: string | null;
  source_id: string;
  inputs: TreeInput[];
}

export interface ObtainNode {
  item: string;
  producers: TreeProducer[];
  expandable: boolean;
  back_reference: string | null;
}

export interface ObtainTree {
  root: ObtainNode;
}

export interface BuildTreeOptions {
  maxDepth?: number;
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
    return [
      {
        label,
        item: null,
        tag: inputSpec.t,
        count,
        members,
        node: null,
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

  const rawProducers = graph.producers[itemId] ?? [];
  const treeProducers: TreeProducer[] = [];

  for (const producer of rawProducers) {
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
      station: producer.st ?? null,
      note: producer.nt ?? null,
      source_id: producer.src,
      inputs,
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
 * Builds the obtain tree of an item under the four rules of pipeline/obtain/tree.py:
 * 1. Cycle: drop, do not draw.
 * 2. Memoize on (itemId, remainingDepth), not itemId alone.
 * 3. Depth cap -> expandable stub.
 * 4. Repeated-subtree collapse -> back_reference.
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

  return buildNode(itemId, graph, maxDepth, maxDepth, path, firstOccurrence, ROOT_PATH, true);
}
