"""`BuildSnapshot`: the counts and coverage figures the regression half of the gate compares.

`pipeline.validate.regression` needs two numbers for every check in its table: what the
*previous* build looked like, and what *this* build looks like. `BuildSnapshot` is the one shape
both numbers share, so the comparison never has to reconcile two different representations of
"how many entities of kind X" -- it is the same model on both sides of every check.

## Counts and coverage only, nothing else

A snapshot carries no entity, no id, no name -- only the aggregates `pipeline.validate.regression`'s
table actually needs: a total, a per-kind breakdown, how many entities carry each required and
optional field, how many sections of each type exist, the obtain graph's producer count, and the
sprite atlas's icon count. This is a deliberate narrowing, not laziness. The regression half exists
to answer one question -- "did this build lose data it should not have" -- and a model that also
carried, say, every entity's `id` would invite a caller to build a diff of *which* entities changed,
which is a different and much larger feature than the one `TODO.md`'s Phase 3 bullet asks for.
Keeping this model to counts keeps it cheap to build from a committed `data/dist` (a scan, not a
full parse into `Entity` models) and cheap to compare (integer and float arithmetic, no set
operations over thousands of ids).

`atlas_icon_count` arrives here as a plain `int`, never as a `pipeline.emit.atlas.Atlas`, and that
narrowing is forced rather than stylistic. `pipeline.emit.write` already imports `pipeline.validate`
(for `GateCallback`) and `pipeline.validate.conformance` (for `GateDocuments`), so this module
importing `pipeline.emit.atlas` back would close an import cycle: `pipeline.emit.write` imports
`pipeline.validate`, which would import `pipeline.validate.snapshot`, which would import
`pipeline.emit.atlas` -- and the first of those three arrows already makes the cycle a fact, not a
risk. And the count is all this model ever needed anyway -- the same narrowing that already stores
`obtain_producer_count` as a bare `int` rather than holding the `ProducerIndex` itself, for the
identical reason: a snapshot answers "how many", never "which one" or "packed how".

## Two constructors, because the two sides come from two different places

`from_merge_result` builds a snapshot from the `MergeResult` and `ProducerIndex` a build already
holds in memory, mid-run, before `pipeline.emit.write.emit_build` has written anything -- this is
always the *new* side of a comparison. `from_dist` builds one by reading a committed `data/dist`
back off disk -- this is always the *baseline* side, because the committed tree already written to
the repository at HEAD *is* the previous build, per this task's own resolution of "the baseline
for 'across versions'". There is no third constructor that reads a `data/dist` mid-build, because
nothing in this pipeline needs one: the new side is always freshly merged, never freshly written,
by the time the gate runs.

`from_dist` parses raw JSON rather than validating each entity back into an `Entity` model. Two
reasons. First, half of what this function counts -- whether a key is present in the dumped
document -- is a fact about the JSON, not about the model backing it; re-validating into `Entity`
and then re-deriving key presence from the model would launder the same fact through pydantic for
no benefit. Second, and more importantly, a `data/dist` that has drifted from what `Entity` can
still validate is exactly the shape of problem `pipeline.validate.conformance` exists to catch, not
this module -- forcing every baseline read through `Entity.model_validate` would make a snapshot
read fail on the same fault the conformance half already reports in full, with a worse message and
no JSON pointer.

## Reading the baseline is the caller's problem to sequence correctly

Nothing in this module opens `data/dist` more than once or writes to it. But `from_dist` has to run
*before* `pipeline.emit.write.emit_build` overwrites the very directory this function reads --
`pipeline.validate`'s own package docstring names this the read-write hazard, and `validate_build`
is the one function in this package that actually orders the two calls correctly, by reading the
baseline the moment it is asked for a gate rather than lazily, inside the gate's own `__call__`,
which would run *after* `emit_build` had already started assembling (though not yet writing) the
new build's documents. Nothing about `BuildSnapshot` itself enforces that ordering; it is a pure
function of whatever `MergeResult`, `ProducerIndex`, or `Path` it is given.

## The three cases `from_dist` folds into one `None`

An absent `data/dist` (a clean checkout), a `data/dist` with an `entities/` directory holding no
shard files, and a `data/dist` whose shards are all empty are three different states on disk and
one state to this function: no baseline. `pipeline.validate.regression.check_regression`'s own
docstring explains why `None` always passes rather than failing -- a gate that failed to bootstrap
a fresh checkout would make the repository impossible to build from nothing, which is worse than
any regression this gate is meant to catch.
"""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from pipeline.normalize.merge import MergeResult
from pipeline.obtain.producer import ProducerIndex

__all__ = ["OPTIONAL_ENTITY_FIELDS", "REQUIRED_ENTITY_FIELDS", "BuildSnapshot"]

# `entity.schema.json`'s own `required` list, in the same order `pipeline.normalize.entity.Entity`
# declares them. Kept here rather than imported from `Entity.model_fields`, because this list is
# read against *dumped JSON documents* -- both the ones `MergeResult.entities` would dump and the
# ones a committed shard file already holds -- and a literal tuple reads the same way against
# either source, where deriving it from the live model would only work for the first.
REQUIRED_ENTITY_FIELDS: tuple[str, ...] = (
    "id",
    "kind",
    "name",
    "aliases",
    "sourceTiers",
    "sections",
)

# The three optional fields `pipeline.validate.regression`'s table tracks coverage of. `icon`,
# `blurb`, and `wikiUrl` are the only fields `Entity` ever omits from a dump (`exclude_none=True`
# drops an unset one entirely), so these three are the only fields for which "coverage" -- the
# fraction of entities that carry the key at all -- is a meaningful number to trend across builds.
OPTIONAL_ENTITY_FIELDS: tuple[str, ...] = ("wikiUrl", "blurb", "icon")

_EMPTY_PRODUCER_INDEX = ProducerIndex(by_output={})


def _empty_counts() -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """Return fresh, independent `by_kind`/`required`/`optional` accumulator dicts.

    A small helper only because both constructors below need the identical three dicts, and a
    shared literal (`dict.fromkeys(REQUIRED_ENTITY_FIELDS, 0)`, repeated in two places) is the
    kind of duplication that drifts the moment one copy gains a field the other does not.
    """
    return (dict.fromkeys(REQUIRED_ENTITY_FIELDS, 0), dict.fromkeys(OPTIONAL_ENTITY_FIELDS, 0), {})


class BuildSnapshot(BaseModel, frozen=True):
    """Counts and coverage of one build -- either just merged, or read back from a committed
    `data/dist`.

    See the module docstring for why this model carries aggregates only, and for what each of the
    two constructors below reads from.
    """

    total: int
    by_kind: Mapping[str, int]
    required_field_coverage: Mapping[str, int]
    optional_field_coverage: Mapping[str, int]
    section_type_counts: Mapping[str, int]
    obtain_producer_count: int
    atlas_icon_count: int = 0

    @classmethod
    def from_merge_result(
        cls,
        result: MergeResult,
        producer_index: ProducerIndex = _EMPTY_PRODUCER_INDEX,
        atlas_icon_count: int = 0,
    ) -> "BuildSnapshot":
        """Return the snapshot of a build that has been merged but not yet emitted.

        Reads `result.entities` directly -- the same entities `pipeline.emit.write.emit_build`
        is about to dump into shards -- and `producer_index` the same way `pipeline.emit.write`'s
        own `EmitReport.obtain_producer_count` computes it: the number of producers across every
        item id `producer_index.by_output` names, not the number of distinct items. `producer_
        index` defaults to an index over nothing, matching `emit_build`'s own default, for a
        caller that does not care about the obtain graph. `atlas_icon_count` defaults to zero the
        same way, for a caller (most of this module's own tests included) that has no atlas at
        all to report on.
        """
        required_field_coverage, optional_field_coverage, section_type_counts = _empty_counts()
        by_kind: dict[str, int] = {}

        for entity in result.entities:
            by_kind[entity.kind.value] = by_kind.get(entity.kind.value, 0) + 1
            dumped = entity.model_dump(mode="json", by_alias=True, exclude_none=True)
            for field in REQUIRED_ENTITY_FIELDS:
                if field in dumped:
                    required_field_coverage[field] += 1
            for field in OPTIONAL_ENTITY_FIELDS:
                if field in dumped:
                    optional_field_coverage[field] += 1
            for section in entity.sections:
                section_type_counts[section.type] = section_type_counts.get(section.type, 0) + 1

        return cls(
            total=len(result.entities),
            by_kind=by_kind,
            required_field_coverage=required_field_coverage,
            optional_field_coverage=optional_field_coverage,
            section_type_counts=section_type_counts,
            obtain_producer_count=sum(len(group) for group in producer_index.by_output.values()),
            atlas_icon_count=atlas_icon_count,
        )

    @classmethod
    def from_dist(cls, dist: Path) -> "BuildSnapshot | None":
        """Return the snapshot of a committed `data/dist`, or `None` when there is no baseline.

        Reads every `*.json` file under `dist/entities/` -- the same files `pipeline.emit.write`'s
        stale-file sweep scopes itself to -- `dist/obtain.json`, and `dist/sprites.json`. Returns
        `None` for any of the three shapes the module docstring's closing section names as "no
        baseline": an absent `entities/` directory, one with no shard files in it, or shards that
        between them hold no entities at all. See `pipeline.validate.regression.check_regression`'s
        own docstring for why every one of those three passes the gate rather than failing it. An
        absent `sprites.json`, or one whose `sprites` is not an object, never triggers that `None`
        path on its own -- it only zeroes `atlas_icon_count`, the same tolerant read `obtain.json`
        already gets just above it, because a build predating the atlas is still a real baseline for
        every other count this snapshot carries. Neither read defends against a file that is not
        valid JSON at all: that is a corrupted `data/dist`, not an older one, and it should surface
        as the decode error it is rather than as a silently zeroed count.
        """
        entities_dir = dist / "entities"
        if not entities_dir.is_dir():
            return None

        required_field_coverage, optional_field_coverage, section_type_counts = _empty_counts()
        by_kind: dict[str, int] = {}
        total = 0

        for shard_path in sorted(entities_dir.glob("*.json")):
            payload: Any = json.loads(shard_path.read_text(encoding="utf-8"))
            entities = payload.get("entities", ()) if isinstance(payload, dict) else ()
            for entity in entities:
                if not isinstance(entity, dict):
                    continue
                total += 1
                kind = entity.get("kind")
                if isinstance(kind, str):
                    by_kind[kind] = by_kind.get(kind, 0) + 1
                for field in REQUIRED_ENTITY_FIELDS:
                    if field in entity:
                        required_field_coverage[field] += 1
                for field in OPTIONAL_ENTITY_FIELDS:
                    if field in entity:
                        optional_field_coverage[field] += 1
                for section in entity.get("sections", ()):
                    if isinstance(section, dict) and isinstance(section.get("type"), str):
                        section_type = section["type"]
                        section_type_counts[section_type] = (
                            section_type_counts.get(section_type, 0) + 1
                        )

        if total == 0:
            return None

        obtain_producer_count = 0
        obtain_path = dist / "obtain.json"
        if obtain_path.is_file():
            obtain_payload: Any = json.loads(obtain_path.read_text(encoding="utf-8"))
            producers = (
                obtain_payload.get("producers") if isinstance(obtain_payload, dict) else None
            )
            if isinstance(producers, dict):
                obtain_producer_count = sum(
                    len(group) for group in producers.values() if isinstance(group, list)
                )

        atlas_icon_count = 0
        sprites_path = dist / "sprites.json"
        if sprites_path.is_file():
            sprites_payload: Any = json.loads(sprites_path.read_text(encoding="utf-8"))
            sprites = (
                sprites_payload.get("sprites") if isinstance(sprites_payload, dict) else None
            )
            if isinstance(sprites, dict):
                atlas_icon_count = len(sprites)

        return cls(
            total=total,
            by_kind=by_kind,
            required_field_coverage=required_field_coverage,
            optional_field_coverage=optional_field_coverage,
            section_type_counts=section_type_counts,
            obtain_producer_count=obtain_producer_count,
            atlas_icon_count=atlas_icon_count,
        )
