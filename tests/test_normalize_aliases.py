"""Alias generation rules, and the acceptance table the user's own feedback asks for.

The acceptance table below is not incidental coverage -- it is the literal
check the plan review's feedback demanded: "if this query were 'golden apple'
it would only show golden apple, not all other golden items." Every row names
the one entity that must rank first, and the candidate set of the table-driven
test deliberately includes distractors that share a word with the right
answer, so the test fails if a future change lets a `SEGMENT` alias swamp a
`FULL_PHRASE` one.
"""

import pytest

from pipeline.normalize.aliases import (
    ROMAN_NUMERALS,
    AliasStrength,
    RankingCandidate,
    generate_aliases,
    rank_candidates,
)
from pipeline.normalize.entity import EntityKind

# --- `generate_aliases` -------------------------------------------------------


def test_a_full_phrase_alias_is_generated_underscored_and_spaced() -> None:
    aliases = dict(
        generate_aliases(entity_id="minecraft:golden_apple", kind=EntityKind.ITEM, name="X")
    )
    assert aliases["golden_apple"] is AliasStrength.FULL_PHRASE
    assert aliases["golden apple"] is AliasStrength.FULL_PHRASE


def test_a_single_word_id_gives_one_full_phrase_alias_not_two() -> None:
    """`creeper` spaced is `creeper` -- generating both would just duplicate one alias."""
    aliases = generate_aliases(entity_id="minecraft:creeper", kind=EntityKind.MOB, name="X")
    full_phrase = [alias for alias, strength in aliases if strength is AliasStrength.FULL_PHRASE]
    assert full_phrase == ["creeper"]


def test_segments_are_generated_for_every_underscore_separated_piece() -> None:
    aliases = dict(
        generate_aliases(entity_id="minecraft:golden_apple", kind=EntityKind.ITEM, name="X")
    )
    assert aliases["golden"] is AliasStrength.SEGMENT
    assert aliases["apple"] is AliasStrength.SEGMENT


def test_curated_aliases_are_tagged_curated_strength() -> None:
    aliases = dict(
        generate_aliases(
            entity_id="minecraft:golden_apple",
            kind=EntityKind.ITEM,
            name="X",
            curated=["gapple"],
        )
    )
    assert aliases["gapple"] is AliasStrength.CURATED


def test_an_alias_equal_to_the_own_name_casefolded_is_dropped() -> None:
    """`Entity`'s own validator refuses this; the merge must never hand it one."""
    aliases = dict(
        generate_aliases(entity_id="minecraft:creeper", kind=EntityKind.MOB, name="Creeper")
    )
    assert "creeper" not in aliases


def test_a_curated_alias_equal_to_the_name_casefolded_is_also_dropped() -> None:
    aliases = dict(
        generate_aliases(
            entity_id="minecraft:creeper",
            kind=EntityKind.MOB,
            name="Creeper",
            curated=["Creeper"],
        )
    )
    assert "creeper" not in aliases


def test_an_empty_curated_alias_is_dropped() -> None:
    aliases = dict(
        generate_aliases(
            entity_id="minecraft:golden_apple", kind=EntityKind.ITEM, name="X", curated=["  "]
        )
    )
    assert "" not in aliases


def test_a_duplicate_alias_keeps_only_its_strongest_occurrence() -> None:
    """`pearl` is curated for `ender_pearl`, and would also arise as a `SEGMENT`.

    The strongest tier wins, and the weaker proposal leaves no second entry.
    """
    aliases = generate_aliases(
        entity_id="minecraft:ender_pearl", kind=EntityKind.ITEM, name="X", curated=["pearl"]
    )
    matches = [strength for alias, strength in aliases if alias == "pearl"]
    assert matches == [AliasStrength.CURATED]


def test_the_output_is_sorted_strongest_first_then_alphabetically() -> None:
    aliases = generate_aliases(
        entity_id="minecraft:golden_apple", kind=EntityKind.ITEM, name="X", curated=["gapple"]
    )
    strengths = [strength for _, strength in aliases]
    assert strengths == sorted(strengths, reverse=True)
    # Within one strength tier, alphabetical: "apple" before "golden".
    segment_aliases = [alias for alias, strength in aliases if strength is AliasStrength.SEGMENT]
    assert segment_aliases == sorted(segment_aliases)


def test_the_output_is_deterministic() -> None:
    first = generate_aliases(
        entity_id="minecraft:golden_apple", kind=EntityKind.ITEM, name="X", curated=["gapple"]
    )
    second = generate_aliases(
        entity_id="minecraft:golden_apple", kind=EntityKind.ITEM, name="X", curated=["gapple"]
    )
    assert first == second


# --- Effect and potion cross-linking ------------------------------------------


def test_an_effect_gets_a_potion_of_cross_link() -> None:
    aliases = dict(
        generate_aliases(entity_id="minecraft:weakness", kind=EntityKind.EFFECT, name="Weakness")
    )
    assert aliases["potion of weakness"] is AliasStrength.CROSS_LINK


def test_a_non_effect_gets_no_potion_of_cross_link() -> None:
    aliases = dict(
        generate_aliases(entity_id="minecraft:golden_apple", kind=EntityKind.ITEM, name="X")
    )
    assert not any(alias.startswith("potion of") for alias in aliases)


# --- Enchantment levels --------------------------------------------------------


def test_an_enchantment_gets_arabic_and_roman_levels_one_through_five() -> None:
    aliases = dict(
        generate_aliases(
            entity_id="minecraft:efficiency", kind=EntityKind.ENCHANTMENT, name="Efficiency"
        )
    )
    assert aliases["efficiency 5"] is AliasStrength.SEGMENT
    assert aliases["efficiency v"] is AliasStrength.SEGMENT
    assert aliases["efficiency 1"] is AliasStrength.SEGMENT
    assert aliases["efficiency i"] is AliasStrength.SEGMENT


def test_no_level_alias_is_generated_past_five() -> None:
    assert len(ROMAN_NUMERALS) == 5
    aliases = dict(
        generate_aliases(
            entity_id="minecraft:efficiency", kind=EntityKind.ENCHANTMENT, name="Efficiency"
        )
    )
    assert "efficiency 6" not in aliases
    assert "efficiency vi" not in aliases


def test_a_non_enchantment_gets_no_level_aliases() -> None:
    aliases = dict(
        generate_aliases(entity_id="minecraft:golden_apple", kind=EntityKind.ITEM, name="X")
    )
    assert not any(alias[-1].isdigit() for alias in aliases)


# --- `rank_candidates`: the acceptance table -----------------------------------


def _candidate(
    entity_id: str, kind: EntityKind, name: str, curated: list[str] | None = None
) -> RankingCandidate:
    return RankingCandidate(
        id=entity_id,
        name=name,
        aliases=generate_aliases(
            entity_id=entity_id, kind=kind, name=name, curated=curated or []
        ),
    )


# The full candidate set every acceptance-table query is ranked against.
# Every distractor of `golden apple`, `blaze rod`, and `pearl` is here on
# purpose: the test asserts the #1 result, and a candidate set of one entity
# would pass even if `SEGMENT` aliases had swamped `FULL_PHRASE` ones.
_CANDIDATES = (
    _candidate("minecraft:golden_apple", EntityKind.ITEM, "Golden Apple", ["gapple"]),
    _candidate("minecraft:golden_carrot", EntityKind.ITEM, "Golden Carrot"),
    _candidate("minecraft:golden_sword", EntityKind.ITEM, "Golden Sword"),
    _candidate("minecraft:golden_boots", EntityKind.ITEM, "Golden Boots"),
    _candidate("minecraft:enchanted_golden_apple", EntityKind.ITEM, "Enchanted Golden Apple"),
    _candidate("minecraft:blaze_rod", EntityKind.ITEM, "Blaze Rod"),
    _candidate("minecraft:blaze_powder", EntityKind.ITEM, "Blaze Powder"),
    _candidate("minecraft:ender_pearl", EntityKind.ITEM, "Ender Pearl", ["pearl"]),
    _candidate("minecraft:ender_chest", EntityKind.BLOCK, "Ender Chest"),
    _candidate("minecraft:ender_eye", EntityKind.ITEM, "Eye of Ender"),
    _candidate("minecraft:efficiency", EntityKind.ENCHANTMENT, "Efficiency"),
    _candidate("minecraft:weakness", EntityKind.EFFECT, "Weakness", ["weak"]),
)

ACCEPTANCE_TABLE = (
    ("golden apple", "minecraft:golden_apple"),
    ("golden_apple", "minecraft:golden_apple"),
    ("gapple", "minecraft:golden_apple"),
    ("blaze rod", "minecraft:blaze_rod"),
    ("pearl", "minecraft:ender_pearl"),
    ("efficiency 5", "minecraft:efficiency"),
    ("weak", "minecraft:weakness"),
)


@pytest.mark.parametrize(("query", "expected_first"), ACCEPTANCE_TABLE)
def test_the_acceptance_table_ranks_the_required_entity_first(
    query: str, expected_first: str
) -> None:
    ranked = rank_candidates(query, _CANDIDATES)
    assert ranked, f"{query!r} returned no results at all"
    assert ranked[0].candidate.id == expected_first


def test_a_query_of_golden_alone_legitimately_returns_many_results() -> None:
    """`TODO.md` requires this. Nobody may 'fix' the ranking by dropping segment aliases,
    because a bare `golden` query has to keep finding every golden item.
    """
    ranked = rank_candidates("golden", _CANDIDATES)
    matched_ids = {entry.candidate.id for entry in ranked}
    assert {
        "minecraft:golden_apple",
        "minecraft:golden_carrot",
        "minecraft:golden_sword",
        "minecraft:golden_boots",
        "minecraft:enchanted_golden_apple",
    }.issubset(matched_ids)
    assert len(ranked) >= 5


def test_unrelated_candidates_do_not_appear_at_all() -> None:
    ranked = rank_candidates("golden apple", _CANDIDATES)
    matched_ids = {entry.candidate.id for entry in ranked}
    assert "minecraft:blaze_rod" not in matched_ids
    assert "minecraft:weakness" not in matched_ids


# --- The regression `FULL_PHRASE` exists to prevent ----------------------------


def test_without_a_full_phrase_alias_a_distractor_would_outrank_the_exact_match() -> None:
    """Pins the reason `FULL_PHRASE` exists at all.

    With only `SEGMENT` aliases, `golden_apple` and `enchanted_golden_apple`
    tie in the all-tokens tier -- both carry `golden` and `apple` -- and the
    alphabetical tie-break then puts `enchanted_golden_apple` first, which is
    exactly the wrong answer the user's feedback named. Restoring the
    `FULL_PHRASE` alias fixes it, over the same two candidates.
    """
    segment_only = (
        RankingCandidate(
            id="minecraft:golden_apple",
            name="Something Else",
            aliases=(("golden", AliasStrength.SEGMENT), ("apple", AliasStrength.SEGMENT)),
        ),
        RankingCandidate(
            id="minecraft:enchanted_golden_apple",
            name="Something Else Too",
            aliases=(
                ("enchanted", AliasStrength.SEGMENT),
                ("golden", AliasStrength.SEGMENT),
                ("apple", AliasStrength.SEGMENT),
            ),
        ),
    )
    ranked = rank_candidates("golden apple", segment_only)
    assert ranked[0].candidate.id == "minecraft:enchanted_golden_apple"

    with_phrase = (
        RankingCandidate(
            id="minecraft:golden_apple",
            name="Something Else",
            aliases=(
                ("golden_apple", AliasStrength.FULL_PHRASE),
                ("golden apple", AliasStrength.FULL_PHRASE),
                ("golden", AliasStrength.SEGMENT),
                ("apple", AliasStrength.SEGMENT),
            ),
        ),
        segment_only[1],
    )
    ranked = rank_candidates("golden apple", with_phrase)
    assert ranked[0].candidate.id == "minecraft:golden_apple"


# --- `rank_candidates`: tiers and tie-breaking ---------------------------------


def test_an_exact_name_match_beats_a_prefix_match() -> None:
    exact = RankingCandidate(id="minecraft:a", name="Stone")
    prefix = RankingCandidate(id="minecraft:b", name="Stone Bricks")
    ranked = rank_candidates("stone", (prefix, exact))
    assert [entry.candidate.id for entry in ranked] == ["minecraft:a", "minecraft:b"]


def test_a_name_match_beats_an_alias_match_at_the_same_tier() -> None:
    """The entity's own name is stronger evidence than even a `FULL_PHRASE` alias."""
    by_name = RankingCandidate(id="minecraft:a", name="Stone")
    by_alias = RankingCandidate(
        id="minecraft:b", name="Cobblestone", aliases=(("stone", AliasStrength.FULL_PHRASE),)
    )
    ranked = rank_candidates("stone", (by_alias, by_name))
    assert ranked[0].candidate.id == "minecraft:a"


def test_ties_break_alphabetically_by_id() -> None:
    first = RankingCandidate(id="minecraft:a", name="Widget")
    second = RankingCandidate(id="minecraft:b", name="Widget")
    ranked = rank_candidates("widget", (second, first))
    assert [entry.candidate.id for entry in ranked] == ["minecraft:a", "minecraft:b"]


def test_a_candidate_that_matches_nothing_is_dropped() -> None:
    ranked = rank_candidates("zzz", (RankingCandidate(id="minecraft:a", name="Stone"),))
    assert ranked == ()


def test_an_empty_query_matches_nothing() -> None:
    ranked = rank_candidates("", (RankingCandidate(id="minecraft:a", name="Stone"),))
    assert ranked == ()
