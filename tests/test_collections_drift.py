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


def test_advancements_drift_guard() -> None:
    """The built advancements page holds exactly 126 advancement entities across 5 groups."""
    collection_entities = _load_shard_entities("collection-0")
    adv_entity = next(
        (e for e in collection_entities if e.get("id") == "collection:advancements"),
        None,
    )
    assert adv_entity is not None, "collection:advancements not found in collection-0 shard"

    tree_sections = [
        s
        for s in adv_entity.get("sections", [])
        if isinstance(s, dict) and s.get("type") == "CollectionTree"
    ]
    assert len(tree_sections) == 5, f"Expected 5 CollectionTree sections, got {len(tree_sections)}"

    expected_groups = [
        ("minecraft:story/root", "Minecraft"),
        ("minecraft:nether/root", "Nether"),
        ("minecraft:end/root", "The End"),
        ("minecraft:adventure/root", "Adventure"),
        ("minecraft:husbandry/root", "Husbandry"),
    ]

    total_members = 0
    all_member_ids: set[str] = set()

    for idx, (expected_root_id, expected_title) in enumerate(expected_groups):
        section = tree_sections[idx]
        assert section.get("title") == expected_title, (
            f"Group {idx} title mismatch: expected {expected_title!r}, got {section.get('title')!r}"
        )
        members = section.get("members", [])
        assert len(members) > 0, f"Group {expected_title} has no members"

        root_member = members[0]
        assert root_member["depth"] == 0
        assert root_member["ref"]["id"] == expected_root_id

        for m in members[1:]:
            assert m["depth"] > 0, (
                f"Member {m['ref']['id']} in {expected_title} has non-positive depth"
            )

        for m in members:
            mid = m["ref"]["id"]
            assert mid not in all_member_ids, f"Duplicate member {mid} across advancement trees"
            all_member_ids.add(mid)

        total_members += len(members)

    assert total_members == 126, f"Expected 126 total advancement members, got {total_members}"


def test_compostable_drift_guard() -> None:
    """The built compostable page holds exactly 116 items sorted descending by chance."""
    collection_entities = _load_shard_entities("collection-0")
    compost_entity = next(
        (e for e in collection_entities if e.get("id") == "collection:compostable"),
        None,
    )
    assert compost_entity is not None, "collection:compostable not found in collection-0 shard"

    members_section = next(
        (
            s
            for s in compost_entity.get("sections", [])
            if isinstance(s, dict) and s.get("type") == "CollectionMembers"
        ),
        None,
    )
    assert members_section is not None, "CollectionMembers section not found on compostable"

    members = members_section.get("members", [])
    assert len(members) == 116, f"Expected 116 compostable members, got {len(members)}"

    # Check anchors and formatting
    members_by_id = {m["ref"]["id"]: m for m in members}
    assert members_by_id["minecraft:cake"]["values"]["compost.chance"] == "100%"
    assert members_by_id["minecraft:baked_potato"]["values"]["compost.chance"] == "85%"
    assert members_by_id["minecraft:flowering_azalea"]["values"]["compost.chance"] == "85%"
    assert members_by_id["minecraft:azalea"]["values"]["compost.chance"] == "65%"
    assert members_by_id["minecraft:flowering_azalea_leaves"]["values"]["compost.chance"] == "50%"
    assert members_by_id["minecraft:oak_leaves"]["values"]["compost.chance"] == "30%"

    # Check sort order: chance is descending
    chances = [int(m["values"]["compost.chance"].rstrip("%")) for m in members]
    assert chances == sorted(chances, reverse=True)


def test_fuel_drift_guard() -> None:
    """The built fuel page holds exactly 280 items sorted descending by burn time."""
    collection_entities = _load_shard_entities("collection-0")
    fuel_entity = next(
        (e for e in collection_entities if e.get("id") == "collection:fuel"),
        None,
    )
    assert fuel_entity is not None, "collection:fuel not found in collection-0 shard"

    members_section = next(
        (
            s
            for s in fuel_entity.get("sections", [])
            if isinstance(s, dict) and s.get("type") == "CollectionMembers"
        ),
        None,
    )
    assert members_section is not None, "CollectionMembers section not found on fuel"

    members = members_section.get("members", [])
    assert len(members) == 280, f"Expected 280 fuel members, got {len(members)}"

    # Check anchors and formatting
    members_by_id = {m["ref"]["id"]: m for m in members}
    lava = members_by_id["minecraft:lava_bucket"]["values"]
    assert lava["fuel.burnTime"] == "1000s"
    assert lava["fuel.operations"] == "100"

    coal = members_by_id["minecraft:coal"]["values"]
    assert coal["fuel.burnTime"] == "80s"
    assert coal["fuel.operations"] == "8"

    stick = members_by_id["minecraft:stick"]["values"]
    assert stick["fuel.burnTime"] == "5s"
    assert stick["fuel.operations"] == "0.5"

    carpet = members_by_id["minecraft:white_carpet"]["values"]
    assert carpet["fuel.burnTime"] == "3.35s"
    assert carpet["fuel.operations"] == "0.34"

    scaffold = members_by_id["minecraft:scaffolding"]["values"]
    assert scaffold["fuel.burnTime"] == "2.5s"
    assert scaffold["fuel.operations"] == "0.25"

    # Check sort order: burnTime is descending
    burn_seconds = [float(m["values"]["fuel.burnTime"].rstrip("s")) for m in members]
    assert burn_seconds == sorted(burn_seconds, reverse=True)


def test_chest_loot_drift_guard() -> None:
    """The built chest_loot page holds exactly 31 structures sorted ascending by name."""
    collection_entities = _load_shard_entities("collection-0")
    chest_entity = next(
        (e for e in collection_entities if e.get("id") == "collection:chest_loot"),
        None,
    )
    assert chest_entity is not None, "collection:chest_loot not found in collection-0 shard"

    members_section = next(
        (
            s
            for s in chest_entity.get("sections", [])
            if isinstance(s, dict) and s.get("type") == "CollectionMembers"
        ),
        None,
    )
    assert members_section is not None, "CollectionMembers section not found on chest_loot"

    members = members_section.get("members", [])
    assert len(members) == 31, f"Expected 31 chest_loot members, got {len(members)}"

    # Check anchors and formatting against reference data
    members_by_id = {m["ref"]["id"]: m for m in members}
    ac = members_by_id["minecraft:ancient_city"]["values"]
    assert ac["chest.containers"] == "2"
    assert ac["chest.items"] == "32"

    bm = members_by_id["minecraft:mineshaft_mesa"]["values"]
    assert bm["chest.containers"] == "1"
    assert bm["chest.items"] == "22"

    tc = members_by_id["minecraft:trial_chambers"]["values"]
    assert tc["chest.containers"] == "20"
    assert tc["chest.items"] == "67"

    dv = members_by_id["minecraft:village_desert"]["values"]
    assert dv["chest.containers"] == "12"
    assert dv["chest.items"] == "65"

    # Check sort order: name ascending
    names = [m["ref"]["name"].casefold() for m in members]
    assert names == sorted(names)


def test_villager_trades_drift_guard() -> None:
    """The built villager_trades page holds exactly 13 professions sorted ascending by name."""
    collection_entities = _load_shard_entities("collection-0")
    trades_entity = next(
        (e for e in collection_entities if e.get("id") == "collection:villager_trades"),
        None,
    )
    assert trades_entity is not None, "collection:villager_trades not found in collection-0 shard"

    members_section = next(
        (
            s
            for s in trades_entity.get("sections", [])
            if isinstance(s, dict) and s.get("type") == "CollectionMembers"
        ),
        None,
    )
    assert members_section is not None, "CollectionMembers section not found on villager_trades"

    members = members_section.get("members", [])
    assert len(members) == 13, f"Expected 13 villager_trades members, got {len(members)}"

    # Check anchors and formatting against reference data
    members_by_id = {m["ref"]["id"]: m for m in members}
    armorer = members_by_id["minecraft:armorer"]["values"]
    assert armorer["profession.workstation"] == "Blast Furnace"
    assert armorer["profession.tradeCount"] == "18"

    farmer = members_by_id["minecraft:farmer"]["values"]
    assert farmer["profession.workstation"] == "Composter"
    assert farmer["profession.tradeCount"] == "14"

    shepherd = members_by_id["minecraft:shepherd"]["values"]
    assert shepherd["profession.workstation"] == "Loom"
    assert shepherd["profession.tradeCount"] == "26"

    weaponsmith = members_by_id["minecraft:weaponsmith"]["values"]
    assert weaponsmith["profession.workstation"] == "Grindstone"
    assert weaponsmith["profession.tradeCount"] == "9"

    # Check sort order: name ascending
    names = [m["ref"]["name"].casefold() for m in members]
    assert names == sorted(names)


def test_bartering_drift_guard() -> None:
    """The built bartering page holds exactly 18 items sorted descending by chance."""
    collection_entities = _load_shard_entities("collection-0")
    barter_entity = next(
        (e for e in collection_entities if e.get("id") == "collection:bartering"),
        None,
    )
    assert barter_entity is not None, "collection:bartering not found in collection-0 shard"

    members_section = next(
        (
            s
            for s in barter_entity.get("sections", [])
            if isinstance(s, dict) and s.get("type") == "CollectionMembers"
        ),
        None,
    )
    assert members_section is not None, "CollectionMembers section not found on bartering"

    members = members_section.get("members", [])
    assert len(members) == 18, f"Expected 18 bartering members, got {len(members)}"

    # Check anchors and formatting against reference data
    members_by_id = {m["ref"]["id"]: m for m in members}
    bs = members_by_id["minecraft:blackstone"]["values"]
    assert bs["obtain.chance"] == "8.529%"
    assert bs["obtain.stackRange"] == "8-16"
    assert bs["obtain.perAttempt"] == "1.023"

    fc = members_by_id["minecraft:fire_charge"]["values"]
    assert fc["obtain.chance"] == "8.529%"
    assert fc["obtain.stackRange"] == "1"
    assert fc["obtain.perAttempt"] == "0.085"

    nq = members_by_id["minecraft:quartz"]["values"]
    assert nq["obtain.chance"] == "4.264%"
    assert nq["obtain.stackRange"] == "5-12"
    assert nq["obtain.perAttempt"] == "0.362"

    potion = members_by_id["minecraft:potion"]["values"]
    assert potion["obtain.chance"] == "3.838%"
    assert potion["obtain.stackRange"] == "1"
    assert potion["obtain.perAttempt"] == "0.038"

    inug = members_by_id["minecraft:iron_nugget"]["values"]
    assert inug["obtain.chance"] == "2.132%"
    assert inug["obtain.stackRange"] == "10-36"
    assert inug["obtain.perAttempt"] == "0.490"

    book = members_by_id["minecraft:book"]["values"]
    assert book["obtain.chance"] == "1.066%"
    assert book["obtain.stackRange"] == "1"
    assert book["obtain.perAttempt"] == "0.011"

    # Check sort order: chance is descending
    chances = [float(m["values"]["obtain.chance"].rstrip("%")) for m in members]
    assert chances == sorted(chances, reverse=True)


