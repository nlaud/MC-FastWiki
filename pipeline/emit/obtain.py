"""Build the `data/dist/obtain.json` payload from a build's `ProducerIndex`.

`pipeline.obtain.tree.build_obtain_tree` used to be a step of `pipeline.
normalize.merge`: the merge stage walked every entity's producers into a
`RecipeTree` and wrote the finished tree into that entity's own shard. That
was measured against the real 26.2 data on 2026-09-01 and found to cost far
more than it was worth. Materialising a tree per entity, depth-capped at 4,
came to 73.8 MB raw and 4.1 MB gzipped across the whole build -- and it still
lost information, because the deepest real producer chain in the graph is 15
levels (`minecraft:chiseled_resin_bricks`, height 16), a depth no cap of 4
ever reaches. Shipping the flat producer graph instead -- every one of the
4001 producers the same build finds, with no depth cap at all -- costs 1.05 MB
raw and 0.07 MB gzipped: 70x smaller, and strictly deeper. The 18x gzip ratio
the materialised trees showed was never real content; it was the same
subtrees written into hundreds of shards, compressing well only because they
repeated.

So the tree is no longer something the pipeline builds and ships. It is
something the web app assembles at render time by walking this file, using
`pipeline.obtain.tree.build_obtain_tree` itself as the reference
implementation of how to do it -- see that module's own docstring for the
argument that its role changed but its behaviour did not. This module's only
job is the one `build_obtain_graph` name: take the `ProducerIndex` a build
already assembled from every `pipeline.obtain` adapter, and turn it into the
flat, deterministic JSON payload the web app fetches once, the moment a
player first opens an item's Obtaining tab, and keeps in memory for the rest
of the session.

## Shape, following `pipeline.emit.search_index`

`search_index.py` is the nearest precedent in this package for a payload the
browser downloads whole, and this module follows its shape closely: an
`OBTAIN_SCHEMA_VERSION` constant, a `Field(alias="schemaVersion")` schema
version field, and `build_obtain_graph(index: ProducerIndex) -> ObtainGraph`
as the one function this module exists to expose.

`search_index.py`'s own reason for a compact wire format is Phase 4's 16
ms-per-keystroke budget against the whole file -- `index.json` is parsed once
and then read on every character a player types. `obtain.json` is read far
less often, once per item a player actually opens the Obtaining tab for
rather than once per keystroke, but it is still fetched over the network as
one flat file with no depth cap, so the same style of savings is worth
taking for the same reason: a smaller file downloads and parses faster with
no cost to what it can express. This module follows `search_index.py`'s own
convention rather than inventing a third one -- every field but the ones a
person is unlikely to guess wrong (`schemaVersion`, `producers`) gets a
short key, and each short key's own schema description in `obtain.schema.
json` names the long field it stands for, the same way `index.schema.json`'s
`indexEntry` does. The letters themselves do not reuse `search_index.py`'s
(`n`, `k`, `a`, `s`, `i`) beyond `i` for `item`, because the two payloads
describe different concepts and forcing a borrowed letter onto an unrelated
field would be a coincidence dressed up as a convention. What is reused is
the *policy*: the wire key is short, the Python attribute name is spelled
out in full, and `Field(alias=...)` -- never `alias_generator` -- is the only
mechanism, for the identical `warn_required_dynamic_aliases` reason `pipeline.
normalize.entity`'s own module docstring gives.

## Why the graph carries no display name, and no `EntityRef`

`pipeline.normalize.merge`'s removed `RecipeTree` attachment used to convert
every `pipeline.obtain.tree.TreeInput`/`ObtainNode` into an `EntityRef` --
an id paired with the entity's own display name -- because a shard is read on
its own, with nothing else guaranteed to be loaded yet, so a rendered tree
node needed to carry its own label. `obtain.json` has no such constraint: the
web app that walks this file already has `index.json` loaded, and every item
id this graph names is, by construction, an id `pipeline.obtain`'s adapters
read out of a real mcmeta registry -- so the renderer looks the name up
itself rather than this file repeating it once per appearance of the same
id across however many producers reference it. This is where most of the
70x size difference actually comes from: not the depth cap, but the display
name that used to be copied onto every single node of every single tree.

## Determinism

`pipeline.emit.write` holds the whole build to byte-for-byte reproduction
between two runs, and this module keeps that guarantee the same way `pipeline.
emit.search_index` does: nothing here reads `index.by_output` and trusts its
key order to already be right. `build_obtain_graph` sorts by item id before
building the returned mapping, and within one item id, `ProducerIndex.
producers_of`'s own `(method, output id, source_id)` order -- fixed once, in
`ProducerIndex.from_producers`, per that module's own docstring -- is kept
unchanged. `pipeline.emit.write._encode`'s `json.dumps(..., sort_keys=True)`
would paper over a mis-ordered top-level mapping regardless, but a producer
list is a JSON array, which `sort_keys` does not touch, so keeping that order
right here is the part that actually matters.

## The round trip, and why this module also builds a `ProducerIndex` back

Shipping the graph instead of the tree is only safe if the tree the web app
assembles from `obtain.json` is the same tree `pipeline.obtain.tree.
build_obtain_tree` would have built from the in-memory `ProducerIndex` --
otherwise this whole restructuring would be trading a real feature for a
smaller file that quietly renders something else. `producer_index_from_graph`
is the other half of that proof: it takes a parsed `ObtainGraph` -- built the
same way a browser would build one, from the same JSON bytes `pipeline.emit.
write` writes -- and reconstructs a `ProducerIndex` from it. Nothing in the
web app calls this function; it exists so `tests/test_emit_obtain.py` can
serialise a `ProducerIndex` through `build_obtain_graph`, parse the result
back with `ObtainGraph.model_validate`, rebuild a `ProducerIndex` with this
function, and assert that `build_obtain_tree` gives byte-identical trees from
the original index and the round-tripped one, at several depths, over a
fixture built specifically to exercise crafting, brewing, a tag input, a
cycle, and a diamond. That test is the one the user's own condition on this
restructuring asked for: "just confirm that we can make the same obtaining
tree in the end."
"""

from collections.abc import Mapping

from pydantic import BaseModel, Field

from pipeline.obtain.chests import ChestSource
from pipeline.obtain.producer import (
    ObtainMethod,
    Producer,
    ProducerIndex,
    ProducerInput,
    ProducerOutput,
)

__all__ = [
    "OBTAIN_SCHEMA_VERSION",
    "ChestSource",
    "ObtainGraph",
    "ObtainProducer",
    "ObtainProducerInput",
    "build_obtain_graph",
    "load_merged_sources",
    "producer_index_from_graph",
]

# The constant `obtain.schema.json`'s `schemaVersion` pins. Its own number
# line is independent of `INDEX_SCHEMA_VERSION`, `MANIFEST_SCHEMA_VERSION`,
# and `SHARD_SCHEMA_VERSION` -- see `pipeline.emit.search_index`'s own
# docstring for why the four payloads each version their own contract rather
# than sharing one number.
OBTAIN_SCHEMA_VERSION = 1


class ObtainProducerInput(BaseModel, frozen=True, populate_by_name=True):
    """One ingredient slot of an `ObtainProducer`, mirroring `pipeline.obtain.producer.
    ProducerInput`.

    Exactly one of `item` or `tag` is set, matching `ProducerInput._exactly_
    one_of_item_or_tag`'s own rule -- this model does not re-validate that
    rule itself, because it is only ever built from an already-valid
    `ProducerInput` by `build_obtain_graph`, or from a JSON payload this same
    module wrote, and `producer_index_from_graph` hands whichever one it
    reads straight to `ProducerInput`'s own constructor, which enforces the
    rule on the way back.
    """

    item: str | None = Field(default=None, alias="i")
    tag: str | None = Field(default=None, alias="t")
    count: int = Field(default=1, alias="c")
    members: tuple[str, ...] = Field(default=(), alias="mb")


class ObtainProducer(BaseModel, frozen=True, populate_by_name=True):
    """One way to produce an item, mirroring `pipeline.obtain.producer.Producer`.

    Carries no `item` field of its own for what it produces -- unlike
    `Producer.output`, whose `item` always equals the key this `ObtainProducer`
    sits under in `ObtainGraph.producers`, so repeating it here would be
    redundant data written once per producer instead of once per item.
    `count` is `Producer.output.count`, the one part of `ProducerOutput` that
    is not implied by the key.

    `chance`, `count_max` and `per_attempt` are the three odds fields, carried
    through unchanged and unrounded. They are absent together on a producer
    whose outcome no upstream source states odds for -- see `pipeline.obtain.
    producer.Producer` for which shapes forfeit them and why. Rounding is left
    to the renderer, because the payload is read by a display that wants one
    decimal place and by a test that wants the exact figure, and a payload that
    has already rounded cannot serve the second.
    """

    method: ObtainMethod = Field(alias="m")
    count: int = Field(default=1, alias="c")
    source_id: str = Field(alias="src")
    station: str | None = Field(default=None, alias="st")
    note: str | None = Field(default=None, alias="nt")
    chance: float | None = Field(default=None, alias="ch")
    count_max: int | None = Field(default=None, alias="cx")
    per_attempt: float | None = Field(default=None, alias="pa")
    inputs: tuple[ObtainProducerInput, ...] = Field(default=(), alias="in")
    grid: tuple[int | None, ...] | None = Field(default=None, alias="g")
    grid_width: int | None = Field(default=None, alias="gw")
    grid_height: int | None = Field(default=None, alias="gh")


class ObtainGraph(BaseModel, frozen=True, populate_by_name=True):
    """The whole `obtain.json` payload: a schema version, every producer keyed by output
    item id, and curated sources metadata.

    Unlike `pipeline.emit.search_index.SearchIndex.entities`, `producers`
    carries no `min_length`. An empty `SearchIndex` is a search payload that
    matches every query with nothing, which that module's own docstring
    calls a failed build rather than a version of Minecraft with nothing to
    search. An empty `ObtainGraph` is not the same kind of failure: a build
    over test fixtures with no recipe, loot, or brewing data wired up
    genuinely has no producers to report, and `pipeline.emit.write.
    emit_build`'s own default `producer_index` -- an index over nothing --
    exists precisely so a caller that only cares about entities, the search
    index, and the manifest is not forced to construct a `ProducerIndex`
    just to call it. Refusing an empty graph here would turn that default
    into a build-time failure it was never meant to be.
    """

    schema_version: int = Field(default=OBTAIN_SCHEMA_VERSION, alias="schemaVersion")
    producers: Mapping[str, tuple[ObtainProducer, ...]]
    sources: Mapping[str, ChestSource] = Field(default_factory=dict)


def _to_obtain_input(input_spec: ProducerInput) -> ObtainProducerInput:
    return ObtainProducerInput(
        item=input_spec.item,
        tag=input_spec.tag,
        count=input_spec.count,
        members=input_spec.members,
    )


def _to_obtain_producer(producer: Producer) -> ObtainProducer:
    return ObtainProducer(
        method=producer.method,
        count=producer.output.count,
        source_id=producer.source_id,
        station=producer.station,
        note=producer.note,
        chance=producer.chance,
        count_max=producer.count_max,
        per_attempt=producer.per_attempt,
        inputs=tuple(_to_obtain_input(one_input) for one_input in producer.inputs),
        grid=producer.grid,
        grid_width=producer.grid_width,
        grid_height=producer.grid_height,
    )


def load_merged_sources(
    chests: Mapping[str, ChestSource] | None = None,
    loot: Mapping[str, ChestSource] | None = None,
) -> dict[str, ChestSource]:
    """Merge chest sources, loot sources, and curated producer sources into one mapping."""
    merged_sources: dict[str, ChestSource] = {}
    if chests is not None:
        merged_sources.update(chests)
    else:
        try:
            from pipeline.obtain.chests import DEFAULT_CHEST_SOURCES_PATH, load_chest_sources

            if DEFAULT_CHEST_SOURCES_PATH.is_file():
                merged_sources.update(load_chest_sources(DEFAULT_CHEST_SOURCES_PATH))
        except Exception:
            pass

    if loot is not None:
        merged_sources.update(loot)
    else:
        try:
            from pipeline.obtain.loot import DEFAULT_LOOT_SOURCES_PATH, load_loot_sources

            if DEFAULT_LOOT_SOURCES_PATH.is_file():
                merged_sources.update(load_loot_sources(DEFAULT_LOOT_SOURCES_PATH))
        except Exception:
            pass

    try:
        from pipeline.obtain.curated import DEFAULT_PRODUCERS_PATH, load_curated_sources

        if DEFAULT_PRODUCERS_PATH.is_file():
            merged_sources.update(load_curated_sources(DEFAULT_PRODUCERS_PATH))
    except Exception:
        pass

    return merged_sources


def build_obtain_graph(
    index: ProducerIndex, sources: Mapping[str, ChestSource] | None = None
) -> ObtainGraph:
    """Return the `ObtainGraph` of every producer `index` holds, keyed by output item id.

    Sorted by item id -- see the module docstring's determinism section for
    why this function does that explicitly rather than trusting `index.by_
    output`'s own iteration order, and for why the order of producers
    *within* one item id is left exactly as `index.producers_of` already
    returns it.
    """
    if sources is None:
        sources = load_merged_sources()

    sorted_sources = {k: sources[k] for k in sorted(sources)}
    producers = {
        item_id: tuple(_to_obtain_producer(producer) for producer in index.producers_of(item_id))
        for item_id in sorted(index.by_output)
    }
    return ObtainGraph(producers=producers, sources=sorted_sources)


def _from_obtain_input(input_spec: ObtainProducerInput) -> ProducerInput:
    return ProducerInput(
        item=input_spec.item,
        tag=input_spec.tag,
        count=input_spec.count,
        members=input_spec.members,
    )


def producer_index_from_graph(graph: ObtainGraph) -> ProducerIndex:
    """Return the `ProducerIndex` that `graph` encodes.

    The reverse of `build_obtain_graph`. See the module docstring's "round
    trip" section for why this function exists at all -- it is not part of
    the web app's own reading of `obtain.json`, it is the other half of the
    proof that shipping the graph instead of the tree loses nothing
    `pipeline.obtain.tree.build_obtain_tree` needs. `ProducerIndex.from_
    producers` re-sorts by `(method, output item id, source_id)` regardless
    of the order this function hands it producers in, so the result is
    identical to the original index whether or not `graph.producers` itself
    came back from a JSON parse in the same key order it was written in.
    """
    producers = [
        Producer(
            method=entry.method,
            output=ProducerOutput(item=item_id, count=entry.count),
            inputs=tuple(_from_obtain_input(one_input) for one_input in entry.inputs),
            source_id=entry.source_id,
            station=entry.station,
            note=entry.note,
            chance=entry.chance,
            count_max=entry.count_max,
            per_attempt=entry.per_attempt,
            grid=entry.grid,
            grid_width=entry.grid_width,
            grid_height=entry.grid_height,
        )
        for item_id, group in graph.producers.items()
        for entry in group
    ]
    return ProducerIndex.from_producers(producers)
