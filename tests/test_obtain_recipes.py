"""`pipeline.obtain.recipes`: mcmeta `recipe/*.json` turned into `Producer`s.

Every shape tested here was verified live against the pinned `26.2-data`
archive on 2026-09-01 -- see the module's own docstring for the exact
recipes read. No test opens a socket; `archive()` below builds a small
`recipe/` tree in memory, the same way `tests/test_extract_harvest.py`
builds its own tag files.
"""

import json
from collections.abc import Mapping
from typing import Any

import pytest

from pipeline.extract.tags import TagIndex
from pipeline.obtain import ObtainError
from pipeline.obtain.producer import ObtainMethod
from pipeline.obtain.recipes import RecipeExtractionResult, extract_recipes


def archive(
    recipes: Mapping[str, Any], *, tags: Mapping[str, list[str]] = {}
) -> dict[str, bytes]:
    """Return a fake `data/minecraft` archive of `recipe/*.json` files, plus any tag files."""
    files = {
        f"recipe/{name}.json": json.dumps(document).encode() for name, document in recipes.items()
    }
    files.update(
        {
            f"tags/item/{path}.json": json.dumps({"values": values}).encode()
            for path, values in tags.items()
        }
    )
    return files


def item_tags(files: Mapping[str, bytes]) -> TagIndex:
    return TagIndex(files, registry="item")


def extract(
    recipes: Mapping[str, Any], *, tags: Mapping[str, list[str]] = {}
) -> RecipeExtractionResult:
    files = archive(recipes, tags=tags)
    return extract_recipes(files, tags=item_tags(files))


# --- crafting_shaped ----------------------------------------------------------


def test_crafting_shaped_reads_the_key_pattern_and_result() -> None:
    result = extract(
        {
            "iron_pickaxe": {
                "type": "minecraft:crafting_shaped",
                "key": {"#": "minecraft:stick", "X": "minecraft:iron_ingot"},
                "pattern": ["XXX", " # ", " # "],
                "result": {"id": "minecraft:iron_pickaxe"},
            }
        }
    )
    assert len(result.producers) == 1
    producer = result.producers[0]
    assert producer.method is ObtainMethod.CRAFTING
    assert producer.output.item == "minecraft:iron_pickaxe"
    assert producer.output.count == 1
    inputs = {i.item: i.count for i in producer.inputs}
    assert inputs == {"minecraft:stick": 2, "minecraft:iron_ingot": 3}
    assert producer.grid_width == 3
    assert producer.grid_height == 3
    assert producer.grid == (1, 1, 1, None, 0, None, None, 0, None)


def test_crafting_shaped_resolves_a_tag_ingredient_through_the_item_registry() -> None:
    result = extract(
        {
            "stairs": {
                "type": "minecraft:crafting_shaped",
                "key": {"#": "#minecraft:planks"},
                "pattern": ["#  "],
                "result": {"id": "minecraft:oak_stairs", "count": 4},
            }
        },
        tags={"planks": ["minecraft:oak_planks", "minecraft:spruce_planks"]},
    )
    producer = result.producers[0]
    assert producer.output.count == 4
    (single_input,) = producer.inputs
    assert single_input.item is None
    assert single_input.tag == "minecraft:planks"
    assert single_input.members == ("minecraft:oak_planks", "minecraft:spruce_planks")


def test_crafting_shaped_raises_on_a_pattern_symbol_the_key_does_not_define() -> None:
    with pytest.raises(ObtainError, match="key does not define"):
        extract(
            {
                "bad": {
                    "type": "minecraft:crafting_shaped",
                    "key": {"X": "minecraft:stick"},
                    "pattern": ["XY"],
                    "result": {"id": "minecraft:stick"},
                }
            }
        )


# --- crafting_shapeless --------------------------------------------------------


def test_crafting_shapeless_reads_a_list_of_ingredients() -> None:
    result = extract(
        {
            "fire_charge": {
                "type": "minecraft:crafting_shapeless",
                "ingredients": [
                    "minecraft:gunpowder",
                    "minecraft:blaze_powder",
                    ["minecraft:coal", "minecraft:charcoal"],
                ],
                "result": {"id": "minecraft:fire_charge", "count": 3},
            }
        }
    )
    producer = result.producers[0]
    assert producer.output.count == 3
    by_item = {i.item: i for i in producer.inputs}
    assert set(by_item) == {"minecraft:gunpowder", "minecraft:blaze_powder", "minecraft:charcoal"}
    # The untagged alternatives list: no tag id exists to label it, so the
    # alphabetically-first alternative becomes the representative `item`,
    # and the full list survives in `members`.
    alternatives = by_item["minecraft:charcoal"]
    assert alternatives.tag is None
    assert alternatives.members == ("minecraft:charcoal", "minecraft:coal")
    assert producer.grid is None
    assert producer.grid_width is None
    assert producer.grid_height is None


def test_crafting_shapeless_sums_the_count_of_a_repeated_ingredient() -> None:
    result = extract(
        {
            "bowl": {
                "type": "minecraft:crafting_shapeless",
                "ingredients": [
                    "minecraft:oak_planks",
                    "minecraft:oak_planks",
                    "minecraft:oak_planks",
                ],
                "result": {"id": "minecraft:bowl"},
            }
        }
    )
    (single_input,) = result.producers[0].inputs
    assert single_input.item == "minecraft:oak_planks"
    assert single_input.count == 3


# --- smelting family ------------------------------------------------------------


@pytest.mark.parametrize(
    ("recipe_type", "station"),
    [
        ("minecraft:smelting", "furnace"),
        ("minecraft:blasting", "blast_furnace"),
        ("minecraft:smoking", "smoker"),
        ("minecraft:campfire_cooking", "campfire"),
    ],
)
def test_each_cooking_recipe_type_gets_smelting_method_and_its_own_station(
    recipe_type: str, station: str
) -> None:
    result = extract(
        {
            "iron_ingot_from_smelting_iron_ore": {
                "type": recipe_type,
                "experience": 0.7,
                "ingredient": "minecraft:iron_ore",
                "result": {"id": "minecraft:iron_ingot"},
            }
        }
    )
    producer = result.producers[0]
    assert producer.method is ObtainMethod.SMELTING
    assert producer.station == station
    assert producer.inputs == (producer.inputs[0],)
    assert producer.inputs[0].item == "minecraft:iron_ore"


# --- stonecutting and smithing_transform ---------------------------------------


def test_stonecutting_reads_the_single_ingredient_and_a_result_count() -> None:
    result = extract(
        {
            "andesite_slab_from_andesite_stonecutting": {
                "type": "minecraft:stonecutting",
                "ingredient": "minecraft:andesite",
                "result": {"count": 2, "id": "minecraft:andesite_slab"},
            }
        }
    )
    producer = result.producers[0]
    assert producer.method is ObtainMethod.CRAFTING
    assert producer.station == "stonecutter"
    assert producer.output.count == 2


def test_smithing_transform_reads_all_three_ingredient_slots() -> None:
    result = extract(
        {
            "netherite_sword_smithing": {
                "type": "minecraft:smithing_transform",
                "template": "minecraft:netherite_upgrade_smithing_template",
                "base": "minecraft:diamond_sword",
                "addition": "#minecraft:netherite_tool_materials",
                "result": {"id": "minecraft:netherite_sword"},
            }
        },
        tags={"netherite_tool_materials": ["minecraft:netherite_ingot"]},
    )
    producer = result.producers[0]
    assert producer.method is ObtainMethod.CRAFTING
    assert producer.station == "smithing_table"
    items = {i.item for i in producer.inputs if i.item is not None}
    tags = {i.tag for i in producer.inputs if i.tag is not None}
    assert items == {"minecraft:netherite_upgrade_smithing_template", "minecraft:diamond_sword"}
    assert tags == {"minecraft:netherite_tool_materials"}


# --- crafting_transmute, crafting_dye, crafting_special_firework_star_fade -----


def test_crafting_transmute_reads_input_and_material() -> None:
    result = extract(
        {
            "light_blue_bundle": {
                "type": "minecraft:crafting_transmute",
                "input": "#minecraft:bundles",
                "material": "minecraft:light_blue_dye",
                "result": {"id": "minecraft:light_blue_bundle"},
            }
        },
        tags={"bundles": ["minecraft:bundle", "minecraft:light_blue_bundle"]},
    )
    assert len(result.producers) == 1
    producer = result.producers[0]
    assert producer.method is ObtainMethod.CRAFTING
    assert producer.station is None
    assert producer.output.item == "minecraft:light_blue_bundle"
    assert producer.output.count == 1
    assert len(producer.inputs) == 2
    assert producer.inputs[0].tag == "minecraft:bundles"
    assert producer.inputs[0].count == 1
    assert producer.inputs[1].item == "minecraft:light_blue_dye"
    assert producer.inputs[1].count == 1
    assert producer.note is None


def test_crafting_transmute_map_cloning_records_range_in_note() -> None:
    result = extract(
        {
            "map_cloning": {
                "type": "minecraft:crafting_transmute",
                "add_material_count_to_result": True,
                "input": "minecraft:filled_map",
                "material": "minecraft:map",
                "material_count": {"max": 8, "min": 1},
                "result": {"id": "minecraft:filled_map"},
            }
        }
    )
    assert len(result.producers) == 1
    producer = result.producers[0]
    assert producer.method is ObtainMethod.CRAFTING
    assert producer.output.item == "minecraft:filled_map"
    assert producer.output.count == 1
    assert len(producer.inputs) == 2
    assert producer.inputs[0].item == "minecraft:filled_map"
    assert producer.inputs[0].count == 1
    assert producer.inputs[1].item == "minecraft:map"
    assert producer.inputs[1].count == 1
    assert producer.note is not None
    assert "1 to 8" in producer.note


def test_crafting_dye_reads_target_and_dye() -> None:
    result = extract(
        {
            "leather_boots_dyed": {
                "type": "minecraft:crafting_dye",
                "dye": "#minecraft:dyes",
                "group": "dyed_armor",
                "target": "minecraft:leather_boots",
                "result": {"id": "minecraft:leather_boots"},
            }
        },
        tags={"dyes": ["minecraft:red_dye", "minecraft:blue_dye"]},
    )
    assert len(result.producers) == 1
    producer = result.producers[0]
    assert producer.method is ObtainMethod.CRAFTING
    assert producer.station is None
    assert producer.output.item == "minecraft:leather_boots"
    assert producer.inputs[0].item == "minecraft:leather_boots"
    assert producer.inputs[1].tag == "minecraft:dyes"


def test_crafting_special_firework_star_fade_reads_target_and_dye() -> None:
    result = extract(
        {
            "firework_star_fade": {
                "type": "minecraft:crafting_special_firework_star_fade",
                "dye": "#minecraft:dyes",
                "target": "minecraft:firework_star",
                "result": {"id": "minecraft:firework_star"},
            }
        },
        tags={"dyes": ["minecraft:red_dye", "minecraft:blue_dye"]},
    )
    assert len(result.producers) == 1
    producer = result.producers[0]
    assert producer.method is ObtainMethod.CRAFTING
    assert producer.station is None
    assert producer.output.item == "minecraft:firework_star"
    assert producer.inputs[0].item == "minecraft:firework_star"
    assert producer.inputs[1].tag == "minecraft:dyes"


# --- firework_star, imbue, decorated_pot ---------------------------------------


def test_crafting_special_firework_star_reads_fuel_and_dye_and_records_modifiers() -> None:
    result = extract(
        {
            "firework_star": {
                "type": "minecraft:crafting_special_firework_star",
                "fuel": "minecraft:gunpowder",
                "dye": "#minecraft:dyes",
                "shapes": {
                    "burst": "minecraft:feather",
                    "creeper": "#minecraft:skulls",
                    "large_ball": "minecraft:fire_charge",
                    "star": "minecraft:gold_nugget",
                },
                "trail": "minecraft:diamond",
                "twinkle": "minecraft:glowstone_dust",
                "result": {"id": "minecraft:firework_star"},
            }
        },
        tags={"dyes": ["minecraft:red_dye", "minecraft:blue_dye"]},
    )
    assert len(result.producers) == 1
    producer = result.producers[0]
    assert producer.method is ObtainMethod.CRAFTING
    assert producer.station is None
    assert producer.output.item == "minecraft:firework_star"
    assert producer.output.count == 1
    assert len(producer.inputs) == 2
    assert producer.inputs[0].item == "minecraft:gunpowder"
    assert producer.inputs[0].count == 1
    assert producer.inputs[1].tag == "minecraft:dyes"
    assert producer.inputs[1].count == 1
    assert producer.note is not None
    assert "shapes" in producer.note
    assert "trail" in producer.note
    assert "twinkle" in producer.note


def test_crafting_imbue_reads_material_and_source_with_count_eight() -> None:
    result = extract(
        {
            "tipped_arrow": {
                "type": "minecraft:crafting_imbue",
                "material": "minecraft:arrow",
                "source": "minecraft:lingering_potion",
                "result": {"count": 8, "id": "minecraft:tipped_arrow"},
            }
        }
    )
    assert len(result.producers) == 1
    producer = result.producers[0]
    assert producer.method is ObtainMethod.CRAFTING
    assert producer.station is None
    assert producer.output.item == "minecraft:tipped_arrow"
    assert producer.output.count == 8
    assert len(producer.inputs) == 2
    assert producer.inputs[0].item == "minecraft:arrow"
    assert producer.inputs[0].count == 1
    assert producer.inputs[1].item == "minecraft:lingering_potion"
    assert producer.inputs[1].count == 1


def test_crafting_decorated_pot_aggregates_into_single_input_with_count_four() -> None:
    result = extract(
        {
            "decorated_pot": {
                "type": "minecraft:crafting_decorated_pot",
                "back": "#minecraft:decorated_pot_ingredients",
                "front": "#minecraft:decorated_pot_ingredients",
                "left": "#minecraft:decorated_pot_ingredients",
                "right": "#minecraft:decorated_pot_ingredients",
                "result": {"id": "minecraft:decorated_pot"},
            }
        },
        tags={"decorated_pot_ingredients": ["minecraft:brick", "minecraft:angler_pottery_sherd"]},
    )
    assert len(result.producers) == 1
    producer = result.producers[0]
    assert producer.method is ObtainMethod.CRAFTING
    assert producer.station is None
    assert producer.output.item == "minecraft:decorated_pot"
    assert len(producer.inputs) == 1
    assert producer.inputs[0].tag == "minecraft:decorated_pot_ingredients"
    assert producer.inputs[0].count == 4


# --- Skipped, not raised: crafting_special_* and unhandled types --------------


def test_crafting_special_recipes_are_skipped_and_reported_not_raised() -> None:
    result = extract(
        {
            "map_extending": {
                "type": "minecraft:crafting_special_mapextending",
                "map": "minecraft:filled_map",
                "material": "minecraft:paper",
                "result": {"id": "minecraft:filled_map"},
            },
            "banner_duplicate": {
                "type": "minecraft:crafting_special_bannerduplicate",
                "result": {"id": "minecraft:white_banner"},
            },
        }
    )
    assert result.producers == ()
    assert len(result.skipped) == 2
    for skipped in result.skipped:
        assert skipped.reason == "a crafting_special_* recipe declares no ingredient list"


def test_smithing_trim_is_skipped_as_unhandled_type() -> None:
    """`smithing_trim` is skipped under unhandled recipe type."""
    result = extract(
        {
            "sentry_armor_trim": {
                "type": "minecraft:smithing_trim",
                "template": "minecraft:sentry_armor_trim_smithing_template",
                "base": "minecraft:iron_chestplate",
                "addition": "minecraft:redstone",
            }
        }
    )
    assert result.producers == ()
    assert len(result.skipped) == 1
    assert result.skipped[0].recipe_type == "minecraft:smithing_trim"
    assert result.skipped[0].reason == "unhandled recipe type"


def test_an_unrecognized_future_recipe_type_is_skipped_not_raised() -> None:
    """A new recipe type is new data, not a broken read -- `TODO.md` Decision 6's own reasoning."""
    result = extract(
        {
            "mystery": {
                "type": "minecraft:some_future_type",
                "result": {"id": "minecraft:mystery"},
            }
        }
    )
    assert result.producers == ()
    assert result.skipped[0].reason == "unhandled recipe type"


# --- Malformed shapes of a type this module claims to handle raise -----------


@pytest.mark.parametrize(
    "document",
    [
        {"type": "minecraft:crafting_shaped", "key": {}, "pattern": ["X"], "result": {"id": "x"}},
        {"type": "minecraft:crafting_shapeless", "ingredients": [], "result": {"id": "x"}},
        {"type": "minecraft:smelting", "result": {"id": "x"}},
        {"type": "minecraft:smelting", "ingredient": "minecraft:iron_ore", "result": {}},
        {
            "type": "minecraft:crafting_transmute",
            "input": "minecraft:filled_map",
            "result": {"id": "minecraft:filled_map"},
        },
        {
            "type": "minecraft:crafting_dye",
            "dye": "minecraft:red_dye",
            "result": {"id": "minecraft:leather_boots"},
        },
        {
            "type": "minecraft:crafting_special_firework_star",
            "dye": "minecraft:red_dye",
            "result": {"id": "minecraft:firework_star"},
        },
        {
            "type": "minecraft:crafting_imbue",
            "material": "minecraft:arrow",
            "result": {"id": "minecraft:tipped_arrow"},
        },
        {
            "type": "minecraft:crafting_decorated_pot",
            "front": "minecraft:brick",
            "left": "minecraft:brick",
            "right": "minecraft:brick",
            "result": {"id": "minecraft:decorated_pot"},
        },
    ],
)
def test_a_malformed_recipe_of_a_known_type_raises(document: dict[str, Any]) -> None:
    with pytest.raises(ObtainError):
        extract({"bad": document})


def test_no_recipe_file_at_all_raises() -> None:
    with pytest.raises(ObtainError, match="broken scrape"):
        extract_recipes({}, tags=TagIndex({}, registry="item"))


def test_results_are_read_in_sorted_recipe_key_order() -> None:
    """Determinism: two recipes read in dict-insertion order regardless of key order."""
    result = extract(
        {
            "z_recipe": {
                "type": "minecraft:smelting",
                "ingredient": "minecraft:iron_ore",
                "result": {"id": "minecraft:iron_ingot"},
            },
            "a_recipe": {
                "type": "minecraft:smelting",
                "ingredient": "minecraft:gold_ore",
                "result": {"id": "minecraft:gold_ingot"},
            },
        }
    )
    assert [p.source_id for p in result.producers] == ["minecraft:a_recipe", "minecraft:z_recipe"]


def test_dyeing_recipe_picks_only_white_variant_without_cycling_members() -> None:
    """Dyeing recipes take only the white item, without an alternatives list."""
    result = extract(
        {
            "dye_red_bed": {
                "type": "minecraft:crafting_shapeless",
                "group": "bed_dye",
                "ingredients": [
                    "minecraft:red_dye",
                    [
                        "minecraft:white_bed",
                        "minecraft:orange_bed",
                        "minecraft:black_bed",
                    ],
                ],
                "result": {"id": "minecraft:red_bed"},
            }
        }
    )
    assert len(result.producers) == 1
    producer = result.producers[0]
    by_item = {i.item: i for i in producer.inputs}
    assert "minecraft:white_bed" in by_item
    assert "minecraft:black_bed" not in by_item
    bed_input = by_item["minecraft:white_bed"]
    assert bed_input.members == ()


def test_dye_white_recipes_are_skipped() -> None:
    """White dyeing recipes bleach colored items; white items are crafted from base materials."""
    result = extract(
        {
            "dye_white_bed": {
                "type": "minecraft:crafting_shapeless",
                "group": "bed_dye",
                "ingredients": [
                    "minecraft:white_dye",
                    ["minecraft:red_bed", "minecraft:black_bed"],
                ],
                "result": {"id": "minecraft:white_bed"},
            }
        }
    )
    assert len(result.producers) == 0
    assert len(result.skipped) == 1
    assert result.skipped[0].recipe_id == "minecraft:dye_white_bed"
    assert "bleach" in result.skipped[0].reason
