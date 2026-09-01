"""`build_search_index`: the flat, `id`-sorted `index.json` payload built from a shard assignment.

Every entry's `s` field has to name a shard that genuinely holds the entity it
describes -- that cross-reference is what lets the web app fetch exactly one
file per opened entity rather than guessing which shard to ask for. These
tests build a small, deliberately out-of-alphabetical-order shard assignment
by hand, rather than routing through `assign_shards`, so a bug in the chunking
rule cannot also hide a bug in this module.
"""

import pytest
from pydantic import ValidationError

from pipeline.emit.search_index import IndexEntry, SearchIndex, build_search_index
from pipeline.emit.shard import Shard
from pipeline.normalize.entity import Entity, EntityKind


def _entity(entity_id: str, kind: EntityKind, *, icon: str | None = None) -> Entity:
    return Entity(
        id=entity_id,
        kind=kind,
        name=entity_id.split(":", 1)[-1],
        aliases=("alias-of-" + entity_id,),
        icon=icon,
        source_tiers={},
        sections=(),
    )


def test_an_entry_carries_every_required_field_under_its_short_key() -> None:
    entity = _entity("minecraft:creeper", EntityKind.MOB, icon="EntitySprite:creeper")
    shard = Shard(name="mob-0", kind=EntityKind.MOB, entities=(entity,))

    index = build_search_index([shard])
    assert len(index.entities) == 1
    entry = index.entities[0]

    assert entry.id == "minecraft:creeper"
    assert entry.name == "creeper"
    assert entry.kind is EntityKind.MOB
    assert entry.aliases == ("alias-of-minecraft:creeper",)
    assert entry.shard == "mob-0"
    assert entry.icon == "EntitySprite:creeper"

    dumped = entry.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert dumped == {
        "id": "minecraft:creeper",
        "n": "creeper",
        "k": "mob",
        "a": ["alias-of-minecraft:creeper"],
        "s": "mob-0",
        "i": "EntitySprite:creeper",
    }


def test_icon_is_omitted_from_the_wire_shape_when_the_entity_has_none() -> None:
    entity = _entity("minecraft:poplar_boat", EntityKind.ITEM, icon=None)
    shard = Shard(name="item-0", kind=EntityKind.ITEM, entities=(entity,))

    entry = build_search_index([shard]).entities[0]
    assert entry.icon is None

    dumped = entry.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert "i" not in dumped


def test_the_shard_field_names_the_shard_that_actually_holds_the_entity() -> None:
    """A regression shape: two shards of the same kind must not blur into one name."""
    first = _entity("minecraft:apple", EntityKind.ITEM)
    second = _entity("minecraft:zombie_head", EntityKind.ITEM)
    shards = [
        Shard(name="item-0", kind=EntityKind.ITEM, entities=(first,)),
        Shard(name="item-1", kind=EntityKind.ITEM, entities=(second,)),
    ]

    index = build_search_index(shards)
    by_id = {entry.id: entry for entry in index.entities}
    assert by_id["minecraft:apple"].shard == "item-0"
    assert by_id["minecraft:zombie_head"].shard == "item-1"


def test_entities_are_sorted_by_id_across_every_shard_and_kind() -> None:
    """The global sort must not fall back to shard order or kind order."""
    mob = _entity("minecraft:zombie", EntityKind.MOB)
    item = _entity("minecraft:apple", EntityKind.ITEM)
    block = _entity("minecraft:mud", EntityKind.BLOCK)
    shards = [
        Shard(name="mob-0", kind=EntityKind.MOB, entities=(mob,)),
        Shard(name="item-0", kind=EntityKind.ITEM, entities=(item,)),
        Shard(name="block-0", kind=EntityKind.BLOCK, entities=(block,)),
    ]

    index = build_search_index(shards)
    assert [entry.id for entry in index.entities] == [
        "minecraft:apple",
        "minecraft:mud",
        "minecraft:zombie",
    ]


def test_the_index_carries_schema_version_one_by_default() -> None:
    entity = _entity("minecraft:creeper", EntityKind.MOB)
    shard = Shard(name="mob-0", kind=EntityKind.MOB, entities=(entity,))
    index = build_search_index([shard])
    assert index.schema_version == 1
    assert index.model_dump(mode="json", by_alias=True)["schemaVersion"] == 1


def test_an_entry_can_be_constructed_by_its_python_names_or_by_its_wire_aliases() -> None:
    """`populate_by_name=True` on `IndexEntry` matches `Entity`'s own convention."""
    by_name = IndexEntry(
        id="minecraft:creeper", name="Creeper", kind=EntityKind.MOB, aliases=(), shard="mob-0"
    )
    by_alias = IndexEntry.model_validate(
        {"id": "minecraft:creeper", "n": "Creeper", "k": "mob", "a": [], "s": "mob-0"}
    )
    assert by_name == by_alias


def test_an_index_with_no_entries_is_refused() -> None:
    """`SearchIndex` must restate `index.schema.json`'s `minItems: 1` in Python.

    This pipeline builds its models directly and never runs a JSON Schema
    validator over its own output, so a constraint that lives only in the
    schema file binds nothing at build time. `pipeline.normalize.entity.Entity`
    makes the same point about its conditional `wikiUrl` rule. An index with no
    entries is a search payload that answers every query with nothing, so it is
    a failed build rather than a Minecraft version with nothing to search.
    """
    with pytest.raises(ValidationError):
        SearchIndex(entities=())
