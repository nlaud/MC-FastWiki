"""Tests for curated producers loader and staleness checking."""

import json
from pathlib import Path

import pytest

from pipeline.normalize.curated import PRODUCERS_FILENAME, load_curated
from pipeline.obtain import ObtainError
from pipeline.obtain.curated import (
    DEFAULT_PRODUCERS_PATH,
    load_curated_producers,
    load_curated_sources,
)
from pipeline.obtain.producer import ObtainMethod


def test_load_curated_producers_default_file() -> None:
    producers = load_curated_producers(DEFAULT_PRODUCERS_PATH)
    assert len(producers) == 14

    by_output = {p.output.item: p for p in producers}
    assert "minecraft:water_bucket" in by_output
    assert "minecraft:written_book" in by_output
    assert "minecraft:elytra" in by_output
    assert "minecraft:flow_pottery_sherd" in by_output
    assert "minecraft:guster_pottery_sherd" in by_output
    assert "minecraft:scrape_pottery_sherd" in by_output

    filling = [p for p in producers if p.method is ObtainMethod.FILLING]
    using = [p for p in producers if p.method is ObtainMethod.USING]
    world_gen = [p for p in producers if p.method is ObtainMethod.WORLD_GENERATION]

    assert len(filling) == 9
    assert len(using) == 1
    assert len(world_gen) == 4

    written_book = by_output["minecraft:written_book"]
    assert written_book.method is ObtainMethod.USING
    assert written_book.station == "using"
    assert len(written_book.inputs) == 1
    assert written_book.inputs[0].item == "minecraft:writable_book"

    elytra = by_output["minecraft:elytra"]
    assert elytra.method is ObtainMethod.WORLD_GENERATION
    assert len(elytra.inputs) == 0


def test_load_curated_sources_default_file() -> None:
    sources = load_curated_sources(DEFAULT_PRODUCERS_PATH)
    assert len(sources) == 4
    elytra_src = sources["world_generation/end_ship/elytra"]
    assert elytra_src.structure == "End Ship"
    assert elytra_src.container == "Item Frame"

    for sherd in ("flow", "guster", "scrape"):
        sherd_src = sources[f"world_generation/trial_chamber/{sherd}_pottery_sherd"]
        assert sherd_src.structure == "Trial Chamber"
        assert sherd_src.container == "Decorated Pot"


def test_load_curated_producers_rejects_missing_registry_item(tmp_path: Path) -> None:
    doc = {
        "verifiedFor": "26.2",
        "note": "test",
        "producers": [
            {
                "output": "minecraft:non_existent_item",
                "method": "filling",
                "inputs": ["minecraft:bucket"],
                "source_id": "curated/test",
                "wiki": "Test",
            }
        ],
    }
    file_path = tmp_path / "producers.json"
    file_path.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(ObtainError, match="not in the item registry"):
        load_curated_producers(file_path, item_registry=["bucket"])


def test_load_curated_producers_rejects_missing_registry_input(tmp_path: Path) -> None:
    doc = {
        "verifiedFor": "26.2",
        "note": "test",
        "producers": [
            {
                "output": "minecraft:water_bucket",
                "method": "filling",
                "inputs": ["minecraft:bad_input"],
                "source_id": "curated/test",
                "wiki": "Test",
            }
        ],
    }
    file_path = tmp_path / "producers.json"
    file_path.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(ObtainError, match="not in the item registry"):
        load_curated_producers(file_path, item_registry=["water_bucket"])


def test_load_curated_producers_rejects_extra_keys(tmp_path: Path) -> None:
    doc = {
        "verifiedFor": "26.2",
        "note": "test",
        "producers": [
            {
                "output": "minecraft:water_bucket",
                "method": "filling",
                "inputs": ["minecraft:bucket"],
                "source_id": "curated/test",
                "wiki": "Test",
                "unknown_extra_key": "fail",
            }
        ],
    }
    file_path = tmp_path / "producers.json"
    file_path.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(ObtainError, match="invalid curated producers document"):
        load_curated_producers(file_path)


def test_load_curated_producers_rejects_world_gen_without_structure(tmp_path: Path) -> None:
    doc = {
        "verifiedFor": "26.2",
        "note": "test",
        "producers": [
            {
                "output": "minecraft:elytra",
                "method": "world_generation",
                "source_id": "curated/elytra",
                "wiki": "Elytra",
            }
        ],
    }
    file_path = tmp_path / "producers.json"
    file_path.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(ObtainError, match="must declare structure and container"):
        load_curated_producers(file_path)


def test_producers_staleness_checked_in_load_curated(tmp_path: Path) -> None:
    curated_dir = Path("data/curated")
    data = load_curated(curated_dir, release_order=["26.2", "26.1"], target_version="26.2")
    assert not any(stale.document == PRODUCERS_FILENAME for stale in data.stale)

    data_stale = load_curated(curated_dir, release_order=["26.3", "26.2"], target_version="26.3")
    assert any(stale.document == PRODUCERS_FILENAME for stale in data_stale.stale)
