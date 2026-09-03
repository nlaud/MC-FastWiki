# Search Architecture and Benchmarks

This document records the search engine design, performance benchmarks, matcher configuration,
and ranking rules for Phase 4 of MC-FastWiki.

---

## 1. Index Size and Keystroke Timings

Measured against `data/dist/index.json` (Minecraft 26.2, built 2026-09-03) on Node 22.19.

| Measurement | Value |
| --- | --- |
| Index, raw | 345,822 B (~338 KiB) |
| Index, gzip -9 | 50,025 B (~48.8 KiB) |
| Entities | 2,120 |
| Aliases | 7,583 |
| Entities with no icon | 219 |
| Haystack strings (names + aliases) | 9,703 |
| Deterministic linear scan, median keystroke | 0.235 ms |
| Deterministic linear scan, worst keystroke | 0.493 ms |
| uFuzzy filter, typical query | 0.26 ms |
| uFuzzy filter, worst query (`g`) | 1.80 ms |
| Budget ceiling | 16 ms |

### Key Takeaways

1. **Speed is well within budget:** Flat linear scans over all names and aliases run over 30x
   under the 16 ms per-keystroke frame budget. Complex indexing structures (tries, inverted indexes)
   are unjustified complexity.
2. **uFuzzy filters, FastWiki ranks:** uFuzzy's built-in `sort()` orders by character proximity
   and term compactness without knowledge of alias strengths or Minecraft entity kinds. Thus,
   uFuzzy is used solely for candidate filtering at Tier 3, while our tier stack and tiebreak rules
   control ranking.

---

## 2. Tier Stack

Search queries are evaluated through four descending tiers:

| Tier | Rule | Rationale |
| --- | --- | --- |
| 0 | Query equals name or equals an alias | Exact matches always win |
| 1 | Name or an alias starts with query | Standard prefix completion |
| 2 | An alias contains the query | Substring / segment alias hit |
| 3 | uFuzzy accepts term (1 typo per term) | Typo tolerance fallback |

Tiers 0-2 follow `pipeline.normalize.aliases._tier_of`, the executable specification defined in the
Python pipeline, with one deliberate narrowing recorded below.

### Tier 2 drops one half of the Python rule, on purpose

`_tier_of` reads tier 2 as `query in folded_alias or folded_alias in query`. The matcher implements
only the first half: an alias that *contains* the query. An alias that is *contained by* the query
is not a tier 2 hit here.

The reason is that the Python ranker is exercised against a synthetic set of twelve candidates,
where the second clause is harmless, while the matcher runs against all 2,120 real entities, where
it is not. The real index carries 1- and 2-character aliases produced from advancement registry
paths: `a` (from `adventure/kill_a_mob`), `of`, `on`, `to`, `in`, `at`, `an`, `ol`, `uh`, `oh`.
Under the second clause every one of those matches any query containing that substring anywhere.

Measured against the committed index, the clause would add these tier 2 matches that are otherwise
correctly excluded:

| Query | Extra tier 2 matches | Example |
| --- | --- | --- |
| `diamond` | 10 | Kill a Mob, via the alias `a` |
| `golden apple` | 36 | Ol' Betsy, via the alias `ol` |
| `villager` | 9 | Carrot on a Stick, via the alias `a` |
| `stone` | 9 | Two Birds, One Arrow, via the alias `one` |

`Kill a Mob` would match every query containing the letter `a`. The narrowing costs nothing real,
because uFuzzy at tier 3 still recovers genuine multi-word recall, and the top result is unchanged
for every row of `tests/fixtures/search_acceptance.json`.

If the alias generator ever stops emitting sub-3-character aliases, this narrowing can be removed
and the two implementations brought back into exact agreement.

---

## 3. Typo Tolerance and `@leeoniya/ufuzzy` Configuration

uFuzzy is configured with:

```ts
{
  intraMode: 1, // SingleError mode: allow 1 error within terms
  intraIns: 1,  // Allow 1 insertion (e.g. "enchanting tabele")
  intraSub: 1,  // Allow 1 substitution (e.g. "blase rod" -> "blaze rod")
  intraTrn: 1,  // Allow 1 transposition (e.g. "dimaond" -> "diamond")
  intraDel: 1,  // Allow 1 deletion / omission (e.g. "dimond" -> "diamond")
}
```

### Why Typo Tolerance Requires Explicit Flags

At default settings (`intraMode: 0`), uFuzzy only permits character insertions (missing characters
in query), failing on common transpositions (`dimaond`) or phonetic substitutions (`blase rod`).
Enabling all four single-error flags ensures common drafting typos resolve smoothly.

---

## 4. Tiebreak Order and Kind Priority

Within any single tier, ties between candidates are broken in strict order:

1. **Name match beats alias match:** The canonical name is stronger evidence than an alias.
2. **A whole-registry-path alias beats any other alias:** the `FULL_PHRASE` band, recovered
   structurally from the entity's own `id` rather than from the alias's position (Decision D1).
3. **Kind priority:** When alias strength ties, entity kinds are ordered by match utility:
   ```
   mob · item · block · effect · enchantment · biome · structure · collection · advancement · entity
   ```
4. **Shorter display name:** More concise names rank ahead of longer compound phrases.
5. **Entity ID, alphabetically:** Deterministic final tiebreak.

### Kind Priority Rationale

- **"Popularity" is kind-based:** The codebase contains no usage analytics or external popularity
  metrics. Kind priority serves as the deterministic proxy for match utility.
- **`mob`, `item`, `block` at the top:** Mid-match, players query mob health/drops, crafting
  recipes, and block harvest requirements.
- **`advancement` sits low:** Advancements frequently contain mob names in descriptions or titles
  (e.g., Surge Protector and Zombie Doctor matching `villager`). Kind priority prevents them from
  displacing the mob itself.
- **`entity` sits last:** The 24 technical entities (`Marker`, `Interaction`, `Falling Block`,
  `Fishing Bobber`) are technical artifacts never queried intentionally during a match.

---

## 5. Settled Decisions

### D1: Alias Strength Recovered Structurally, Not from Array Position

`AliasStrength` (`FULL_PHRASE` > `CURATED` > `CROSS_LINK` > `SEGMENT`) does not survive into
`index.json`. `EntityDraft._aliases` is a `dict[str, SourceTier]`, so the strength tag is dropped
at the merge boundary and `a` reaches the web app as a plain `string[]`.

- **Rejected:** shipping a parallel `w` array of strength digits. Measured at +28 kB raw and
  +2.0 kB gzipped, which is cheap, but reviving the tag means changing `EntityDraft`,
  `Entity.aliases`, `entity.schema.json`, `index.schema.json`, both emitters, and both generated
  type files. That is the entity contract itself, and it grows every shard as well as the index.

- **Also rejected, after it shipped and was caught in browser testing:** treating the alias's
  *position* in `a` as its strength. `generate_aliases` does sort strongest-first, but it sorts
  **alphabetically inside one strength band**, so a position encodes spelling, not strength:

  | Entity | Aliases | Index of `diamond` |
  | --- | --- | --- |
  | `minecraft:diamond_axe` | `diamond_axe`, `axe`, `diamond` | 2 |
  | `minecraft:diamond_hoe` | `diamond_hoe`, `diamond`, `hoe` | 1 |
  | `minecraft:diamond_ore` | `diamond_ore`, `diamond`, `ore` | 1 |

  `axe` sorts before `diamond` and `hoe` does not, so comparing positions across entities made
  Diamond Ore, a block, outrank Diamond Axe for the query `diamond`. The fault is not narrow: it
  reaches every entity whose registry path has more than one segment.

- **Chosen:** derive the `FULL_PHRASE` band from the entity's own `id`. An alias is a whole-phrase
  alias exactly when it equals the registry path after the namespace, spelled with underscores or
  with spaces. That is what `pipeline.normalize.aliases._phrase_aliases` emits, so the strongest
  band is recovered *exactly*, from data the index already carries, with no schema change and
  nothing the pipeline is free to reorder underneath it.

- **What this still cannot see:** `CURATED` versus `CROSS_LINK` versus `SEGMENT`, and the two
  potion-specific `FULL_PHRASE` aliases (`potion of weakness`, `weakness potion`) that are not
  derived from the path. Kind priority resolves the potion case, since an `item` outranks an
  `effect`. If a fault ever appears that needs those finer bands, the rejected `w` array is the
  known fix.
