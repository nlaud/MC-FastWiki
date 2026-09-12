"""Resolve manifest-driven collections into ``Entity`` objects.

This is the core of stage 7a. Each manifest names a rule that selects its
members from the build context -- item components, entity-type tags, or the
entity list itself -- and a set of columns whose values are extracted from
the member's own merged entity via ``pipeline.collections.facts``.

The resolver never opens a network connection. Every input it reads is
already in memory at the point where stage 7a runs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pipeline.collections import CollectionError
from pipeline.collections.facts import extract_fact
from pipeline.collections.manifest import (
    CollectionManifest,
    ComponentRule,
    KindRule,
    ListRule,
    SectionRule,
    TagRule,
    TreeLayout,
)
from pipeline.collections.tree import build_collection_tree_sections
from pipeline.extract.tags import TagIndex
from pipeline.normalize.aliases import generate_aliases
from pipeline.normalize.entity import (
    CollectionMember,
    CollectionMembers,
    Entity,
    EntityKind,
    EntityRef,
    MemberColumn,
    Section,
    SourceTier,
)
from pipeline.obtain.chests import ChestSource
from pipeline.obtain.producer import ProducerIndex

__all__ = ["resolve_collections"]

VANILLA_NAMESPACE = "minecraft"
COLLECTION_NAMESPACE = "collection"


def _resolve_component_rule(
    rule: ComponentRule,
    item_components: Mapping[str, Mapping[str, object]],
) -> list[str]:
    """Return every namespaced item ID that carries *rule.component*.

    ``item_components`` is keyed by bare item paths (``apple``, ``beef``),
    not namespaced IDs. Namespace at the boundary, as
    ``pipeline/extract/food.py`` already does.
    """
    ids: list[str] = []
    for path in sorted(item_components):
        components = item_components[path]
        if isinstance(components, dict) and rule.component in components:
            ids.append(f"{VANILLA_NAMESPACE}:{path}")
    return ids


def _resolve_tag_rule(
    rule: TagRule,
    tag_index: TagIndex,
) -> list[str]:
    """Return every ID under the tag named by *rule*."""
    members = tag_index.resolve(rule.tag)
    return sorted(members)


def _resolve_kind_rule(
    rule: KindRule,
    entities_by_id: Mapping[str, Entity],
) -> list[str]:
    """Return every entity ID whose kind matches *rule.kind*."""
    return sorted(
        eid for eid, entity in entities_by_id.items() if entity.kind.value == rule.kind
    )


def _resolve_list_rule(rule: ListRule) -> list[str]:
    """Return the explicit list of IDs from the manifest."""
    return list(rule.ids)


def _resolve_section_rule(
    rule: SectionRule,
    entities_by_id: Mapping[str, Entity],
) -> list[str]:
    """Return every entity ID that carries a section of type *rule.section*."""
    return sorted(
        eid
        for eid, entity in entities_by_id.items()
        if any(s.type == rule.section for s in entity.sections)
    )


def _resolve_members(
    manifest: CollectionManifest,
    item_components: Mapping[str, Mapping[str, object]],
    tag_indexes: Mapping[str, TagIndex],
    entities_by_id: Mapping[str, Entity],
) -> list[str]:
    """Return the member IDs a manifest's rule selects, raising on zero."""
    rule = manifest.rule

    if isinstance(rule, ComponentRule):
        member_ids = _resolve_component_rule(rule, item_components)
    elif isinstance(rule, TagRule):
        tag_index = tag_indexes.get(rule.registry)
        if tag_index is None:
            raise CollectionError(
                f"Manifest {manifest.id!r} names the tag registry {rule.registry!r}, "
                f"which this build has no TagIndex for. It holds "
                f"{sorted(tag_indexes) or 'none'}."
            )
        member_ids = _resolve_tag_rule(rule, tag_index)
    elif isinstance(rule, KindRule):
        member_ids = _resolve_kind_rule(rule, entities_by_id)
    elif isinstance(rule, ListRule):
        member_ids = _resolve_list_rule(rule)
    elif isinstance(rule, SectionRule):
        member_ids = _resolve_section_rule(rule, entities_by_id)
    else:
        raise CollectionError(
            f"Manifest {manifest.id!r}: unknown rule type {type(rule).__name__!r}."
        )

    if not member_ids:
        raise CollectionError(
            f"Manifest {manifest.id!r}: the {type(rule).__name__} rule resolved to zero "
            f"members. A collection page with nothing on it is a broken read, not a "
            f"version of Minecraft with no {manifest.title.lower()}."
        )

    return member_ids


def _resolve_icon(
    manifest: CollectionManifest,
    entities_by_id: Mapping[str, Entity],
) -> str | None:
    """Return the icon key this collection borrows, or None when it declares none.

    `iconFrom` is checked against this build rather than trusted: an entity
    that is absent, or that resolved no icon of its own, raises here and names
    itself. The alternative is an icon key that reaches the atlas, fails to
    resolve, and surfaces as one more line in the unresolved-icon report that
    nobody reads per-build.

    `icon` cannot be checked the same way, because the whole point of it is a
    key no entity owns, and this stage holds no sprite index. It stays the
    narrower field for that reason.
    """
    if manifest.icon is not None:
        return manifest.icon
    if manifest.icon_from is None:
        return None

    source = entities_by_id.get(manifest.icon_from)
    if source is None:
        raise CollectionError(
            f"Manifest {manifest.id!r} borrows its icon from {manifest.icon_from!r}, "
            f"which this build has no entity for."
        )
    if source.icon is None:
        raise CollectionError(
            f"Manifest {manifest.id!r} borrows its icon from {manifest.icon_from!r}, "
            f"which resolved no icon of its own. Name an entity that has one, or use "
            f"'icon' to state a sprite key outright."
        )
    return source.icon


def _build_collection_entity(
    manifest: CollectionManifest,
    member_ids: list[str],
    entities_by_id: Mapping[str, Entity],
    producer_index: ProducerIndex | None = None,
    sources: Mapping[str, ChestSource] | None = None,
) -> Entity:
    """Build one collection ``Entity`` from a resolved manifest."""
    entity_id = f"{COLLECTION_NAMESPACE}:{manifest.id}"

    # Validate every member resolves to an entity
    missing = [mid for mid in member_ids if mid not in entities_by_id]
    if missing:
        raise CollectionError(
            f"Manifest {manifest.id!r}: {len(missing)} member ID(s) have no entity: "
            f"{missing[:10]}{'...' if len(missing) > 10 else ''}. "
            f"A member with no entity would render as a missing row nobody sees."
        )

    sections: tuple[Section, ...]
    if isinstance(manifest.layout, TreeLayout):
        sections = build_collection_tree_sections(
            layout=manifest.layout,
            member_ids=member_ids,
            entities_by_id=entities_by_id,
        )
        section_provenance_key = "sections.CollectionTree"
    else:
        # Build column definitions
        columns = tuple(
            MemberColumn(key=col.fact, label=col.label) for col in manifest.columns
        )

        # Build member rows with fact values
        members_list: list[CollectionMember] = []
        for mid in member_ids:
            member_entity = entities_by_id[mid]
            values: dict[str, str] = {}
            for col in manifest.columns:
                value = extract_fact(
                    member_entity,
                    col.fact,
                    producer_index=producer_index,
                    sources=sources,
                )
                if value:
                    values[col.fact] = value

            members_list.append(
                CollectionMember(
                    ref=EntityRef(id=mid, name=member_entity.name),
                    values=values,
                )
            )

        # Sort members
        sort_key = manifest.sort_by
        descending = manifest.sort_direction == "descending"

        if sort_key == "name":
            members_list.sort(key=lambda m: m.ref.name.casefold(), reverse=descending)
        elif sort_key is not None:
            # Sort by fact value, numerically where the value parses as a number.
            #
            # The direction is applied by negating the numeric key rather than by passing
            # `reverse=True`, so that the name tie-break stays alphabetical in both
            # directions. `reverse=True` reverses the whole composite key, which put the
            # three 8-nutrition foods on the Food page in the order Steak, Pumpkin Pie,
            # Cooked Porkchop -- backwards, for rows the reader scans as a group.
            #
            # A value that is not a number keeps its own text as the tie-break and sorts
            # after every numeric one, so a mixed column stays deterministic instead of
            # collapsing every non-numeric row onto the same key.
            sign = -1.0 if descending else 1.0

            def _sort_value(m: CollectionMember) -> tuple[int, float, str]:
                raw = m.values.get(sort_key, "")
                if not raw:
                    # A member missing the fact sorts last whichever way the column runs.
                    return (2, 0.0, m.ref.name.casefold())
                try:
                    # A unit-bearing fact formats as "65%" or "15s", and the column
                    # sorts on the number underneath it. `removesuffix` rather than
                    # `rstrip`, because `rstrip("%s")` strips a character *set*: it
                    # would turn a future "Ruins" into "Ruin" and a "100ss" typo into
                    # "100", quietly, where this raises ValueError and falls through
                    # to the text tie-break below.
                    clean_raw = raw.removesuffix("%").removesuffix("s")
                    return (0, sign * float(clean_raw), m.ref.name.casefold())
                except ValueError:
                    return (1, 0.0, raw.casefold())

            members_list.sort(key=_sort_value)
        else:
            # Default: sort by name ascending
            members_list.sort(key=lambda m: m.ref.name.casefold())

        sections = (
            CollectionMembers(
                columns=columns,
                members=tuple(members_list),
            ),
        )
        section_provenance_key = "sections.CollectionMembers"

    # Generate aliases
    alias_pairs = generate_aliases(
        entity_id=entity_id,
        kind=EntityKind.COLLECTION,
        name=manifest.title,
        curated=manifest.aliases,
    )
    aliases = tuple(alias for alias, _strength in alias_pairs)

    # Build provenance
    source_tiers: dict[str, SourceTier] = {
        "name": SourceTier.C,
        "blurb": SourceTier.C,
        section_provenance_key: SourceTier.A,
    }
    if aliases:
        source_tiers["aliases"] = SourceTier.C

    icon = _resolve_icon(manifest, entities_by_id)
    if icon is not None:
        # Tier C: a person chose which icon stands for this page, in the manifest.
        source_tiers["icon"] = SourceTier.C

    return Entity(
        id=entity_id,
        kind=EntityKind.COLLECTION,
        name=manifest.title,
        aliases=aliases,
        icon=icon,
        blurb=manifest.blurb,
        wiki_url=None,
        source_tiers=source_tiers,
        sections=sections,
    )


def resolve_collections(
    manifests: Sequence[CollectionManifest],
    entities: Sequence[Entity],
    item_components: Mapping[str, Mapping[str, object]],
    tag_indexes: Mapping[str, TagIndex],
    *,
    producer_index: ProducerIndex | None = None,
    sources: Mapping[str, ChestSource] | None = None,
) -> list[Entity]:
    """Resolve all manifests into collection ``Entity`` objects.

    ``entities`` is the merged entity list from stage 7. ``item_components``
    is the decoded ``item_components/data.json`` from stage 3 (its keys are
    unprefixed item paths). ``tag_indexes`` maps a registry name to the
    ``TagIndex`` that reads it, both built from the same ``files`` mapping
    stage 3 uses.

    The mapping is keyed by registry rather than being one index, because a
    tag name can live in two registries at once and resolve differently in
    each. `arrows` and `frog_food` are both an item tag and an entity_type
    tag in 26.2, so a rule naming `minecraft:arrows` is only answerable once
    its own `registry` field has chosen a tree -- which is the same trap
    `pipeline.extract.tags.TagIndex` refuses a default registry over.

    Returns one ``Entity`` per manifest, sorted by entity ID.
    """
    entities_by_id: dict[str, Entity] = {e.id: e for e in entities}
    collections: list[Entity] = []

    for manifest in manifests:
        member_ids = _resolve_members(
            manifest, item_components, tag_indexes, entities_by_id
        )
        collection_entity = _build_collection_entity(
            manifest,
            member_ids,
            entities_by_id,
            producer_index=producer_index,
            sources=sources,
        )
        collections.append(collection_entity)

    return sorted(collections, key=lambda e: e.id)
