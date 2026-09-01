"""Build the `data/dist/index.json` payload from a build's shard assignment.

`pipeline.emit.shard.assign_shards` already decided which file holds each
entity; this module's only job is to turn that assignment into the flat,
`id`-sorted list Phase 4 loads at boot and searches over on every keystroke.
`index.schema.json`'s module description gives the reason every field but `id`
is a single letter: the payload repeats them roughly 5,000 times, once per
entity, against a 16 ms-per-keystroke budget once the file is parsed.

**Why this module takes the shard assignment rather than the entity list
alone.** An `IndexEntry.shard` (`s` on the wire) names the file
`pipeline.emit.write` will ask the web app to fetch when this entity opens,
and that name only exists once `assign_shards` has run -- it is `<kind>-<n>`
for the chunk this entity landed in, and `<n>` depends on every other entity of
the same kind that sorted before it. Building the index from the entities
alone and recomputing `<n>` here a second time would let this module's
chunking silently drift from `assign_shards`'s own, which is precisely the
two-implementations failure decision D2 of `pipeline.emit.shard`'s docstring
exists to rule out. Reading `Shard.name` off the assignment `pipeline.emit.
write` already built keeps there being exactly one place that decides it.
"""

from collections.abc import Sequence

from pydantic import BaseModel, Field

from pipeline.emit.shard import Shard
from pipeline.normalize.entity import EntityKind

__all__ = ["INDEX_SCHEMA_VERSION", "IndexEntry", "SearchIndex", "build_search_index"]

# The constant `index.schema.json`'s `schemaVersion` pins. It equals
# `pipeline.emit.manifest.MANIFEST_SCHEMA_VERSION` and `pipeline.emit.shard.
# SHARD_SCHEMA_VERSION` today, and the three stay independent numbers that
# happen to start at the same place -- each file's `schemaVersion` versions its
# own contract, not the build as a whole, so one of them can move alone.
INDEX_SCHEMA_VERSION = 1


class IndexEntry(BaseModel, frozen=True, populate_by_name=True):
    """One row of `index.json`, mirroring `index.schema.json`'s `$defs.indexEntry`.

    Every field but `id` carries an explicit short `Field(alias=...)`, the
    same mechanism `pipeline.normalize.entity`'s module docstring explains for
    `Entity` -- chosen there, and here, over `alias_generator` because
    `pyproject.toml` turns on the pydantic mypy plugin's
    `warn_required_dynamic_aliases`. The Python attribute names spell each key
    out in full so the code that builds an `IndexEntry` reads as English; the
    wire format stays the short keys `index.schema.json` describes.
    """

    id: str
    name: str = Field(alias="n")
    kind: EntityKind = Field(alias="k")
    aliases: tuple[str, ...] = Field(alias="a")
    shard: str = Field(alias="s")
    icon: str | None = Field(default=None, alias="i")


class SearchIndex(BaseModel, frozen=True, populate_by_name=True):
    """The whole `index.json` payload: a schema version and the sorted entry list.

    `entities` carries `min_length=1` for the same reason
    `pipeline.normalize.entity.Entity` restates its schema's conditional
    `wikiUrl` rule in Python: this pipeline constructs its models directly and
    never round-trips them through a JSON Schema validator, so
    `index.schema.json`'s `minItems: 1` binds nothing at build time unless the
    Python side states it too. An index with no entries is a search payload
    that matches every query with nothing, which is a failed build rather than
    a version of Minecraft with nothing to search.
    """

    schema_version: int = Field(default=INDEX_SCHEMA_VERSION, alias="schemaVersion")
    entities: tuple[IndexEntry, ...] = Field(min_length=1)


def build_search_index(shards: Sequence[Shard]) -> SearchIndex:
    """Return the `SearchIndex` of every entity `shards` carries, sorted by `id`.

    One `IndexEntry` per entity, across every shard, in no particular order
    until the final sort -- `shards` themselves are already `EntityKind.value`
    ordered by `assign_shards`, but that grouping has nothing to do with a
    global `id` sort across kinds, so this function re-sorts rather than
    relying on the input order to already be right. `icon` is left `None` for
    an entity with no icon; the caller serialises with `exclude_none=True`,
    matching `entity.schema.json`'s own optional fields, so the key is absent
    from the file rather than present and `null`.
    """
    entries = [
        IndexEntry(
            id=entity.id,
            name=entity.name,
            kind=entity.kind,
            aliases=entity.aliases,
            shard=shard.name,
            icon=entity.icon,
        )
        for shard in shards
        for entity in shard.entities
    ]
    entries.sort(key=lambda entry: entry.id)
    return SearchIndex(entities=tuple(entries))
