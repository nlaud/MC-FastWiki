"""Unit tests for Overworld biome noise climate parsing (pipeline/enrich/worldgen_noise.py)."""

from pathlib import Path

import pytest

from pipeline.enrich import EnrichError
from pipeline.enrich.worldgen_noise import (
    extract_worldgen_noise,
    parse_noise_legend,
    parse_wikitable_to_grid,
    slice_overworld_section,
)

FIXTURE_PATH = Path("tests") / "fixtures" / "wiki_worldgen_overworld.txt"


BIOME_REGISTRY = [
    "badlands", "bamboo_jungle", "basalt_deltas", "beach", "birch_forest",
    "cherry_grove", "cold_ocean", "crimson_forest", "dark_forest",
    "deep_cold_ocean", "deep_dark", "deep_frozen_ocean", "deep_lukewarm_ocean",
    "deep_ocean", "desert", "dripstone_caves", "end_barrens", "end_highlands",
    "end_midlands", "eroded_badlands", "flower_forest", "forest",
    "frozen_ocean", "frozen_peaks", "frozen_river", "grove", "ice_spikes",
    "jagged_peaks", "jungle", "lukewarm_ocean", "lush_caves",
    "mangrove_swamp", "meadow", "mushroom_fields", "nether_wastes",
    "ocean", "old_growth_birch_forest", "old_growth_pine_taiga",
    "old_growth_spruce_taiga", "pale_garden", "plains", "river",
    "savanna", "savanna_plateau", "small_end_islands", "snowy_beach",
    "snowy_plains", "snowy_slopes", "snowy_taiga", "soul_sand_valley",
    "sparse_jungle", "stony_peaks", "stony_shore", "sulfur_caves",
    "sunflower_plains", "swamp", "taiga", "the_end", "the_void",
    "warm_ocean", "warped_forest", "windswept_forest",
    "windswept_gravelly_hills", "windswept_hills", "windswept_savanna",
    "wooded_badlands",
]


@pytest.fixture
def overworld_wikitext() -> str:
    assert FIXTURE_PATH.is_file(), f"Fixture missing: {FIXTURE_PATH}"
    return FIXTURE_PATH.read_text(encoding="utf-8")


def test_slice_overworld_section(overworld_wikitext: str) -> None:
    sliced = slice_overworld_section(overworld_wikitext)
    assert "=== Overworld ===" in sliced
    assert "===The Nether===" not in sliced
    assert "Mushroom Fields" in sliced


def test_slice_overworld_section_missing() -> None:
    with pytest.raises(EnrichError, match="could not find '=== Overworld ==='"):
        slice_overworld_section("Some random wikitext without section")


def test_parse_noise_legend(overworld_wikitext: str) -> None:
    legend = parse_noise_legend(overworld_wikitext)
    # Check prose-parsed temperature: T=0 must be -1.0~-0.45 (not the tooltip typo -1.0~0.45)
    assert legend.temperature[0] == "-1.0~-0.45"
    assert legend.temperature[1] == "-0.45~-0.15"
    assert legend.temperature[2] == "-0.15~0.2"
    assert legend.temperature[3] == "0.2~0.55"
    assert legend.temperature[4] == "0.55~1.0"

    # Check continentalness
    assert len(legend.continentalness) == 7
    assert legend.continentalness[0] == ("Mushroom fields", "-1.2~-1.05")
    assert legend.continentalness[1] == ("Deep ocean", "-1.05~-0.455")
    assert legend.continentalness[2] == ("Ocean", "-0.455~-0.19")
    assert legend.continentalness[3] == ("Coast", "-0.19~-0.11")
    assert legend.continentalness[4] == ("Near-inland", "-0.11~0.03")
    assert legend.continentalness[5] == ("Mid-inland", "0.03~0.3")
    assert legend.continentalness[6] == ("Far-inland", "0.3~1.0")

    # Check erosion
    assert len(legend.erosion) == 7
    assert legend.erosion[0] == "-1.0~-0.78"
    assert legend.erosion[6] == "0.55~1.0"

    # Check PV
    assert len(legend.pv) == 5
    assert legend.pv[0] == ("Valleys", "-1.0~-0.85")
    assert legend.pv[1] == ("Low", "-0.85~-0.2")
    assert legend.pv[2] == ("Mid", "-0.2~0.2")
    assert legend.pv[3] == ("High", "0.2~0.7")
    assert legend.pv[4] == ("Peaks", "0.7~1.0")


def test_parse_wikitable_to_grid_inland_table(overworld_wikitext: str) -> None:
    section = slice_overworld_section(overworld_wikitext)
    import re
    tables = list(re.finditer(r"\{\|.*?\n\|\}", section, re.DOTALL))
    assert len(tables) == 8
    inland_table = tables[2].group(0)

    grid = parse_wikitable_to_grid(inland_table)
    # Inland surface table has 32 rows and 6 columns
    assert len(grid) == 32
    for r_idx, row in enumerate(grid):
        assert len(row) == 6, f"Row {r_idx} length is {len(row)}, expected 6"
        for c_idx, cell in enumerate(row):
            assert cell is not None, f"Cell at ({r_idx}, {c_idx}) is unfilled"
            assert cell.text, f"Cell at ({r_idx}, {c_idx}) has empty text"


def test_extract_worldgen_noise_fixture_counts(overworld_wikitext: str) -> None:
    result = extract_worldgen_noise(overworld_wikitext, biome_registry=BIOME_REGISTRY)

    # Table counts
    assert result.report.table_counts["depth"] == 4
    assert result.report.table_counts["non_inland"] == 14
    assert result.report.table_counts["direct_inland"] == 40
    assert result.report.table_counts["beach"] == 3
    assert result.report.table_counts["badland"] == 4
    assert result.report.table_counts["middle"] == 33
    assert result.report.table_counts["plateau"] == 36
    assert result.report.table_counts["shattered"] == 19

    # 55 Overworld biomes covered
    assert len(result.placements_by_biome) == 55

    # Dappled Forest is upcoming, must be in unresolved_biomes and NOT in placements
    assert "Dappled Forest" in result.report.unresolved_biome_names
    assert not any("dappled" in b_id for b_id in result.placements_by_biome)


def test_extract_worldgen_noise_depth_routes(overworld_wikitext: str) -> None:
    result = extract_worldgen_noise(overworld_wikitext, biome_registry=BIOME_REGISTRY)
    # 4 cave biomes
    caves = [
        "minecraft:dripstone_caves",
        "minecraft:lush_caves",
        "minecraft:deep_dark",
    ]
    for cave_id in caves:
        assert cave_id in result.placements_by_biome
        placements = result.placements_by_biome[cave_id]
        depth_placements = [p for p in placements if p.route == "depth"]
        assert len(depth_placements) >= 1
        assert depth_placements[0].depth is not None


def test_extract_worldgen_noise_siblings(overworld_wikitext: str) -> None:
    result = extract_worldgen_noise(overworld_wikitext, biome_registry=BIOME_REGISTRY)

    # River and Frozen River are siblings in Table 2
    river_placements = result.placements_by_biome["minecraft:river"]
    frozen_river_placements = result.placements_by_biome["minecraft:frozen_river"]

    river_with_sib = [p for p in river_placements if p.sibling is not None]
    assert len(river_with_sib) > 0
    assert river_with_sib[0].sibling is not None
    assert river_with_sib[0].sibling.id == "minecraft:frozen_river"
    assert river_with_sib[0].sibling.name == "Frozen River"

    frozen_with_sib = [p for p in frozen_river_placements if p.sibling is not None]
    assert len(frozen_with_sib) > 0
    assert frozen_with_sib[0].sibling is not None
    assert frozen_with_sib[0].sibling.id == "minecraft:river"
    assert frozen_with_sib[0].sibling.name == "River"


def test_extract_worldgen_noise_condition_parsing(overworld_wikitext: str) -> None:
    result = extract_worldgen_noise(overworld_wikitext, biome_registry=BIOME_REGISTRY)

    # Fullwidth condition (fullwidth parens) and ASCII condition e.g. (T<4)
    river_placements = result.placements_by_biome["minecraft:river"]
    conditions = [p.condition for p in river_placements if p.condition]
    assert any("T>0" in c for c in conditions)

    frozen_river_placements = result.placements_by_biome["minecraft:frozen_river"]
    f_conditions = [p.condition for p in frozen_river_placements if p.condition]
    assert any("T=0" in c for c in conditions) or any("T=0" in c for c in f_conditions)


def test_extract_worldgen_noise_contiguous_collapse(overworld_wikitext: str) -> None:
    result = extract_worldgen_noise(overworld_wikitext, biome_registry=BIOME_REGISTRY)

    # Jungle is placed via Middle biomes across contiguous terrain ranges
    jungle_placements = result.placements_by_biome["minecraft:jungle"]
    assert len(jungle_placements) > 0

    # Must have both group chips and group_terrain entries
    group_placements = [p for p in jungle_placements if p.route == "group"]
    terrain_placements = [p for p in jungle_placements if p.route == "group_terrain"]
    assert len(group_placements) > 0
    assert len(terrain_placements) > 0
    assert "Middle biomes" in {p.group for p in group_placements}
    assert "Middle biomes" in {p.group for p in terrain_placements}


def test_extract_worldgen_noise_table_count_mismatch() -> None:
    wikitext = "=== Overworld ===\n{| class='wikitable'\n|-\n| Test\n|}\n===The Nether==="
    with pytest.raises(EnrichError, match="expected exactly 8 tables"):
        extract_worldgen_noise(wikitext)



def test_placements_carry_levels_as_integers(overworld_wikitext: str) -> None:
    """The display strings and the level integers must state the same fact.

    A renderer plots a biome on the temperature axis from the integers and
    spells the exact band from the string. If the two ever disagree the page
    shows one number and highlights another, so they are checked together.
    """
    result = extract_worldgen_noise(overworld_wikitext, biome_registry=BIOME_REGISTRY)
    jungle = result.placements_by_biome["minecraft:jungle"]

    group_rows = [p for p in jungle if p.route == "group"]
    for placement in group_rows:
        assert placement.temperature is not None
        assert placement.temperature_levels
        # "T=3 (0.2~0.55)" and (3,) are the same claim.
        for level in placement.temperature_levels:
            assert f"T={level}" in placement.temperature

    t_levels = {lvl for p in jungle for lvl in p.temperature_levels}
    h_levels = {lvl for p in jungle for lvl in p.humidity_levels}
    assert t_levels == {3}
    assert h_levels == {3, 4}

    # Erosion does not constrain Jungle at all, and the axis should show that
    # rather than implying a narrow band.
    e_levels = {lvl for p in jungle for lvl in p.erosion_levels}
    assert e_levels == {0, 1, 2, 3, 4, 5, 6}


def test_continentalness_bands_share_one_absolute_axis(overworld_wikitext: str) -> None:
    """Ocean-side and inland placements must index the same seven prose bands.

    The inland table names only its own four columns, so a reader that took the
    column index literally would place Coast at 0 and collide it with Mushroom
    fields, which is band 0 on the real axis.
    """
    result = extract_worldgen_noise(overworld_wikitext, biome_registry=BIOME_REGISTRY)

    def bands(biome_id: str) -> set[int]:
        return {
            band
            for placement in result.placements_by_biome[biome_id]
            for band in placement.continentalness_bands
        }

    ocean_bands = bands("minecraft:ocean")
    mushroom_bands = bands("minecraft:mushroom_fields")
    jungle_bands = bands("minecraft:jungle")

    assert mushroom_bands == {0}
    assert ocean_bands == {2}
    # Coast is band 3, so every inland band sits above the ocean ones.
    assert jungle_bands == {3, 4, 5, 6}
    assert min(jungle_bands) > max(ocean_bands)


def test_beach_biomes_take_every_humidity_level(overworld_wikitext: str) -> None:
    """Beach placement reads temperature only, so humidity must not read empty.

    The prose says the beach biome "is related only to the temperature value".
    An empty humidity tuple would render as a blank axis, which reads as "no
    data" rather than "every level qualifies".
    """
    result = extract_worldgen_noise(overworld_wikitext, biome_registry=BIOME_REGISTRY)
    beach_groups = [
        p for p in result.placements_by_biome["minecraft:beach"] if p.route == "group"
    ]
    assert beach_groups
    for placement in beach_groups:
        assert set(placement.humidity_levels) == {0, 1, 2, 3, 4}
