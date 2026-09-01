"""Write one build's shards, index, and manifest into `data/dist`, deterministically.

`pipeline.emit.shard`, `pipeline.emit.search_index`, and `pipeline.emit.
manifest` each build one payload in memory. This module is the only one that
opens a file for writing, and `emit_build` is the one function this whole
package exists to expose. Four rules govern everything it does, and each one
earns its own section below because getting any of them wrong corrupts
`data/dist` in a way that is invisible until a later build, a later diff, or a
later cache read notices.

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

The sweep never looks outside `data/dist/entities/`. `index.json` and
`manifest.json` are both root-level files this module always rewrites in
full on every build, so neither one can go stale the way a shard can, and
nothing about this module's stale-file logic ever walks `data/dist` itself.

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

Every payload this build produces -- every shard, `index.json`, and
`manifest.json` -- is built as a complete `{Path: bytes}` mapping in memory
before this function writes a single byte to disk. An entity that somehow
fails to serialise, or a build that fails the two `EmitError` checks above,
therefore fails before `data/dist` is touched at all, rather than leaving a
mix of this build's shards and the previous build's shards on disk with
nothing to say which is which.
"""

import gzip
import json
from pathlib import Path

from pydantic import BaseModel

from pipeline.emit import EmitError
from pipeline.emit.manifest import BuildInfo, build_manifest
from pipeline.emit.search_index import build_search_index
from pipeline.emit.shard import (
    DEFAULT_SHARD_SIZE,
    SHARD_SCHEMA_VERSION,
    Shard,
    assign_shards,
)
from pipeline.normalize.entity import EntityKind
from pipeline.normalize.merge import MergeResult

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

# The name every shard file carries under `data/dist/entities/`, and the glob
# the stale-file sweep reads against that same directory.
_ENTITIES_DIR_NAME = "entities"
_INDEX_FILE_NAME = "index.json"
_MANIFEST_FILE_NAME = "manifest.json"


class ShardSummary(BaseModel, frozen=True):
    """How one shard came out of one build, so a report reads without reopening the file."""

    name: str
    kind: EntityKind
    entity_count: int
    bytes: int


class EmitReport(BaseModel, frozen=True):
    """What one `emit_build` call wrote, and what it swept away."""

    entity_count: int
    shards: tuple[ShardSummary, ...]
    index_bytes: int
    index_gzipped_bytes: int
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
) -> EmitReport:
    """Write `result` and `build` into `dist`, and return a report of what was written.

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

    entities_dir = dist / _ENTITIES_DIR_NAME
    files: dict[Path, bytes] = {}
    shard_bytes: dict[str, bytes] = {}
    for shard in shards:
        encoded = _encode(_shard_payload(shard))
        shard_bytes[shard.name] = encoded
        files[entities_dir / f"{shard.name}.json"] = encoded

    index_bytes = _encode(search_index.model_dump(mode="json", by_alias=True, exclude_none=True))
    files[dist / _INDEX_FILE_NAME] = index_bytes

    manifest_bytes = _encode(
        manifest.model_dump(mode="json", by_alias=True, exclude_none=True)
    )
    files[dist / _MANIFEST_FILE_NAME] = manifest_bytes

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
        removed=tuple(path.relative_to(dist).as_posix() for path in stale),
    )


def write_report(report: EmitReport, path: Path = DEFAULT_REPORT_PATH) -> None:
    """Write `report` to `path` as indented JSON, creating parent directories as needed.

    Copies `pipeline.normalize.merge.write_report`'s shape exactly.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    document = report.model_dump(mode="json")
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
