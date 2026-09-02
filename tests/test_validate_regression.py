"""`check_regression`: every row of the table `pipeline.validate.regression`'s module docstring
names.

Most tests here build `BuildSnapshot` instances directly rather than through a `MergeResult` --
`check_regression` is a pure function of two snapshots, and constructing them directly is what lets
a test land exactly on a threshold's boundary (2120 -> 2014, a kind losing exactly 2 of 24) without
also having to build the `Entity` objects that would produce those counts. The two tests that do
build a `MergeResult` (`test_every_mob_stripped_fails_...`) are there because the task this module
was written against asks for that path to be exercised at least once, end to end.
"""

from pipeline.enrich.advancement import Reconciliation
from pipeline.normalize.entity import Entity, EntityKind, Section, SpawnInfo, StatBlock
from pipeline.normalize.merge import MergeReport, MergeResult
from pipeline.validate.regression import check_regression, format_measure
from pipeline.validate.snapshot import BuildSnapshot


def _snapshot(
    *,
    total: int,
    by_kind: dict[str, int] | None = None,
    required_field_coverage: dict[str, int] | None = None,
    optional_field_coverage: dict[str, int] | None = None,
    section_type_counts: dict[str, int] | None = None,
    obtain_producer_count: int = 0,
) -> BuildSnapshot:
    required = required_field_coverage or {
        "id": total,
        "kind": total,
        "name": total,
        "aliases": total,
        "sourceTiers": total,
        "sections": total,
    }
    return BuildSnapshot(
        total=total,
        by_kind=by_kind or {},
        required_field_coverage=required,
        optional_field_coverage=optional_field_coverage or {},
        section_type_counts=section_type_counts or {},
        obtain_producer_count=obtain_producer_count,
    )


def test_no_baseline_passes_with_no_checks() -> None:
    report = check_regression(new=_snapshot(total=10), baseline=None, allow_regression=False)
    assert report.has_baseline is False
    assert report.checks == ()
    assert report.blocking_failures == ()


def test_total_count_dropping_exactly_five_percent_passes() -> None:
    baseline = _snapshot(total=2120)
    new = _snapshot(total=2014)  # exactly a 5% drop
    report = check_regression(new=new, baseline=baseline, allow_regression=False)

    check = next(c for c in report.checks if c.name == "total entity count")
    assert check.passed is True
    assert report.blocking_failures == ()


def test_total_count_dropping_more_than_five_percent_fails_naming_the_floor() -> None:
    baseline = _snapshot(total=2120)
    new = _snapshot(total=1920)
    report = check_regression(new=new, baseline=baseline, allow_regression=False)

    check = next(c for c in report.checks if c.name == "total entity count")
    assert check.baseline == 2120
    assert check.new == 1920
    assert check.passed is False
    assert check in report.blocking_failures
    # The floor this check applies: 5% below 2120 is 2014 -- 1920 sits well below it.
    floor = 2120 * 0.95
    assert new.total < floor


def test_a_kind_losing_two_of_twenty_four_passes() -> None:
    # `total` is held fixed across baseline and new on purpose, isolating the per-kind check
    # from the unrelated "total entity count" check, which would otherwise also fire on a
    # 24 -> 22 drop measured against a matching total.
    baseline = _snapshot(total=100, by_kind={"entity": 24})
    new = _snapshot(total=100, by_kind={"entity": 22})
    report = check_regression(new=new, baseline=baseline, allow_regression=False)

    per_kind = next(c for c in report.checks if c.name == "per-kind count: entity")
    assert per_kind.passed is True
    assert report.blocking_failures == ()


def test_a_kind_losing_three_of_twenty_four_fails() -> None:
    baseline = _snapshot(total=24, by_kind={"entity": 24})
    new = _snapshot(total=21, by_kind={"entity": 21})
    report = check_regression(new=new, baseline=baseline, allow_regression=False)

    per_kind = next(c for c in report.checks if c.name == "per-kind count: entity")
    assert per_kind.passed is False
    assert per_kind in report.blocking_failures


def test_a_kind_reaching_zero_fails_the_disappearance_check_even_with_few_members() -> None:
    """A kind with only 2 members can never lose 3 of them, so the AND rule alone would never
    catch total extinction of a small kind -- the disappearance check is the safety net for it.
    """
    baseline = _snapshot(total=2, by_kind={"biome": 2})
    new = _snapshot(total=0, by_kind={"biome": 0})
    report = check_regression(new=new, baseline=baseline, allow_regression=False)

    disappeared = next(c for c in report.checks if c.name == "kind disappears: biome")
    assert disappeared.passed is False
    assert disappeared in report.blocking_failures


def test_required_field_coverage_below_100_percent_fails() -> None:
    baseline = _snapshot(total=10)
    new = _snapshot(
        total=10,
        required_field_coverage={
            "id": 10,
            "kind": 10,
            "name": 10,
            "aliases": 10,
            "sourceTiers": 9,  # one entity is missing it
            "sections": 10,
        },
    )
    report = check_regression(new=new, baseline=baseline, allow_regression=False)

    check = next(c for c in report.checks if c.name == "required-field coverage: sourceTiers")
    assert check.passed is False
    assert check in report.blocking_failures


def test_optional_field_coverage_dropping_more_than_five_points_fails() -> None:
    baseline = _snapshot(total=100, optional_field_coverage={"wikiUrl": 100})  # 100%
    new = _snapshot(total=100, optional_field_coverage={"wikiUrl": 94})  # 94%, a 6-point drop
    report = check_regression(new=new, baseline=baseline, allow_regression=False)

    check = next(c for c in report.checks if c.name == "optional-field coverage: wikiUrl")
    assert check.passed is False
    assert check in report.blocking_failures


def test_optional_field_coverage_dropping_exactly_five_points_passes() -> None:
    baseline = _snapshot(total=100, optional_field_coverage={"wikiUrl": 100})
    new = _snapshot(total=100, optional_field_coverage={"wikiUrl": 95})
    report = check_regression(new=new, baseline=baseline, allow_regression=False)

    check = next(c for c in report.checks if c.name == "optional-field coverage: wikiUrl")
    assert check.passed is True


def test_a_section_type_reaching_zero_fails() -> None:
    baseline = _snapshot(total=10, section_type_counts={"StatBlock": 5})
    new = _snapshot(total=10, section_type_counts={"StatBlock": 0})
    report = check_regression(new=new, baseline=baseline, allow_regression=False)

    check = next(c for c in report.checks if c.name == "section type: StatBlock")
    assert check.passed is False
    assert check in report.blocking_failures


def test_obtain_graph_dropping_more_than_five_percent_fails() -> None:
    baseline = _snapshot(total=10, obtain_producer_count=4002)
    new = _snapshot(total=10, obtain_producer_count=3000)
    report = check_regression(new=new, baseline=baseline, allow_regression=False)

    check = next(c for c in report.checks if c.name == "obtain graph producer count")
    assert check.passed is False
    assert check in report.blocking_failures


def test_growth_never_fails_anything() -> None:
    baseline = _snapshot(
        total=100,
        by_kind={"item": 100},
        optional_field_coverage={"wikiUrl": 50},
        section_type_counts={"StatBlock": 10},
        obtain_producer_count=100,
    )
    new = _snapshot(
        total=200,
        by_kind={"item": 200},
        optional_field_coverage={"wikiUrl": 200},
        section_type_counts={"StatBlock": 20},
        obtain_producer_count=500,
    )
    report = check_regression(new=new, baseline=baseline, allow_regression=False)
    assert report.blocking_failures == ()
    assert all(check.passed for check in report.checks)


def test_allow_regression_downgrades_a_failure_but_still_records_it() -> None:
    baseline = _snapshot(total=2120)
    new = _snapshot(total=1920)
    report = check_regression(new=new, baseline=baseline, allow_regression=True)

    check = next(c for c in report.checks if c.name == "total entity count")
    assert check.passed is False
    assert check.downgraded is True
    assert report.blocking_failures == ()


def test_every_mob_stripped_fails_per_kind_disappearance_and_the_two_section_types() -> None:
    """The `MergeResult`-driven path: a merge that lost every mob must fail the per-kind count,
    the kind-disappearance check, and both `StatBlock` and `SpawnInfo` reaching zero -- the two
    section types that, on the real baseline, only a mob ever carries.
    """
    reconciliation = Reconciliation(matched=(), missing_from_wiki=(), missing_from_tier_a=())

    def entity(entity_id: str, kind: EntityKind, sections: tuple[Section, ...] = ()) -> Entity:
        return Entity(
            id=entity_id,
            kind=kind,
            name=entity_id.split(":", 1)[-1],
            aliases=(),
            source_tiers={},
            sections=sections,
        )

    baseline_entities = (
        *(
            entity(f"minecraft:mob-{i}", EntityKind.MOB, (StatBlock(), SpawnInfo()))
            for i in range(24)
        ),
        entity("minecraft:apple", EntityKind.ITEM),
    )
    baseline_result = MergeResult(
        entities=baseline_entities,
        by_id={e.id: e for e in baseline_entities},
        report=MergeReport(advancement_reconciliation=reconciliation),
    )
    baseline_snapshot = BuildSnapshot.from_merge_result(baseline_result)

    new_entities = (entity("minecraft:apple", EntityKind.ITEM),)
    new_result = MergeResult(
        entities=new_entities,
        by_id={e.id: e for e in new_entities},
        report=MergeReport(advancement_reconciliation=reconciliation),
    )
    new_snapshot = BuildSnapshot.from_merge_result(new_result)

    report = check_regression(new=new_snapshot, baseline=baseline_snapshot, allow_regression=False)

    names_failing = {check.name for check in report.blocking_failures}
    assert "per-kind count: mob" in names_failing
    assert "kind disappears: mob" in names_failing
    assert "section type: StatBlock" in names_failing
    assert "section type: SpawnInfo" in names_failing


def test_a_whole_number_reports_as_an_integer_and_a_fraction_keeps_its_decimal() -> None:
    """Counts are read by people deciding whether a drop is real, so they must not say `2120.0`.

    `RegressionCheck.baseline` and `.new` are one uniform `float` because the two coverage checks
    compare percentages. That is an internal convenience, and it must not reach the reader of
    `validation.json` or of a refusal message.
    """
    assert format_measure(2120.0) == "2120"
    assert format_measure(100.0) == "100"
    assert format_measure(89.7) == "89.7"


def test_the_report_serialises_counts_as_integers() -> None:
    baseline = _snapshot(total=2120)
    new = _snapshot(total=1920)
    report = check_regression(new=new, baseline=baseline, allow_regression=False)

    check = next(c for c in report.checks if c.name == "total entity count")
    document = check.model_dump(mode="json")
    assert document["baseline"] == 2120
    assert document["new"] == 1920
    assert isinstance(document["baseline"], int)
    assert isinstance(document["new"], int)
