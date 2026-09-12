"""Tests for pipeline.collections.manifest."""

import json
from pathlib import Path

import pytest

from pipeline.collections import CollectionError
from pipeline.collections.manifest import (
    CollectionManifest,
    ComponentRule,
    KindRule,
    ListLayout,
    ListRule,
    TagRule,
    TreeLayout,
    load_manifests,
)


def test_load_default_manifests_loads_all_ten() -> None:
    manifests = load_manifests()
    assert len(manifests) == 10
    ids = [m.id for m in manifests]
    assert ids == [
        "advancements",
        "armor_trims",
        "arthropods",
        "banner_patterns",
        "enchantments",
        "minecarts",
        "structures",
        "undead",
        "unique_food",
        "workstations",
    ]


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


def test_manifest_layout_default_and_parsing() -> None:
    # Omitted layout defaults to ListLayout
    default_manifest = CollectionManifest.model_validate(
        {
            "id": "test_default",
            "title": "Default Layout",
            "blurb": "Blurb",
            "rule": {"type": "kind", "kind": "item"},
        }
    )
    assert isinstance(default_manifest.layout, ListLayout)
    assert default_manifest.layout.type == "list"

    # Explicit tree layout parses with groupOrder
    tree_manifest = CollectionManifest.model_validate(
        {
            "id": "test_tree",
            "title": "Tree Layout",
            "blurb": "Blurb",
            "rule": {"type": "kind", "kind": "advancement"},
            "layout": {
                "type": "tree",
                "section": "AdvancementInfo",
                "groupOrder": ["minecraft:story/root", "minecraft:nether/root"],
            },
        }
    )
    assert isinstance(tree_manifest.layout, TreeLayout)
    assert tree_manifest.layout.type == "tree"
    assert tree_manifest.layout.section == "AdvancementInfo"
    assert tree_manifest.layout.group_order == (
        "minecraft:story/root",
        "minecraft:nether/root",
    )


def test_tree_layout_refuses_columns(tmp_path: Path) -> None:
    manifest = {
        "id": "tree_with_columns",
        "title": "Tree With Columns",
        "blurb": "Blurb",
        "rule": {"type": "kind", "kind": "advancement"},
        "layout": {
            "type": "tree",
            "section": "AdvancementInfo",
        },
        "columns": [{"fact": "food.nutrition", "label": "Hunger"}],
    }
    (tmp_path / "bad.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CollectionError, match="tree layout does not support 'columns'"):
        load_manifests(tmp_path)


def test_tree_layout_refuses_sort_by(tmp_path: Path) -> None:
    manifest = {
        "id": "tree_with_sort",
        "title": "Tree With Sort",
        "blurb": "Blurb",
        "rule": {"type": "kind", "kind": "advancement"},
        "layout": {
            "type": "tree",
            "section": "AdvancementInfo",
        },
        "sortBy": "name",
    }
    (tmp_path / "bad.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CollectionError, match="tree layout does not support 'sortBy'"):
        load_manifests(tmp_path)

