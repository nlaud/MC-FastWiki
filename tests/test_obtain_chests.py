"""Tests for `pipeline.obtain.chests`: curated chest loot sources and structure attribution."""

import pytest

from pipeline.obtain import ObtainError
from pipeline.obtain.chests import (
    DEFAULT_CHEST_SOURCES_PATH,
    ChestSource,
    by_structure,
    load_chest_sources,
    verify_chest_sources,
)


def test_chest_source_structure_ref_coercion() -> None:
    # Single string coerced to tuple
    source1 = ChestSource.model_validate(
        {
            "structure": "End City",
            "container": "Chest",
            "structure_ref": "minecraft:end_city",
        }
    )
    assert source1.structure_ref == ("minecraft:end_city",)

    # List coerced to tuple
    source2 = ChestSource.model_validate(
        {
            "structure": "Mineshaft",
            "container": "Minecart with Chest",
            "structure_ref": ["minecraft:mineshaft", "minecraft:mineshaft_mesa"],
        }
    )
    assert source2.structure_ref == ("minecraft:mineshaft", "minecraft:mineshaft_mesa")

    # Wire alias structureRef
    source3 = ChestSource.model_validate(
        {
            "structure": "Stronghold",
            "container": "Corridor Chest",
            "structureRef": "minecraft:stronghold",
        }
    )
    assert source3.structure_ref == ("minecraft:stronghold",)
    dumped = source3.model_dump(by_alias=True)
    assert dumped["structureRef"] == ["minecraft:stronghold"] or dumped["structureRef"] == (
        "minecraft:stronghold",
    )


def test_by_structure() -> None:
    s1 = ChestSource(
        structure="End City",
        container="Chest",
        structure_ref=("minecraft:end_city",),
    )
    s2 = ChestSource(
        structure="Mineshaft",
        container="Chest",
        structure_ref=("minecraft:mineshaft", "minecraft:mineshaft_mesa"),
    )
    s3 = ChestSource(
        structure="Fishing",
        container="Catch",
        structure_ref=(),
    )

    mapping = by_structure({"table1": s1, "table2": s2, "table3": s3})

    assert "minecraft:end_city" in mapping
    assert len(mapping["minecraft:end_city"]) == 1
    assert mapping["minecraft:end_city"][0] == ("table1", s1)

    assert "minecraft:mineshaft" in mapping
    assert ("table2", s2) in mapping["minecraft:mineshaft"]

    assert "minecraft:mineshaft_mesa" in mapping
    assert ("table2", s2) in mapping["minecraft:mineshaft_mesa"]

    assert len(mapping) == 3


def test_verify_chest_sources_valid() -> None:
    sources = {
        "chests/end_city": ChestSource(
            structure="End City",
            container="Chest",
            structure_ref=("minecraft:end_city",),
        ),
    }
    # Found tables matching extracted structures
    verify_chest_sources(
        found_tables=["chests/end_city"],
        curated=sources,
        extracted_structures={"minecraft:end_city"},
    )


def test_verify_chest_sources_empty_ref_allowed() -> None:
    sources = {
        "chests/simple_dungeon": ChestSource(
            structure="Dungeon",
            container="Chest",
            structure_ref=(),
        ),
    }
    # Non-structure chests have empty structure_ref and pass verification
    verify_chest_sources(
        found_tables=["chests/simple_dungeon"],
        curated=sources,
        extracted_structures={"minecraft:end_city"},
    )


def test_verify_chest_sources_unknown_structure() -> None:
    sources = {
        "chests/end_city": ChestSource(
            structure="End City",
            container="Chest",
            structure_ref=("minecraft:non_existent",),
        ),
    }
    with pytest.raises(ObtainError, match="names unknown structure"):
        verify_chest_sources(
            found_tables=["chests/end_city"],
            curated=sources,
            extracted_structures={"minecraft:end_city"},
        )


def test_load_curated_chest_sources() -> None:
    assert DEFAULT_CHEST_SOURCES_PATH.is_file()
    sources = load_chest_sources(DEFAULT_CHEST_SOURCES_PATH)
    assert len(sources) > 0
    structure_sources = [s for s in sources.values() if s.structure_ref]
    assert len(structure_sources) > 0
    # The dungeon has a page now. It is a configured feature rather than a
    # `worldgen/structure`, so `pipeline.extract.feature_place` enumerates it and
    # its chest points at that entity like any other.
    assert sources["loot_table/chests/simple_dungeon.json"].structure_ref == (
        "minecraft:monster_room",
    )
    # The bonus chest still names no place, and never will: `Spawn` is where a
    # world drops the player, not somewhere that generates.
    assert sources["loot_table/chests/spawn_bonus_chest.json"].structure_ref == ()
