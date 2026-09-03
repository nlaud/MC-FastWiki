"""Compare one build's `BuildSnapshot` against the committed baseline, and name every check that
ran.

`TODO.md`'s Phase 3 bullet asks for a check that "fails the build if entity count drops more than
5% or a required field disappears across versions." This module is that check, widened from the
two examples the bullet names into the eight-row table the module docstring of `pipeline.validate`
records in full, and narrowed from "fails the build" to "reports what it found" --
`check_regression` never raises; `pipeline.validate.ValidationGate` decides whether
`RegressionReport.blocking_failures` is enough to refuse a build, because that decision also has to
weigh `--allow-regression`, which this module knows nothing about beyond the one flag it is handed.

## Eight checks, each one an integer or a float, never a fuzzy read

Every threshold below is written as an integer comparison, not a float ratio compared against
another float. `100 * (baseline - new) > percent * baseline` and `baseline - new >= 3` are both
exact for integer counts; `baseline_total * 0.95` is not, because `0.95` has no exact binary
floating-point representation, and a boundary case -- 2120 entities dropping to exactly 2014, a
drop of precisely 5% -- is the case this task's own examples are built around. Comparing as
integers means that boundary lands on the same side of the line on every machine and every Python
build, rather than depending on how one particular float happened to round.

## Percentage-point checks are the one place a float is unavoidable, and why that is fine

Optional-field coverage is itself a percentage (`wikiUrl` present on 2089 of 2120 entities is
98.5%), and the check compares two percentages' *difference* against a flat five-point threshold.
There is no integer reformulation of "did coverage drop by more than five percentage points" that
avoids computing a percentage at all, so this one check uses `float` division. Nothing in this
task's own examples exercises this check's exact boundary, so no exactness guarantee is being
given up that anything currently depends on.

## The per-kind AND rule, and why it exists

A literal reading of "drops more than 5%" applied per kind fails a build the moment `entity`, the
smallest kind at 24 members, loses 2 of them -- 5% of 24 is 1.2, so losing 2 already clears that
bar. But `pipeline.normalize.merge`'s own module docstring describes `entity` as exactly the kind a
legitimate reclassification moves members out of: an `entity_type` ID gaining a spawn egg in a
later Minecraft version reclassifies from `EntityKind.ENTITY` to `EntityKind.MOB`, which is real
game content changing meaning, not a build silently losing data. A gate that fails a build over two
such reclassifications is a gate a maintainer disables within a month, and a disabled gate catches
nothing at all -- worse than a noisy one, because nobody is looking at it any more. So a kind must
lose *both* more than 5% of its members *and* at least three of them, `_KIND_MINIMUM_LOST_MEMBERS`
below, before this check fails. `check_regression`'s own kind-disappearance check is the other half
of that trade: it never applies the three-member floor, because a kind reaching zero is never a
small, ordinary reclassification regardless of how few members it started with.

## Growth is not a regression, on purpose

Every threshold below is one-sided: `new >= baseline * (1 - drop)`, never `new <= baseline *
(1 + growth)`. `pipeline.validate`'s own package docstring records the reason this module inherits
rather than re-deriving: the failure `TODO.md`'s bullet names is a wiki outage or a scrape gap
quietly shipping *less* data than the version before it, and every real Minecraft release adds
entities, sections, and producers -- a two-sided gate would refuse the ordinary case in order to
catch a failure mode that only ever shrinks a build.

## No baseline is not a regression either

`check_regression(baseline=None, ...)` returns immediately with `has_baseline=False` and no checks
at all -- never a failure. `pipeline.validate.snapshot.BuildSnapshot.from_dist`'s own docstring
names the three shapes on disk that reach `None`: an absent `data/dist`, one with no shard files,
or shards that hold no entities between them. All three describe a clean checkout building for the
first time, not a version that lost data relative to a version that came before it -- there is no
"before" to have regressed from, so failing here would only make the repository impossible to
build from nothing.

## Sprite atlas coverage counts icon keys, not packed frames

`BuildSnapshot.atlas_icon_count` is `len(sprites.json's "sprites" map)` -- the number of icon KEYS
`sprites.json` resolves, not `pipeline.emit.atlas.Atlas.frame_count`, the number of distinct
packed frames. The two differ today (1823 frames against 1901 keys), and the gap is not a fault:
several icon keys can share one packed frame, the `Sculk Block` alias `pipeline.emit.atlas`'s own
module docstring names is a live example, and how many keys happen to share a frame is a packing
detail of which wiki `File:` pages collide, not a fact about how much icon coverage a build shipped.
A key is what `Entity.icon` actually resolves against at render time, so it is the only number a
"did this build stop being able to draw an icon for something it used to draw" check can be about.
Tracking `frame_count` instead would fail this check the moment two icon keys started, or stopped,
sharing one `File:` page -- a packing-table change with no missing icon behind it at all -- while
missing the actual regression this check exists to catch: a key that resolved to a frame in the
baseline and resolves to nothing now.

## A pre-atlas baseline can never fail this row

`_dropped_more_than_percent` already answers `False` for a non-positive `baseline_count` -- see its
own docstring -- so a baseline of `0`, the `atlas_icon_count` every `data/dist` predating this
module's own atlas reads back as, can never register as a drop no matter what `new.atlas_icon_count`
turns out to be. `obtain_producer_count` already relies on this identical graceful path, for the
identical reason: both counts describe build outputs that did not always exist, and a gate that
failed the first build to introduce one would make that build impossible to land at all. This is
what makes this check safe to add on a tree whose committed `data/dist` was written before the
atlas existed, with no special-casing beyond the one already built into the helper both checks
share.
"""

from pydantic import BaseModel, field_serializer

from pipeline.validate.snapshot import BuildSnapshot

__all__ = ["RegressionCheck", "RegressionReport", "check_regression"]

# Every percentage threshold this module applies. Kept as named integers rather than inlined at
# each call site, so a reader (or a future change) finds "5%" once, not four times with a chance
# for one copy to drift from the others.
_TOTAL_DROP_PERCENT = 5
_KIND_DROP_PERCENT = 5
_KIND_MINIMUM_LOST_MEMBERS = 3
_OBTAIN_DROP_PERCENT = 5
_ATLAS_DROP_PERCENT = 5  # sprite atlas icon coverage's own floor, held to the same 5% as the rest
_OPTIONAL_COVERAGE_DROP_POINTS = 5.0


class RegressionCheck(BaseModel, frozen=True):
    """One row of a `RegressionReport`: what was checked, its baseline and new value, and the
    verdict.

    `baseline` and `new` are `float` even though most checks compare integer counts, because the
    two coverage checks compare percentages -- keeping one field type for every row is what lets
    `RegressionReport.checks` be one flat, uniform tuple rather than a union of two check shapes.
    `downgraded` is `True` only for a failing check (`passed=False`) that `--allow-regression`
    demoted from a build-blocker to a warning; a passing check is never downgraded, because there
    is nothing to downgrade.

    The one uniform `float` field type is an internal convenience, and `validation.json` is read by
    people -- a count written as `2120.0` invites the reader to wonder what the fractional entity
    is. The serialiser below writes an integral value back as an `int`, so a count reports as
    `2120` and only the two coverage percentages keep a decimal point.
    """

    name: str
    baseline: float
    new: float
    rule: str
    passed: bool
    downgraded: bool = False

    @field_serializer("baseline", "new")
    def _write_whole_numbers_as_integers(self, value: float) -> int | float:
        """Serialise an integral value as an `int`, and leave a real fraction alone."""
        return int(value) if value.is_integer() else value


def format_measure(value: float) -> str:
    """Return the human-readable form of a `RegressionCheck` baseline or new value.

    The counterpart of `RegressionCheck._write_whole_numbers_as_integers`, for the failure message
    rather than for the report file, so that a build refused over an entity count says `2120` and
    not `2120.0`. Both exist for the same reason and must stay in step: these numbers are read by
    a person deciding whether a drop is real.
    """
    return str(int(value)) if value.is_integer() else f"{value:.1f}"


class RegressionReport(BaseModel, frozen=True):
    """Every regression check one build ran, and whether the build should be blocked over any of
    them.

    `has_baseline` is `False` exactly when `check_regression` was given no baseline to compare
    against -- see the module docstring's closing section -- in which case `checks` is empty rather
    than a list of checks that all trivially passed against nothing.
    """

    has_baseline: bool
    checks: tuple[RegressionCheck, ...] = ()

    @property
    def blocking_failures(self) -> tuple[RegressionCheck, ...]:
        """Every failing check that `--allow-regression` did not downgrade to a warning."""
        return tuple(check for check in self.checks if not check.passed and not check.downgraded)


def _dropped_more_than_percent(baseline_count: int, new_count: int, *, percent: int) -> bool:
    """Return whether `new_count` is more than `percent` percent below `baseline_count`.

    Integer arithmetic throughout -- see the module docstring's exactness section for why. A
    `baseline_count` of zero can never have "dropped" from nothing, so it always answers `False`
    rather than dividing by zero.
    """
    if baseline_count <= 0:
        return False
    dropped = baseline_count - new_count
    return 100 * dropped > percent * baseline_count


def _coverage_percent(count: int, total: int) -> float:
    """Return `count` as a percentage of `total`, or `0.0` when `total` is zero."""
    return (count / total * 100.0) if total else 0.0


def check_regression(
    *, new: BuildSnapshot, baseline: BuildSnapshot | None, allow_regression: bool
) -> RegressionReport:
    """Compare `new` against `baseline`, and return every check the module docstring's table names.

    Returns `RegressionReport(has_baseline=False)` immediately when `baseline` is `None` -- see the
    module docstring's closing section. Never raises: a failing check is recorded, with `downgraded`
    set when `allow_regression` is `True`, and it is `pipeline.validate.ValidationGate`'s job to
    turn `RegressionReport.blocking_failures` into a refusal.
    """
    if baseline is None:
        return RegressionReport(has_baseline=False, checks=())

    checks: list[RegressionCheck] = []

    def add(name: str, baseline_value: float, new_value: float, rule: str, ok: bool) -> None:
        checks.append(
            RegressionCheck(
                name=name,
                baseline=baseline_value,
                new=new_value,
                rule=rule,
                passed=ok,
                downgraded=(not ok) and allow_regression,
            )
        )

    add(
        "total entity count",
        baseline.total,
        new.total,
        f"must not drop more than {_TOTAL_DROP_PERCENT}% below the baseline",
        not _dropped_more_than_percent(baseline.total, new.total, percent=_TOTAL_DROP_PERCENT),
    )

    for kind, baseline_count in sorted(baseline.by_kind.items()):
        new_count = new.by_kind.get(kind, 0)
        lost = baseline_count - new_count
        percent_dropped = _dropped_more_than_percent(
            baseline_count, new_count, percent=_KIND_DROP_PERCENT
        )
        add(
            f"per-kind count: {kind}",
            baseline_count,
            new_count,
            f"must not (drop more than {_KIND_DROP_PERCENT}% AND lose at least "
            f"{_KIND_MINIMUM_LOST_MEMBERS} members) -- both must hold, see the module docstring's "
            f"per-kind AND rule",
            not (percent_dropped and lost >= _KIND_MINIMUM_LOST_MEMBERS),
        )
        add(
            f"kind disappears: {kind}",
            baseline_count,
            new_count,
            "a kind present in the baseline must not reach zero",
            not (baseline_count > 0 and new_count == 0),
        )

    for field in sorted(baseline.required_field_coverage):
        new_count = new.required_field_coverage.get(field, 0)
        add(
            f"required-field coverage: {field}",
            100.0,
            _coverage_percent(new_count, new.total),
            "must stay at 100% coverage",
            new.total > 0 and new_count == new.total,
        )

    for field in sorted(baseline.optional_field_coverage):
        baseline_percent = _coverage_percent(
            baseline.optional_field_coverage[field], baseline.total
        )
        new_percent = _coverage_percent(new.optional_field_coverage.get(field, 0), new.total)
        add(
            f"optional-field coverage: {field}",
            baseline_percent,
            new_percent,
            f"must not drop more than {_OPTIONAL_COVERAGE_DROP_POINTS:g} percentage points below "
            f"the baseline",
            baseline_percent - new_percent <= _OPTIONAL_COVERAGE_DROP_POINTS,
        )

    for section_type, baseline_count in sorted(baseline.section_type_counts.items()):
        new_count = new.section_type_counts.get(section_type, 0)
        add(
            f"section type: {section_type}",
            baseline_count,
            new_count,
            "a section type present in the baseline must not reach zero",
            not (baseline_count > 0 and new_count == 0),
        )

    add(
        "obtain graph producer count",
        baseline.obtain_producer_count,
        new.obtain_producer_count,
        f"must not drop more than {_OBTAIN_DROP_PERCENT}% below the baseline",
        not _dropped_more_than_percent(
            baseline.obtain_producer_count, new.obtain_producer_count, percent=_OBTAIN_DROP_PERCENT
        ),
    )

    add(
        "sprite atlas icon coverage",
        baseline.atlas_icon_count,
        new.atlas_icon_count,
        f"must not drop more than {_ATLAS_DROP_PERCENT}% below the baseline",
        not _dropped_more_than_percent(
            baseline.atlas_icon_count, new.atlas_icon_count, percent=_ATLAS_DROP_PERCENT
        ),
    )

    return RegressionReport(has_baseline=True, checks=tuple(checks))
