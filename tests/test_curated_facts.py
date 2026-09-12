"""Tests for curated fact tier loading, precedence, and validation faults."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline.extract.tags import TagIndex
from pipeline.normalize import NormalizeError
from pipeline.normalize.curated_facts import (
    COMPOSTABLE_FILENAME,
    FUEL_FILENAME,
    load_curated_facts,
)

RELEASES = ("26.1", "26.2")


def _make_dummy_tag_index(tags: dict[str, list[str]]) -> TagIndex:
    files = {
        f"tags/item/{tag.removeprefix('minecraft:')}.json": json.dumps(
            {"values": members}
        ).encode("utf-8")
        for tag, members in tags.items()
    }
    return TagIndex(files, registry="item")


def _write_curated(
    tmp_path: Path,
    *,
    compost_tiers: list[dict[str, Any]] | None = None,
    fuel_tiers: list[dict[str, Any]] | None = None,
    verified_for: str = "26.2",
) -> None:
    compost = {
        "verifiedFor": verified_for,
        "tiers": compost_tiers
        if compost_tiers is not None
        else [{"chance": 30, "items": ["minecraft:oak_leaves"]}],
    }
    fuel = {
        "verifiedFor": verified_for,
        "tiers": fuel_tiers
        if fuel_tiers is not None
        else [{"burnTime": 300, "items": ["minecraft:stick"]}],
    }
    (tmp_path / COMPOSTABLE_FILENAME).write_text(json.dumps(compost), encoding="utf-8")
    (tmp_path / FUEL_FILENAME).write_text(json.dumps(fuel), encoding="utf-8")


def test_fault_1_duplicate_explicit_id_in_two_tiers(tmp_path: Path) -> None:
    _write_curated(
        tmp_path,
        compost_tiers=[
            {"chance": 30, "items": ["minecraft:apple"]},
            {"chance": 50, "items": ["minecraft:apple"]},
        ],
    )
    tag_index = _make_dummy_tag_index({})
    with pytest.raises(NormalizeError, match="explicitly in multiple tiers"):
        load_curated_facts(
            tmp_path,
            item_tags=tag_index,
            known_entity_ids={"minecraft:apple", "minecraft:stick"},
            release_order=RELEASES,
            target_version="26.2",
        )


def test_fault_2_explicit_id_not_in_build(tmp_path: Path) -> None:
    _write_curated(
        tmp_path,
        compost_tiers=[{"chance": 30, "items": ["minecraft:unknown_item"]}],
    )
    tag_index = _make_dummy_tag_index({})
    with pytest.raises(NormalizeError, match="names no entity in this build"):
        load_curated_facts(
            tmp_path,
            item_tags=tag_index,
            known_entity_ids={"minecraft:stick"},
            release_order=RELEASES,
            target_version="26.2",
        )


def test_fault_2_tag_member_not_in_build(tmp_path: Path) -> None:
    _write_curated(
        tmp_path,
        compost_tiers=[{"chance": 30, "tags": ["minecraft:leaves"]}],
    )
    tag_index = _make_dummy_tag_index({"minecraft:leaves": ["minecraft:ghost_leaf"]})
    with pytest.raises(NormalizeError, match="names no entity in this build"):
        load_curated_facts(
            tmp_path,
            item_tags=tag_index,
            known_entity_ids={"minecraft:stick"},
            release_order=RELEASES,
            target_version="26.2",
        )


def test_fault_3_tag_resolves_to_zero_members(tmp_path: Path) -> None:
    _write_curated(
        tmp_path,
        compost_tiers=[{"chance": 30, "tags": ["minecraft:nonexistent_tag"]}],
    )
    tag_index = _make_dummy_tag_index({})
    with pytest.raises(NormalizeError, match="resolved to zero members"):
        load_curated_facts(
            tmp_path,
            item_tags=tag_index,
            known_entity_ids={"minecraft:stick"},
            release_order=RELEASES,
            target_version="26.2",
        )


def test_fault_4_chance_out_of_bounds(tmp_path: Path) -> None:
    _write_curated(
        tmp_path,
        compost_tiers=[{"chance": 105, "items": ["minecraft:apple"]}],
    )
    tag_index = _make_dummy_tag_index({})
    with pytest.raises(NormalizeError, match="tier chance 105 is outside 1 to 100"):
        load_curated_facts(
            tmp_path,
            item_tags=tag_index,
            known_entity_ids={"minecraft:apple", "minecraft:stick"},
            release_order=RELEASES,
            target_version="26.2",
        )


def test_fault_4_burn_time_non_positive(tmp_path: Path) -> None:
    _write_curated(
        tmp_path,
        fuel_tiers=[{"burnTime": 0, "items": ["minecraft:stick"]}],
    )
    tag_index = _make_dummy_tag_index({})
    with pytest.raises(NormalizeError, match="tier burn time 0 is not a positive integer"):
        load_curated_facts(
            tmp_path,
            item_tags=tag_index,
            known_entity_ids={"minecraft:oak_leaves", "minecraft:stick"},
            release_order=RELEASES,
            target_version="26.2",
        )


def test_fault_5_verified_for_unknown_release(tmp_path: Path) -> None:
    _write_curated(tmp_path, verified_for="99.9")
    tag_index = _make_dummy_tag_index({})
    with pytest.raises(NormalizeError, match="which release_order does not contain"):
        load_curated_facts(
            tmp_path,
            item_tags=tag_index,
            known_entity_ids={"minecraft:oak_leaves", "minecraft:stick"},
            release_order=RELEASES,
            target_version="26.2",
        )


def test_explicit_id_overrides_tag_precedence(tmp_path: Path) -> None:
    _write_curated(
        tmp_path,
        compost_tiers=[
            {"chance": 30, "tags": ["minecraft:leaves"]},
            {"chance": 50, "items": ["minecraft:flowering_azalea_leaves"]},
        ],
    )
    tag_index = _make_dummy_tag_index({
        "minecraft:leaves": [
            "minecraft:oak_leaves",
            "minecraft:flowering_azalea_leaves",
        ]
    })
    known = {"minecraft:oak_leaves", "minecraft:flowering_azalea_leaves", "minecraft:stick"}
    result = load_curated_facts(
        tmp_path,
        item_tags=tag_index,
        known_entity_ids=known,
        release_order=RELEASES,
        target_version="26.2",
    )
    assert result.compostable["minecraft:oak_leaves"] == 30
    assert result.compostable["minecraft:flowering_azalea_leaves"] == 50
    assert len(result.report.compost_overrides) == 1
    override = result.report.compost_overrides[0]
    assert override.entity_id == "minecraft:flowering_azalea_leaves"
    assert override.from_value == 30
    assert override.to_value == 50


def test_exclude_tags(tmp_path: Path) -> None:
    compost = {
        "verifiedFor": "26.2",
        "tiers": [{"chance": 30, "items": ["minecraft:apple"]}],
    }
    fuel = {
        "verifiedFor": "26.2",
        "excludeTags": ["minecraft:non_flammable_wood"],
        "tiers": [
            {"burnTime": 300, "tags": ["minecraft:planks"]},
        ],
    }
    (tmp_path / COMPOSTABLE_FILENAME).write_text(json.dumps(compost), encoding="utf-8")
    (tmp_path / FUEL_FILENAME).write_text(json.dumps(fuel), encoding="utf-8")

    tag_index = _make_dummy_tag_index({
        "minecraft:planks": ["minecraft:oak_planks", "minecraft:crimson_planks"],
        "minecraft:non_flammable_wood": ["minecraft:crimson_planks"],
    })
    known = {"minecraft:apple", "minecraft:oak_planks", "minecraft:crimson_planks"}
    result = load_curated_facts(
        tmp_path,
        item_tags=tag_index,
        known_entity_ids=known,
        release_order=RELEASES,
        target_version="26.2",
    )
    assert "minecraft:oak_planks" in result.fuel
    assert "minecraft:crimson_planks" not in result.fuel
