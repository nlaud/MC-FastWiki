"""Rebuild the obtain tree acceptance fixture that pins obtain tree expansion.

A person runs this module by hand. It is not a test, and pytest does not collect
it, because the name does not start with `test_`.

`tests/test_obtain_tree_acceptance.py` and `web/render/obtain-tree.test.ts`
both read the file this module writes, ensuring that Python's `build_obtain_tree`
and TypeScript's `buildObtainTree` produce identical JSON representations for
the canonical test items against the real committed `data/dist/obtain.json`.

Run it from the repository root:

    python -m tests.fixtures.build_obtain_tree_acceptance
"""

import json
from pathlib import Path

from pipeline.emit.obtain import ObtainGraph, producer_index_from_graph
from pipeline.obtain.tree import DEFAULT_MAX_DEPTH, build_obtain_tree

FIXTURE_PATH = Path(__file__).resolve().parent / "obtain_tree_acceptance.json"
OBTAIN_JSON_PATH = Path(__file__).resolve().parents[2] / "data" / "dist" / "obtain.json"

ACCEPTANCE_ITEMS = (
    "minecraft:iron_ingot",
    "minecraft:oak_stairs",
    "minecraft:chiseled_resin_bricks",
    "minecraft:emerald",
    "minecraft:barrel",
    "minecraft:splash_potion",
)


def build_acceptance_trees() -> dict[str, object]:
    graph_bytes = OBTAIN_JSON_PATH.read_text(encoding="utf-8")
    graph = ObtainGraph.model_validate_json(graph_bytes)
    index = producer_index_from_graph(graph)

    trees: dict[str, object] = {}
    for item_id in ACCEPTANCE_ITEMS:
        tree = build_obtain_tree(item_id, index, max_depth=DEFAULT_MAX_DEPTH)
        trees[item_id] = tree.model_dump(mode="json")
    return trees


def main() -> None:
    trees = build_acceptance_trees()
    # Write with indent=2 and Unix LF line endings
    content = json.dumps(trees, indent=2) + "\n"
    FIXTURE_PATH.write_text(content, encoding="utf-8", newline="\n")
    print(f"Wrote {len(trees)} acceptance trees to {FIXTURE_PATH}")


if __name__ == "__main__":
    main()
