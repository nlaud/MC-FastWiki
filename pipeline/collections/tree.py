"""Tree layout resolver for collection pages.

Builds grouped depth-first sections from an entity section type that carries
`parent` and `children` links (such as `AdvancementInfo`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pipeline.collections import CollectionError
from pipeline.collections.manifest import TreeLayout
from pipeline.normalize.entity import (
    CollectionTree,
    CollectionTreeMember,
    Entity,
    EntityRef,
    Section,
)

__all__ = ["build_collection_tree_sections"]


def _get_ref_id(ref: object) -> str:
    """Extract string ID from an EntityRef, dict, or string."""
    if hasattr(ref, "id"):
        return str(ref.id)
    if isinstance(ref, dict) and "id" in ref:
        return str(ref["id"])
    return str(ref)


def _find_section(entity: Entity, section_type: str) -> Section | None:
    """Return the first section matching section_type, or None."""
    for section in entity.sections:
        if section.type == section_type:
            return section
    return None


def _walk_tree(
    root_id: str,
    sections_by_id: Mapping[str, Section],
    entities_by_id: Mapping[str, Entity],
    member_ids_set: set[str],
    all_visited: set[str],
) -> tuple[CollectionTreeMember, ...]:
    """Traverse depth-first from root_id and return members with depth."""
    group_members: list[CollectionTreeMember] = []
    in_stack: set[str] = set()

    def _dfs(node_id: str, depth: int) -> None:
        if node_id in in_stack:
            raise CollectionError(
                f"Cycle detected in child links involving {node_id!r}."
            )
        if node_id in all_visited:
            raise CollectionError(
                f"Duplicate path or cycle detected: entity {node_id!r} reached more than once."
            )

        all_visited.add(node_id)
        in_stack.add(node_id)

        node_entity = entities_by_id[node_id]
        group_members.append(
            CollectionTreeMember(
                ref=EntityRef(id=node_id, name=node_entity.name),
                depth=depth,
            )
        )

        sec = sections_by_id[node_id]
        raw_children = getattr(sec, "children", ())
        # Siblings sort by display name, case-folded, which is deterministic
        # and stable across builds (the game's sibling order is a screen position, not data).
        valid_children: list[str] = []
        for child in raw_children:
            cid = _get_ref_id(child)
            if cid in member_ids_set:
                valid_children.append(cid)

        valid_children.sort(
            key=lambda cid: (entities_by_id[cid].name.casefold(), cid)
        )

        for cid in valid_children:
            _dfs(cid, depth + 1)

        in_stack.remove(node_id)

    _dfs(root_id, 0)
    return tuple(group_members)


def build_collection_tree_sections(
    layout: TreeLayout,
    member_ids: Sequence[str],
    entities_by_id: Mapping[str, Entity],
) -> tuple[CollectionTree, ...]:
    """Build grouped depth-first CollectionTree sections.

    Raises CollectionError on:
    - a member whose entity carries no section of the named type,
    - zero roots among the members,
    - a groupOrder ID that is not a root entity,
    - a cycle in the parent or child links,
    - a member unreachable from any root.
    """
    member_ids_set = set(member_ids)

    # 1. Validate that every member carries the named section type
    sections_by_id: dict[str, Section] = {}
    for mid in member_ids:
        entity = entities_by_id[mid]
        section = _find_section(entity, layout.section)
        if section is None:
            raise CollectionError(
                f"Member entity {mid!r} carries no section of type {layout.section!r}."
            )
        sections_by_id[mid] = section

    # 2. Identify root entities: members whose section has parent is None
    roots: list[str] = []
    for mid in member_ids:
        section = sections_by_id[mid]
        parent = getattr(section, "parent", None)
        if parent is None:
            roots.append(mid)

    if not roots:
        raise CollectionError(
            f"Zero roots found among {len(member_ids)} members for section type "
            f"{layout.section!r}. A tree collection requires at least one root."
        )

    root_ids_set = set(roots)

    # 3. Validate and order roots
    for gid in layout.group_order:
        if gid not in root_ids_set:
            raise CollectionError(
                f"groupOrder contains {gid!r}, which is not a root entity. "
                f"Known roots: {sorted(root_ids_set)}."
            )

    # Named roots first, preserving groupOrder
    ordered_roots = [gid for gid in layout.group_order if gid in root_ids_set]
    # Unnamed roots follow, sorted alphabetically by entity display name (casefolded)
    unnamed_roots = [r for r in roots if r not in layout.group_order]
    unnamed_roots.sort(key=lambda rid: (entities_by_id[rid].name.casefold(), rid))
    ordered_roots.extend(unnamed_roots)

    # 4. Check for cycles in parent chains upward
    for mid in member_ids:
        curr = mid
        seen_ancestors: set[str] = set()
        while True:
            seen_ancestors.add(curr)
            sec = sections_by_id.get(curr)
            if sec is None:
                break
            p = getattr(sec, "parent", None)
            if p is None:
                break
            pid = _get_ref_id(p)
            if pid in seen_ancestors:
                raise CollectionError(
                    f"Cycle detected in parent chain involving {pid!r}."
                )
            if pid not in member_ids_set:
                break
            curr = pid

    # 5. Build depth-first order for each root group
    all_visited: set[str] = set()
    result_trees: list[CollectionTree] = []

    for root_id in ordered_roots:
        root_entity = entities_by_id[root_id]
        members = _walk_tree(
            root_id=root_id,
            sections_by_id=sections_by_id,
            entities_by_id=entities_by_id,
            member_ids_set=member_ids_set,
            all_visited=all_visited,
        )
        result_trees.append(
            CollectionTree(
                title=root_entity.name,
                members=members,
            )
        )

    # 6. Check for unreachable members
    unreachable = member_ids_set - all_visited
    if unreachable:
        raise CollectionError(
            f"Found {len(unreachable)} member(s) unreachable from any root: "
            f"{sorted(unreachable)}."
        )

    return tuple(result_trees)
