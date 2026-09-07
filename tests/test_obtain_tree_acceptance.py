"""Acceptance test: assert build_obtain_tree reproduces obtain_tree_acceptance.json.

This fixture pins the four rules of obtain tree generation across both Python
and TypeScript implementations, asserting that both reproduce the identical
JSON tree structure against real data in data/dist/obtain.json.
"""

import json
from pathlib import Path

import pytest

from pipeline.emit.obtain import ObtainGraph, producer_index_from_graph
from pipeline.obtain.producer import ObtainMethod
from pipeline.obtain.tree import DEFAULT_MAX_DEPTH, build_obtain_tree

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "obtain_tree_acceptance.json"
OBTAIN_JSON_PATH = Path(__file__).resolve().parent.parent / "data" / "dist" / "obtain.json"

_ACCEPTANCE_FIXTURE: dict[str, dict[str, object]] = json.loads(
    FIXTURE_PATH.read_text(encoding="utf-8")
)
_GRAPH = ObtainGraph.model_validate_json(OBTAIN_JSON_PATH.read_text(encoding="utf-8"))
_INDEX = producer_index_from_graph(_GRAPH)


@pytest.mark.parametrize("item_id", list(_ACCEPTANCE_FIXTURE.keys()))
def test_build_obtain_tree_reproduces_acceptance_fixture(item_id: str) -> None:
    expected_tree = _ACCEPTANCE_FIXTURE[item_id]
    actual_tree = build_obtain_tree(item_id, _INDEX, max_depth=DEFAULT_MAX_DEPTH)
    assert actual_tree.model_dump(mode="json") == expected_tree


def test_colored_bundle_resolves_to_real_root() -> None:
    # #minecraft:bundles contains all 17 bundles including the result (soft self-reference).
    # Assert it still resolves to a real root, since the tag also holds plain minecraft:bundle,
    # which is craftable from base materials (string and leather).
    tree = build_obtain_tree("minecraft:light_blue_bundle", _INDEX, max_depth=DEFAULT_MAX_DEPTH)
    assert tree.root.item == "minecraft:light_blue_bundle"
    assert len(tree.root.producers) == 1
    producer = tree.root.producers[0]
    assert producer.method is ObtainMethod.CRAFTING
    tag_input = next(i for i in producer.inputs if i.tag == "minecraft:bundles")
    assert "minecraft:bundle" in tag_input.members
    bundle_tree = build_obtain_tree("minecraft:bundle", _INDEX, max_depth=DEFAULT_MAX_DEPTH)
    crafting = next(p for p in bundle_tree.root.producers if p.method is ObtainMethod.CRAFTING)
    assert {i.item for i in crafting.inputs} == {"minecraft:leather", "minecraft:string"}
