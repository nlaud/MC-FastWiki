"""Tests for pipeline.collections.manifest."""

import json
from pathlib import Path

import pytest

from pipeline.collections import CollectionError
from pipeline.collections.manifest import (
    CollectionManifest,
    ComponentRule,
    KindRule,
    ListRule,
    TagRule,
    load_manifests,
)


def test_load_default_manifests_loads_all_five() -> None:
    manifests = load_manifests()
    assert len(manifests) == 5
    ids = [m.id for m in manifests]
    assert ids == ["arthropods", "enchantments", "structures", "undead", "unique_food"]


def test_manifest_rule_discriminated_union() -> None:
    comp = CollectionManifest.model_validate(
        {
            "id": "test_comp",
            "title": "Test Component",
            "blurb": "Test blurb",
            "rule": {"type": "component", "component": "minecraft:food"},
        }
    )
    assert isinstance(comp.rule, ComponentRule)
    assert comp.rule.component == "minecraft:food"

    tag = CollectionManifest.model_validate(
        {
            "id": "test_tag",
            "title": "Test Tag",
            "blurb": "Test blurb",
            "rule": {"type": "tag", "registry": "entity_type", "tag": "minecraft:undead"},
        }
    )
    assert isinstance(tag.rule, TagRule)
    assert tag.rule.registry == "entity_type"
    assert tag.rule.tag == "minecraft:undead"

    kind = CollectionManifest.model_validate(
        {
            "id": "test_kind",
            "title": "Test Kind",
            "blurb": "Test blurb",
            "rule": {"type": "kind", "kind": "enchantment"},
        }
    )
    assert isinstance(kind.rule, KindRule)
    assert kind.rule.kind == "enchantment"

    list_rule = CollectionManifest.model_validate(
        {
            "id": "test_list",
            "title": "Test List",
            "blurb": "Test blurb",
            "rule": {"type": "list", "ids": ["minecraft:zombie"]},
        }
    )
    assert isinstance(list_rule.rule, ListRule)
    assert list_rule.rule.ids == ("minecraft:zombie",)


def test_load_manifests_missing_directory_raises(tmp_path: Path) -> None:
    non_existent = tmp_path / "missing"
    with pytest.raises(CollectionError, match="does not exist"):
        load_manifests(non_existent)


def test_load_manifests_empty_directory_returns_empty(tmp_path: Path) -> None:
    assert load_manifests(tmp_path) == ()


def test_load_manifests_invalid_json_raises(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{invalid json", encoding="utf-8")
    with pytest.raises(CollectionError, match="Failed to read manifest"):
        load_manifests(tmp_path)


def test_load_manifests_malformed_shape_raises(tmp_path: Path) -> None:
    bad_manifest = tmp_path / "bad.json"
    bad_manifest.write_text(json.dumps({"id": "incomplete"}), encoding="utf-8")
    with pytest.raises(CollectionError, match="is malformed"):
        load_manifests(tmp_path)


def test_load_manifests_duplicate_id_raises(tmp_path: Path) -> None:
    m1 = {
        "id": "dup",
        "title": "First",
        "blurb": "Blurb",
        "rule": {"type": "list", "ids": []},
    }
    m2 = {
        "id": "dup",
        "title": "Second",
        "blurb": "Blurb",
        "rule": {"type": "list", "ids": []},
    }
    (tmp_path / "a.json").write_text(json.dumps(m1), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(m2), encoding="utf-8")
    with pytest.raises(CollectionError, match="Duplicate collection ID 'dup'"):
        load_manifests(tmp_path)


def test_manifest_invalid_sort_by_raises(tmp_path: Path) -> None:
    m = {
        "id": "bad_sort",
        "title": "Bad Sort",
        "blurb": "Blurb",
        "rule": {"type": "list", "ids": []},
        "columns": [{"fact": "food.nutrition", "label": "Hunger"}],
        "sortBy": "invalid_fact_key",
    }
    (tmp_path / "test.json").write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(CollectionError, match="sortBy='invalid_fact_key' does not name 'name'"):
        load_manifests(tmp_path)


def test_manifest_setting_both_icon_fields_raises(tmp_path: Path) -> None:
    manifest = {
        "id": "both",
        "title": "Both",
        "blurb": "Blurb",
        "icon": "HudSprite:hunger-full",
        "iconFrom": "minecraft:zombie",
        "rule": {"type": "kind", "kind": "mob"},
    }
    (tmp_path / "both.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CollectionError, match="sets both 'icon'"):
        load_manifests(tmp_path)


def test_every_shipped_manifest_declares_an_icon() -> None:
    """A collection with no icon is a blank row in the suggestion list."""
    for manifest in load_manifests():
        assert (manifest.icon is not None) or (manifest.icon_from is not None), (
            f"{manifest.id} declares neither 'icon' nor 'iconFrom'"
        )
