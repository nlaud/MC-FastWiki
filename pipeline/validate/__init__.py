"""Refuse a build before `pipeline.emit.write.emit_build` writes a single byte of it.

`pipeline.normalize.merge` builds one `Entity` per registry ID and never fails a build over a
per-entity gap -- that module's own docstring is explicit that a threshold on how much of a merge
is acceptable belongs to "Phase 3's validation gate," not to the merge itself. `pipeline.emit`
agreed from the other side: its own module docstring used to list the validation gate among the
things it deliberately does not do, because deciding whether a build is good enough is a policy
question and `pipeline.emit`'s job is to write whatever it is handed. This package is where that
policy question finally gets answered. It sits between `pipeline.normalize` (stage 7) and
`pipeline.emit` (stage 8) in `pipeline.cli.build.run_build`'s own stage order, and it has exactly
one job: decide whether the build stage 7 produced is good enough to let stage 8 write it.

## Two independent halves, and why neither one is optional

**Conformance** (`pipeline.validate.conformance`) asks whether every document this build is about
to write is *shaped* right -- does this entity satisfy `entity.schema.json`, does this shard
satisfy `shard.schema.json`, and so on for the index, the obtain graph, and the manifest. It is a
per-document check with no memory of any earlier build: a single malformed `wikiUrl` fails it,
regardless of whether the build that produced it also happens to be the very first one this
repository has ever run.

**Regression** (`pipeline.validate.regression`) asks a question conformance cannot: is this build
suspiciously *smaller* than the one before it, in a way that is shaped perfectly correctly but
still wrong -- a wiki outage that quietly serves empty tables, a scrape that silently drops a whole
kind, or a sprite fetch that quietly stops resolving icons for entities that used to have one. It
needs a memory conformance does not: the previous build's counts, which `pipeline.validate.
snapshot.BuildSnapshot.from_dist` reads from the committed `data/dist` itself, because that
directory *is* the previous build, per this task's own resolution of "the baseline for 'across
versions'" that `TODO.md`'s Phase 3 bullet leaves unspecified. Its eight checks -- total entity
count, per-kind count and disappearance, required- and optional-field coverage, section-type
disappearance, obtain graph producer count, and sprite atlas icon coverage -- are each a plain
integer or percentage comparison against that baseline; `pipeline.validate.regression`'s own module
docstring is where each one's threshold and reasoning actually live.

Neither half can stand in for the other. A build can be perfectly shaped and still have silently
lost 90% of its mobs -- conformance has nothing to say about that, because every entity it does
still find is a completely valid `Entity`. And a build can hold its numbers steady while writing a
`sourceTiers` key that names a field that does not exist -- regression has nothing to say about
that, because it never looks inside a document, only at how many of them there are.

## Where the gate hooks in, and the read-write hazard that ordering has to respect

`pipeline.emit.write.emit_build` takes an optional `gate: GateCallback | None` keyword. When
one is given, `emit_build` assembles every document it is about to write -- the same `dict`s and
payloads it always builds -- and calls the gate with them, *after* they exist in memory and
*before* any of them reaches disk. The gate raises `ValidationError` to refuse the build, or
returns to let `emit_build` proceed to its own all-or-nothing write. `emit_build`'s own module
docstring names this as the one new thing this task adds to its Rule 4: the write loop was always
the first moment that function touched the filesystem, and it still is -- the gate call is one more
thing that has to succeed first, not a second write path.

This creates a hazard `pipeline.validate.snapshot`'s own docstring names directly: `BuildSnapshot.
from_dist` has to read the committed `data/dist` *before* `emit_build` overwrites it, but the gate
itself is only invoked from inside `emit_build`, by which point the read would be reading the very
build it is supposed to be a baseline for. `validate_build` is what keeps the two calls in the
right order -- it reads the baseline the moment a caller asks it for a gate, not lazily inside the
gate's own `__call__`, so `pipeline.cli.build.run_build` only has to call it once, before
`emit_build`, and the ordering is correct by construction rather than by a caller remembering to
sequence two calls correctly.

## Why `pipeline.emit` still owns no policy

Handing `emit_build` a callback rather than a `dist: Path` it reads itself, or a hard-coded call to
this package, keeps `pipeline.emit`'s own boundary exactly where its module docstring already drew
it: that package writes whatever it is given, and does not itself know what a threshold is. A `gate
=None` caller -- every one of the 1343 tests this task's baseline already has -- sees no change in
behaviour at all. The one caller that does pass a gate, `pipeline.cli.build.run_build`, is the one
that is choosing to enforce a policy; `pipeline.emit.write` is only choosing *when*, in its own
sequence, to ask whatever callable it was handed.

## `--allow-regression` downgrades one half, never the other

A version that genuinely removes content -- Mojang deleting a mob, a curated override correcting a
past misclassification at scale -- is not a bug, and a gate with no escape hatch for it would block
every build of that version forever. `--allow-regression` is that escape hatch, but it reaches only
`pipeline.validate.regression`'s report: every regression failure is still recorded, in full, in
`RegressionCheck.downgraded`, and still written to `data/reports/validation.json` -- the flag
changes whether the build is refused, never whether the finding is written down. It does not reach
`pipeline.validate.conformance` at all. A malformed document is never an acceptable build, no matter
how many times a maintainer means to override the check that would otherwise catch it -- there is
no version of Minecraft that makes an invalid `wikiUrl` a correct one.
"""

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from pipeline.normalize.merge import MergeResult
from pipeline.obtain.producer import ProducerIndex
from pipeline.validate.conformance import ConformanceReport, GateDocuments, validate_conformance
from pipeline.validate.regression import (
    RegressionCheck,
    RegressionReport,
    check_regression,
    format_measure,
)
from pipeline.validate.snapshot import BuildSnapshot

__all__ = [
    "GateCallback",
    "ValidationError",
    "ValidationGate",
    "ValidationReport",
    "validate_build",
]


class ValidationError(Exception):
    """A build failed the validation gate: either a document is malformed, or an unexplained
    regression.

    Raised only by `ValidationGate.__call__`, and only for one of two reasons: `pipeline.validate.
    conformance.ConformanceReport.failures` is non-empty (never downgradable -- see the module
    docstring's closing section), or `pipeline.validate.regression.RegressionReport.blocking_
    failures` is non-empty and the build was not run with `--allow-regression`. `str(error)` names
    every failure that caused the refusal, matching every other stage exception's own convention of
    writing a message meant for a person to read at the command line.
    """


class ValidationReport(BaseModel, frozen=True):
    """What one validation gate call found, across both halves. Written whole to
    `data/reports/validation.json`.
    """

    conformance: ConformanceReport
    regression: RegressionReport


class GateCallback(Protocol):
    """The shape `pipeline.emit.write.emit_build`'s `gate` parameter accepts.

    A `Protocol` rather than `Callable[[GateDocuments], None]`, so a caller can see the parameter's
    name (`documents`) at the call site and so a future gate implementation can satisfy this shape
    without inheriting from anything `pipeline.validate` exports -- structural typing, matching how
    this callback is actually used: `pipeline.emit.write` imports only this shape, never `Validation
    Gate` itself, keeping the dependency one-directional (`pipeline.emit` depends on `pipeline.
    validate`'s *type*, never on its implementation).
    """

    def __call__(self, documents: GateDocuments) -> None:
        """Raise `ValidationError` to refuse the build `documents` describes, or return to allow
        it.
        """
        ...


class ValidationGate:
    """A stateful `GateCallback`: call it once, then read `.report` for everything it found.

    `pipeline.emit.write.emit_build` only ever calls a gate for its return value (`None`, or a
    raised `ValidationError`) -- it has no way to hand a report back to its own caller, because
    `EmitReport` was never widened to carry one and this task does not widen it. `ValidationGate`
    is where the report actually goes: `pipeline.cli.build.run_build` reads `gate.report` after
    `emit_build` returns, by which point `__call__` below has always already set it, whether the
    call went on to raise or not.
    """

    def __init__(
        self,
        *,
        baseline: BuildSnapshot | None,
        merge_result: MergeResult,
        producer_index: ProducerIndex,
        allow_regression: bool,
        atlas_icon_count: int = 0,
    ) -> None:
        self._baseline = baseline
        self._merge_result = merge_result
        self._producer_index = producer_index
        self._allow_regression = allow_regression
        self._atlas_icon_count = atlas_icon_count
        self.report: ValidationReport | None = None

    def __call__(self, documents: GateDocuments) -> None:
        """Run both halves against `documents`, record the report, and raise on a blocking
        failure.

        `documents` drives the conformance half only. The regression half compares a fresh `Build
        Snapshot.from_merge_result` of the `MergeResult` this gate was built from against the
        baseline `validate_build` already read -- not `documents` itself, because `documents` is
        shaped for schema validation (nested dicts) and a `MergeResult` is what `BuildSnapshot`
        already knows how to summarise directly, with no JSON round trip in between.
        """
        conformance = validate_conformance(documents)
        new_snapshot = BuildSnapshot.from_merge_result(
            self._merge_result, self._producer_index, atlas_icon_count=self._atlas_icon_count
        )
        regression = check_regression(
            new=new_snapshot, baseline=self._baseline, allow_regression=self._allow_regression
        )
        self.report = ValidationReport(conformance=conformance, regression=regression)

        if conformance.failures:
            raise ValidationError(_conformance_message(conformance))
        blocking = regression.blocking_failures
        if blocking:
            raise ValidationError(_regression_message(blocking))


def _conformance_message(report: ConformanceReport) -> str:
    lines = [
        f"  {failure.document}"
        + (f" ({failure.entity_id})" if failure.entity_id else "")
        + f" at {failure.pointer or '/'}: {failure.message}"
        for failure in report.failures
    ]
    more = f" (+{report.truncated_count} more not shown)" if report.truncated_count else ""
    return (
        f"the validation gate refused this build: {len(report.failures)} document(s) failed "
        f"schema conformance{more}:\n" + "\n".join(lines)
    )


def _regression_message(blocking: tuple[RegressionCheck, ...]) -> str:
    lines = [
        f"  {check.name}: baseline={format_measure(check.baseline)} "
        f"new={format_measure(check.new)} ({check.rule})"
        for check in blocking
    ]
    return (
        f"the validation gate refused this build: {len(blocking)} regression check(s) failed. "
        f"Pass --allow-regression if this drop is expected -- it downgrades a regression failure "
        f"to a warning that is still recorded in data/reports/validation.json; it never downgrades "
        f"a schema conformance failure.\n" + "\n".join(lines)
    )


def validate_build(
    *,
    dist: Path,
    merge_result: MergeResult,
    producer_index: ProducerIndex,
    allow_regression: bool,
    atlas_icon_count: int = 0,
) -> ValidationGate:
    """Return a `ValidationGate` bound to `merge_result`, ready to pass as `emit_build`'s `gate=`.

    Reads `dist`'s baseline snapshot right now, before this function's caller ever calls
    `emit_build` -- see the module docstring's read-write hazard section for why that ordering is
    this function's job to get right rather than the gate's own `__call__`'s. `atlas_icon_count`
    is the new side of the sprite atlas coverage check -- `pipeline.cli.build.run_build` passes
    `len(atlas.coordinates.sprites)`, the same `Atlas` stage 7b already packed before this function
    is ever called, and it defaults to zero for a caller (most of this package's own tests) with no
    atlas to report on at all.
    """
    baseline = BuildSnapshot.from_dist(dist)
    return ValidationGate(
        baseline=baseline,
        merge_result=merge_result,
        producer_index=producer_index,
        allow_regression=allow_regression,
        atlas_icon_count=atlas_icon_count,
    )
