"""`pipeline.enrich.brewing`: the `Brewing` page's wikitext, parsed without a socket.

The `Effect ingredients` table fixture below is the real table, fetched live
on 2026-09-01 and pasted in verbatim (trimmed of nothing), so the rowspan
runs and the one mixed-edition cell are exactly what the live page carries --
`rowspan="2"` for Sugar/Rabbit's Foot both corrupting to Slowness,
`rowspan="10"` for the run from Ghast Tear through Slime Block, and Blaze
Powder's `None{{only|java|short=1}} <br> [[Weakness]]{{only|bedrock|short=1}}`
corrupted cell.
"""

import pytest

from pipeline.enrich import EnrichError
from pipeline.enrich.brewing import BrewingIndex, parse_brewing

# --- The real `Effect ingredients` table, verified live 2026-09-01 ----------

EFFECT_INGREDIENTS = """
=== Effect ingredients ===
{| class="wikitable sortable" style="text-align: center;" data-description="Effect ingredients"
|+Effect ingredients
|-
! Name
! Icon
! Effect
! Effect when corrupted
|-
!{{anchor|Sugar}}[[Sugar]]
|{{Slot|Sugar}}
|[[Speed]]
| rowspan="2" |[[Slowness]]
|-
!{{anchor|Rabbit's Foot}}[[Rabbit's Foot]]
|{{Slot|Rabbit's Foot}}
|[[Jump Boost]]
|-
!{{anchor|Glistering Melon Slice}}[[Glistering Melon Slice]]
|{{Slot|Glistering Melon Slice}}
|[[Instant Health]]
| rowspan="2" | [[Instant Damage]]
|-
!{{anchor|Spider Eye}}[[Spider Eye]]
|{{Slot|Spider Eye}}
|[[Poison]]
|-
!{{anchor|Blaze Powder}}[[Blaze Powder]]
|{{Slot|Blaze Powder}}
|[[Strength]]
| None{{only|java|short=1}} <br> [[Weakness]]{{only|bedrock|short=1}}
|-
!{{anchor|Golden Carrot}}[[Golden Carrot]]
|{{Slot|Golden Carrot}}
|[[Night Vision]]
| [[Invisibility]]
|-
!{{anchor|Ghast Tear}}[[Ghast Tear]]
|{{Slot|Ghast Tear}}
|[[Regeneration]]
| rowspan="10" | None
|-
!{{anchor|Pufferfish}}[[Pufferfish (item)|Pufferfish]]
|{{Slot|Pufferfish|link=Pufferfish (item)}}
|[[Water Breathing]]
|-
!{{anchor|Magma Cream}}[[Magma Cream]]
|{{Slot|Magma Cream}}
|[[Fire Resistance]]
|-
!{{anchor|Turtle Shell}}[[Turtle Shell]]
|{{Slot|Turtle Shell}}
|[[Slowness]] + [[Resistance]]
|-
!{{anchor|Phantom Membrane}}[[Phantom Membrane]]
|{{Slot|Phantom Membrane}}
|[[Slow Falling]]
|-
!{{anchor|Breeze Rod}}[[Breeze Rod]]
|{{Slot|Breeze Rod}}
|[[Wind Charged]]
|-
!{{anchor|Stone}}[[Stone]]
|{{Slot|Stone}}
|[[Infested]]
|-
!{{anchor|Cobweb}}[[Cobweb]]
|{{Slot|Cobweb}}
|[[Weaving]]
|-
!{{anchor|Fermented Spider Eye}}[[Fermented spider eye|Fermented Spider Eye]]
|{{Slot|Fermented Spider Eye}}
|[[Weakness]]
|-
!{{anchor|Slime Block}}[[Slime Block]]
|{{Slot|Slime Block}}
|[[Oozing]]
|}
"""

BASE_POTIONS = """
== Brewing recipes ==
=== Base potions ===
{| class="wikitable" style="text-align: center;" data-description="Base potions"
|+Base potions
! Potion
! Recipe(s)
! Precursor to
|-
!{{Inventory slot|Awkward Potion}}<br>Awkward potion
|{{Brewing Stand
 |Input= Nether Wart
 |Output2= Water Bottle
<!-- comment -->
 }}
| Effect potions
|-
!{{Inventory slot|Mundane Potion}}<br>Mundane potion
|{{Brewing Stand
 |Input= Redstone Dust; Sugar; Rabbit's Foot; Glistering Melon Slice; Spider Eye;
 Magma Cream; Blaze Powder; Ghast Tear; Breeze Rod; Stone; Cobweb; Slime Block
<!-- comment -->
 |Output2= Water Bottle
 }}
| None{{only|je|short=1}}<br> [[Potion of Weakness]]{{only|be|short=1}}
|-
!{{Inventory slot|Thick Potion}}<br>Thick potion
|{{Brewing Stand
 |Input= Glowstone Dust
 |Output2= Water Bottle
 }}
| None{{only|je|short=1}}<br> [[Potion of Weakness]]{{only|be|short=1}}
|}
"""

SPLASH_LINGERING = """
==== Splash and lingering potions ====
By adding gunpowder, a drinking potion can be turned into a [[splash potion]].
Subsequently, adding dragon's breath to a splash potion makes a lingering potion.
"""

UNBREWABLE = """
=== Un-brewable potions ===
The ''[[uncraftable potion]]'', ''[[potion of Luck]]{{only|java|short=JE}}'' and
the [[potion of Decay|''potion of Decay'']]{{only|bedrock|short=BE}} cannot be brewed.
"""


def page(*, effect_ingredients: str = EFFECT_INGREDIENTS, base_potions: str = BASE_POTIONS) -> str:
    return effect_ingredients + base_potions + SPLASH_LINGERING + UNBREWABLE


# --- The rowspan trap ---------------------------------------------------------


def test_a_rowspan_of_two_carries_the_corrupted_value_to_the_next_row() -> None:
    """Sugar declares `rowspan=\"2\"`; Rabbit's Foot inherits it with no cell of its own."""
    index = parse_brewing(page())
    assert index.corruption_map["Speed"] == "Slowness"
    assert index.corruption_map["Jump Boost"] == "Slowness"


def test_a_rowspan_of_ten_covers_every_row_it_claims() -> None:
    """Ghast Tear declares `rowspan=\"10\"`; None of the ten rows adds a corruption edge."""
    index = parse_brewing(page())
    corrupted_by_ten_row_ingredients = {
        "Regeneration",
        "Water Breathing",
        "Fire Resistance",
        "Slowness + Resistance",
        "Slow Falling",
        "Wind Charged",
        "Infested",
        "Weaving",
        "Oozing",
    }
    assert not corrupted_by_ten_row_ingredients & set(index.corruption_map)


def test_the_weakness_row_becomes_a_base_recipe_not_an_effect_recipe() -> None:
    """Fermented Spider Eye + water bottle -> Weakness, per the page's own prose."""
    index = parse_brewing(page())
    assert index.weakness_recipe.ingredient_item == "minecraft:fermented_spider_eye"
    assert index.weakness_recipe.result_path == "weakness"
    assert "Weakness" not in {r.effect_name for r in index.effect_recipes}


# --- The one mixed-edition cell ------------------------------------------------


def test_blaze_powders_mixed_edition_cell_keeps_only_the_java_half() -> None:
    """`None{{only|java}}` / `[[Weakness]]{{only|bedrock}}`: Java has no Strength corruption."""
    index = parse_brewing(page())
    assert "Strength" not in index.corruption_map


def test_golden_carrots_unmarked_single_row_cell_is_read_directly() -> None:
    index = parse_brewing(page())
    assert index.corruption_map["Night Vision"] == "Invisibility"


def test_a_two_row_rowspan_that_is_itself_edition_marked_still_carries_forward() -> None:
    """Glistering Melon Slice/Spider Eye share a rowspan="2" corrupted cell: Instant Damage."""
    index = parse_brewing(page())
    assert index.corruption_map["Instant Health"] == "Instant Damage"
    assert index.corruption_map["Poison"] == "Instant Damage"


# --- Base potions ---------------------------------------------------------------


def test_base_potions_reads_all_twelve_mundane_ingredients() -> None:
    index = parse_brewing(page())
    mundane = [r.ingredient_item for r in index.base_recipes if r.result_path == "mundane"]
    assert len(mundane) == 12
    assert "minecraft:redstone" in mundane  # "Redstone Dust" is irregular: not redstone_dust


def test_base_potions_reads_awkward_and_thick_as_single_ingredient_recipes() -> None:
    index = parse_brewing(page())
    awkward = [r for r in index.base_recipes if r.result_path == "awkward"]
    thick = [r for r in index.base_recipes if r.result_path == "thick"]
    assert [r.ingredient_item for r in awkward] == ["minecraft:nether_wart"]
    assert [r.ingredient_item for r in thick] == ["minecraft:glowstone_dust"]


# --- Un-brewable potions ---------------------------------------------------------


def test_unbrewable_potions_keeps_only_java_relevant_names() -> None:
    index = parse_brewing(page())
    assert "potion of Luck" in index.unbrewable_names
    assert "uncraftable potion" in index.unbrewable_names
    assert "potion of Decay" not in index.unbrewable_names


# --- Failure guards -------------------------------------------------------------


def test_an_empty_parse_raises() -> None:
    with pytest.raises(EnrichError):
        parse_brewing("no brewing content here at all")


def test_a_short_effect_ingredients_table_raises() -> None:
    short = """
=== Effect ingredients ===
{| class="wikitable"
|-
! Name
! Icon
! Effect
! Effect when corrupted
|-
!{{anchor|Sugar}}[[Sugar]]
|{{Slot|Sugar}}
|[[Speed]]
|None
|-
!{{anchor|Fermented Spider Eye}}[[Fermented spider eye|Fermented Spider Eye]]
|{{Slot|Fermented Spider Eye}}
|[[Weakness]]
|None
|}
"""
    with pytest.raises(EnrichError, match="too few"):
        parse_brewing(page(effect_ingredients=short))


def test_an_unknown_ingredient_name_raises() -> None:
    unknown = EFFECT_INGREDIENTS.replace("Sugar", "Mystery Dust")
    with pytest.raises(EnrichError, match="unknown"):
        parse_brewing(page(effect_ingredients=unknown))


def test_a_page_with_no_weakness_row_raises() -> None:
    """`weakness_recipe` is a required field this module must always be able to fill."""
    no_weakness = EFFECT_INGREDIENTS.replace("Fermented Spider Eye", "Sugar")
    with pytest.raises(EnrichError):
        parse_brewing(page(effect_ingredients=no_weakness))


def test_a_missing_splash_lingering_mention_raises() -> None:
    text = page().replace("gunpowder", "TNT")
    with pytest.raises(EnrichError, match="gunpowder"):
        parse_brewing(text)


def test_a_missing_un_brewable_section_raises() -> None:
    text = EFFECT_INGREDIENTS + BASE_POTIONS + SPLASH_LINGERING
    with pytest.raises(EnrichError, match="Un-brewable"):
        parse_brewing(text)


def test_the_index_is_frozen_and_cannot_be_mutated_after_it_is_built() -> None:
    index = parse_brewing(page())
    assert isinstance(index, BrewingIndex)
    with pytest.raises(Exception):  # noqa: B017,PT011 -- pydantic's frozen-model error
        index.gunpowder_item = "minecraft:stick"  # type: ignore[misc]
