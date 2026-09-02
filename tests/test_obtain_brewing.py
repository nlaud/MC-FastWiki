"""`pipeline.obtain.brewing`: a `BrewingIndex` plus the potion registry, turned into producers.

The registry list `REAL_POTION_PATHS` below is the live 46-entry
`registries["potion"]` of the pinned `26.2-summary`, fetched 2026-09-01 --
see this module's own docstring for why every producer is checked against
exactly this list before it is emitted.
"""

from collections.abc import Mapping

import pytest

from pipeline.enrich.brewing import BaseRecipe, BrewingIndex, EffectRecipe
from pipeline.obtain.brewing import (
    LINGERING_POTION_ITEM,
    SPLASH_POTION_ITEM,
    build_brewing_producers,
)
from pipeline.obtain.producer import ObtainMethod

# The live 46-entry `registries["potion"]` of the pinned `26.2-summary`,
# verified 2026-09-01.
REAL_POTION_PATHS: tuple[str, ...] = (
    "awkward",
    "fire_resistance",
    "harming",
    "healing",
    "infested",
    "invisibility",
    "leaping",
    "long_fire_resistance",
    "long_invisibility",
    "long_leaping",
    "long_night_vision",
    "long_poison",
    "long_regeneration",
    "long_slow_falling",
    "long_slowness",
    "long_strength",
    "long_swiftness",
    "long_turtle_master",
    "long_water_breathing",
    "long_weakness",
    "luck",
    "mundane",
    "night_vision",
    "oozing",
    "poison",
    "regeneration",
    "slow_falling",
    "slowness",
    "strength",
    "strong_harming",
    "strong_healing",
    "strong_leaping",
    "strong_poison",
    "strong_regeneration",
    "strong_slowness",
    "strong_strength",
    "strong_swiftness",
    "strong_turtle_master",
    "swiftness",
    "thick",
    "turtle_master",
    "water",
    "water_breathing",
    "weakness",
    "weaving",
    "wind_charged",
)

# The corruption map the live `Effect ingredients` table produces (see
# `tests/test_enrich_brewing.py` for the parse itself).
CORRUPTION_MAP: Mapping[str, str] = {
    "Speed": "Slowness",
    "Jump Boost": "Slowness",
    "Instant Health": "Instant Damage",
    "Poison": "Instant Damage",
    "Night Vision": "Invisibility",
}

# The fifteen effect ingredient rows, minus Fermented Spider Eye, matching
# the live table.
EFFECT_RECIPES = (
    EffectRecipe(ingredient_item="minecraft:sugar", effect_name="Speed"),
    EffectRecipe(ingredient_item="minecraft:rabbit_foot", effect_name="Jump Boost"),
    EffectRecipe(ingredient_item="minecraft:glistering_melon_slice", effect_name="Instant Health"),
    EffectRecipe(ingredient_item="minecraft:spider_eye", effect_name="Poison"),
    EffectRecipe(ingredient_item="minecraft:blaze_powder", effect_name="Strength"),
    EffectRecipe(ingredient_item="minecraft:golden_carrot", effect_name="Night Vision"),
    EffectRecipe(ingredient_item="minecraft:ghast_tear", effect_name="Regeneration"),
    EffectRecipe(ingredient_item="minecraft:pufferfish", effect_name="Water Breathing"),
    EffectRecipe(ingredient_item="minecraft:magma_cream", effect_name="Fire Resistance"),
    EffectRecipe(
        ingredient_item="minecraft:turtle_helmet", effect_name="Slowness + Resistance"
    ),
    EffectRecipe(ingredient_item="minecraft:phantom_membrane", effect_name="Slow Falling"),
    EffectRecipe(ingredient_item="minecraft:breeze_rod", effect_name="Wind Charged"),
    EffectRecipe(ingredient_item="minecraft:stone", effect_name="Infested"),
    EffectRecipe(ingredient_item="minecraft:cobweb", effect_name="Weaving"),
    EffectRecipe(ingredient_item="minecraft:slime_block", effect_name="Oozing"),
)


def real_index(*, effect_recipes: tuple[EffectRecipe, ...] = EFFECT_RECIPES) -> BrewingIndex:
    return BrewingIndex(
        base_recipes=(
            BaseRecipe(ingredient_item="minecraft:nether_wart", result_path="awkward"),
            BaseRecipe(ingredient_item="minecraft:glowstone_dust", result_path="thick"),
            BaseRecipe(ingredient_item="minecraft:redstone", result_path="mundane"),
        ),
        weakness_recipe=BaseRecipe(
            ingredient_item="minecraft:fermented_spider_eye", result_path="weakness"
        ),
        effect_recipes=effect_recipes,
        corruption_map=CORRUPTION_MAP,
        gunpowder_item="minecraft:gunpowder",
        dragon_breath_item="minecraft:dragon_breath",
        unbrewable_names=("potion of Luck", "uncraftable potion"),
    )


# --- The five effect-name exceptions -------------------------------------------


@pytest.mark.parametrize(
    ("effect_name", "potion_path"),
    [
        ("Speed", "swiftness"),
        ("Jump Boost", "leaping"),
        ("Instant Health", "healing"),
        ("Instant Damage", "harming"),  # only reached via corruption, not a direct row
        ("Slowness + Resistance", "turtle_master"),
    ],
)
def test_the_five_irregular_effect_names_resolve_to_their_potion_path(
    effect_name: str, potion_path: str
) -> None:
    result = build_brewing_producers(real_index(), REAL_POTION_PATHS)
    ids = {p.output.item for p in result.producers}
    assert f"minecraft:potion/{potion_path}" in ids


def test_a_regular_effect_name_resolves_by_casefold_and_underscore_join() -> None:
    result = build_brewing_producers(real_index(), REAL_POTION_PATHS)
    ids = {p.output.item for p in result.producers}
    assert "minecraft:potion/water_breathing" in ids


# --- Coverage: only luck is unobtainable, and the water bottle is filled ------


def test_the_full_registry_leaves_exactly_luck_uncovered() -> None:
    """`luck` is the one potion the wiki's own Un-brewable section names for Java.

    `water` was uncovered too until the water bottle got its `FILLING`
    producer. It is not brewed, so it has no brewing recipe and never will,
    but it is obtainable -- and leaving it with no producer at all stopped
    every potion tree in the game one step above the glass bottle.
    """
    result = build_brewing_producers(real_index(), REAL_POTION_PATHS)
    assert result.uncovered_potions == ("luck",)


def test_the_water_bottle_is_filled_from_a_glass_bottle() -> None:
    """Without this edge no potion tree reaches the glass bottle, the glass, or the sand.

    The water bottle is an input of all 44 brewable potions and the output of
    nothing else in the pipeline, so it is the one place a missing producer
    truncates every tree at once rather than just its own.
    """
    result = build_brewing_producers(real_index(), REAL_POTION_PATHS)
    filling = [p for p in result.producers if p.method is ObtainMethod.FILLING]

    assert len(filling) == 1
    assert filling[0].output.item == "minecraft:potion/water"
    assert [i.item for i in filling[0].inputs] == ["minecraft:glass_bottle"]
    assert filling[0].station is None


def test_the_water_bottle_is_not_emitted_when_the_registry_lacks_it() -> None:
    """Every producer is checked against the registry, and this one is no exception."""
    without_water = tuple(path for path in REAL_POTION_PATHS if path != "water")
    result = build_brewing_producers(real_index(), without_water)
    assert not [p for p in result.producers if p.method is ObtainMethod.FILLING]


def test_long_healing_is_never_invented() -> None:
    """Instant effects take no duration extension; the registry holds no `long_healing`."""
    result = build_brewing_producers(real_index(), REAL_POTION_PATHS)
    ids = {p.output.item for p in result.producers}
    assert "minecraft:potion/long_healing" not in ids
    assert "minecraft:potion/strong_invisibility" not in ids


# --- Long/strong modifiers, mechanical against the registry -------------------


def test_a_long_variant_is_only_emitted_when_the_registry_holds_it() -> None:
    result = build_brewing_producers(real_index(), REAL_POTION_PATHS)
    long_regeneration = [
        p for p in result.producers if p.output.item == "minecraft:potion/long_regeneration"
    ]
    assert len(long_regeneration) == 1
    producer = long_regeneration[0]
    assert producer.method is ObtainMethod.BREWING
    inputs = {i.item for i in producer.inputs}
    assert inputs == {"minecraft:redstone", "minecraft:potion/regeneration"}


def test_a_strong_variant_uses_glowstone_dust() -> None:
    result = build_brewing_producers(real_index(), REAL_POTION_PATHS)
    strong_strength = next(
        p for p in result.producers if p.output.item == "minecraft:potion/strong_strength"
    )
    inputs = {i.item for i in strong_strength.inputs}
    assert inputs == {"minecraft:glowstone_dust", "minecraft:potion/strength"}


# --- Corruption, per prefix -----------------------------------------------------


def test_corruption_applies_to_the_base_pair() -> None:
    result = build_brewing_producers(real_index(), REAL_POTION_PATHS)
    matches = [p for p in result.producers if p.output.item == "minecraft:potion/slowness"]
    sources = {frozenset(i.item for i in p.inputs) for p in matches}
    assert frozenset({"minecraft:fermented_spider_eye", "minecraft:potion/swiftness"}) in sources
    assert frozenset({"minecraft:fermented_spider_eye", "minecraft:potion/leaping"}) in sources


def test_corruption_carries_through_the_long_prefix() -> None:
    """`long_swiftness` + fermented spider eye -> `long_slowness`, both real registry ids."""
    result = build_brewing_producers(real_index(), REAL_POTION_PATHS)
    matches = [p for p in result.producers if p.output.item == "minecraft:potion/long_slowness"]
    sources = {
        i.item
        for p in matches
        for i in p.inputs
        if i.item != "minecraft:fermented_spider_eye"
    }
    assert "minecraft:potion/long_swiftness" in sources
    assert "minecraft:potion/long_leaping" in sources


def test_corruption_is_skipped_when_the_prefixed_target_does_not_exist() -> None:
    """`long_poison` exists but `long_harming` does not, so that corruption producer never fires."""
    result = build_brewing_producers(real_index(), REAL_POTION_PATHS)
    assert not any(p.output.item == "minecraft:potion/long_harming" for p in result.producers)


# --- Container steps: real vanilla items, not invented entities --------------


def test_every_potion_gets_a_splash_producer() -> None:
    result = build_brewing_producers(real_index(), REAL_POTION_PATHS)
    splash = [p for p in result.producers if p.output.item == SPLASH_POTION_ITEM]
    assert len(splash) == len(REAL_POTION_PATHS)


def test_lingering_comes_from_splash_not_from_a_drinkable_potion_directly() -> None:
    result = build_brewing_producers(real_index(), REAL_POTION_PATHS)
    lingering = [p for p in result.producers if p.output.item == LINGERING_POTION_ITEM]
    assert len(lingering) == 1
    inputs = {i.item for i in lingering[0].inputs}
    assert inputs == {"minecraft:dragon_breath", SPLASH_POTION_ITEM}


# --- An unresolvable effect lands in the report, never silently dropped -------


def test_an_effect_name_with_no_registry_match_is_reported() -> None:
    mystery = (
        *EFFECT_RECIPES,
        EffectRecipe(ingredient_item="minecraft:mystery_item", effect_name="Mystery Effect"),
    )
    result = build_brewing_producers(real_index(effect_recipes=mystery), REAL_POTION_PATHS)
    assert any(u.effect_name == "Mystery Effect" for u in result.unresolved_effects)
    ids = {p.output.item for p in result.producers}
    assert "minecraft:potion/mystery_effect" not in ids
