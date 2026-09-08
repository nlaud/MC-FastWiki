"""Tests for `pipeline.extract.generation`: natural generation extraction from mcmeta."""

import json
from pathlib import Path

import pytest

from pipeline.cli.build import _mcmeta_transport, _offline_transport
from pipeline.extract.generation import (
    BlockGeneration,
    Dimension,
    GenerationScope,
    VeinFacts,
    _band,
    _densest_y_of_scope,
    _extract_blocks_from_config,
    _rate,
    extract_generation,
    resolve_anchor,
)
from pipeline.fetch.cache import ContentCache
from pipeline.fetch.mcmeta import fetch_data_files, resolve_mcmeta_tag

WORLDGEN_GROUPS = (
    "worldgen/configured_feature",
    "worldgen/placed_feature",
    "worldgen/biome",
    "tags",
)


def _scope(block: BlockGeneration, dimension: Dimension) -> GenerationScope:
    """Return the one scope of `block` in `dimension`, failing if there is none."""
    scopes = [s for s in block.scopes if s.dimension is dimension]
    assert len(scopes) == 1, f"expected exactly one {dimension} scope, got {len(scopes)}"
    return scopes[0]


def test_resolve_anchor() -> None:
    # Absolute
    assert resolve_anchor({"absolute": 15}, floor=-64, top=320) == 15
    assert resolve_anchor(20, floor=-64, top=320) == 20

    # Above bottom
    assert resolve_anchor({"above_bottom": 10}, floor=-64, top=320) == -54
    assert resolve_anchor({"above_bottom": 0}, floor=0, top=256) == 0
    assert resolve_anchor({"above_bottom": 10}, floor=0, top=256) == 10

    # Below top
    assert resolve_anchor({"below_top": 10}, floor=-64, top=320) == 310
    assert resolve_anchor({"below_top": 0}, floor=0, top=256) == 256
    assert resolve_anchor({"below_top": 16}, floor=0, top=256) == 240

    # String anchors
    assert resolve_anchor("bottom", floor=-64, top=320) == -64
    assert resolve_anchor("top", floor=-64, top=320) == 320


def test_extract_blocks_from_config() -> None:
    # Ore
    ore_cfg = {
        "size": 8,
        "targets": [
            {"state": {"Name": "minecraft:coal_ore"}},
            {"state": {"Name": "minecraft:deepslate_coal_ore"}},
        ],
    }
    blocks, size = _extract_blocks_from_config("minecraft:ore", ore_cfg)
    assert blocks == ["minecraft:coal_ore", "minecraft:deepslate_coal_ore"]
    assert size == 8

    # Simple block
    simple_cfg = {
        "to_place": {
            "type": "minecraft:simple_state_provider",
            "state": {"Name": "minecraft:sweet_berry_bush"},
        }
    }
    blocks, size = _extract_blocks_from_config("minecraft:simple_block", simple_cfg)
    assert blocks == ["minecraft:sweet_berry_bush"]
    assert size is None

    # Disk
    disk_cfg = {
        "state_provider": {
            "type": "minecraft:simple_state_provider",
            "state": {"Name": "minecraft:clay"},
        },
        "radius": 2,
    }
    blocks, size = _extract_blocks_from_config("minecraft:disk", disk_cfg)
    assert blocks == ["minecraft:clay"]
    assert size is None

    # Block blob
    blob_cfg = {
        "state": {"Name": "minecraft:moss_block"},
        "radius": 5,
    }
    blocks, size = _extract_blocks_from_config("minecraft:block_blob", blob_cfg)
    assert blocks == ["minecraft:moss_block"]
    assert size is None


def test_band_clips_to_the_build_range_and_peaks_on_the_declared_one() -> None:
    """A band below the world floor is clipped; the trapezoid peak is not moved with it.

    This is `ore_diamond`, whose declared band is Y -144 to Y 16 in a world whose
    floor is -64.
    """
    placement = [
        {"type": "minecraft:count", "count": 7},
        {
            "type": "minecraft:height_range",
            "height": {
                "type": "minecraft:trapezoid",
                "min_inclusive": {"above_bottom": -80},
                "max_inclusive": {"above_bottom": 80},
            },
        },
    ]
    assert _band(placement, floor=-64, top=320) == (-64, 16, False, -64)


def test_band_of_a_heightmap_placement_is_a_surface_not_the_whole_world() -> None:
    placement = [
        {"type": "minecraft:in_square"},
        {"type": "minecraft:heightmap", "heightmap": "WORLD_SURFACE_WG"},
    ]
    assert _band(placement, floor=-64, top=320) == (None, None, True, None)

    # A placement that states neither states nothing, and gets nothing.
    assert _band([{"type": "minecraft:in_square"}], floor=-64, top=320) == (
        None,
        None,
        False,
        None,
    )


def test_rate_reads_only_the_counts_that_run_per_chunk() -> None:
    position = {"type": "minecraft:heightmap", "heightmap": "WORLD_SURFACE_WG"}

    # A count ahead of the position modifier is an attempt count.
    assert _rate([{"type": "minecraft:count", "count": 7}, position]) == (7, None)

    # A count behind it is patch density, so no attempt count is stated -- and the
    # "no modifier means one attempt" fallback must not fire either.
    assert _rate([position, {"type": "minecraft:count", "count": 96}]) == (None, None)

    # Rarity survives that, because the rarity filter did run per chunk.
    assert _rate(
        [
            {"type": "minecraft:rarity_filter", "chance": 32},
            position,
            {"type": "minecraft:count", "count": 96},
        ]
    ) == (None, 32)

    # A noise-driven count is no fixed number at all.
    assert _rate([{"type": "minecraft:noise_threshold_count", "noise_level": 0}, position]) == (
        None,
        None,
    )

    # A uniform count carries its average.
    assert _rate(
        [
            {
                "type": "minecraft:count",
                "count": {"type": "minecraft:uniform", "min_inclusive": 0, "max_inclusive": 1},
            },
            position,
        ]
    ) == (0.5, None)

    # Nothing at all means one attempt.
    assert _rate([{"type": "minecraft:in_square"}, position]) == (1, None)


def test_densest_y_of_scope() -> None:
    # Multiple veins with same densest_y covering the span -> kept
    veins = [
        VeinFacts(feature="f1", dimension=Dimension.OVERWORLD, min_y=-64, max_y=16, densest_y=-64),
        VeinFacts(feature="f2", dimension=Dimension.OVERWORLD, min_y=-64, max_y=32, densest_y=-64),
    ]
    assert _densest_y_of_scope(veins, -64, 32) == -64

    # Veins with different densest_y -> None
    veins_diff = [
        VeinFacts(feature="f1", dimension=Dimension.OVERWORLD, min_y=-64, max_y=16, densest_y=-64),
        VeinFacts(feature="f2", dimension=Dimension.OVERWORLD, min_y=-64, max_y=32, densest_y=0),
    ]
    assert _densest_y_of_scope(veins_diff, -64, 32) is None

    # Peaked veins do not cover the whole band -> None (e.g. Ancient Debris)
    veins_gap = [
        VeinFacts(feature="f1", dimension=Dimension.NETHER, min_y=8, max_y=24, densest_y=16),
        VeinFacts(feature="f2", dimension=Dimension.NETHER, min_y=8, max_y=119, densest_y=None),
    ]
    assert _densest_y_of_scope(veins_gap, 8, 119) is None

    # A scope with no band of its own cannot state a peak.
    assert _densest_y_of_scope(veins, None, None) is None


def test_synthetic_extraction_and_unsupported_skips() -> None:
    files = {
        "tags/worldgen/biome/is_overworld.json": json.dumps(
            {"values": ["minecraft:plains"]}
        ).encode("utf-8"),
        "tags/worldgen/biome/is_nether.json": json.dumps({"values": []}).encode("utf-8"),
        "tags/worldgen/biome/is_end.json": json.dumps({"values": []}).encode("utf-8"),
        "worldgen/biome/plains.json": json.dumps(
            {
                "features": [
                    ["minecraft:ore_test_placed", "minecraft:fancy_tree_placed"],
                ]
            }
        ).encode("utf-8"),
        "worldgen/configured_feature/fancy_tree.json": json.dumps(
            {"type": "minecraft:tree", "config": {}}
        ).encode("utf-8"),
        "worldgen/placed_feature/fancy_tree_placed.json": json.dumps(
            {"feature": "minecraft:fancy_tree", "placement": []}
        ).encode("utf-8"),
        "worldgen/configured_feature/ore_test.json": json.dumps(
            {
                "type": "minecraft:ore",
                "config": {
                    "size": 4,
                    "targets": [{"state": {"Name": "minecraft:iron_ore"}}],
                },
            }
        ).encode("utf-8"),
        "worldgen/placed_feature/ore_test_placed.json": json.dumps(
            {
                "feature": "minecraft:ore_test",
                "placement": [
                    {"type": "minecraft:count", "count": 10},
                    {
                        "type": "minecraft:height_range",
                        "height": {
                            "type": "minecraft:uniform",
                            "min_inclusive": {"absolute": 0},
                            "max_inclusive": {"absolute": 64},
                        },
                    },
                ],
            }
        ).encode("utf-8"),
    }

    result = extract_generation(files)
    assert "minecraft:iron_ore" in result.blocks
    iron = result.blocks["minecraft:iron_ore"]
    assert len(iron.scopes) == 1
    overworld = _scope(iron, Dimension.OVERWORLD)
    assert overworld.min_y == 0
    assert overworld.max_y == 64
    assert overworld.attempts_per_chunk == 10
    assert overworld.biome_count == 1
    assert overworld.all_biomes_of_dimension is True
    assert overworld.biomes == ()
    assert len(overworld.veins) == 1
    assert overworld.veins[0].feature == "minecraft:ore_test_placed"
    assert overworld.veins[0].vein_size == 4

    # Tree feature was skipped
    assert len(result.report.skipped_features) == 1
    assert result.report.skipped_features[0].feature_id == "minecraft:fancy_tree"
    assert result.report.skipped_features[0].feature_type == "minecraft:tree"


def test_a_feature_in_two_dimensions_becomes_two_scopes() -> None:
    """A feature both worlds run states each world's own band, and drops neither.

    This is the shape of `brown_mushroom_normal`, which three nether biomes run
    alongside the overworld ones. The same `above_bottom 0` anchor resolves to a
    different Y in each world, which is why a scope is per dimension.
    """
    files = {
        "tags/worldgen/biome/is_overworld.json": json.dumps(
            {"values": ["minecraft:plains", "minecraft:forest"]}
        ).encode("utf-8"),
        "tags/worldgen/biome/is_nether.json": json.dumps(
            {"values": ["minecraft:nether_wastes"]}
        ).encode("utf-8"),
        "tags/worldgen/biome/is_end.json": json.dumps({"values": []}).encode("utf-8"),
        "worldgen/biome/plains.json": json.dumps(
            {"features": [["minecraft:both_worlds_placed"]]}
        ).encode("utf-8"),
        "worldgen/biome/forest.json": json.dumps({"features": [[]]}).encode("utf-8"),
        "worldgen/biome/nether_wastes.json": json.dumps(
            {"features": [["minecraft:both_worlds_placed"]]}
        ).encode("utf-8"),
        "worldgen/configured_feature/both_worlds.json": json.dumps(
            {
                "type": "minecraft:ore",
                "config": {"size": 3, "targets": [{"state": {"Name": "minecraft:gravel"}}]},
            }
        ).encode("utf-8"),
        "worldgen/placed_feature/both_worlds_placed.json": json.dumps(
            {
                "feature": "minecraft:both_worlds",
                "placement": [
                    {"type": "minecraft:count", "count": 2},
                    {
                        "type": "minecraft:height_range",
                        "height": {
                            "type": "minecraft:uniform",
                            "min_inclusive": {"above_bottom": 0},
                            "max_inclusive": {"above_bottom": 32},
                        },
                    },
                ],
            }
        ).encode("utf-8"),
    }

    gravel = extract_generation(files).blocks["minecraft:gravel"]
    assert [s.dimension for s in gravel.scopes] == [Dimension.OVERWORLD, Dimension.NETHER]

    overworld = _scope(gravel, Dimension.OVERWORLD)
    assert (overworld.min_y, overworld.max_y) == (-64, -32)
    assert overworld.biome_count == 1
    # One of the two overworld biomes runs it, so this is not "every biome".
    assert overworld.all_biomes_of_dimension is False
    assert overworld.biomes == ("minecraft:plains",)

    nether = _scope(gravel, Dimension.NETHER)
    assert (nether.min_y, nether.max_y) == (0, 32)
    assert nether.all_biomes_of_dimension is True


def test_real_cached_generation_extraction() -> None:
    cache_dir = Path("data/.cache")
    if not cache_dir.is_dir():
        pytest.skip("Cache not primed")

    store = ContentCache(cache_dir)
    transport = _mcmeta_transport(_offline_transport(store))
    try:
        data_tag = resolve_mcmeta_tag("26.2", branch="data", cache=store, transport=transport)
        files = fetch_data_files(
            data_tag,
            groups=WORLDGEN_GROUPS,
            cache=store,
            transport=transport,
        )
    except Exception:
        pytest.skip("mcmeta cache not primed")

    result = extract_generation(files)

    # Invariants from plan:
    assert len(result.blocks) == 52
    assert len(result.report.skipped_features) == 156

    # An ore whose band is clipped, and whose four veins agree on the peak.
    diamond = _scope(result.blocks["minecraft:diamond_ore"], Dimension.OVERWORLD)
    assert (diamond.min_y, diamond.max_y, diamond.densest_y) == (-64, 16, -64)
    assert diamond.all_biomes_of_dimension is True
    assert diamond.attempts_per_chunk == 13
    assert len(diamond.veins) == 4

    # Two veins at different depths, so the scope states no single peak.
    debris = _scope(result.blocks["minecraft:ancient_debris"], Dimension.NETHER)
    assert (debris.min_y, debris.max_y) == (8, 120)
    assert debris.densest_y is None
    assert len(debris.veins) == 2

    # Gravel generates in both worlds, and neither is dropped.
    gravel = result.blocks["minecraft:gravel"]
    assert [s.dimension for s in gravel.scopes] == [Dimension.OVERWORLD, Dimension.NETHER]
    gravel_nether = _scope(gravel, Dimension.NETHER)
    assert (gravel_nether.min_y, gravel_nether.max_y) == (5, 41)
    assert gravel_nether.attempts_per_chunk == 2

    # So do the mushrooms, which reach the nether through their overworld feature.
    mushroom = result.blocks["minecraft:brown_mushroom"]
    assert [s.dimension for s in mushroom.scopes] == [Dimension.OVERWORLD, Dimension.NETHER]

    # A surface plant states a surface, not the dimension's build range.
    berry = _scope(result.blocks["minecraft:sweet_berry_bush"], Dimension.OVERWORLD)
    assert berry.surface_only is True
    assert berry.min_y is None
    assert berry.max_y is None
    assert all(v.surface for v in berry.veins)

    # Its counts all run after the position modifier, so no attempt rate is stated.
    assert berry.attempts_per_chunk is None
    assert {v.chunk_chance for v in berry.veins} == {32, 384}

    # Emerald ore is the biome case the plan named: 10 biomes, not all 55.
    emerald = _scope(result.blocks["minecraft:emerald_ore"], Dimension.OVERWORLD)
    assert emerald.all_biomes_of_dimension is False
    assert emerald.biome_count == 10
