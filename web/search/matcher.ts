import uFuzzy from "@leeoniya/ufuzzy";

import type { EntityKind, Index, IndexEntry } from "../types/index.js";

/**
 * Kind priority order for tiebreaking within one tier, most useful mid-match first:
 * mob · item · block · effect · enchantment · biome · structure · collection · advancement · entity
 */
const KIND_PRIORITY: Record<EntityKind, number> = {
  mob: 0,
  item: 1,
  block: 2,
  effect: 3,
  enchantment: 4,
  biome: 5,
  structure: 6,
  collection: 7,
  advancement: 8,
  entity: 9,
};

interface PreppedEntry {
  readonly entry: IndexEntry;
  readonly foldedName: string;
  readonly foldedAliases: readonly string[];
  /** Parallel to `foldedAliases`: is that alias the entity's own whole registry path? */
  readonly aliasIsPhrase: readonly boolean[];
}

/**
 * Returns the whole-phrase forms of an entity id: the registry path after the
 * namespace, spelled with underscores and with spaces.
 *
 * This reconstructs, from the id alone, the two aliases
 * `pipeline.normalize.aliases._phrase_aliases` emits at `FULL_PHRASE` strength --
 * the strongest band, and the one that decides whether "golden apple" resolves to
 * Golden Apple or to five unrelated golden things.
 *
 * The strength tag itself does not survive into `index.json` (TODO.md decision 16),
 * so the matcher needs some way back to it. Alias *position* is not that way. Within
 * one strength band `generate_aliases` sorts alphabetically, so the index of a given
 * alias encodes its spelling, not its strength: `diamond` sits at index 2 for
 * `diamond_axe` (after `axe`) and at index 1 for `diamond_hoe` (before `hoe`).
 * Ranking on that position let Diamond Ore outrank Diamond Axe for the query
 * `diamond` purely because "axe" sorts before "diamond" and "ore" does not.
 * Deriving the phrase forms structurally is exact for the band that matters and
 * depends on nothing the pipeline is free to reorder.
 */
function phraseFormsOf(entityId: string): ReadonlySet<string> {
  const path = entityId.slice(entityId.indexOf(":") + 1).toLowerCase();
  return new Set([path, path.replaceAll("_", " ")]);
}

interface HaystackMapping {
  readonly entityIdx: number;
  readonly isName: boolean;
  readonly aliasIdx: number;
}

export interface Corpus {
  readonly entities: readonly IndexEntry[];
  readonly prepped: readonly PreppedEntry[];
  readonly haystack: readonly string[];
  readonly haystackMap: readonly HaystackMapping[];
  readonly uf: uFuzzy;
}

interface CandidateMatch {
  readonly entry: IndexEntry;
  readonly tier: number;
  readonly isName: boolean;
  /** The match was won by an alias that is the entity's own whole registry path. */
  readonly isPhraseAlias: boolean;
}

/**
 * Builds a search corpus from the loaded search index.
 * Run once at boot.
 */
export function buildCorpus(index: Index): Corpus {
  const entities = index.entities;
  const prepped: PreppedEntry[] = [];
  const haystack: string[] = [];
  const haystackMap: HaystackMapping[] = [];

  for (let eIdx = 0; eIdx < entities.length; eIdx++) {
    const entry = entities[eIdx];
    if (entry === undefined) continue;

    const foldedName = entry.n.toLowerCase();
    const foldedAliases = entry.a.map((a) => a.toLowerCase());
    const phraseForms = phraseFormsOf(entry.id);

    prepped.push({
      entry,
      foldedName,
      foldedAliases,
      aliasIsPhrase: foldedAliases.map((a) => phraseForms.has(a)),
    });

    haystack.push(foldedName);
    haystackMap.push({ entityIdx: eIdx, isName: true, aliasIdx: -1 });

    for (let aIdx = 0; aIdx < foldedAliases.length; aIdx++) {
      const alias = foldedAliases[aIdx];
      if (alias === undefined) continue;
      haystack.push(alias);
      haystackMap.push({ entityIdx: eIdx, isName: false, aliasIdx: aIdx });
    }
  }

  const uf = new uFuzzy({
    intraMode: 1,
    intraIns: 1,
    intraSub: 1,
    intraTrn: 1,
    intraDel: 1,
  });

  return { entities, prepped, haystack, haystackMap, uf };
}

/**
 * Searches the corpus for entities matching query.
 *
 * Tiers:
 * 0: query equals name or equals an alias
 * 1: name or an alias starts with the query
 * 2: an alias contains the query
 * 3: uFuzzy accepts it (one typo per term)
 *
 * Ordered tiebreaks inside one tier:
 * 1. a name match beats an alias match
 * 2. a whole-registry-path alias beats any other alias
 * 3. kind priority
 * 4. the shorter display name
 * 5. id, alphabetically
 */
export function search(corpus: Corpus, query: string, limit?: number): IndexEntry[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];

  const candidates: CandidateMatch[] = [];
  const matchedEntities = new Set<number>();

  // Tiers 0, 1, 2
  for (let i = 0; i < corpus.prepped.length; i++) {
    const p = corpus.prepped[i];
    if (p === undefined) continue;

    let bestTier = 4;
    let isName = false;
    let bestIsPhrase = false;

    if (p.foldedName === q) {
      bestTier = 0;
      isName = true;
    } else if (p.foldedName.startsWith(q)) {
      bestTier = 1;
      isName = true;
    }

    for (let aIdx = 0; aIdx < p.foldedAliases.length; aIdx++) {
      const alias = p.foldedAliases[aIdx];
      if (alias === undefined) continue;

      let tier = 4;
      if (alias === q) {
        tier = 0;
      } else if (alias.startsWith(q)) {
        tier = 1;
      } else if (alias.includes(q)) {
        // Tier 2 is `alias.includes(q)` only. `pipeline.normalize.aliases._tier_of`
        // also accepts the reverse, an alias contained by the query, which is safe
        // over its twelve synthetic candidates and harmful over the real 2,120:
        // advancement paths yield aliases as short as `a` and `ol`, so that clause
        // makes `Kill a Mob` match every query containing the letter "a". Measured
        // in docs/search.md, which also records what would let it be restored.
        tier = 2;
      }

      // A stronger tier always wins. At an equal tier, a whole-path alias is
      // preferred over the segment alias that happened to be checked first --
      // the alias list is alphabetical inside a strength band, so "first" alone
      // carries no ranking meaning. See `phraseFormsOf`.
      const isPhrase = p.aliasIsPhrase[aIdx] === true;
      if (tier < bestTier || (tier === bestTier && !isName && isPhrase && !bestIsPhrase)) {
        bestTier = tier;
        isName = false;
        bestIsPhrase = isPhrase;
      }
    }

    if (bestTier < 4) {
      candidates.push({
        entry: p.entry,
        tier: bestTier,
        isName,
        isPhraseAlias: bestIsPhrase,
      });
      matchedEntities.add(i);
    }
  }

  // Tier 3: uFuzzy filter
  const ufMatches = corpus.uf.filter(corpus.haystack as string[], q);
  if (ufMatches !== null) {
    const tier3ByEntity = new Map<number, { isName: boolean; isPhraseAlias: boolean }>();

    for (const hIdx of ufMatches) {
      const info = corpus.haystackMap[hIdx];
      if (info === undefined || matchedEntities.has(info.entityIdx)) continue;

      // One entity can match through several haystack strings. Keep the strongest
      // evidence: its own name first, then a whole-path alias, then anything else.
      const isPhrase =
        !info.isName && corpus.prepped[info.entityIdx]?.aliasIsPhrase[info.aliasIdx] === true;
      const existing = tier3ByEntity.get(info.entityIdx);
      if (existing === undefined) {
        tier3ByEntity.set(info.entityIdx, { isName: info.isName, isPhraseAlias: isPhrase });
      } else if (info.isName && !existing.isName) {
        existing.isName = true;
        existing.isPhraseAlias = false;
      } else if (!existing.isName && isPhrase) {
        existing.isPhraseAlias = true;
      }
    }

    for (const [entityIdx, matchInfo] of tier3ByEntity.entries()) {
      const entry = corpus.entities[entityIdx];
      if (entry === undefined) continue;
      candidates.push({
        entry,
        tier: 3,
        isName: matchInfo.isName,
        isPhraseAlias: matchInfo.isPhraseAlias,
      });
    }
  }

  candidates.sort((a, b) => {
    if (a.tier !== b.tier) return a.tier - b.tier;

    // 1. Name match beats alias match
    const nameA = a.isName ? 1 : 0;
    const nameB = b.isName ? 1 : 0;
    if (nameA !== nameB) return nameB - nameA;

    // 2. A whole-registry-path alias beats any other alias
    if (!a.isName && !b.isName && a.isPhraseAlias !== b.isPhraseAlias) {
      return a.isPhraseAlias ? -1 : 1;
    }

    // 3. Kind priority
    const kindA = KIND_PRIORITY[a.entry.k];
    const kindB = KIND_PRIORITY[b.entry.k];
    if (kindA !== kindB) return kindA - kindB;

    // 4. Shorter display name
    if (a.entry.n.length !== b.entry.n.length) {
      return a.entry.n.length - b.entry.n.length;
    }

    // 5. id, alphabetically
    return a.entry.id < b.entry.id ? -1 : a.entry.id > b.entry.id ? 1 : 0;
  });

  const results = candidates.map((c) => c.entry);
  return limit !== undefined ? results.slice(0, limit) : results;
}
