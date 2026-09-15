"""Tests for `python -m pipeline diff`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.cli import CliError, main
from pipeline.cli.diff import run_diff


def write_index(path: Path, entities: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"entities": entities}), encoding="utf-8")
    return path


def test_diff_counts_and_grouping(tmp_path: Path) -> None:
    before = [
        {"id": "minecraft:apple", "k": "item", "n": "Apple"},
        {"id": "minecraft:stone", "k": "block", "n": "Stone"},
        {"id": "minecraft:zombie", "k": "mob", "n": "Zombie"},
    ]
    after = [
        {"id": "minecraft:apple", "k": "item", "n": "Apple"},  # unchanged
        {"id": "minecraft:golden_apple", "k": "item", "n": "Golden Apple"},  # added item
        {"id": "minecraft:creeper", "k": "mob", "n": "Creeper"},  # added mob
        # stone removed
        # zombie removed
    ]

    before_path = write_index(tmp_path / "before.json", before)
    after_path = write_index(tmp_path / "after.json", after)

    md = run_diff(before=before_path, after=after_path)

    # Net diff counts in table
    assert "| **item** | 1 | 2 | +1 | 1 | 0 |" in md
    assert "| **block** | 1 | 0 | -1 | 0 | 1 |" in md
    assert "| **mob** | 1 | 1 | 0 | 1 | 1 |" in md
    assert "| **Total** | **3** | **3** | **0** | **2** | **2** |" in md

    # Added entities
    assert "### Added Entities (2)" in md
    assert "- **Golden Apple** (`minecraft:golden_apple`)" in md
    assert "- **Creeper** (`minecraft:creeper`)" in md

    # Removed entities
    assert "### Removed Entities (2)" in md
    assert "- **Stone** (`minecraft:stone`)" in md
    assert "- **Zombie** (`minecraft:zombie`)" in md


def test_diff_truncation_and_full_report(tmp_path: Path) -> None:
    # Generate 60 added items to trigger truncation at max_list_items=50
    before: list[dict[str, str]] = []
    after = [
        {"id": f"minecraft:item_{i:02d}", "k": "item", "n": f"Item {i:02d}"}
        for i in range(60)
    ]

    before_path = write_index(tmp_path / "before.json", before)
    after_path = write_index(tmp_path / "after.json", after)
    full_path = tmp_path / "full_diff.md"

    stdout_md = run_diff(
        before=before_path,
        after=after_path,
        full_report=full_path,
        max_list_items=50,
    )

    # stdout markdown is truncated
    assert "- _... and 10 more (see full diff artifact)_" in stdout_md
    assert "- **Item 49** (`minecraft:item_49`)" in stdout_md
    assert "- **Item 50** (`minecraft:item_50`)" not in stdout_md

    # full_path has the untruncated markdown
    assert full_path.is_file()
    full_md = full_path.read_text(encoding="utf-8")
    assert "... and 10 more" not in full_md
    assert "- **Item 50** (`minecraft:item_50`)" in full_md
    assert "- **Item 59** (`minecraft:item_59`)" in full_md


def test_diff_with_validation_report(tmp_path: Path) -> None:
    before_path = write_index(tmp_path / "before.json", [])
    after_path = write_index(tmp_path / "after.json", [])
    val_path = tmp_path / "validation.json"

    val_data = {
        "conformance": {"checked": {"entity": 10}, "failures": []},
        "references": {"classified": {}, "failures": []},
        "regression": {
            "checks": [
                {
                    "name": "total entity count",
                    "baseline": 100,
                    "new": 105,
                    "passed": True,
                    "rule": "must not drop",
                },
                {
                    "name": "per-kind count: mob",
                    "baseline": 50,
                    "new": 40,
                    "passed": False,
                    "downgraded": False,
                    "rule": "must not drop",
                },
            ]
        },
    }
    val_path.write_text(json.dumps(val_data), encoding="utf-8")

    md = run_diff(before=before_path, after=after_path, validation=val_path)

    assert "### Validation Gate: Check Summary" in md
    assert "- **Schema Conformance:** PASSED" in md
    assert "- **Reference Integrity:** PASSED" in md
    assert "| total entity count | 100 | 105 | PASS |" in md
    assert "| per-kind count: mob | 50 | 40 | **FAIL** |" in md


def test_diff_missing_file_raises_cli_error(tmp_path: Path) -> None:
    existing = write_index(tmp_path / "existing.json", [])
    missing = tmp_path / "missing.json"

    with pytest.raises(CliError, match="does not exist"):
        run_diff(before=missing, after=existing)

    with pytest.raises(CliError, match="does not exist"):
        run_diff(before=existing, after=missing)


def test_diff_cli_main_invocation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before_path = write_index(tmp_path / "before.json", [])
    after_path = write_index(tmp_path / "after.json", [])

    exit_code = main(
        ["diff", "--before", str(before_path), "--after", str(after_path)]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "## Data Diff Summary" in captured.out
