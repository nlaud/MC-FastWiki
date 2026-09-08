"""Tests for pipeline.extract.enchantment."""

import json
from collections.abc import Iterable, Mapping
from typing import Any

import pytest

from pipeline.extract import ExtractError
from pipeline.extract.enchantment import extract_enchantments
from pipeline.normalize.entity import IntegerRange


def _make_files(
    enchantments: Mapping[str, dict[str, Any]],
    *,
    item_tags: Mapping[str, Iterable[str]] | None = None,
    enchant_tags: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, bytes]:
    """Create in-memory archive files for enchantments and tags."""
    files: dict[str, bytes] = {}
    for name, data in enchantments.items():
        files[f"enchantment/{name}.json"] = json.dumps(data).encode("utf-8")

    if item_tags:
        for tag_path, values in item_tags.items():
            files[f"tags/item/{tag_path}.json"] = json.dumps({"values": list(values)}).encode(
                "utf-8"
            )

    if enchant_tags:
        for tag_path, values in enchant_tags.items():
            files[f"tags/enchantment/{tag_path}.json"] = json.dumps(
                {"values": list(values)}
            ).encode("utf-8")

    return files


def test_extract_fortune_in_memory() -> None:
    enchantments = {
        "fortune": {
            "anvil_cost": 4,
            "max_level": 3,
            "weight": 2,
            "slots": ["mainhand"],
            "min_cost": {"base": 15, "per_level_above_first": 9},
            "max_cost": {"base": 65, "per_level_above_first": 9},
            "supported_items": "#minecraft:enchantable/mining_loot",
            "exclusive_set": "#minecraft:exclusive_set/mining",
        }
    }
    item_tags = {
        "enchantable/mining_loot": [
            "minecraft:diamond_pickaxe",
            "minecraft:iron_pickaxe",
        ]
    }
    enchant_tags = {
        "exclusive_set/mining": [
            "minecraft:fortune",
            "minecraft:silk_touch",
        ],
        "treasure": [],
        "curse": [],
        "tradeable": ["minecraft:fortune"],
    }

    files = _make_files(enchantments, item_tags=item_tags, enchant_tags=enchant_tags)
    index = extract_enchantments(files)

    assert len(index) == 1
    assert "minecraft:fortune" in index
    fortune = index["minecraft:fortune"]

    assert fortune.id == "minecraft:fortune"
    assert fortune.max_level == 3
    assert fortune.anvil_cost == 4
    assert fortune.weight == 2
    assert fortune.rarity == "rare"
    assert fortune.slots == ("mainhand",)
    assert fortune.cost_ranges == (
        IntegerRange(minimum=15, maximum=65),
        IntegerRange(minimum=24, maximum=74),
        IntegerRange(minimum=33, maximum=83),
    )
    assert fortune.supported_items_group == "enchantable/mining_loot"
    assert fortune.supported_items == (
        "minecraft:diamond_pickaxe",
        "minecraft:iron_pickaxe",
    )
    assert fortune.primary_items is None
    # Own id must be excluded from exclusive set
    assert fortune.exclusive_set == ("minecraft:silk_touch",)
    assert fortune.treasure is False
    assert fortune.curse is False
    assert fortune.tradeable is True


def test_exclusive_set_formats() -> None:
    """Exclusive set handles tag ref, bare list, and single string ID."""
    enchantments = {
        "e_tag": {
            "anvil_cost": 1,
            "max_level": 1,
            "weight": 10,
            "slots": ["any"],
            "min_cost": {"base": 1, "per_level_above_first": 0},
            "max_cost": {"base": 10, "per_level_above_first": 0},
            "supported_items": "#minecraft:items",
            "exclusive_set": "#minecraft:conflicts",
        },
        "e_list": {
            "anvil_cost": 1,
            "max_level": 1,
            "weight": 10,
            "slots": ["any"],
            "min_cost": {"base": 1, "per_level_above_first": 0},
            "max_cost": {"base": 10, "per_level_above_first": 0},
            "supported_items": "#minecraft:items",
            "exclusive_set": ["minecraft:other_a", "minecraft:e_list", "other_b"],
        },
        "e_single": {
            "anvil_cost": 1,
            "max_level": 1,
            "weight": 10,
            "slots": ["any"],
            "min_cost": {"base": 1, "per_level_above_first": 0},
            "max_cost": {"base": 10, "per_level_above_first": 0},
            "supported_items": "#minecraft:items",
            "exclusive_set": "minecraft:conflict_c",
        },
    }
    item_tags = {"items": ["minecraft:stick"]}
    enchant_tags = {
        "conflicts": ["minecraft:e_tag", "minecraft:other_tag"],
    }

    files = _make_files(enchantments, item_tags=item_tags, enchant_tags=enchant_tags)
    index = extract_enchantments(files)

    assert index["minecraft:e_tag"].exclusive_set == ("minecraft:other_tag",)
    assert index["minecraft:e_list"].exclusive_set == ("minecraft:other_a", "minecraft:other_b")
    assert index["minecraft:e_single"].exclusive_set == ("minecraft:conflict_c",)


def test_supported_and_primary_items_formats() -> None:
    """Item sets handle tags, lists, and single item IDs, and drop primary when identical."""
    enchantments = {
        "e_identical": {
            "anvil_cost": 1,
            "max_level": 1,
            "weight": 10,
            "slots": ["mainhand"],
            "min_cost": {"base": 1, "per_level_above_first": 0},
            "max_cost": {"base": 10, "per_level_above_first": 0},
            "supported_items": "#minecraft:group_a",
            "primary_items": "#minecraft:group_a",
        },
        "e_different": {
            "anvil_cost": 1,
            "max_level": 1,
            "weight": 10,
            "slots": ["mainhand"],
            "min_cost": {"base": 1, "per_level_above_first": 0},
            "max_cost": {"base": 10, "per_level_above_first": 0},
            "supported_items": ["minecraft:sword", "minecraft:axe"],
            "primary_items": "minecraft:sword",
        },
    }
    item_tags = {"group_a": ["minecraft:iron_sword"]}

    files = _make_files(enchantments, item_tags=item_tags)
    index = extract_enchantments(files)

    assert index["minecraft:e_identical"].primary_items is None
    assert index["minecraft:e_different"].primary_items_group == "sword"
    assert index["minecraft:e_different"].primary_items == ("minecraft:sword",)
    assert index["minecraft:e_different"].supported_items_group == "custom"
    assert index["minecraft:e_different"].supported_items == (
        "minecraft:axe",
        "minecraft:sword",
    )


def test_treasure_and_curse_flags() -> None:
    enchantments = {
        "mending": {
            "anvil_cost": 4,
            "max_level": 1,
            "weight": 2,
            "slots": ["any"],
            "min_cost": {"base": 25, "per_level_above_first": 0},
            "max_cost": {"base": 75, "per_level_above_first": 0},
            "supported_items": ["minecraft:bow"],
        },
        "curse": {
            "anvil_cost": 8,
            "max_level": 1,
            "weight": 1,
            "slots": ["any"],
            "min_cost": {"base": 25, "per_level_above_first": 0},
            "max_cost": {"base": 50, "per_level_above_first": 0},
            "supported_items": ["minecraft:bow"],
        },
    }
    enchant_tags = {
        "treasure": ["minecraft:mending", "minecraft:curse"],
        "curse": ["minecraft:curse"],
        "tradeable": ["minecraft:mending"],
    }
    files = _make_files(enchantments, enchant_tags=enchant_tags)
    index = extract_enchantments(files)

    assert index["minecraft:mending"].treasure is True
    assert index["minecraft:mending"].curse is False
    assert index["minecraft:mending"].tradeable is True

    assert index["minecraft:curse"].treasure is True
    assert index["minecraft:curse"].curse is True
    assert index["minecraft:curse"].tradeable is False


def test_empty_directory_raises_extract_error() -> None:
    with pytest.raises(ExtractError, match="holds no enchantment files"):
        extract_enchantments({})


def test_unknown_weight_raises_extract_error() -> None:
    enchantments = {
        "bad_weight": {
            "anvil_cost": 1,
            "max_level": 1,
            "weight": 99,
            "slots": ["any"],
            "min_cost": {"base": 1, "per_level_above_first": 0},
            "max_cost": {"base": 10, "per_level_above_first": 0},
            "supported_items": ["minecraft:bow"],
        }
    }
    files = _make_files(enchantments)
    with pytest.raises(ExtractError, match="unknown enchantment weight"):
        extract_enchantments(files)
