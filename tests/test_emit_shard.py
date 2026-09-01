"""`assign_shards`: the chunking rule every other emit module builds on.

`pipeline.emit.shard`'s module docstring names the two decisions this file
pins down: sequential, `id`-sorted chunking rather than a hash bucket (D1), and
a shard name computed exactly once, here, rather than re-derived by a caller
(D2). The kind-coverage test below iterates `EntityKind` itself rather than a
hardcoded list of kind names, so a kind added to the enum later fails this
test until `assign_shards` (which needs no per-kind special case) and this
test's own fixture both cover it.
"""

import pytest

from pipeline.emit import EmitError
from pipeline.emit.shard import DEFAULT_SHARD_SIZE, assign_shards
from pipeline.normalize.entity import Entity, EntityKind


def _entity(entity_id: str, kind: EntityKind) -> Entity:
    """Return the smallest `Entity` that satisfies every one of its own validators."""
    return Entity(id=entity_id, kind=kind, name=entity_id, aliases=(), source_tiers={}, sections=())


def _entities(kind: EntityKind, count: int) -> list[Entity]:
    """Return `count` entities of `kind`, with ids that sort in a known, non-trivial order.

    Zero-padded so `id`-sort order and construction order agree up to 999
    entities, which is more than any boundary this test needs.
    """
    return [_entity(f"minecraft:{kind.value}_{index:04d}", kind) for index in range(count)]


def test_every_entity_kind_produces_a_shard_when_it_has_members() -> None:
    """A kind added to `EntityKind` later must fail this test until it is handled.

    Iterating `EntityKind` itself, rather than a hardcoded tuple of kind
    strings, is what makes that true: one entity per kind here, and the
    assertion below checks that every one of them landed in some shard.
    """
    entities = [_entity(f"minecraft:{kind.value}_only", kind) for kind in EntityKind]
    shards = assign_shards(entities)

    assert {shard.kind for shard in shards} == set(EntityKind)
    for kind in EntityKind:
        shard = next(s for s in shards if s.kind is kind)
        assert shard.entities == (next(e for e in entities if e.kind is kind),)


def test_a_kind_with_no_members_produces_no_shard() -> None:
    entities = _entities(EntityKind.ITEM, 3)
    shards = assign_shards(entities)
    assert {shard.kind for shard in shards} == {EntityKind.ITEM}


def test_exactly_one_shard_size_worth_of_entities_makes_one_shard() -> None:
    entities = _entities(EntityKind.ITEM, DEFAULT_SHARD_SIZE)
    shards = assign_shards(entities)
    assert len(shards) == 1
    assert shards[0].name == "item-0"
    assert len(shards[0].entities) == DEFAULT_SHARD_SIZE


def test_one_more_than_a_shard_size_worth_spills_into_a_second_shard() -> None:
    entities = _entities(EntityKind.ITEM, DEFAULT_SHARD_SIZE + 1)
    shards = assign_shards(entities)
    assert [shard.name for shard in shards] == ["item-0", "item-1"]
    assert len(shards[0].entities) == DEFAULT_SHARD_SIZE
    assert len(shards[1].entities) == 1


def test_exactly_two_shard_sizes_worth_makes_two_full_shards_and_no_trailing_empty_one() -> None:
    entities = _entities(EntityKind.ITEM, DEFAULT_SHARD_SIZE * 2)
    shards = assign_shards(entities)
    assert [shard.name for shard in shards] == ["item-0", "item-1"]
    assert len(shards[0].entities) == DEFAULT_SHARD_SIZE
    assert len(shards[1].entities) == DEFAULT_SHARD_SIZE


def test_one_more_than_two_shard_sizes_worth_spills_into_a_third_shard() -> None:
    entities = _entities(EntityKind.ITEM, DEFAULT_SHARD_SIZE * 2 + 1)
    shards = assign_shards(entities)
    assert [shard.name for shard in shards] == ["item-0", "item-1", "item-2"]
    assert len(shards[2].entities) == 1


def test_entities_within_a_shard_are_sorted_by_id_regardless_of_input_order() -> None:
    entities = list(reversed(_entities(EntityKind.MOB, 5)))
    shards = assign_shards(entities)
    assert len(shards) == 1
    assert [entity.id for entity in shards[0].entities] == sorted(
        entity.id for entity in entities
    )


def test_kinds_are_written_in_a_stable_value_sorted_order() -> None:
    """Kind order follows `EntityKind.value` alphabetically, not enum declaration order.

    `EntityKind`'s own declaration order is mob, item, block, effect,
    advancement, enchantment, structure, biome, collection, entity --
    alphabetical order is different, which is exactly what proves this test is
    checking the sort and not just repeating whatever order construction
    happened to produce.
    """
    entities = [_entity(f"minecraft:only_{kind.value}", kind) for kind in EntityKind]
    shards = assign_shards(entities)
    assert [shard.kind.value for shard in shards] == sorted(
        kind.value for kind in EntityKind
    )


def test_a_custom_shard_size_is_honored() -> None:
    entities = _entities(EntityKind.BLOCK, 5)
    shards = assign_shards(entities, shard_size=2)
    assert [shard.name for shard in shards] == ["block-0", "block-1", "block-2"]
    assert [len(shard.entities) for shard in shards] == [2, 2, 1]


def test_shard_names_carry_no_directory_and_no_json_suffix() -> None:
    """`pipeline.emit.write` appends both; a shard that already carried either would double it."""
    entities = _entities(EntityKind.ITEM, 1)
    shard = assign_shards(entities)[0]
    assert shard.name == "item-0"
    assert "/" not in shard.name
    assert not shard.name.endswith(".json")


@pytest.mark.parametrize("shard_size", [0, -1, -200])
def test_a_shard_size_below_one_raises_rather_than_dropping_every_entity(
    shard_size: int,
) -> None:
    """The guard exists because a negative step makes `range` empty, not loud.

    `range(0, n, 0)` raises, so a size of zero was always going to stop a
    build. `range(0, n, -1)` does not: it is simply empty, so without this
    guard `assign_shards` would return no shards for a negative size,
    `pipeline.emit.write` would write an index naming nothing, sweep every
    shard of the previous build away as stale, and return a report saying the
    build succeeded. This test is what keeps that path closed.
    """
    entities = _entities(EntityKind.ITEM, 5)
    with pytest.raises(EmitError, match="at least one"):
        assign_shards(entities, shard_size=shard_size)
