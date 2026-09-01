"""Chunk the merged entities into the shard files `data/dist/entities/` ships.

`pipeline.normalize.merge` builds one `Entity` per registry ID and hands back a
flat `MergeResult`. Nothing in that result groups the entities into files, and
something has to: `TODO.md`'s Phase 3 bullet asks for "sharded entity JSON,"
never one file per entity, both so the web app fetches a handful of files
instead of five thousand and so Decision 4 of `TODO.md`'s 20,000-file
Cloudflare cap stays nowhere near binding. `assign_shards` is that grouping
rule, and it is the one place the rule lives -- see decision D2 below for why
that matters beyond tidiness.

## D1 -- sequential chunking, not hash bucketing

Two ways to cut one kind's entities into files were on the table. Hash
bucketing -- `sha256(id) mod N` -- spreads entities evenly across a fixed file
count and keeps each file's membership stable as entities are added or removed
elsewhere in the same kind, which is the property that makes it attractive for
a diff that a person reviews. That property is worth nothing here.
`.gitattributes` already marks the whole of `data/dist/**` as
`linguist-generated`, with its own comment recording why: every Minecraft
release rewrites the tree, and no person reads the diff line by line. Optimising
for a diff nobody reads is optimising for nothing, and it costs something real
in exchange: a hash bucket groups `acacia_boat` with whatever else happens to
share its digest modulo `N`, which is exactly the alphabetically-scattered
membership that gives a person no way to tell which file broke by reading its
name.

Sequential chunking -- sort by `id`, cut into contiguous runs of at most
`DEFAULT_SHARD_SIZE` -- costs nothing by comparison and buys two things
instead. First, prefix locality: a search index entry's `s` field names one
shard per entity, but the shards a prefix query's results actually land in are
themselves alphabetically adjacent, which is exactly the property CLAUDE.md's
two-second budget rewards when several results of one query share a fetch.
Second, a shard is inspectable by hand -- `item-3.json` holds a contiguous
alphabetical run of items, so a wrong entry is findable by eye during a build
investigation, where a hash bucket's membership answers no question a reader
brings to it.

## D2 -- the caller never recomputes a shard name

`Shard.name` is `<kind>-<n>.json`'s stem, built once, here, from the position a
chunk lands in after this module's own sort. `pipeline.emit.search_index`
reads it off the `Shard` this module returns rather than re-deriving it from an
entity's `id` and position, and `index.schema.json`'s `indexEntry.s` field
description names the same rule from the schema side: the chunking rule lives
entirely inside this one function, and changing it later -- a different
`shard_size`, a different sort key -- is a rebuild of this module's output, not
a coordinated change to a second implementation of the same rule living in the
web app or in `search_index.py`.

## Kind order is sorted by `.value`, not by `EntityKind`'s declaration order

Something has to decide which kind's shards get written first, for the same
reason `pipeline.normalize.entity`'s `_TIER_RANK` comment gives for keeping an
explicit tier-rank mapping rather than trusting `SourceTier`'s member order to
stay meaningful: relying on an enum's declaration order invites a silent
change in behaviour the day somebody reorders the enum for an unrelated
reason -- alphabetising it, or grouping the render-heavy kinds together for a
comment. Sorting by `EntityKind.value` is stable under that reordering by
construction, because the string values themselves do not move. It also means
the output order matches the same alphabetical intuition `id`-sorting already
gives inside one kind, so nothing about this module reads as `A < B` in one
place and `B < A` in another.

## Chunk boundaries

`assign_shards` groups entities by `kind`, sorts each group by `id`, then cuts
every `shard_size` entities into one `Shard`. A kind with 200 entities and
`shard_size=200` produces exactly one shard, not two -- there is no trailing
empty chunk -- and 201 entities produce two, the second holding one entity. A
kind with no entities at all produces no shard: an empty file that nothing
ever reads would be one more entry for `pipeline.emit.write`'s stale-file sweep
to consider deleting on every later build, for no reader it ever serves.

A `shard_size` below 1 raises `EmitError` rather than being clamped, and a
specific silent failure is the reason rather than tidiness. Python's `range`
raises on a step of zero, which is loud enough on its own, but it returns an
*empty* range for a negative step -- so `assign_shards(entities,
shard_size=-1)` would otherwise return no shards at all, and
`pipeline.emit.write` would go on to write an index with no entries, sweep
every shard the previous build wrote as stale, and return a report saying it
succeeded. That is exactly the invisible corruption of `data/dist` that
module's Rule 3 exists to refuse, so the guard sits at the point the bad
argument arrives rather than at the point its consequences show.
"""

from collections.abc import Sequence

from pydantic import BaseModel

from pipeline.emit import EmitError
from pipeline.normalize.entity import Entity, EntityKind

__all__ = ["DEFAULT_SHARD_SIZE", "SHARD_SCHEMA_VERSION", "Shard", "assign_shards"]

# The maximum number of entities one shard file holds. Chosen so that the
# largest kinds -- `item` and `block`, each in the low thousands of registry
# IDs -- still land in single-digit shard counts, keeping `TODO.md`'s "shard
# count in the tens" bullet true without tuning the number per kind.
DEFAULT_SHARD_SIZE = 200

# The constant `shard.schema.json`'s `schemaVersion` pins, and the value
# `pipeline.emit.write` stamps on every shard file it writes. It sits here
# rather than in `write.py` for the same reason `INDEX_SCHEMA_VERSION` sits in
# `pipeline.emit.search_index`: the module that owns a payload's shape owns the
# number that versions it.
SHARD_SCHEMA_VERSION = 1


class Shard(BaseModel, frozen=True):
    """One shard file: the name it is written under, the kind it holds, and its entities.

    `name` is the file's stem, without a directory and without `.json` --
    `pipeline.emit.write` appends both when it writes the file, and
    `pipeline.emit.search_index` writes the same bare stem into every
    `indexEntry.s` this shard's entities produce, matching `index.schema.json`'s
    own description of that field.
    """

    name: str
    kind: EntityKind
    entities: tuple[Entity, ...]


def assign_shards(
    entities: Sequence[Entity], *, shard_size: int = DEFAULT_SHARD_SIZE
) -> tuple[Shard, ...]:
    """Return the shard assignment of `entities`: grouped by kind, sorted by id, chunked.

    See the module docstring for the reasoning behind every choice this
    function makes: sequential chunking over hash bucketing (D1), why the
    shard name is computed exactly once and carried on the `Shard` rather than
    recomputed by a caller (D2), and why kinds are iterated in
    `EntityKind.value` order rather than the enum's declaration order.

    A kind with no members among `entities` produces no `Shard` at all -- the
    returned tuple only ever holds shards with at least one entity.

    Raises `EmitError` for a `shard_size` below 1, which the module docstring
    explains is the one argument to this function that can otherwise drop
    every entity without raising anything.
    """
    if shard_size < 1:
        raise EmitError(
            f"assign_shards was given a shard_size of {shard_size}. A shard holds at least one "
            f"entity, and a size below 1 would silently assign every entity to no file at all."
        )

    by_kind: dict[EntityKind, list[Entity]] = {}
    for entity in entities:
        by_kind.setdefault(entity.kind, []).append(entity)

    shards: list[Shard] = []
    for kind in sorted(EntityKind, key=lambda member: member.value):
        members = sorted(by_kind.get(kind, ()), key=lambda entity: entity.id)
        for index, start in enumerate(range(0, len(members), shard_size)):
            chunk = tuple(members[start : start + shard_size])
            shards.append(Shard(name=f"{kind.value}-{index}", kind=kind, entities=chunk))
    return tuple(shards)
