"""Tests for `pipeline.extract.profession`."""

from pipeline.extract.profession import (
    ProfessionEntry,
    ProfessionIndex,
    extract_professions,
)

ALL_15_REGISTRY_PATHS = [
    "armorer",
    "butcher",
    "cartographer",
    "cleric",
    "farmer",
    "fisherman",
    "fletcher",
    "leatherworker",
    "librarian",
    "mason",
    "nitwit",
    "none",
    "shepherd",
    "toolsmith",
    "weaponsmith",
]

TRADE_PROFESSIONS = [
    "Armorer",
    "Butcher",
    "Cartographer",
    "Cleric",
    "Farmer",
    "Fisherman",
    "Fletcher",
    "Leatherworker",
    "Librarian",
    "Mason",
    "Shepherd",
    "Toolsmith",
    "Wandering Trader",
    "Weaponsmith",
]


def test_extract_professions_extracts_13_known_professions() -> None:
    """The 13 professions known to the trade index become entries."""
    index = extract_professions(ALL_15_REGISTRY_PATHS, TRADE_PROFESSIONS)
    assert len(index) == 13
    assert len(index.entries) == 13

    expected_ids = {
        "minecraft:armorer",
        "minecraft:butcher",
        "minecraft:cartographer",
        "minecraft:cleric",
        "minecraft:farmer",
        "minecraft:fisherman",
        "minecraft:fletcher",
        "minecraft:leatherworker",
        "minecraft:librarian",
        "minecraft:mason",
        "minecraft:shepherd",
        "minecraft:toolsmith",
        "minecraft:weaponsmith",
    }
    assert isinstance(index, ProfessionIndex)
    assert {e.id for e in index.entries} == expected_ids
    assert set(index) == expected_ids


def test_none_and_nitwit_produce_nothing_under_trade_index_rule() -> None:
    """Neither none nor nitwit offers trades in the trade index, so both are excluded."""
    index = extract_professions(["none", "nitwit"], TRADE_PROFESSIONS)
    assert len(index) == 0
    assert "none" not in index
    assert "nitwit" not in index
    assert "minecraft:none" not in index
    assert "minecraft:nitwit" not in index


def test_profession_index_lookup_methods() -> None:
    """ProfessionIndex supports lookup by ID, path, and name."""
    index = extract_professions(["librarian"], ["Librarian"])
    assert len(index) == 1

    entry = index["minecraft:librarian"]
    assert isinstance(entry, ProfessionEntry)
    assert entry.id == "minecraft:librarian"
    assert entry.path == "librarian"
    assert entry.name == "Librarian"
    assert entry.page_title == "Librarian"
    assert entry.trade_name == "Librarian"

    assert index["librarian"] == entry
    assert index["Librarian"] == entry
    assert "librarian" in index
    assert "Librarian" in index
    assert "minecraft:librarian" in index
