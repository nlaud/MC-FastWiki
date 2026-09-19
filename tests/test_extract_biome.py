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


def natural_mob_spawns(
    spawns_by_category: dict[str, list[dict[str, object]]],
    spawn_costs: dict[str, dict[str, float]] | None = None,
) -> dict[str, object]:
    """Return the attribute block a 26.3 biome states its spawn table in.

    Up to 26.2 a biome carried `spawners` and `spawn_costs` at its top level.
    26.3 moved both behind `minecraft:gameplay/natural_mob_spawns` and replaced
    each entry's `minCount`/`maxCount` pair with one `count`, which is a fixed
    integer or a uniform provider. The tests below write the real shape rather
    than the old one, so a reader of this file sees what the pack now holds.
    """
    return {
        "attributes": {
            "minecraft:gameplay/natural_mob_spawns": {
                "modifier": "overlay",
                "argument": {
                    "spawns_by_category": spawns_by_category,
                    "spawn_costs": spawn_costs or {},
                },
            }
        }
    }


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
            **natural_mob_spawns({
                "creature": [
                    {
                        "type": "minecraft:parrot",
                        "weight": 40,
                        "count": {
                            "type": "minecraft:uniform",
                            "min_inclusive": 1,
                            "max_inclusive": 2,
                        },
                    },
                    {"type": "minecraft:chicken", "weight": 10, "count": 4},
                    {"type": "minecraft:chicken", "weight": 10, "count": 4},
                ],
                "monster": [
                    {
                        "type": "minecraft:ocelot",
                        "weight": 2,
                        "count": {
                            "type": "minecraft:uniform",
                            "min_inclusive": 1,
                            "max_inclusive": 3,
                        },
                    },
                ],
            }),
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
            **natural_mob_spawns({
                "monster": [
                    {"type": "minecraft:slime", "weight": 100, "count": 4},
                    {"type": "minecraft:slime", "weight": 1, "count": 1},
                ],
            }),
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
            **natural_mob_spawns({}),
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
            **natural_mob_spawns(
                {}, {"minecraft:skeleton": {"charge": 0.7, "energy_budget": 0.15}}
            ),
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
            **natural_mob_spawns({}),
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
            **natural_mob_spawns({}),
        }).encode("utf-8"),
    }

    with pytest.raises(ExtractError, match="resolves 2 dimensions"):
        extract_biomes(files)


def test_a_biome_with_no_spawn_attribute_raises_rather_than_reading_as_empty() -> None:
    """A pack this reader does not understand is a broken read, not a dead biome.

    26.3 moved the spawn table behind `minecraft:gameplay/natural_mob_spawns`.
    A reader that shrugged at a missing attribute would turn the next such move
    into "nothing spawns anywhere" and publish it, which is the failure the
    whole 26.3 break was made of.
    """
    files = {
        "tags/worldgen/biome/is_overworld.json": json.dumps({"values": []}).encode("utf-8"),
        "tags/worldgen/biome/is_nether.json": json.dumps({"values": []}).encode("utf-8"),
        "tags/worldgen/biome/is_end.json": json.dumps({"values": []}).encode("utf-8"),
        "worldgen/biome/plains.json": json.dumps({
            "temperature": 0.8,
            "downfall": 0.4,
            "has_precipitation": True,
            "attributes": {"minecraft:visual/sky_color": {"argument": 7907327}},
        }).encode("utf-8"),
    }
    with pytest.raises(ExtractError, match="natural_mob_spawns"):
        extract_biomes(files)


def test_a_fixed_count_and_a_uniform_count_both_resolve_to_a_group_size() -> None:
    """26.3 states one `count` where 26.2 stated `minCount` and `maxCount`.

    A fixed integer is the same number twice, which is what the two old fields
    held for every entry that did not vary. A uniform provider carries the pair.
    """
    files = {
        "tags/worldgen/biome/is_overworld.json": json.dumps(
            {"values": ["minecraft:plains"]}
        ).encode("utf-8"),
        "tags/worldgen/biome/is_nether.json": json.dumps({"values": []}).encode("utf-8"),
        "tags/worldgen/biome/is_end.json": json.dumps({"values": []}).encode("utf-8"),
        "worldgen/biome/plains.json": json.dumps({
            "temperature": 0.8,
            "downfall": 0.4,
            "has_precipitation": True,
            **natural_mob_spawns({
                "creature": [
                    {"type": "minecraft:cow", "weight": 8, "count": 4},
                    {
                        "type": "minecraft:horse",
                        "weight": 5,
                        "count": {
                            "type": "minecraft:uniform",
                            "min_inclusive": 2,
                            "max_inclusive": 6,
                        },
                    },
                ]
            }),
        }).encode("utf-8"),
    }
    creatures = extract_biomes(files)["minecraft:plains"].spawners["creature"]
    by_type = {e.entity_type: e for e in creatures}
    assert (by_type["minecraft:cow"].min_count, by_type["minecraft:cow"].max_count) == (4, 4)
    assert (by_type["minecraft:horse"].min_count, by_type["minecraft:horse"].max_count) == (2, 6)


def test_a_count_this_reader_cannot_model_drops_the_entry_rather_than_guessing() -> None:
    """A provider that is not a plain inclusive range states no group size."""
    files = {
        "tags/worldgen/biome/is_overworld.json": json.dumps(
            {"values": ["minecraft:plains"]}
        ).encode("utf-8"),
        "tags/worldgen/biome/is_nether.json": json.dumps({"values": []}).encode("utf-8"),
        "tags/worldgen/biome/is_end.json": json.dumps({"values": []}).encode("utf-8"),
        "worldgen/biome/plains.json": json.dumps({
            "temperature": 0.8,
            "downfall": 0.4,
            "has_precipitation": True,
            **natural_mob_spawns({
                "creature": [
                    {
                        "type": "minecraft:cow",
                        "weight": 8,
                        "count": {"type": "minecraft:biased_to_bottom", "n": 3, "p": 0.5},
                    }
                ]
            }),
        }).encode("utf-8"),
    }
    assert extract_biomes(files)["minecraft:plains"].spawners["creature"] == ()
