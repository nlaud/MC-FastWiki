"""Tests for `pipeline.extract.structure`: structure extraction from mcmeta."""

import json

from pipeline.extract.structure import (
    STRUCTURE_DIRECTORY,
    STRUCTURE_SET_DIRECTORY,
    ConcentricRingsPlacement,
    ExclusionZone,
    RandomSpreadPlacement,
    SiblingStructure,
    _namespaced,
    _parse_placement,
    _resolve_biomes,
    extract_structures,
)
from pipeline.extract.tags import TagIndex


def test_namespaced() -> None:
    assert _namespaced("plains") == "minecraft:plains"
    assert _namespaced("minecraft:plains") == "minecraft:plains"


def test_resolve_biomes_direct() -> None:
    tags = TagIndex({}, registry="worldgen/biome")
    assert _resolve_biomes("plains", biome_tags=tags, source="test") == ("minecraft:plains",)
    assert _resolve_biomes(
        ["plains", "minecraft:desert"], biome_tags=tags, source="test"
    ) == ("minecraft:desert", "minecraft:plains")


def test_resolve_biomes_tag() -> None:
    files = {
        "tags/worldgen/biome/has_structure/village_plains.json": json.dumps(
            {"values": ["minecraft:plains", "minecraft:meadow"]}
        ).encode("utf-8")
    }
    tags = TagIndex(files, registry="worldgen/biome")
    resolved = _resolve_biomes(
        "#minecraft:has_structure/village_plains", biome_tags=tags, source="test"
    )
    assert resolved == ("minecraft:meadow", "minecraft:plains")


def test_parse_placement_random_spread() -> None:
    raw = {
        "type": "minecraft:random_spread",
        "spacing": 32,
        "separation": 8,
        "spread_type": "linear",
        "frequency": 0.004,
        "exclusion_zone": {
            "other_set": "minecraft:villages",
            "chunk_count": 10,
        },
        "salt": 12345,
    }
    placement = _parse_placement(raw, source="test")
    assert isinstance(placement, RandomSpreadPlacement)
    assert placement.spacing == 32
    assert placement.separation == 8
    assert placement.spread_type == "linear"
    assert placement.frequency == 0.004
    assert placement.exclusion_zone == ExclusionZone(
        other_set="minecraft:villages", chunk_count=10
    )
    assert placement.salt == 12345


def test_parse_placement_concentric_rings() -> None:
    raw = {
        "type": "minecraft:concentric_rings",
        "count": 128,
        "distance": 32,
        "spread": 3,
        "preferred_biomes": "#minecraft:stronghold_biased_to",
        "salt": 0,
    }
    placement = _parse_placement(raw, source="test")
    assert isinstance(placement, ConcentricRingsPlacement)
    assert placement.count == 128
    assert placement.distance == 32
    assert placement.spread == 3
    assert placement.preferred_biomes == "#minecraft:stronghold_biased_to"


def test_extract_structures_mock() -> None:
    files = {
        # Dimension tags so dimension resolution succeeds
        "tags/worldgen/biome/is_overworld.json": json.dumps(
            {"values": ["minecraft:plains", "minecraft:desert"]}
        ).encode("utf-8"),
        "tags/worldgen/biome/is_nether.json": json.dumps(
            {"values": ["minecraft:nether_wastes"]}
        ).encode("utf-8"),
        "tags/worldgen/biome/is_end.json": json.dumps(
            {"values": ["minecraft:the_end"]}
        ).encode("utf-8"),
        # Structure sets
        f"{STRUCTURE_SET_DIRECTORY}villages.json": json.dumps(
            {
                "structures": [
                    {"structure": "minecraft:village_plains", "weight": 1},
                    {"structure": "minecraft:village_desert", "weight": 2},
                ],
                "placement": {
                    "type": "minecraft:random_spread",
                    "spacing": 34,
                    "separation": 8,
                },
            }
        ).encode("utf-8"),
        f"{STRUCTURE_SET_DIRECTORY}pillager_outposts.json": json.dumps(
            {
                "structures": [
                    {"structure": "minecraft:pillager_outpost", "weight": 1},
                ],
                "placement": {
                    "type": "minecraft:random_spread",
                    "spacing": 40,
                    "separation": 16,
                    "exclusion_zone": {
                        "other_set": "minecraft:villages",
                        "chunk_count": 10,
                    },
                },
            }
        ).encode("utf-8"),
        # Structures
        f"{STRUCTURE_DIRECTORY}village_plains.json": json.dumps(
            {
                "type": "minecraft:jigsaw",
                "biomes": ["minecraft:plains"],
                "step": "surface_structures",
                "spawn_overrides": {},
            }
        ).encode("utf-8"),
        f"{STRUCTURE_DIRECTORY}village_desert.json": json.dumps(
            {
                "type": "minecraft:jigsaw",
                "biomes": ["minecraft:desert"],
                "step": "surface_structures",
                "spawn_overrides": {
                    "monster": {"spawns": []},  # Suppressed category
                },
            }
        ).encode("utf-8"),
        f"{STRUCTURE_DIRECTORY}pillager_outpost.json": json.dumps(
            {
                "type": "minecraft:jigsaw",
                "biomes": ["minecraft:plains", "minecraft:desert"],
                "step": "surface_structures",
                "spawn_overrides": {
                    "monster": {
                        "spawns": [
                            {
                                "type": "minecraft:pillager",
                                "weight": 1,
                                "minCount": 1,
                                "maxCount": 1,
                            }
                        ]
                    }
                },
            }
        ).encode("utf-8"),
    }

    index = extract_structures(files)
    assert len(index) == 3
    assert "minecraft:village_plains" in index.structures
    assert "minecraft:village_desert" in index.structures
    assert "minecraft:pillager_outpost" in index.structures

    plains = index.structures["minecraft:village_plains"]
    assert plains.dimension == "overworld"
    assert plains.step == "surface_structures"
    assert plains.biomes == ("minecraft:plains",)
    # Siblings excludes self
    assert plains.siblings == (
        SiblingStructure(structure="minecraft:village_desert", weight=2),
    )

    desert = index.structures["minecraft:village_desert"]
    assert desert.suppressed_spawns == ("monster",)
    assert desert.siblings == (
        SiblingStructure(structure="minecraft:village_plains", weight=1),
    )

    outpost = index.structures["minecraft:pillager_outpost"]
    assert len(outpost.spawns) == 1
    assert outpost.spawns[0].entity_type == "minecraft:pillager"
    assert outpost.siblings == ()
    assert isinstance(outpost.placement, RandomSpreadPlacement)
    assert outpost.placement.exclusion_zone == ExclusionZone(
        other_set="minecraft:villages", chunk_count=10
    )

    # Check biomes on structure entries
    assert plains.biomes == ("minecraft:plains",)
    assert outpost.biomes == ("minecraft:desert", "minecraft:plains")
    assert desert.biomes == ("minecraft:desert",)
