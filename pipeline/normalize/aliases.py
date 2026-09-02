"""Alias generation, and the reference ranker that pins what "good search" means.

`TODO.md` calls alias generation "the quality bar for search," and review of
this plan carried one piece of direct user feedback that this module exists to
satisfy word for word:

    Make sure that if this query were 'golden apple' it would only show golden
    apple, not all other golden items (or at least golden apple should always
    show up first).

The trap that feedback names is real and specific to how `Entity.aliases`
would otherwise be built. `minecraft:golden_apple`'s registry path splits on
`_` into two segments, `golden` and `apple`, and if those segments were the
*only* aliases this pipeline produced, a query of `golden apple` would have no
single alias to match exactly -- it would only ever find two separate segment
hits, spread across every `golden_*` item the registries hold: `golden_carrot`,
`golden_sword`, `golden_boots`, `golden_apple` itself, and more. Nothing in
that shape lets a matcher prefer the one entity whose whole name is "golden
apple" over five entities that merely contain the word "golden." So this
module's first and strongest kind of alias is the whole phrase, not the pieces
of it: `generate_aliases` always emits `golden_apple` and `golden apple`
together, ahead of `golden` and `apple` alone, and `AliasStrength` records that
ordering as a fact of the data rather than leaving it to a matcher to
rediscover.

## Where this module's job ends and Phase 4's begins

Ranking a set of search results against a query is `TODO.md` Phase 4's job,
written in TypeScript, against the built search index. This module is Python,
runs at build time, and produces the alias *data* that Phase 4 reads -- it
never ranks anything for the live site. But an alias list that Phase 4 cannot
possibly rank correctly, however it is written, is a Phase 3 bug wearing a
Phase 4 costume: no matcher can put the right answer first over data that
does not distinguish "the exact thing" from "a thing with the same word in
it." So this module also exports `rank_candidates`, a small reference
implementation of the ranking rule `TODO.md` Phase 4 already commits to --
exact, then prefix, then alias hit ordered by `AliasStrength`, then
all-tokens-present, with a deterministic tie-break. It is not the shipped
matcher; it is the *acceptance spec* this module's own alias output has to
satisfy, and the table-driven test in `tests/test_normalize_aliases.py`
exercises it directly rather than trusting the alias data alone to look right.

## Effect and potion cross-linking: no longer a one-sided ask

`TODO.md` asks that a query of `weak` finds Weakness *and* Potion of
Weakness. This module's docstring used to spend several paragraphs arguing
that only half of that ask had a real target, because modern Minecraft
(post-1.20.5, the item-component rewrite this project's `26.2` target lives
well past) carries every brewed potion as one item, `minecraft:potion`,
distinguished at the stack level by a `minecraft:potion_contents` component
rather than by a distinct registry ID -- so there was no registry ID "Potion
of Weakness" for an alias to point at, and inventing one would have been
exactly the kind of guess CLAUDE.md's Tier B rule refuses to make.

That reasoning is obsolete. `pipeline.normalize.merge` now synthesizes a real
entity per potion, `minecraft:potion/<path>`, from `registries["potion"]`
directly rather than from the wiki's `Type` column -- the `/` separator is
required, not cosmetic, because fifteen potion paths collide with a
`mob_effect` path of the same name (`weakness`, `poison`, `strength`, and
twelve more). A potion page to point at now exists, so this module gives
each potion its own strong aliases -- `potion of weakness`, `weakness
potion` -- generated the same way `FULL_PHRASE` already covers an ordinary
registry path, rather than reusing the weaker `CROSS_LINK` mechanism built
for an effect page standing in for a potion that had nowhere else to go.

The effect's own `potion of <name>` alias stays, deliberately, at its
original `CROSS_LINK` strength, rather than being removed now that a
stronger competitor exists. Not every `mob_effect` has a potion counterpart
-- Hunger, Nausea, Blindness, and a dozen more have no brewable potion at
all -- so removing the effect's alias unconditionally would leave those
queries resolving to nothing, and this module has no cheap way to tell,
entity by entity, which effects a potion exists for and which do not; that
answer lives in a different registry this module is never handed. Where a
potion genuinely does exist, `AliasStrength`'s own ordering is what makes it
win the tie without any special case: `FULL_PHRASE` outranks `CROSS_LINK`,
so `rank_candidates` already prefers the potion's own alias over the
effect's borrowed one for the identical query string, the same way it
already prefers a name match over an alias match. `weak` itself reaching
Weakness is a separate, shorter piece of community shorthand, curated by
hand in `/data/curated/aliases.json` rather than generated -- see that
file's own note for why a curated entry suits it better than a generated
rule.

## Enchantment levels: no wired Tier A max-level source

`TODO.md` Phase 6c lists "max level" as future work for the enchantment kind,
and no Tier A extractor for it exists yet in this codebase as of this task.
Rather than block level-alias generation on a source that does not exist,
`generate_aliases` generates Roman numerals I through V for every enchantment,
unconditionally. Every vanilla enchantment's real maximum sits at or below V
(Impaling, Piercing, Power, and Sharpness all cap at V; nothing in the game
goes higher), so this never *invents* a level a player could reach, but it can
offer a level alias -- `efficiency 6`, say -- above an enchantment's real cap.
That is a knowingly loose bound rather than a guess at a number: Phase 6c's
own max-level source, once wired, narrows this without changing the shape of
the alias list. This is called out again in the top-level task report per the
brief's own request to name it explicitly rather than let it pass silently.
"""

import re
from collections.abc import Iterable, Sequence
from enum import IntEnum

from pydantic import BaseModel

from pipeline.normalize.entity import EntityKind

__all__ = [
    "ROMAN_NUMERALS",
    "AliasStrength",
    "RankedCandidate",
    "RankingCandidate",
    "generate_aliases",
    "rank_candidates",
]

# Roman numerals I through V. See the module docstring's section on
# enchantment levels for why the ceiling is V and why it is unconditional.
ROMAN_NUMERALS: tuple[str, ...] = ("I", "II", "III", "IV", "V")

_SEGMENT_SPLIT = re.compile(r"[_/]+")


class AliasStrength(IntEnum):
    """How strongly one alias identifies its entity, strongest first.

    The order is the whole point of this enum: `EntityDraft.add_aliases`
    preserves insertion order and `Entity.aliases` emits it unchanged, so
    whatever order this module hands the merge stage is the order Phase 4's
    matcher sees, and the strength ordering below is what keeps a
    multi-token query such as "golden apple" resolving to the one entity
    whose whole name is that phrase, ahead of the five other entities that
    merely share one word of it.

    `FULL_PHRASE` is the entity's own whole registry path, spelled both with
    underscores and with spaces -- the load-bearing case the module docstring
    opens with. `CURATED` is hand-written shorthand from
    `/data/curated/aliases.json`, trusted above a generated cross-link because
    a person chose it deliberately for this one entity. `CROSS_LINK` is this
    module's own generated effect/potion linking. `SEGMENT` is the weakest:
    one `_`-separated piece of the registry path on its own, which is exactly
    the shape that, alone, would let "golden" find every golden item with no
    way to prefer the one named "golden apple."

    Enchantment level aliases (`efficiency 5`, `efficiency v`) are recorded at
    `SEGMENT` strength. They are generated shorthand rather than the entity's
    own name or a hand-vetted curation, which is the same category `SEGMENT`
    already describes, and a query that also names a level is specific enough
    that the strength of the level alias itself rarely decides the outcome --
    see `tests/test_normalize_aliases.py`'s `efficiency 5` case.
    """

    FULL_PHRASE = 4
    CURATED = 3
    CROSS_LINK = 2
    SEGMENT = 1


class RankingCandidate(BaseModel, frozen=True):
    """One entity as `rank_candidates` sees it: an id, a name, and its strengthed aliases.

    Deliberately narrower than `pipeline.normalize.entity.Entity` -- the
    reference ranker below only ever reads these three fields, and importing
    the full `Entity` model here would let a future field on it change this
    module's behaviour by accident. `aliases` takes the same `(alias,
    strength)` shape `generate_aliases` returns, in the same strongest-first
    order, so a caller can pass that function's output straight through.
    """

    id: str
    name: str
    aliases: tuple[tuple[str, AliasStrength], ...] = ()


class RankedCandidate(BaseModel, frozen=True):
    """One `rank_candidates` result: a candidate, its tier, and what won it.

    `tier` is lower-is-better, matching the `_TIER_*` constants below, and is
    exposed on the model (rather than kept private) so a test can assert not
    just the order of the results but *why* one result beat another -- an
    "exact" win and an "alias hit" win are both correct, but a test that
    cannot tell them apart cannot catch a change that turns one into the
    other.
    """

    candidate: RankingCandidate
    tier: int
    matched_alias: str | None = None
    matched_strength: AliasStrength | None = None


# The four ranking tiers `TODO.md` Phase 4 names, in the order it names them:
# "exact match, then prefix, then alias hit, then fuzzy." This reference
# ranker reads the fourth tier as "every query token is present somewhere in
# the name or the aliases" -- the closest a non-fuzzy stand-in can get to
# `TODO.md`'s "fuzzy," and precise enough to prove the alias data does not
# depend on fuzziness to rank correctly. The real fuzzy matcher is Phase 4's
# to choose and tune. "Exact" and "prefix" are read against the name *and*
# every alias, not the name alone, because an exact hit on a curated alias
# such as `gapple` is exactly as strong a signal as an exact hit on the name
# itself -- CLAUDE.md's whole reason for curating `gapple` at all is that a
# player types it expecting the same certainty a real name would give.
_TIER_EXACT = 0
_TIER_PREFIX = 1
_TIER_ALIAS_HIT = 2
_TIER_ALL_TOKENS = 3
_TIER_NONE = 4

# The sort rank given to a match won by the entity's own name, used only to
# order results within one tier. It is one more than the strongest
# `AliasStrength`, so a name match always outranks even a `FULL_PHRASE` alias
# match landing in the same tier -- the name is what the entity actually is
# called today, and an alias is, by construction, a second-best way to reach
# it.
_NAME_MATCH_RANK = max(strength.value for strength in AliasStrength) + 1


def _segments(path: str) -> tuple[str, ...]:
    """Return the non-empty `_`/`/`-separated pieces of a registry path."""
    return tuple(piece for piece in _SEGMENT_SPLIT.split(path) if piece)


def _phrase_aliases(path: str) -> tuple[str, ...]:
    """Return the whole-phrase aliases of `path`: itself, and with `_` as spaces."""
    spaced = path.replace("_", " ")
    return (path, spaced) if spaced != path else (path,)


def _level_aliases(base: str) -> tuple[str, ...]:
    """Return `f"{base} <level>"` for every level of `ROMAN_NUMERALS`, arabic and roman."""
    levels: list[str] = []
    for index, roman in enumerate(ROMAN_NUMERALS, start=1):
        levels.append(f"{base} {index}")
        levels.append(f"{base} {roman.lower()}")
    return tuple(levels)


def generate_aliases(
    *,
    entity_id: str,
    kind: EntityKind,
    name: str,
    curated: Sequence[str] = (),
) -> tuple[tuple[str, AliasStrength], ...]:
    """Return the `(alias, strength)` pairs of one entity, strongest first.

    `entity_id` is the namespaced registry ID, such as `minecraft:golden_
    apple`; the path after the colon is what `FULL_PHRASE` and `SEGMENT`
    aliases are built from. `kind` selects the kind-specific generators: a
    `mob_effect` gets a `potion of <name>` cross-link at `CROSS_LINK`
    strength, an `item` whose path starts with `potion/` (a real potion
    entity) gets `potion of <name>` and `<name> potion` at the stronger
    `FULL_PHRASE`, and an `enchantment` gets the level aliases the module
    docstring describes. `name` is the
    entity's own display name, casefolded and compared against every
    generated and curated alias so that an alias which only repeats the name
    is dropped here rather than reaching `Entity`'s own stricter validator,
    which raises on exactly that. `curated` is the hand-written shorthand for
    this one entity ID, read from `/data/curated/aliases.json` by the merge
    stage and passed straight through.

    The rules, applied in this order: casefold every alias; drop one equal to
    `name` casefolded; drop an empty string; when the same casefolded alias
    is produced more than once, keep only its strongest occurrence; sort what
    remains strongest-first, and alphabetically within one strength, so the
    output of this function is deterministic for a fixed input.
    """
    path = entity_id.split(":", 1)[-1]
    casefolded_name = name.casefold()

    proposals: list[tuple[str, AliasStrength]] = []
    proposals.extend((phrase, AliasStrength.FULL_PHRASE) for phrase in _phrase_aliases(path))
    proposals.extend((value, AliasStrength.CURATED) for value in curated)
    if kind is EntityKind.EFFECT:
        proposals.append((f"potion of {path.replace('_', ' ')}", AliasStrength.CROSS_LINK))
    if kind is EntityKind.ITEM and path.startswith("potion/"):
        # `path` reads `potion/<potion-path>`, e.g. `potion/long_weakness`.
        # Strong aliases, matching `FULL_PHRASE`'s own strength: this is a
        # real page now, not a borrowed one, so it competes for "weakness"
        # and "potion of weakness" on equal footing with every other entity
        # whose own name or segments happen to contain those words -- see
        # the module docstring's cross-linking section for why the effect's
        # own `CROSS_LINK` alias of the same phrase loses that tie rather
        # than needing to be removed.
        effect_words = path.removeprefix("potion/").replace("_", " ")
        proposals.append((f"potion of {effect_words}", AliasStrength.FULL_PHRASE))
        proposals.append((f"{effect_words} potion", AliasStrength.FULL_PHRASE))
    if kind is EntityKind.ENCHANTMENT:
        proposals.extend((level, AliasStrength.SEGMENT) for level in _level_aliases(path))
    proposals.extend((segment, AliasStrength.SEGMENT) for segment in _segments(path))

    best: dict[str, AliasStrength] = {}
    for alias, strength in proposals:
        cleaned = alias.strip().casefold()
        if not cleaned or cleaned == casefolded_name:
            continue
        current = best.get(cleaned)
        if current is None or strength > current:
            best[cleaned] = strength

    return tuple(sorted(best.items(), key=lambda pair: (-pair[1].value, pair[0])))


def _tier_of(
    query: str, candidate: RankingCandidate
) -> tuple[int, str | None, AliasStrength | None]:
    """Return the ranking tier `candidate` earns against `query`, and what won it.

    `query` arrives already casefolded and stripped; `rank_candidates` does
    that once per call rather than once per candidate. Exact and prefix are
    checked against the name first and then against every alias, keeping
    the strongest source at a tied tier -- see the module-level tier
    constants' comment for why an alias can win an exact tie against the
    name. Within the weaker `_TIER_ALIAS_HIT` tier, the strongest matching
    alias by `AliasStrength` is kept, which is the ordering `TODO.md` Phase 4
    asks this module to make possible.
    """
    if not query:
        return _TIER_NONE, None, None
    folded_name = candidate.name.casefold()

    if query == folded_name:
        return _TIER_EXACT, None, None

    best_tier = _TIER_PREFIX if folded_name.startswith(query) else _TIER_NONE
    best_alias: str | None = None
    best_strength: AliasStrength | None = None

    for alias, strength in candidate.aliases:
        folded_alias = alias.casefold()
        if query == folded_alias:
            tier = _TIER_EXACT
        elif folded_alias.startswith(query):
            tier = _TIER_PREFIX
        elif query in folded_alias or folded_alias in query:
            tier = _TIER_ALIAS_HIT
        else:
            continue

        stronger_at_same_tier = (
            tier == best_tier
            and tier == _TIER_ALIAS_HIT
            and (best_strength is None or strength > best_strength)
        )
        if tier < best_tier or stronger_at_same_tier:
            best_tier, best_alias, best_strength = tier, alias, strength

    if best_tier != _TIER_NONE:
        return best_tier, best_alias, best_strength

    tokens = query.split()
    haystack = " ".join((folded_name, *(alias.casefold() for alias, _ in candidate.aliases)))
    if tokens and all(token in haystack for token in tokens):
        return _TIER_ALL_TOKENS, None, None

    return _TIER_NONE, None, None


def rank_candidates(
    query: str, candidates: Iterable[RankingCandidate]
) -> tuple[RankedCandidate, ...]:
    """Return `candidates` ordered the way Phase 4's matcher must order them.

    This is the acceptance rule this module's alias output has to satisfy,
    and an executable spec for the Phase 4 matcher -- not the shipped
    matcher itself. `TODO.md` names the tiers this function reads in order:
    exact match, then prefix, then alias hit (here ordered by
    `AliasStrength`), then "every query token is present," standing in for
    Phase 4's fuzzy tier. A candidate that matches none of the four is
    dropped from the result rather than ranked last, because "every result
    Phase 4 shows" and "every entity that exists" are different lists, and
    this function only ever answers the first one.

    The final tie-break, for two candidates in the same tier with the same
    matched strength, is the candidate's `id`, alphabetically --
    deterministic, and independent of the order `candidates` arrived in, so a
    test can assert an exact result list rather than merely "golden_apple is
    somewhere near the top."
    """
    folded_query = query.strip().casefold()
    ranked: list[RankedCandidate] = []
    for candidate in candidates:
        tier, matched_alias, matched_strength = _tier_of(folded_query, candidate)
        if tier == _TIER_NONE:
            continue
        ranked.append(
            RankedCandidate(
                candidate=candidate,
                tier=tier,
                matched_alias=matched_alias,
                matched_strength=matched_strength,
            )
        )

    def sort_key(entry: RankedCandidate) -> tuple[int, int, str]:
        strength = entry.matched_strength
        rank = strength.value if strength is not None else _NAME_MATCH_RANK
        return (entry.tier, -rank, entry.candidate.id)

    return tuple(sorted(ranked, key=sort_key))
