"""Write one build's shards, index, manifest, and obtain graph into `data/dist`, deterministically.

`pipeline.emit.shard`, `pipeline.emit.search_index`, `pipeline.emit.manifest`,
and `pipeline.emit.obtain` each build one payload in memory. This module is
the only one that opens a file for writing, and `emit_build` is the one
function this whole package exists to expose. Four rules govern everything it
does, and each one earns its own section below because getting any of them
wrong corrupts `data/dist` in a way that is invisible until a later build, a
later diff, or a later cache read notices.

## Rule 1 -- byte-for-byte determinism

Every JSON payload is serialised with `json.dumps(..., sort_keys=True,
ensure_ascii=False, separators=(",", ":"))`, encoded as UTF-8, with exactly one
trailing newline. Rebuilding from unchanged input must leave an empty `git
diff` -- `manifest.json` excepted, because `builtAt` is a clock reading and a
clock is the one honest source of non-determinism a deterministic build is
allowed to have.

The spec this task was written against asks for the file to be opened in text
mode with an explicit line-feed-only newline argument, so that
`.gitattributes`' `eol=lf` normalisation is never fighting a Windows text-mode
carriage-return-plus-line-feed translation on write. This module does
something equivalent but not identical: every payload is built as a complete
`bytes` object in memory first -- `json.dumps` with no `indent` produces one
line with no embedded raw newlines (a literal newline inside a string value
is escaped by the JSON encoder to a backslash followed by the letter n, never
to a raw line-feed byte), and exactly one line feed is appended after it --
and then written with `Path.write_bytes`. A bytes-mode write performs no
newline translation on any platform, by definition, so the single trailing
line feed this module appends is the only line ending that can ever reach the
file, on Windows or anywhere else. This reaches the same guarantee a
line-feed-only text-mode writer gives, through a mode that cannot silently
reintroduce a translation this module forgot to disable.

## Rule 2 -- the stale-file sweep is scoped to `data/dist/entities/`

`assign_shards` can write fewer shards on this build than the last one wrote:
a Minecraft version can retire IDs, `DEFAULT_SHARD_SIZE` can change, or a kind
that used to need two files can shrink to one. Whatever this build writes
under `data/dist/entities/`, every `*.json` file in that directory that is not
one of them is deleted. Left alone, a shrinking build leaves `item-7.json`
behind forever: nothing regenerates it, nothing links to it from a rebuilt
`index.json`, and it stays committed to the repository as dead weight that the
next reader has no way to tell apart from a shard the current build actually
produced.

The sweep never looks outside `data/dist/entities/`. `index.json`, `manifest.
json`, and `obtain.json` are all root-level files this module always rewrites
in full on every build, so none of the three can go stale the way a shard
can, and nothing about this module's stale-file logic ever walks `data/dist`
itself.

## Rule 3 -- shape faults raise, gaps do not

`EmitError` is raised for exactly three conditions, none of which can leave a
partial payload behind: `result.entities` is empty, `dist` exists on disk as
something other than a directory, and `shard_size` is below 1 -- the third
raised by `pipeline.emit.shard.assign_shards`, whose docstring explains why a
negative size is the one bad argument here that would otherwise drop every
entity in silence. All three are the same class of fault
`pipeline.normalize.merge`'s own `NormalizeError` guards against -- a scrape or
a merge that produced structurally nothing, not a Minecraft version that
genuinely has nothing to report.

A duplicate entity id cannot reach this module at all, so no guard against one
is written here. `MergeResult._by_id_must_match_the_entities` already refuses
to construct a `MergeResult` whose `by_id` index disagrees with its own
`entities` tuple, and that validator runs the moment a `MergeResult` is built,
long before `emit_build` ever sees one -- so a second check here would be
redundant against an invariant `pipeline.normalize.entity`'s own model already
owns.

A missing icon or blurb on one entity is not this module's fault to catch,
because it is not a fault at all in the sense `EmitError` reserves the word
for -- it is a gap `MergeReport` already recorded when the merge stage found
it. Such an entity is serialised into its shard exactly as `MergeResult`
handed it over.

## Rule 4 -- all-or-nothing

Every payload this build produces -- every shard, `index.json`, `manifest.
json`, and `obtain.json` -- is built as a complete `{Path: bytes}` mapping in
memory before this function writes a single byte to disk. An entity that
somehow fails to serialise, or a build that fails the two `EmitError` checks
above, therefore fails before `data/dist` is touched at all, rather than
leaving a mix of this build's shards and the previous build's shards on disk
with nothing to say which is which.

## The optional validation gate, and why it runs inside Rule 4's boundary, not after it

`emit_build` takes one more keyword this task adds: `gate: GateCallback | None`, defaulting to
`None`. When a caller passes one, `emit_build` calls it with every document this function has
already built -- the same shard payloads, index, manifest, and obtain graph Rule 4 was already
going to assemble in full before writing anything -- and only proceeds to its own write loop if the
gate returns without raising. This is not a second write path or a second all-or-nothing boundary;
it is one more thing that has to succeed before the write loop Rule 4 already describes is allowed
to start, so a `gate=None` caller (every test this task's own baseline already has) sees no change
in behaviour at all. `pipeline.validate`'s own package docstring owns the reasoning for what the
gate checks and why; this module does not repeat it, because this module still does not know what a
threshold is -- it only knows how to call a callable it was handed, exactly as `pipeline.emit`'s own
package docstring now states.

## The sprite atlas: one more optional argument, exactly as `pipeline.emit`'s own package docstring
## said it would be

`emit_build` takes one more keyword this task adds: `atlas: Atlas | None`, defaulting to `None`. A
`None` atlas changes nothing at all -- no `sprites.png`, no `sprites.json`, and every caller and
every test that predates this task sees identical behaviour, the same contract the `gate` keyword
above already set a precedent for. When a caller passes a real `pipeline.emit.atlas.Atlas`, two more
files join the `files` mapping Rule 4 already builds in full before any of them reaches disk:
`sprites.png`, written from `atlas.png` exactly as it arrives, and `sprites.json`, the encoded
`atlas.coordinates` payload.

`sprites.png` is written raw, never through `_encode`. `_encode` exists for Rule 1's JSON
determinism -- a UTF-8 text payload with exactly one trailing line feed -- and a PNG is binary: it
already carries its own fixed 8-byte signature and its own internal length-prefixed chunks, so there
is no trailing newline to add and no line-ending translation to protect against by writing it as
`bytes` in the first place, which `Atlas.png` already is. `sprites.json` gets the ordinary
treatment: `atlas.coordinates.model_dump(mode="json", by_alias=True, exclude_none=True)`, encoded by
`_encode`, and included in the `gate` call the same way every other document already is.

Rule 2's stale-file sweep stays scoped to `data/dist/entities/`, unchanged by this task. An
`atlas=None` build therefore leaves any `sprites.png`/`sprites.json` an earlier, atlas-writing build
left on disk completely alone -- it neither rewrites them nor deletes them, because this module has
no way to tell "this build has no atlas" apart from "this build does not know its dist directory
already holds sprite files" without reading state this function otherwise never reads. The same
answer applies here as to the gate: nothing in this module sweeps a file it did not itself decide to
write.
"""

import gzip
import json
from pathlib import Path

from pydantic import BaseModel

from pipeline.emit import EmitError
from pipeline.emit.atlas import ATLAS_IMAGE_NAME, Atlas
from pipeline.emit.manifest import BuildInfo, build_manifest
from pipeline.emit.obtain import build_obtain_graph
from pipeline.emit.search_index import build_search_index
from pipeline.emit.shard import (
    DEFAULT_SHARD_SIZE,
    SHARD_SCHEMA_VERSION,
    Shard,
    assign_shards,
)
from pipeline.normalize.entity import EntityKind
from pipeline.normalize.merge import MergeResult
from pipeline.obtain.producer import ProducerIndex
from pipeline.validate import GateCallback
from pipeline.validate.conformance import GateDocuments

__all__ = [
    "DEFAULT_DIST_PATH",
    "DEFAULT_REPORT_PATH",
    "EmitReport",
    "ShardSummary",
    "emit_build",
    "write_report",
]

# Where `emit_build` writes by default. A caller may redirect it -- a test
# always does, into `tmp_path` -- but the default is the one path CLAUDE.md
# and `tests/test_repo_invariants.py` both name as the site's static payload.
DEFAULT_DIST_PATH = Path("data") / "dist"

# Where `emit_build`'s own report lands by default, matching `pipeline.
# normalize.merge.DEFAULT_REPORT_PATH`'s precedent: `data/reports/` is
# gitignored, and the writer takes an explicit path so a future CLI can
# redirect it without editing this module.
DEFAULT_REPORT_PATH = Path("data") / "reports" / "emit-report.json"

# `emit_build`'s default for `producer_index`: an index over no producers at
# all, so a caller that only cares about entities, the search index, and the
# manifest -- most of this package's own tests -- does not have to construct
# one just to call this function. `pipeline.normalize.merge` used to hold an
# identical module-level constant for the identical reason, before this task
# moved the obtain graph out of the merge stage and into this one; see
# `pipeline.emit.obtain`'s module docstring for why it now belongs here.
_EMPTY_PRODUCER_INDEX = ProducerIndex(by_output={})

# The name every shard file carries under `data/dist/entities/`, and the glob
# the stale-file sweep reads against that same directory.
_ENTITIES_DIR_NAME = "entities"
_INDEX_FILE_NAME = "index.json"
_MANIFEST_FILE_NAME = "manifest.json"
_OBTAIN_FILE_NAME = "obtain.json"

# The two sprite-atlas file names. `_SPRITES_IMAGE_NAME` is bound to `pipeline.emit.atlas.
# ATLAS_IMAGE_NAME` rather than repeating the string `"sprites.png"` a second time -- one place
# owns that fact, per `pipeline.emit.shard`'s own D2 section on why a shard's name is computed
# once and never recomputed by a caller. `_SPRITES_MAP_NAME` has no equivalent constant to import:
# no other module names the coordinate map's own file, the same way none names `index.json`'s.
_SPRITES_IMAGE_NAME = ATLAS_IMAGE_NAME
_SPRITES_MAP_NAME = "sprites.json"


class ShardSummary(BaseModel, frozen=True):
    """How one shard came out of one build, so a report reads without reopening the file."""

    name: str
    kind: EntityKind
    entity_count: int
    bytes: int


class EmitReport(BaseModel, frozen=True):
    """What one `emit_build` call wrote, and what it swept away.

    The `atlas_*` fields default to `None`/`0` so a build with no atlas -- every test and every
    build this repository has run before this task -- constructs a report exactly as it always
    has. `atlas_frame_count` is `Atlas.frame_count`: the number of distinct `File:` frames packed,
    which is usually smaller than the number of icon keys the atlas resolves, because more than one
    entity's icon can point at the same packed frame.
    """

    entity_count: int
    shards: tuple[ShardSummary, ...]
    index_bytes: int
    index_gzipped_bytes: int
    obtain_producer_count: int
    obtain_bytes: int
    obtain_gzipped_bytes: int
    atlas_frame_count: int = 0
    atlas_png_bytes: int = 0
    atlas_map_bytes: int = 0
    atlas_map_gzipped_bytes: int = 0
    removed: tuple[str, ...] = ()


def _encode(document: object) -> bytes:
    """Return the deterministic, one-newline-terminated JSON bytes of `document`.

    See the module docstring's Rule 1 for why this is built as `bytes` rather
    than written through a text-mode file handle.
    """
    text = json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"{text}\n".encode()


def _shard_payload(shard: Shard) -> dict[str, object]:
    """Return the `shard.schema.json` document of one `Shard`.

    Each `Entity` is serialised with `model_dump(mode="json", by_alias=True,
    exclude_none=True)`: `by_alias=True` writes the schema's camelCase field
    names rather than `Entity`'s Python attribute names, and `exclude_none=True`
    drops an unset optional (`icon`, `blurb`, `wikiUrl`) rather than writing it
    as an explicit JSON `null` that `entity.schema.json`'s closed objects do
    not declare a type for.
    """
    return {
        "schemaVersion": SHARD_SCHEMA_VERSION,
        "entities": [
            entity.model_dump(mode="json", by_alias=True, exclude_none=True)
            for entity in shard.entities
        ],
    }


def emit_build(
    result: MergeResult,
    build: BuildInfo,
    *,
    dist: Path = DEFAULT_DIST_PATH,
    shard_size: int = DEFAULT_SHARD_SIZE,
    producer_index: ProducerIndex = _EMPTY_PRODUCER_INDEX,
    gate: GateCallback | None = None,
    atlas: Atlas | None = None,
) -> EmitReport:
    """Write `result`, `build`, `producer_index`, and `atlas` into `dist`, and return a report of
    what was written.

    `producer_index` is `pipeline.obtain.producer.ProducerIndex.merge`'s
    output over every `pipeline.obtain` adapter a build ran; it defaults to
    an index over no producers, which writes an `obtain.json` with an empty
    `producers` map rather than forcing a caller who does not care about the
    obtain graph to construct one. See `pipeline.emit.obtain`'s module
    docstring for why an empty graph is not a build fault the way an empty
    `SearchIndex` is.

    `gate` defaults to `None`, in which case this function behaves exactly as
    it always has. When a caller passes one, it is called once every document
    this build is about to write already exists in memory and before any of
    them reaches disk -- see the module docstring's validation-gate section.
    A gate that raises leaves `dist` exactly as it was; this function adds no
    guard of its own around whatever the gate raises.

    `atlas` defaults to `None`, in which case this function writes no `sprites.png` and no
    `sprites.json` and behaves exactly as it always has. When a caller passes a
    `pipeline.emit.atlas.Atlas`, both files join the write loop below -- see the module
    docstring's sprite-atlas section for exactly what each one is written from.

    Raises `EmitError` for a `result` with no entities, a `dist` that exists
    and is not a directory, or a `shard_size` below 1. All three raise before
    anything is written. See the module docstring's four rules for everything
    else this function guarantees: determinism, the stale-shard sweep, which
    faults raise, and the all-or-nothing write.
    """
    if not result.entities:
        raise EmitError(
            "emit_build was given a MergeResult with no entities. An empty merge is a failed "
            "build, not a version of Minecraft with nothing to ship."
        )
    if dist.exists() and not dist.is_dir():
        raise EmitError(
            f"{dist} exists and is not a directory. emit_build refuses to write a site payload "
            f"where a plain file already sits."
        )

    shards = assign_shards(result.entities, shard_size=shard_size)
    search_index = build_search_index(shards)
    manifest = build_manifest(build)
    obtain_graph = build_obtain_graph(producer_index)

    # Every payload below is built once, as the same plain dict `gate` sees and `_encode` then
    # serialises -- never rebuilt a second time for encoding, so a gate that inspects a document
    # and the bytes this function goes on to write can never drift from one another.
    shard_payloads = {shard.name: _shard_payload(shard) for shard in shards}
    index_payload = search_index.model_dump(mode="json", by_alias=True, exclude_none=True)
    manifest_payload = manifest.model_dump(mode="json", by_alias=True, exclude_none=True)
    obtain_payload = obtain_graph.model_dump(mode="json", by_alias=True, exclude_none=True)
    atlas_map_payload = (
        atlas.coordinates.model_dump(mode="json", by_alias=True, exclude_none=True)
        if atlas is not None
        else None
    )

    if gate is not None:
        gate(
            GateDocuments(
                shards=shard_payloads,
                index=index_payload,
                manifest=manifest_payload,
                obtain=obtain_payload,
                atlas=atlas_map_payload,
            )
        )

    entities_dir = dist / _ENTITIES_DIR_NAME
    files: dict[Path, bytes] = {}
    shard_bytes: dict[str, bytes] = {}
    for shard in shards:
        encoded = _encode(shard_payloads[shard.name])
        shard_bytes[shard.name] = encoded
        files[entities_dir / f"{shard.name}.json"] = encoded

    index_bytes = _encode(index_payload)
    files[dist / _INDEX_FILE_NAME] = index_bytes

    manifest_bytes = _encode(manifest_payload)
    files[dist / _MANIFEST_FILE_NAME] = manifest_bytes

    obtain_bytes = _encode(obtain_payload)
    files[dist / _OBTAIN_FILE_NAME] = obtain_bytes

    # The sprite atlas: two more files, only when a caller passed one. `atlas.png` is already
    # `bytes` and is never run through `_encode` -- see the module docstring's sprite-atlas
    # section for why a PNG has no trailing newline to add and no JSON determinism rule to keep.
    atlas_map_bytes = b""
    if atlas is not None and atlas_map_payload is not None:
        files[dist / _SPRITES_IMAGE_NAME] = atlas.png
        atlas_map_bytes = _encode(atlas_map_payload)
        files[dist / _SPRITES_MAP_NAME] = atlas_map_bytes

    # Rule 2: every `*.json` under `entities/` that this build did not just
    # decide to write is stale. Computed before any write, so `removed` in the
    # returned report always matches what the sweep below actually deletes.
    kept_shard_paths = {entities_dir / f"{shard.name}.json" for shard in shards}
    stale = (
        sorted(
            path
            for path in entities_dir.glob("*.json")
            if path.is_file() and path not in kept_shard_paths
        )
        if entities_dir.is_dir()
        else []
    )

    # Rule 4: every payload above is already built. Nothing past this point can
    # fail for a reason rooted in the data, so the write loop below is the
    # first moment this function touches the filesystem.
    dist.mkdir(parents=True, exist_ok=True)
    entities_dir.mkdir(parents=True, exist_ok=True)
    for path, data in files.items():
        path.write_bytes(data)
    for path in stale:
        path.unlink()

    # `mtime=0` for the identical reason `index_gzipped_bytes` below already uses it: a
    # deterministic figure over a build that writes no atlas at all is `0`, not the gzip header
    # of an empty payload.
    atlas_map_gzipped_bytes = (
        len(gzip.compress(atlas_map_bytes, mtime=0)) if atlas_map_bytes else 0
    )

    return EmitReport(
        entity_count=len(result.entities),
        shards=tuple(
            ShardSummary(
                name=shard.name,
                kind=shard.kind,
                entity_count=len(shard.entities),
                bytes=len(shard_bytes[shard.name]),
            )
            for shard in shards
        ),
        index_bytes=len(index_bytes),
        # `mtime=0` keeps the compressed size deterministic: gzip's header
        # otherwise embeds the wall-clock second of compression, which would
        # make this figure -- and the byte-for-byte determinism rule above --
        # differ between two runs over identical input.
        index_gzipped_bytes=len(gzip.compress(index_bytes, mtime=0)),
        obtain_producer_count=sum(len(group) for group in obtain_graph.producers.values()),
        obtain_bytes=len(obtain_bytes),
        obtain_gzipped_bytes=len(gzip.compress(obtain_bytes, mtime=0)),
        atlas_frame_count=atlas.frame_count if atlas is not None else 0,
        atlas_png_bytes=len(atlas.png) if atlas is not None else 0,
        atlas_map_bytes=len(atlas_map_bytes),
        atlas_map_gzipped_bytes=atlas_map_gzipped_bytes,
        removed=tuple(path.relative_to(dist).as_posix() for path in stale),
    )


def write_report(report: EmitReport, path: Path = DEFAULT_REPORT_PATH) -> None:
    """Write `report` to `path` as indented JSON, creating parent directories as needed.

    Copies `pipeline.normalize.merge.write_report`'s shape exactly.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    document = report.model_dump(mode="json")
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
