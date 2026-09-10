"""Tests for pipeline.collections.resolve."""

import pytest

from pipeline.collections import CollectionError
from pipeline.collections.manifest import (
    CollectionManifest,
    ColumnDef,
    ComponentRule,
    KindRule,
    ListRule,
    TagRule,
)
from pipeline.collections.resolve import resolve_collections
from pipeline.extract.tags import TagIndex
from pipeline.normalize.entity import (
    CollectionMembers,
    Entity,
    EntityKind,
    FoodInfo,
    SourceTier,
)


def _minimal_entity(
    entity_id: str,
    name: str,
    kind: EntityKind = EntityKind.ITEM,
    **kwargs: object,
) -> Entity:
    fields: dict[str, object] = {
        "id": entity_id,
        "kind": kind,
        "name": name,
        "aliases": (),
        "sourceTiers": {"name": SourceTier.A},
        "sections": (),
    }
    fields.update(kwargs)
    return Entity.model_validate(fields)


def test_resolve_component_rule() -> None:
    manifest = CollectionManifest(
        id="foods",
        title="Foods",
        blurb="All food items",
        rule=ComponentRule(component="minecraft:food"),
        columns=(ColumnDef(fact="food.nutrition", label="Hunger"),),
        sort_by="food.nutrition",
        sort_direction="descending",
    )
    entities = [
        _minimal_entity(
            "minecraft:apple",
            "Apple",
            sections=(FoodInfo(nutrition=4, saturation=2.4),),
        ),
        _minimal_entity(
            "minecraft:golden_carrot",
            "Golden Carrot",
            sections=(FoodInfo(nutrition=6, saturation=14.4),),
        ),
        _minimal_entity("minecraft:dirt", "Dirt"),
    ]
    item_components = {
        "apple": {"minecraft:food": {"nutrition": 4, "saturation": 2.4}},
        "golden_carrot": {"minecraft:food": {"nutrition": 6, "saturation": 14.4}},
        "dirt": {},
    }

    result = resolve_collections([manifest], entities, item_components, {})
    assert len(result) == 1
    col = result[0]
    assert col.id == "collection:foods"
    assert col.kind == EntityKind.COLLECTION
    assert col.name == "Foods"
    assert col.icon is None
    assert col.wiki_url is None
    assert col.source_tiers["name"] == SourceTier.C
    assert col.source_tiers["blurb"] == SourceTier.C
    assert col.source_tiers["sections.CollectionMembers"] == SourceTier.A

    section = col.sections[0]
    assert isinstance(section, CollectionMembers)
    assert len(section.members) == 2
    # Sorted descending by nutrition: Golden Carrot (6) then Apple (4)
    assert section.members[0].ref.id == "minecraft:golden_carrot"
    assert section.members[0].values["food.nutrition"] == "6"
    assert section.members[1].ref.id == "minecraft:apple"
    assert section.members[1].values["food.nutrition"] == "4"


def test_resolve_tag_rule() -> None:
    manifest = CollectionManifest(
        id="undead",
        title="Undead Mobs",
        blurb="Mobs that take Smite damage",
        rule=TagRule(registry="entity_type", tag="minecraft:undead"),
    )
    entities = [
        _minimal_entity("minecraft:zombie", "Zombie", EntityKind.MOB),
        _minimal_entity("minecraft:skeleton", "Skeleton", EntityKind.MOB),
    ]
    files = {
        "tags/entity_type/undead.json": b'{"values": ["minecraft:zombie", "minecraft:skeleton"]}'
    }
    tag_index = TagIndex(files, registry="entity_type")

    result = resolve_collections([manifest], entities, {}, {"entity_type": tag_index})
    assert len(result) == 1
    col = result[0]
    section = col.sections[0]
    assert isinstance(section, CollectionMembers)
    assert len(section.columns) == 0
    # Default sort by name ascending: Skeleton then Zombie
    assert [m.ref.id for m in section.members] == ["minecraft:skeleton", "minecraft:zombie"]


def test_resolve_kind_rule() -> None:
    manifest = CollectionManifest(
        id="all_structures",
        title="Structures",
        blurb="Worldgen structures",
        rule=KindRule(kind="structure"),
    )
    entities = [
        _minimal_entity("minecraft:fortress", "Nether Fortress", EntityKind.STRUCTURE),
        _minimal_entity("minecraft:village", "Village", EntityKind.STRUCTURE),
        _minimal_entity("minecraft:apple", "Apple", EntityKind.ITEM),
    ]

    result = resolve_collections([manifest], entities, {}, {})
    assert len(result) == 1
    col = result[0]
    section = col.sections[0]
    assert isinstance(section, CollectionMembers)
    assert [m.ref.id for m in section.members] == ["minecraft:fortress", "minecraft:village"]


def test_resolve_list_rule() -> None:
    manifest = CollectionManifest(
        id="special",
        title="Special List",
        blurb="Explicit list",
        rule=ListRule(ids=("minecraft:diamond", "minecraft:emerald")),
    )
    entities = [
        _minimal_entity("minecraft:diamond", "Diamond"),
        _minimal_entity("minecraft:emerald", "Emerald"),
    ]

    result = resolve_collections([manifest], entities, {}, {})
    assert len(result) == 1
    section = result[0].sections[0]
    assert isinstance(section, CollectionMembers)
    assert [m.ref.id for m in section.members] == ["minecraft:diamond", "minecraft:emerald"]


def test_fault_member_id_with_no_entity_raises() -> None:
    manifest = CollectionManifest(
        id="broken",
        title="Broken",
        blurb="Blurb",
        rule=ListRule(ids=("minecraft:non_existent",)),
    )
    entities = [_minimal_entity("minecraft:apple", "Apple")]
    with pytest.raises(CollectionError, match=r"member ID.*have no entity"):
        resolve_collections([manifest], entities, {}, {})


def test_fault_zero_members_resolved_raises() -> None:
    manifest = CollectionManifest(
        id="empty_food",
        title="Food",
        blurb="Blurb",
        rule=ComponentRule(component="minecraft:food"),
    )
    entities = [_minimal_entity("minecraft:apple", "Apple")]
    item_components: dict[str, dict[str, object]] = {"apple": {}}  # No minecraft:food
    with pytest.raises(CollectionError, match="resolved to zero members"):
        resolve_collections([manifest], entities, item_components, {})


def test_alias_generation_for_collections() -> None:
    manifest = CollectionManifest(
        id="unique_food",
        title="Food",
        blurb="All food items",
        aliases=("hunger", "edible"),
        rule=ListRule(ids=("minecraft:apple",)),
    )
    entities = [_minimal_entity("minecraft:apple", "Apple")]
    result = resolve_collections([manifest], entities, {}, {})
    col = result[0]
    assert "hunger" in col.aliases
    assert "edible" in col.aliases
    assert "unique food" in col.aliases
    assert col.source_tiers["aliases"] == SourceTier.C


def test_tag_rule_reads_the_registry_the_manifest_names() -> None:
    """A tag name living in two registries must resolve in the one named.

    `arrows` and `frog_food` are both an item tag and an entity_type tag in
    26.2, and they resolve to different sets. A resolver that picked one index
    for every tag rule would answer the wrong tree without saying so, which is
    the same fault `TagIndex` refuses a default registry over.
    """
    item_tags = TagIndex(
        {"tags/item/arrows.json": b'{"values": ["minecraft:arrow"]}'},
        registry="item",
    )
    entity_type_tags = TagIndex(
        {"tags/entity_type/arrows.json": b'{"values": ["minecraft:spectral_arrow"]}'},
        registry="entity_type",
    )
    indexes = {"item": item_tags, "entity_type": entity_type_tags}
    entities = [
        _minimal_entity("minecraft:arrow", "Arrow"),
        _minimal_entity("minecraft:spectral_arrow", "Spectral Arrow"),
    ]

    def _members(registry: str) -> list[str]:
        manifest = CollectionManifest(
            id="arrows",
            title="Arrows",
            blurb="Blurb",
            rule=TagRule(registry=registry, tag="minecraft:arrows"),
        )
        section = resolve_collections([manifest], entities, {}, indexes)[0].sections[0]
        assert isinstance(section, CollectionMembers)
        return [member.ref.id for member in section.members]

    assert _members("item") == ["minecraft:arrow"]
    assert _members("entity_type") == ["minecraft:spectral_arrow"]


def test_tag_rule_naming_an_absent_registry_raises() -> None:
    manifest = CollectionManifest(
        id="undead",
        title="Undead Mobs",
        blurb="Blurb",
        rule=TagRule(registry="block", tag="minecraft:undead"),
    )
    entities = [_minimal_entity("minecraft:zombie", "Zombie", EntityKind.MOB)]
    with pytest.raises(CollectionError, match="tag registry 'block'"):
        resolve_collections([manifest], entities, {}, {})
