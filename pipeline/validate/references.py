"""Reference validation: classify unplaced Tier B rows into benign groups or failures.

The merge records every Tier B cross-reference it could not resolve in `MergeReport.unplaced`.
A row lands in `unplaced` when the merge has no registry ID to link to:
- Some names represent a set/variant group where picking one ID would be
  fabricated (`VARIANT_GROUP`).
- Some names represent stack/NBT-carried data like maps and banners (`STACK_DATA`).
- Some names come from wiki content that is not part of this release (`NOT_IN_THIS_VERSION`).

Anything outside these defended groups is a failure (e.g. an unlinked item like `Potato`),
which blocks the build unless `--allow-regression` is passed.
"""

from collections.abc import Mapping
from enum import StrEnum

from pydantic import BaseModel

from pipeline.normalize.merge import MergeReport, UnplacedRow

__all__ = [
    "BenignGroup",
    "ReferenceReport",
    "UnlinkedName",
    "check_references",
    "classify_unplaced_row",
]


class BenignGroup(StrEnum):
    """Why an unresolved display name is correct rather than a fault."""

    VARIANT_GROUP = "variant_group"
    STACK_DATA = "stack_data"
    NOT_IN_THIS_VERSION = "not_in_this_version"


class UnlinkedName(BaseModel, frozen=True):
    """One unplaced row this module could not defend, and what it looked like."""

    subject: str
    table: str
    reason: str
    downgraded: bool = False


class ReferenceReport(BaseModel, frozen=True):
    """Every unplaced row, sorted into a group or into `failures`."""

    classified: Mapping[BenignGroup, tuple[str, ...]]
    failures: tuple[UnlinkedName, ...] = ()

    @property
    def blocking_failures(self) -> tuple[UnlinkedName, ...]:
        """Mirrors `RegressionReport.blocking_failures` so the gate reads both alike."""
        return tuple(f for f in self.failures if not f.downgraded)


# The merge writes one of these when it *did* resolve the name to a well-formed
# registry ID and then found this build carries no entity for it. That is the
# `NOT_IN_THIS_VERSION` condition stated by the merge itself, so it is read as a rule
# rather than re-listed here as names. The merge spells it several slightly different
# ways ("..., which this build does not enumerate as an entity", "... and this build
# does not enumerate it as an entity", "biome '...' is not an enumerated biome
# entity"), so the shared core of each phrasing is matched rather than any one full
# sentence.
#
# An earlier version of this module hardcoded the four Poisonous Potato snapshot IDs
# and the string "Dappled Forest" instead. Both lists would pass today and teach
# nothing: the next snapshot entity the wiki documents would fail the build even
# though it is the same benign condition. Verified against the live 26.2 report --
# these phrases classify all five of its group 3 rows and nothing else.
#
# Neither phrase can launder a real miss. `Potato` and `Music Disc <Song>` fail
# resolution outright, so the merge writes "no Tier B display name resolves to a
# registry ID" for them, which matches neither phrase and still fails.
_NOT_ENUMERATED_REASONS = (
    "does not enumerate",
    "is not an enumerated",
)

# Which registry a table's names are looked up in. A name cannot be expected to
# resolve into a registry this build left empty, so an unplaced row from a table whose
# registry has no entities at all is vacuous rather than a fault -- the same reasoning
# `pipeline.validate.regression` uses when it skips every check on a `None` baseline.
#
# This is what keeps a smoke-test build honest: a fixture world that enumerates three
# entities reports all 40 wiki effect names as unplaced, and none of them is a miss
# anyone could have fixed. In the real 26.2 build every one of these registries is
# populated, so every table's rows are classified for real.
_TABLE_REGISTRY: Mapping[str, str] = {
    "trade": "item",
    "droptable": "item",
    "breeding": "item",
    "food": "item",
    "harvest": "block",
    "generation": "block",
    "effect": "mob_effect",
    "enchantment": "enchantment",
    "spawn_table": "worldgen/biome",
}


def classify_unplaced_row(row: UnplacedRow) -> BenignGroup | None:
    """Classify one unplaced row into a BenignGroup, or return None if it is a failure."""
    # Group 1: VARIANT_GROUP (represents a set, not a single registry ID)
    if row.subject.startswith("Any color "):
        return BenignGroup.VARIANT_GROUP

    # Group 2: STACK_DATA (one item carrying map or banner data).
    #
    # The test is the whole word "Map", not "Explorer Map". Every map a trade or a
    # chest names is one `minecraft:filled_map` carrying the location in its stack
    # data, and the name says which location rather than which item -- so the
    # qualifier in front of it is not the part that makes the row benign. An
    # earlier cut keyed on "Explorer Map" and broke the first time the game added
    # another kind: 26.3's cartographer sells a Village Map, which is the same
    # item, the same stack data, and the same non-answer to "which registry ID".
    # That is the failure this module's own docstring warns a name list will
    # always have.
    #
    # It cannot launder a real miss. The two map items that *are* registry entries,
    # `minecraft:map` and `minecraft:filled_map`, resolve by name and never reach
    # this function at all.
    if row.subject == "Map" or row.subject.endswith(" Map"):
        return BenignGroup.STACK_DATA
    if row.subject == "Banner" and "ambiguous" in row.reason.lower():
        return BenignGroup.STACK_DATA

    # Group 3: NOT_IN_THIS_VERSION (the merge resolved a real ID this build has no
    # entity for -- snapshot or future-release content the wiki documents early)
    if any(phrase in row.reason for phrase in _NOT_ENUMERATED_REASONS):
        return BenignGroup.NOT_IN_THIS_VERSION

    return None


# The one kind of unplaced row that is not a cross-link miss at all.
#
# `pipeline.normalize.merge` writes it when a resolved target has no wiki page, so
# attaching a Tier B section would publish wiki-authored content with no attribution
# link. That is an attribution gap, not a name this build failed to link, and it is
# already the merge's own recorded decision rather than a resolution failure.
#
# It is matched on the reason rather than on the table, because the table is not what
# distinguishes it: the same nine table names produce ordinary cross-link misses too.
# An earlier version of this module allowlisted four table names instead, which
# silently ignored a `Potato`-class miss reported against any of the other five --
# exactly the failure this lint exists to catch.
_ATTRIBUTION_GAP_REASON = "has no resolved wiki page"


def check_references(
    *,
    report: MergeReport,
    allow_regression: bool = False,
) -> ReferenceReport:
    """Classify every `report.unplaced` row; anything unplaceable is a failure.

    Every table is read. `unplaced` holds one row per Tier B name the merge could not
    attach, whatever table it came from, and a name that should have linked is a fault
    no matter which table reported it.
    """
    classified: dict[BenignGroup, list[str]] = {
        BenignGroup.VARIANT_GROUP: [],
        BenignGroup.STACK_DATA: [],
        BenignGroup.NOT_IN_THIS_VERSION: [],
    }
    failures: list[UnlinkedName] = []

    for row in report.unplaced:
        if _ATTRIBUTION_GAP_REASON in row.reason:
            continue
        registry = _TABLE_REGISTRY.get(row.table)
        if registry is not None and report.counts.get(registry, 0) == 0:
            continue
        group = classify_unplaced_row(row)
        if group is not None:
            classified[group].append(row.subject)
        else:
            failures.append(
                UnlinkedName(
                    subject=row.subject,
                    table=row.table,
                    reason=row.reason,
                    downgraded=allow_regression,
                )
            )

    return ReferenceReport(
        classified={group: tuple(sorted(items)) for group, items in classified.items()},
        failures=tuple(failures),
    )
