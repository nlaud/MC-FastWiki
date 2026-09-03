"""Turn a `MergeResult` into the static payload the web app ships: `pipeline.emit.emit_build`.

`pipeline.normalize.merge_entities` builds one `Entity` per registry ID and a
report of the merge that produced them. Nothing before this package writes a
single file to disk -- every earlier stage returns an in-memory model, tested
against fixtures built in the test process, exactly as `pipeline.normalize`'s
own package docstring describes for the stage before it. `pipeline.emit` is
where that changes: it is the one stage whose job is specifically to write
`data/dist`, the directory `.gitattributes` marks `linguist-generated` and
CLAUDE.md names as the pure-static payload the web build reads and nothing
else.

Three modules do the actual work, and each one owns one decision named in full
in its own docstring: `pipeline.emit.shard` decides which entities share a
file and names each file it decides on; `pipeline.emit.search_index` turns
that assignment into the flat, `id`-sorted `index.json` payload Phase 4 loads
at boot; `pipeline.emit.manifest` builds the small `manifest.json` that names
the build itself. `pipeline.emit.write` is where those three meet the
filesystem: it is the only module in this package that opens a file for
writing, and its own docstring names the four rules that writing has to keep
-- byte-for-byte determinism, a stale-file sweep scoped to `data/dist/
entities/`, which faults raise and which do not, and an all-or-nothing build.

**Scope.** This task builds the search index, the entity shards, and the
manifest. Two things named in the same `TODO.md` bullet are deliberately not
here. The sprite atlas is not built yet -- `emit_build` writes no `sprites.png`
and no coordinate map, and `TODO.md` keeps that half of the bullet open rather
than checked, because `Entity.icon` already carries a stable `"<family>:
<sprite_id>"` key (see `pipeline.normalize.merge._resolve_entity_icon`'s own
docstring) that a later atlas packer can resolve without this package
changing at all -- adding the atlas is one more argument to `emit_build`, not
a rewrite of it. There is also no `python -m pipeline` entry point yet; nothing
calls `emit_build` outside a test until that CLI exists, which is its own open
`TODO.md` bullet. Nor does this package decide the Phase 3 validation gate's
policy `TODO.md` describes separately -- the threshold on how much of a build
is acceptable belongs beside the report it reads (`pipeline.validate`), not
beside the stage that writes files from whatever report it was handed. What
this package does own, as of a later task, is the one call site: `pipeline.
emit.write.emit_build` takes an optional gate callback and calls it with the
documents this module already assembled, after they exist in memory and
before any of them reaches disk, so a gate that refuses a build can still
refuse it before `data/dist` changes at all. That call is plumbing, not a
policy decision -- a `None` gate, every caller before that task, changes
nothing about what this module does; the one caller that passes a real gate
is the one deciding whether to fail a build, and this module is only deciding
when, in its own sequence, to ask.

`EmitError` is this package's shape-level fault, matching `NormalizeError`,
`EnrichError`, and `ExtractError` of the stages before it: reserved for a
`MergeResult` with no entities, or a `dist` path that exists and is not a
directory. It is never raised for a per-entity gap -- a missing icon or blurb
is `MergeReport`'s concern, already recorded by the stage that found it, and
`emit_build` writes such an entity out unchanged rather than treating an
absence it did not cause as a fault of its own.
"""

__all__ = ["EmitError", "emit_build"]


class EmitError(Exception):
    """The emit stage was asked to write data it cannot trust the shape of.

    Reserved for a shape fault: a `MergeResult` with no entities at all, or a
    `dist` path that exists on disk and is not a directory. It is not raised
    for one entity's missing icon or blurb -- `pipeline.normalize.merge`'s own
    `MergeReport` already carries those, and `emit_build` writes such an
    entity out unchanged, the same distinction `NormalizeError`, `EnrichError`,
    and `ExtractError` each draw for the stage before this one.
    """


# Imported after `EmitError` is defined, not at the top of the file: `pipeline.
# emit.write` imports `EmitError` from this package to raise it, so this
# package's own `EmitError` has to exist as an attribute of the `pipeline.emit`
# module before that submodule is loaded. Swapping the two lines would make
# `write.py`'s `from pipeline.emit import EmitError` fail with a circular-import
# error, because the partially-initialised `pipeline.emit` module would not
# have set the name yet.
from pipeline.emit.write import emit_build  # noqa: E402
