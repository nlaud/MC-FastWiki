"""Tests for pipeline.collections.tree."""

import pytest

from pipeline.collections import CollectionError
from pipeline.collections.manifest import TreeLayout
from pipeline.collections.tree import build_collection_tree_sections
from pipeline.normalize.entity import (
    AdvancementInfo,
    Entity,
    EntityKind,
    EntityRef,
    SourceTier,
)


def _make_entity(
    eid: str,
    name: str,
    parent: str | None = None,
    children: tuple[str, ...] = (),
    has_advancement_section: bool = True,
) -> Entity:
    sections = []
    if has_advancement_section:
        parent_ref = EntityRef(id=parent, name=parent) if parent is not None else None
        child_refs = tuple(EntityRef(id=c, name=c) for c in children)
        sections.append(
            AdvancementInfo(
                internal_id=eid,
                title=name,
                parent=parent_ref,
                children=child_refs,
            )
        )
    return Entity.model_validate(
        {
            "id": eid,
            "kind": EntityKind.ADVANCEMENT,
            "name": name,
            "aliases": (),
            "sourceTiers": {"name": SourceTier.A},
            "sections": sections,
        }
    )


def test_tree_layout_depth_first_order_and_depth_values() -> None:
    # R -> A, B
    # A -> A1
    entities = {
        "m:root": _make_entity("m:root", "Root", children=("m:a", "m:b")),
        "m:a": _make_entity("m:a", "Child A", parent="m:root", children=("m:a1",)),
        "m:a1": _make_entity("m:a1", "Grandchild A1", parent="m:a"),
        "m:b": _make_entity("m:b", "Child B", parent="m:root"),
    }
    layout = TreeLayout(section="AdvancementInfo")
    sections = build_collection_tree_sections(
        layout,
        list(entities),
        entities,
    )

    assert len(sections) == 1
    sec = sections[0]
    assert sec.title == "Root"
    assert len(sec.members) == 4

    rows = [(m.ref.id, m.depth) for m in sec.members]
    assert rows == [
        ("m:root", 0),
        ("m:a", 1),
        ("m:a1", 2),
        ("m:b", 1),
    ]


def test_tree_layout_sibling_sorting() -> None:
    # Siblings sort by display name, case-folded
    entities = {
        "m:root": _make_entity("m:root", "Root", children=("m:z", "m:a", "m:b")),
        "m:z": _make_entity("m:z", "zebra", parent="m:root"),
        "m:a": _make_entity("m:a", "Alpha", parent="m:root"),
        "m:b": _make_entity("m:b", "beta", parent="m:root"),
    }
    layout = TreeLayout(section="AdvancementInfo")
    sections = build_collection_tree_sections(
        layout,
        list(entities),
        entities,
    )

    sec = sections[0]
    names = [m.ref.name for m in sec.members]
    assert names == ["Root", "Alpha", "beta", "zebra"]


def test_tree_layout_group_split_and_titles() -> None:
    entities = {
        "m:r1": _make_entity("m:r1", "Story Tab", children=("m:s1",)),
        "m:s1": _make_entity("m:s1", "Stone Age", parent="m:r1"),
        "m:r2": _make_entity("m:r2", "Nether Tab", children=("m:n1",)),
        "m:n1": _make_entity("m:n1", "Into Fire", parent="m:r2"),
    }
    layout = TreeLayout(section="AdvancementInfo")
    sections = build_collection_tree_sections(
        layout,
        list(entities),
        entities,
    )

    assert len(sections) == 2
    # Without groupOrder, roots sort alphabetically: Nether Tab then Story Tab
    assert sections[0].title == "Nether Tab"
    assert [m.ref.id for m in sections[0].members] == ["m:r2", "m:n1"]
    assert sections[1].title == "Story Tab"
    assert [m.ref.id for m in sections[1].members] == ["m:r1", "m:s1"]


def test_tree_layout_group_order_honoured_and_unnamed_alphabetical() -> None:
    entities = {
        "m:r_hus": _make_entity("m:r_hus", "Husbandry"),
        "m:r_adv": _make_entity("m:r_adv", "Adventure"),
        "m:r_sto": _make_entity("m:r_sto", "Story"),
        "m:r_end": _make_entity("m:r_end", "The End"),
    }
    # groupOrder names Story and Adventure; Husbandry and The End are unnamed
    layout = TreeLayout(
        section="AdvancementInfo",
        group_order=("m:r_sto", "m:r_adv"),
    )
    sections = build_collection_tree_sections(
        layout,
        list(entities),
        entities,
    )

    titles = [s.title for s in sections]
    # Story, Adventure (from groupOrder), then Husbandry, The End (alphabetical)
    assert titles == ["Story", "Adventure", "Husbandry", "The End"]


def test_tree_layout_raises_when_member_missing_section() -> None:
    entities = {
        "m:r": _make_entity("m:r", "Root", children=("m:child",)),
        "m:child": _make_entity("m:child", "Child", parent="m:r", has_advancement_section=False),
    }
    layout = TreeLayout(section="AdvancementInfo")
    with pytest.raises(CollectionError, match="carries no section of type 'AdvancementInfo'"):
        build_collection_tree_sections(layout, list(entities), entities)


def test_tree_layout_raises_when_zero_roots() -> None:
    # A -> B -> A (both have parents)
    entities = {
        "m:a": _make_entity("m:a", "A", parent="m:b", children=("m:b",)),
        "m:b": _make_entity("m:b", "B", parent="m:a", children=("m:a",)),
    }
    layout = TreeLayout(section="AdvancementInfo")
    with pytest.raises(CollectionError, match="Zero roots found among 2 members"):
        build_collection_tree_sections(layout, list(entities), entities)


def test_tree_layout_raises_when_cycle_in_links() -> None:
    # Root -> A -> B -> A
    entities = {
        "m:root": _make_entity("m:root", "Root", children=("m:a",)),
        "m:a": _make_entity("m:a", "A", parent="m:root", children=("m:b",)),
        "m:b": _make_entity("m:b", "B", parent="m:a", children=("m:a",)),
    }
    layout = TreeLayout(section="AdvancementInfo")
    with pytest.raises(CollectionError, match="Cycle detected"):
        build_collection_tree_sections(layout, list(entities), entities)


def test_tree_layout_raises_when_member_unreachable_from_root() -> None:
    # Root -> A. Member C is orphan with parent D (not in member_ids)
    entities = {
        "m:root": _make_entity("m:root", "Root", children=("m:a",)),
        "m:a": _make_entity("m:a", "A", parent="m:root"),
        "m:c": _make_entity("m:c", "C", parent="m:d"),
    }
    layout = TreeLayout(section="AdvancementInfo")
    with pytest.raises(CollectionError, match="unreachable from any root"):
        build_collection_tree_sections(layout, list(entities), entities)


def test_tree_layout_raises_when_group_order_contains_non_root() -> None:
    entities = {
        "m:root": _make_entity("m:root", "Root", children=("m:child",)),
        "m:child": _make_entity("m:child", "Child", parent="m:root"),
    }
    layout = TreeLayout(
        section="AdvancementInfo",
        group_order=("m:child",),  # Not a root!
    )
    with pytest.raises(CollectionError, match="not a root entity"):
        build_collection_tree_sections(layout, list(entities), entities)
