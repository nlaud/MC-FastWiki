"""`python -m pipeline diff`: compare two search index files and summarize changes.

Generates a Markdown diff report between two `index.json` files, detailing:
1. Counts-by-kind summary table (before, after, net diff, added, removed).
2. Added entities grouped by kind with entity names and IDs.
3. Removed entities grouped by kind with entity names and IDs.
4. Validation gate results for changed/regression checks.

Long name lists are truncated on stdout with a stated count to keep PR bodies
within GitHub's limits, while the full untruncated output can be written to an
artifact file.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from pipeline.cli import CliError

__all__ = ["generate_diff_markdown", "run_diff"]

DEFAULT_MAX_LIST_ITEMS = 50


def _load_entities(path: Path) -> dict[str, dict[str, Any]]:
    """Load and index entities from an index.json file by ID."""
    if not path.is_file():
        raise CliError(f"Index file {path} does not exist.")
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise CliError(f"Failed to read index file {path}: {error}") from error

    if not isinstance(content, dict) or "entities" not in content:
        raise CliError(f"Index file {path} is malformed: missing 'entities' list.")

    entities_list = content["entities"]
    if not isinstance(entities_list, list):
        raise CliError(f"Index file {path} has invalid 'entities' field (not a list).")

    indexed: dict[str, dict[str, Any]] = {}
    for entry in entities_list:
        if isinstance(entry, dict) and "id" in entry:
            indexed[str(entry["id"])] = entry
    return indexed


def _format_entity_list(
    entities: list[dict[str, Any]],
    *,
    max_items: int | None,
) -> str:
    """Format a list of entity dicts as Markdown bullet points."""
    lines: list[str] = []
    total = len(entities)
    limit = total if max_items is None else min(total, max_items)

    for entry in entities[:limit]:
        name = entry.get("n", entry["id"])
        eid = entry["id"]
        lines.append(f"- **{name}** (`{eid}`)")

    if max_items is not None and total > limit:
        remaining = total - limit
        lines.append(f"- _... and {remaining} more (see full diff artifact)_")

    return "\n".join(lines)


def _format_validation_section(validation_path: Path | None) -> str:
    """Format the validation gate check table from validation.json."""
    if validation_path is None or not validation_path.is_file():
        return "### Validation Gate\n\n_No validation report provided._\n"

    try:
        val_data = json.loads(validation_path.read_text(encoding="utf-8"))
    except Exception as error:
        return f"### Validation Gate\n\n_Failed to load validation report: {error}_\n"

    lines: list[str] = ["### Validation Gate: Check Summary\n"]

    # Conformance & references status
    conformance = val_data.get("conformance", {})
    conf_failures = conformance.get("failures", [])
    ref_data = val_data.get("references", {})
    ref_failures = ref_data.get("failures", [])

    lines.append(
        f"- **Schema Conformance:** "
        f"{'PASSED' if not conf_failures else f'FAILED ({len(conf_failures)} failures)'}"
    )
    lines.append(
        f"- **Reference Integrity:** "
        f"{'PASSED' if not ref_failures else f'FAILED ({len(ref_failures)} failures)'}"
    )

    regression = val_data.get("regression", {})
    checks = regression.get("checks", [])
    if isinstance(checks, list) and checks:
        lines.append("\n#### Regression Checks\n")
        lines.append("| Check | Baseline | New | Status | Rule |")
        lines.append("| --- | --- | --- | --- | --- |")
        for check in checks:
            if not isinstance(check, dict):
                continue
            name = check.get("name", "unknown")
            base = check.get("baseline", "-")
            new_val = check.get("new", "-")
            passed = check.get("passed", False)
            downgraded = check.get("downgraded", False)
            rule = check.get("rule", "")
            status = "PASS" if passed else ("DOWNGRADED" if downgraded else "**FAIL**")
            lines.append(f"| {name} | {base} | {new_val} | {status} | {rule} |")

    return "\n".join(lines) + "\n"


def generate_diff_markdown(
    *,
    before_entities: dict[str, dict[str, Any]],
    after_entities: dict[str, dict[str, Any]],
    validation_path: Path | None = None,
    max_list_items: int | None = DEFAULT_MAX_LIST_ITEMS,
) -> str:
    """Produce Markdown summarizing the diff between before and after entities."""
    before_ids = set(before_entities.keys())
    after_ids = set(after_entities.keys())

    added_ids = sorted(after_ids - before_ids)
    removed_ids = sorted(before_ids - after_ids)

    # All kinds present in either before or after
    all_kinds = sorted(
        {e.get("k", "unknown") for e in before_entities.values()}
        | {e.get("k", "unknown") for e in after_entities.values()}
    )

    # Group added and removed by kind
    added_by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for eid in added_ids:
        entity = after_entities[eid]
        kind = entity.get("k", "unknown")
        added_by_kind[kind].append(entity)

    removed_by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for eid in removed_ids:
        entity = before_entities[eid]
        kind = entity.get("k", "unknown")
        removed_by_kind[kind].append(entity)

    # Sort entities in each kind by name
    for kind in added_by_kind:
        added_by_kind[kind].sort(key=lambda e: (e.get("n", ""), e["id"]))
    for kind in removed_by_kind:
        removed_by_kind[kind].sort(key=lambda e: (e.get("n", ""), e["id"]))

    out: list[str] = ["## Data Diff Summary\n"]

    # Table of counts by kind
    out.append("| Kind | Before | After | Net Diff | Added | Removed |")
    out.append("| --- | --- | --- | --- | --- | --- |")

    total_before = len(before_entities)
    total_after = len(after_entities)
    total_diff = total_after - total_before
    diff_str = f"+{total_diff}" if total_diff > 0 else str(total_diff)

    for kind in all_kinds:
        b_count = sum(1 for e in before_entities.values() if e.get("k") == kind)
        a_count = sum(1 for e in after_entities.values() if e.get("k") == kind)
        add_cnt = len(added_by_kind.get(kind, []))
        rem_cnt = len(removed_by_kind.get(kind, []))
        k_diff = a_count - b_count
        k_diff_str = f"+{k_diff}" if k_diff > 0 else str(k_diff)
        out.append(
            f"| **{kind}** | {b_count} | {a_count} | {k_diff_str} | {add_cnt} | {rem_cnt} |"
        )

    out.append(
        f"| **Total** | **{total_before}** | **{total_after}** | **{diff_str}** | "
        f"**{len(added_ids)}** | **{len(removed_ids)}** |\n"
    )

    # Added entities
    if added_ids:
        out.append(f"### Added Entities ({len(added_ids)})\n")
        for kind in sorted(added_by_kind.keys()):
            items = added_by_kind[kind]
            out.append(f"#### {kind.capitalize()} ({len(items)})\n")
            out.append(_format_entity_list(items, max_items=max_list_items))
            out.append("")
    else:
        out.append("### Added Entities\n\n_No entities added._\n")

    # Removed entities
    if removed_ids:
        out.append(f"### Removed Entities ({len(removed_ids)})\n")
        for kind in sorted(removed_by_kind.keys()):
            items = removed_by_kind[kind]
            out.append(f"#### {kind.capitalize()} ({len(items)})\n")
            out.append(_format_entity_list(items, max_items=max_list_items))
            out.append("")
    else:
        out.append("### Removed Entities\n\n_No entities removed._\n")

    # Validation check table (the "changed" report)
    out.append(_format_validation_section(validation_path))

    return "\n".join(out)


def run_diff(
    *,
    before: Path,
    after: Path,
    validation: Path | None = None,
    full_report: Path | None = None,
    max_list_items: int = DEFAULT_MAX_LIST_ITEMS,
) -> str:
    """Run entity diff between two index.json files and print Markdown summary."""
    before_entities = _load_entities(before)
    after_entities = _load_entities(after)

    val_path = validation
    if val_path is None:
        default_val = Path("data") / "reports" / "validation.json"
        if default_val.is_file():
            val_path = default_val

    # Markdown for stdout (potentially truncated)
    stdout_md = generate_diff_markdown(
        before_entities=before_entities,
        after_entities=after_entities,
        validation_path=val_path,
        max_list_items=max_list_items,
    )

    if full_report is not None:
        untruncated_md = generate_diff_markdown(
            before_entities=before_entities,
            after_entities=after_entities,
            validation_path=val_path,
            max_list_items=None,
        )
        full_report.parent.mkdir(parents=True, exist_ok=True)
        full_report.write_text(untruncated_md, encoding="utf-8")

    sys.stdout.write(stdout_md)
    return stdout_md
