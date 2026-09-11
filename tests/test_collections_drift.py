"""Drift guards for collection pages with list rules.

Collections with list rules (armor_trims, minecarts, workstations) state their
members explicitly because no tag or component separates them cleanly upstream.
These tests re-derive each list from the build outputs and fail when upstream
adds, removes, or modifies a member.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline.collections.manifest import ListRule, load_manifests

DIST = Path("data") / "dist"
INDEX_PATH = DIST / "index.json"
ENTITIES_DIR = DIST / "entities"


def _load_index_entries() -> list[dict[str, Any]]:
    assert INDEX_PATH.is_file(), f"Search index not found at {INDEX_PATH}"
    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return list(data["entities"])


def _load_shard_entities(shard_name: str) -> list[dict[str, Any]]:
    shard_path = ENTITIES_DIR / f"{shard_name}.json"
    assert shard_path.is_file(), f"Shard not found at {shard_path}"
    data = json.loads(shard_path.read_text(encoding="utf-8"))
    return list(data["entities"])


def test_armor_trims_drift_guard() -> None:
    """The 18 armor trims in the manifest must match every *_armor_trim_smithing_template entity."""
    entries = _load_index_entries()
    expected_ids = {
        str(e["id"])
        for e in entries
        if str(e["id"]).endswith("_armor_trim_smithing_template")
    }
    assert len(expected_ids) == 18

    manifests = {m.id: m for m in load_manifests()}
    trim_manifest = manifests["armor_trims"]
    assert isinstance(trim_manifest.rule, ListRule)
    assert set(trim_manifest.rule.ids) == expected_ids


def test_minecarts_drift_guard() -> None:
    """The 7 minecarts in the manifest must match minecraft:minecart plus every
    *_minecart entity.
    """
    entries = _load_index_entries()
    expected_ids = {
        str(e["id"])
        for e in entries
        if str(e["id"]) == "minecraft:minecart"
        or (str(e["id"]).startswith("minecraft:") and str(e["id"]).endswith("_minecart"))
    }
    assert len(expected_ids) == 7

    manifests = {m.id: m for m in load_manifests()}
    minecart_manifest = manifests["minecarts"]
    assert isinstance(minecart_manifest.rule, ListRule)
    assert set(minecart_manifest.rule.ids) == expected_ids


def test_workstations_drift_guard() -> None:
    """The 13 workstations in the manifest must match the workstation ref on every profession."""
    profession_entities = _load_shard_entities("profession-0")
    workstation_ids: set[str] = set()
    for entity in profession_entities:
        for section in entity.get("sections", []):
            if isinstance(section, dict) and section.get("type") == "ProfessionInfo":
                ws = section.get("workstation")
                if isinstance(ws, dict) and "id" in ws:
                    workstation_ids.add(str(ws["id"]))

    assert len(workstation_ids) == 13

    manifests = {m.id: m for m in load_manifests()}
    workstations_manifest = manifests["workstations"]
    assert isinstance(workstations_manifest.rule, ListRule)
    assert set(workstations_manifest.rule.ids) == workstation_ids


def test_armor_trims_all_resolve_non_empty_found_in() -> None:
    """Every member of armor_trims must resolve a non-empty 'obtain.foundIn' fact."""
    collection_entities = _load_shard_entities("collection-0")
    trims_entity = next(
        (e for e in collection_entities if e.get("id") == "collection:armor_trims"),
        None,
    )
    assert trims_entity is not None, "collection:armor_trims not found in collection-0 shard"

    members_section = next(
        (
            s
            for s in trims_entity.get("sections", [])
            if isinstance(s, dict) and s.get("type") == "CollectionMembers"
        ),
        None,
    )
    assert members_section is not None, "CollectionMembers section not found on armor_trims"

    members = members_section.get("members", [])
    assert len(members) == 18

    for member in members:
        mid = member["ref"]["id"]
        found_in = member.get("values", {}).get("obtain.foundIn", "")
        assert found_in, f"Member {mid} resolved an empty obtain.foundIn cell"
        if mid == "minecraft:tide_armor_trim_smithing_template":
            assert found_in == "dropped by Elder Guardian"
