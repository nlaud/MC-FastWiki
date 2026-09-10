"""Tests for reference validation and unplaced row classification."""

from pipeline.enrich.advancement import Reconciliation
from pipeline.normalize.merge import MergeReport, UnplacedRow
from pipeline.validate.references import (
    BenignGroup,
    check_references,
    classify_unplaced_row,
)

# The per-registry counts of the real 26.2 build. `check_references` skips a table
# whose registry this build left empty, so a report with no counts at all would skip
# every row and quietly assert nothing -- these keep the fixture a populated world.
_REAL_COUNTS = {
    "item": 1537,
    "block": 1196,
    "mob_effect": 40,
    "enchantment": 43,
    "entity_type": 158,
    "worldgen/biome": 66,
}


def _empty_merge_report(unplaced: tuple[UnplacedRow, ...]) -> MergeReport:
    return MergeReport(
        unplaced=unplaced,
        counts=_REAL_COUNTS,
        advancement_reconciliation=Reconciliation(
            matched=(),
            missing_from_wiki=(),
            missing_from_tier_a=(),
        ),
    )


REAL_UNPLACED_ROWS = (
    UnplacedRow(
        table="spawn_table",
        subject="Slime",
        reason="biome 'Dappled Forest' is not an enumerated biome entity",
    ),
    UnplacedRow(
        table="droptable",
        subject="Toxifin Slab",
        reason="resolved to minecraft:toxifin, which this build does not enumerate as an entity",
    ),
    UnplacedRow(
        table="droptable",
        subject="Plaguewhale Slab",
        reason=(
            "resolved to minecraft:plaguewhale, which this build does not enumerate as an entity"
        ),
    ),
    UnplacedRow(
        table="droptable",
        subject="Mega Spud",
        reason="resolved to minecraft:mega_spud, which this build does not enumerate as an entity",
    ),
    UnplacedRow(
        table="droptable",
        subject="Poisonous Potato Zombie",
        reason=(
            "resolved to minecraft:poisonous_potato_zombie, which this build does not "
            "enumerate as an entity"
        ),
    ),
    UnplacedRow(
        table="trade",
        subject="Any color Wool",
        reason="no Tier B display name resolves to a registry ID",
    ),
    UnplacedRow(
        table="trade",
        subject="Any color Carpet",
        reason="no Tier B display name resolves to a registry ID",
    ),
    UnplacedRow(
        table="trade",
        subject="Any color Bed",
        reason="no Tier B display name resolves to a registry ID",
    ),
    UnplacedRow(
        table="trade",
        subject="Any color Banner",
        reason="no Tier B display name resolves to a registry ID",
    ),
    UnplacedRow(
        table="trade",
        subject="Explorer Map",
        reason=(
            "ambiguous display name, candidates: "
            "minecraft:desert_village_map, minecraft:plains_village_map"
        ),
    ),
    UnplacedRow(
        table="trade",
        subject="Ocean Explorer Map",
        reason="no Tier B display name resolves to a registry ID",
    ),
    UnplacedRow(
        table="trade",
        subject="Trial Explorer Map",
        reason="no Tier B display name resolves to a registry ID",
    ),
    UnplacedRow(
        table="trade",
        subject="Banner",
        reason=(
            "ambiguous display name, candidates: "
            "minecraft:black_banner, minecraft:black_wall_banner"
        ),
    ),
    UnplacedRow(
        table="trade",
        subject="Woodland Explorer Map",
        reason="no Tier B display name resolves to a registry ID",
    ),
    UnplacedRow(
        table="trade",
        subject="Any color Stained Terracotta",
        reason="no Tier B display name resolves to a registry ID",
    ),
    UnplacedRow(
        table="trade",
        subject="Any color Glazed Terracotta",
        reason="no Tier B display name resolves to a registry ID",
    ),
)


def test_all_sixteen_real_rows_classify_without_failures() -> None:
    report = check_references(
        report=_empty_merge_report(REAL_UNPLACED_ROWS),
        allow_regression=False,
    )
    assert len(report.failures) == 0
    assert len(report.blocking_failures) == 0

    assert len(report.classified[BenignGroup.VARIANT_GROUP]) == 6
    assert len(report.classified[BenignGroup.STACK_DATA]) == 5
    assert len(report.classified[BenignGroup.NOT_IN_THIS_VERSION]) == 5


def test_variant_group_classification() -> None:
    row = UnplacedRow(
        table="trade",
        subject="Any color Shulker Box",
        reason="no Tier B display name resolves to a registry ID",
    )
    assert classify_unplaced_row(row) == BenignGroup.VARIANT_GROUP


def test_stack_data_classification() -> None:
    map_row = UnplacedRow(
        table="trade",
        subject="Ocean Explorer Map",
        reason="no Tier B display name resolves to a registry ID",
    )
    assert classify_unplaced_row(map_row) == BenignGroup.STACK_DATA

    banner_row = UnplacedRow(
        table="trade",
        subject="Banner",
        reason="ambiguous display name, candidates: minecraft:red_banner",
    )
    assert classify_unplaced_row(banner_row) == BenignGroup.STACK_DATA


def test_not_in_this_version_classification() -> None:
    dappled = UnplacedRow(
        table="spawn_table",
        subject="Slime",
        reason="biome 'Dappled Forest' is not an enumerated biome entity",
    )
    assert classify_unplaced_row(dappled) == BenignGroup.NOT_IN_THIS_VERSION

    toxifin = UnplacedRow(
        table="droptable",
        subject="Toxifin Slab",
        reason="resolved to minecraft:toxifin, which this build does not enumerate as an entity",
    )
    assert classify_unplaced_row(toxifin) == BenignGroup.NOT_IN_THIS_VERSION


def test_synthetic_fault_fails_as_blocking_failure() -> None:
    fault = UnplacedRow(
        table="trade",
        subject="Potato",
        reason="no Tier B display name resolves to a registry ID",
    )
    report = check_references(
        report=_empty_merge_report((fault,)),
        allow_regression=False,
    )
    assert len(report.failures) == 1
    assert report.failures[0].subject == "Potato"
    assert report.failures[0].downgraded is False
    assert len(report.blocking_failures) == 1
    assert report.blocking_failures[0].subject == "Potato"


def test_a_fault_fails_whatever_table_reported_it() -> None:
    """Every table is read, not a chosen few.

    `pipeline.normalize.merge` writes an unplaced row with one of nine table names, and
    the shared resolution helper that produces a `Potato`-class miss is called with all
    of them. An earlier version of this module allowlisted four, so the same miss
    reported against `harvest` or `generation` was silently ignored.
    """
    for table in ("trade", "droptable", "spawn_table", "breeding", "harvest", "generation",
                  "food", "effect", "enchantment"):
        row = UnplacedRow(
            table=table,
            subject="Potato",
            reason="no Tier B display name resolves to a registry ID",
        )
        report = check_references(
            report=_empty_merge_report((row,)),
            allow_regression=False,
        )
        assert report.blocking_failures, f"a Potato miss in {table!r} was not reported"
        assert report.blocking_failures[0].table == table


def test_a_table_whose_registry_is_empty_is_skipped_not_failed() -> None:
    """A smoke-test world reports names it never had anything to join against.

    A fixture build that enumerates three entities reports all 40 wiki effect names as
    unplaced, and none is a miss anyone could fix. This mirrors
    `pipeline.validate.regression` skipping every check on a `None` baseline.
    """
    row = UnplacedRow(
        table="effect",
        subject="Absorption",
        reason="no Tier B display name resolves to a registry ID",
    )
    report = MergeReport(
        unplaced=(row,),
        counts={"item": 3, "mob_effect": 0},
        advancement_reconciliation=Reconciliation(
            matched=(), missing_from_wiki=(), missing_from_tier_a=()
        ),
    )
    assert check_references(report=report, allow_regression=False).failures == ()


def test_an_empty_registry_does_not_excuse_a_populated_one() -> None:
    """The skip is per table, not a blanket amnesty for the whole report."""
    rows = (
        UnplacedRow(
            table="effect",
            subject="Absorption",
            reason="no Tier B display name resolves to a registry ID",
        ),
        UnplacedRow(
            table="trade",
            subject="Potato",
            reason="no Tier B display name resolves to a registry ID",
        ),
    )
    report = MergeReport(
        unplaced=rows,
        counts={"item": 1537, "mob_effect": 0},
        advancement_reconciliation=Reconciliation(
            matched=(), missing_from_wiki=(), missing_from_tier_a=()
        ),
    )
    failures = check_references(report=report, allow_regression=False).failures
    assert [f.subject for f in failures] == ["Potato"]


def test_an_attribution_gap_is_not_a_cross_link_miss() -> None:
    """The one unplaced kind this lint deliberately does not read.

    A target with no wiki page is a decision the merge already recorded about
    attribution, not a name that failed to resolve, so it is neither classified nor
    failed.
    """
    row = UnplacedRow(
        table="effect",
        subject="Speed",
        reason=(
            "minecraft:speed has no resolved wiki page, so a EffectSources section "
            "would carry wiki-authored content with no attribution link"
        ),
    )
    report = check_references(
        report=_empty_merge_report((row,)),
        allow_regression=False,
    )
    assert report.failures == ()
    assert all(items == () for items in report.classified.values())


def test_synthetic_fault_downgrades_with_allow_regression() -> None:
    fault = UnplacedRow(
        table="trade",
        subject="Music Disc <Song>",
        reason="no Tier B display name resolves to a registry ID",
    )
    report = check_references(
        report=_empty_merge_report((fault,)),
        allow_regression=True,
    )
    assert len(report.failures) == 1
    assert report.failures[0].subject == "Music Disc <Song>"
    assert report.failures[0].downgraded is True
    # Blocking failures is empty when downgraded
    assert len(report.blocking_failures) == 0
