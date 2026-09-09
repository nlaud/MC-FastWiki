"""Tests for `pipeline.extract.biome`: biome extraction from mcmeta."""

import json

import pytest

from pipeline.extract import ExtractError
from pipeline.extract.biome import (
    extract_biomes,
    resolve_precipitation,
)
from pipeline.extract.generation import Dimension


def test_resolve_precipitation() -> None:
    assert resolve_precipitation(False, 2.0) == "none"
    assert resolve_precipitation(False, 0.0) == "none"
    assert resolve_precipitation(True, 0.0) == "snow"
    assert resolve_precipitation(True, -0.5) == "snow"
    assert resolve_precipitation(True, 0.14) == "snow"
    assert resolve_precipitation(True, 0.15) == "rain"
    assert resolve_precipitation(True, 0.8) == "rain"


def test_extract_biomes_empty() -> None:
    index = extract_biomes({})
    assert len(index) == 0


def test_extract_biomes_basic_and_duplicate_merging() -> None:
    files = {
        "tags/worldgen/biome/is_overworld.json": json.dumps(
            {"values": ["minecraft:jungle"]}
        ).encode("utf-8"),
        "tags/worldgen/biome/is_nether.json": json.dumps({"values": []}).encode("utf-8"),
        "tags/worldgen/biome/is_end.json": json.dumps({"values": []}).encode("utf-8"),
        "worldgen/biome/jungle.json": json.dumps({
            "temperature": 0.95,
            "downfall": 0.9,
            "has_precipitation": True,
            "spawners": {
                "creature": [
                    {"type": "minecraft:parrot", "weight": 40, "minCount": 1, "maxCount": 2},
                    {"type": "minecraft:chicken", "weight": 10, "minCount": 4, "maxCount": 4},
                    {"type": "minecraft:chicken", "weight": 10, "minCount": 4, "maxCount": 4},
                ],
                "monster": [
                    {"type": "minecraft:ocelot", "weight": 2, "minCount": 1, "maxCount": 3},
                ],
            },
        }).encode("utf-8"),
    }

    index = extract_biomes(files)
    assert len(index) == 1
    assert "minecraft:jungle" in index

    entry = index["minecraft:jungle"]
    assert entry.id == "minecraft:jungle"
    assert entry.dimension == Dimension.OVERWORLD
    assert entry.temperature == 0.95
    assert entry.temperature_modifier is None
    assert entry.downfall == 0.9
    assert entry.has_precipitation is True
    assert entry.precipitation == "rain"

    # Category totals
    assert entry.category_totals["creature"] == 60
    assert entry.category_totals["monster"] == 2

    # Chicken merged into one entry with weight 20
    creatures = entry.spawners["creature"]
    assert len(creatures) == 2
    parrot = next(s for s in creatures if s.entity_type == "minecraft:parrot")
    assert parrot.weight == 40
    assert parrot.min_count == 1
    assert parrot.max_count == 2

    chicken = next(s for s in creatures if s.entity_type == "minecraft:chicken")
    assert chicken.weight == 20
    assert chicken.min_count == 4
    assert chicken.max_count == 4


def test_extract_biomes_group_size_union() -> None:
    files = {
        "tags/worldgen/biome/is_overworld.json": json.dumps(
            {"values": ["minecraft:swamp"]}
        ).encode("utf-8"),
        "tags/worldgen/biome/is_nether.json": json.dumps({"values": []}).encode("utf-8"),
        "tags/worldgen/biome/is_end.json": json.dumps({"values": []}).encode("utf-8"),
        "worldgen/biome/swamp.json": json.dumps({
            "temperature": 0.8,
            "downfall": 0.9,
            "has_precipitation": True,
            "spawners": {
                "monster": [
                    {"type": "minecraft:slime", "weight": 100, "minCount": 4, "maxCount": 4},
                    {"type": "minecraft:slime", "weight": 1, "minCount": 1, "maxCount": 1},
                ],
            },
        }).encode("utf-8"),
    }

    index = extract_biomes(files)
    slime = index["minecraft:swamp"].spawners["monster"][0]
    assert slime.weight == 101
    assert slime.min_count == 1
    assert slime.max_count == 4


def test_extract_biomes_the_void_carries_no_dimension() -> None:
    files = {
        "tags/worldgen/biome/is_overworld.json": json.dumps({"values": []}).encode("utf-8"),
        "tags/worldgen/biome/is_nether.json": json.dumps({"values": []}).encode("utf-8"),
        "tags/worldgen/biome/is_end.json": json.dumps({"values": []}).encode("utf-8"),
        "worldgen/biome/the_void.json": json.dumps({
            "temperature": 0.5,
            "downfall": 0.5,
            "has_precipitation": False,
            "spawners": {},
        }).encode("utf-8"),
    }

    index = extract_biomes(files)
    assert "minecraft:the_void" in index
    entry = index["minecraft:the_void"]
    assert entry.dimension is None
    assert entry.precipitation == "none"
    assert entry.spawners == {}


def test_extract_biomes_modifier_probability_costs() -> None:
    files = {
        "tags/worldgen/biome/is_overworld.json": json.dumps({"values": []}).encode("utf-8"),
        "tags/worldgen/biome/is_nether.json": json.dumps(
            {"values": ["minecraft:soul_sand_valley"]}
        ).encode("utf-8"),
        "tags/worldgen/biome/is_end.json": json.dumps({"values": []}).encode("utf-8"),
        "worldgen/biome/soul_sand_valley.json": json.dumps({
            "temperature": 2.0,
            "temperature_modifier": "frozen",
            "downfall": 0.0,
            "has_precipitation": False,
            "creature_spawn_probability": 0.07,
            "spawn_costs": {
                "minecraft:skeleton": {"charge": 0.7, "energy_budget": 0.15},
            },
            "spawners": {},
        }).encode("utf-8"),
    }

    index = extract_biomes(files)
    entry = index["minecraft:soul_sand_valley"]
    assert entry.dimension == Dimension.NETHER
    assert entry.temperature_modifier == "frozen"
    assert entry.creature_spawn_probability == 0.07
    assert entry.spawn_costs == {"minecraft:skeleton": {"charge": 0.7, "energy_budget": 0.15}}


def test_extract_biomes_no_dimension_tag_carries_no_dimension() -> None:
    """A biome no dimension tag lists carries `None`, not a default.

    `the_void` is the real case: it is in none of the three tags because it belongs
    to no single world. Saying "Overworld" would put a claim on the page that no
    data file makes.
    """
    files = {
        "tags/worldgen/biome/is_overworld.json": json.dumps({"values": []}).encode("utf-8"),
        "tags/worldgen/biome/is_nether.json": json.dumps({"values": []}).encode("utf-8"),
        "tags/worldgen/biome/is_end.json": json.dumps({"values": []}).encode("utf-8"),
        "worldgen/biome/custom_biome.json": json.dumps({
            "temperature": 0.5,
            "downfall": 0.5,
            "has_precipitation": False,
            "spawners": {},
        }).encode("utf-8"),
    }

    index = extract_biomes(files)

    assert index["minecraft:custom_biome"].dimension is None


def test_extract_biomes_ambiguous_dimension_raises() -> None:
    """Two dimension tags claiming one biome is a contradiction, and still raises."""
    values = ["minecraft:custom_biome"]
    files = {
        "tags/worldgen/biome/is_overworld.json": json.dumps({"values": values}).encode("utf-8"),
        "tags/worldgen/biome/is_nether.json": json.dumps({"values": values}).encode("utf-8"),
        "tags/worldgen/biome/is_end.json": json.dumps({"values": []}).encode("utf-8"),
        "worldgen/biome/custom_biome.json": json.dumps({
            "temperature": 0.5,
            "downfall": 0.5,
            "has_precipitation": False,
            "spawners": {},
        }).encode("utf-8"),
    }

    with pytest.raises(ExtractError, match="resolves 2 dimensions"):
        extract_biomes(files)
