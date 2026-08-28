"""Where a mob spawns, how often, and how many at a time. Java only.

mcmeta's biome JSON has a `spawners` field and it is empty, so Tier A cannot
answer this. CLAUDE.md records that gap and points here: per-biome mob lists
come from the wiki's `spawn_table` bucket.

The bucket is 1,602 rows and each row is one mob in one biome. Three things
about its shape are worth knowing before reading it.

**A row lives on the biome's page, not the mob's.** `page_name` is `Desert` and
the `mob` column is `Slime`. That makes the biome page the attribution URL and
makes both directions of the index -- mob to biomes, biome to mobs -- a grouping
rather than a join.

**The `mob` column and the blob's `Spawned mob` are different things, and the
blob is the one to trust.** 122 rows disagree. `Taiga` says `mob: Chicken` and
`Spawned mob: Cold Chicken`; `Forest` says `Wolf` and `Woods Wolf`. The column
is the wiki page that documents the mob; the blob is the entity that actually
spawns. Taking the column would put plain chickens in every taiga and lose the
variants entirely, so `mob` here is the blob's value and the column is kept
beside it as `mob_page` for the link.

**The edition is inside the blob, so Bucket cannot filter it.** `Edition` is a
JSON field, not a column, and `where()` only sees columns. 813 rows are Java and
789 are Bedrock, and the two disagree on more than presence: Bedrock's Sulfur
Caves entry gives the zombie a weight of 50.05 out of 436, which is a spawn
weight that does not exist in Java at all. So the whole table is fetched and
filtered here.

Weight is only meaningful against `total_weight`, which is the sum over the
biome's whole spawn category, so `share` divides them rather than leaving a
renderer to guess what "100" means.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, model_validator

from pipeline.enrich import (
    EnrichError,
    IntegerRange,
    SkippedRow,
    group_by,
    main_namespace,
    optional_text,
    parse_integer_range,
    required_text,
    row_json,
    row_page_name,
    wiki_url,
)
from pipeline.fetch import Transport
from pipeline.fetch.bucket import fetch_bucket_rows
from pipeline.fetch.cache import ContentCache

__all__ = [
    "BUCKET",
    "COLUMNS",
    "JAVA_EDITION",
    "SpawnEntry",
    "SpawnIndex",
    "fetch_spawn_tables",
    "parse_spawn_tables",
]

BUCKET = "spawn_table"

COLUMNS = ("page_name", "mob", "json")

# The value of the blob's `Edition` field that this project keeps.
JAVA_EDITION = "java"


class SpawnEntry(BaseModel, frozen=True):
    """One mob spawning in one biome, at one weight."""

    # The entity that spawns, from the blob's `Spawned mob`. See the module
    # docstring for why this is not the `mob` column.
    mob: str
    # The wiki page that documents that mob, from the `mob` column.
    mob_page: str
    # The biome, from the blob, and the page the row was written on. They agree
    # in every observed row; both are kept because only the page is a URL.
    biome: str
    biome_page: str
    wiki_url: str
    # The spawn category: Monster, Creature, Ambient, Water creature, and so on.
    # Kept as text -- the wiki has seven values and one of them is a typo, and a
    # closed enumeration would fail a build over a word.
    category: str
    weight: int | float
    total_weight: int | float
    # How many spawn at once: `4` is always four, `2-4` is two to four.
    group_size: IntegerRange
    # The condition the wiki attaches to some rows, as wikitext: "Spawn attempt
    # succeeds only in slime chunks." Dropping it would make a conditional spawn
    # read as an ordinary one.
    note: str | None = None
    note_name: str | None = None

    @property
    def share(self) -> float | None:
        """Return this mob's share of its category's spawn weight in this biome.

        `None` when the total is zero, which no observed row has. A weight on
        its own says nothing -- 100 is common and means different things in
        different biomes -- so this is the number a renderer should show.
        """
        if self.total_weight == 0:
            return None
        return self.weight / self.total_weight


class SpawnIndex(BaseModel, frozen=True):
    """Every Java spawn the wiki records, indexed by mob and by biome."""

    entries: tuple[SpawnEntry, ...]
    by_mob: Mapping[str, tuple[SpawnEntry, ...]]
    by_biome: Mapping[str, tuple[SpawnEntry, ...]]
    skipped: tuple[SkippedRow, ...] = ()

    @classmethod
    def build(
        cls, entries: Sequence[SpawnEntry], skipped: Sequence[SkippedRow] = ()
    ) -> "SpawnIndex":
        """Return an index over `entries`, with both lookups computed."""
        return cls(
            entries=tuple(entries),
            by_mob=group_by(entries, lambda entry: entry.mob),
            by_biome=group_by(entries, lambda entry: entry.biome),
            skipped=tuple(skipped),
        )

    @model_validator(mode="after")
    def _indexes_must_match_the_entries(self) -> "SpawnIndex":
        """Refuse an index that does not index its own entries."""
        if dict(self.by_mob) != group_by(self.entries, lambda entry: entry.mob):
            raise EnrichError("the mob index does not match the entries of this table.")
        if dict(self.by_biome) != group_by(self.entries, lambda entry: entry.biome):
            raise EnrichError("the biome index does not match the entries of this table.")
        return self


def _number(document: Mapping[str, Any], field: str, *, source: str) -> int | float:
    """Return the number at `field`, or raise `EnrichError`.

    An integer stays an integer. Every Java row observed carries whole weights,
    and coercing them to float would make a page render `100.0` where the wiki
    renders `100`. Bedrock rows do carry fractional weights, which is why the
    float half of the union is here at all.
    """
    value = document.get(field)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise EnrichError(f"{source} answered {field!r} as {value!r}, not a number.")
    return value


def parse_spawn_tables(rows: Sequence[Mapping[str, Any]], *, source: str = BUCKET) -> SpawnIndex:
    """Return the Java spawn table of `rows`, and a report of what was dropped.

    Pure. A Bedrock row is skipped and reported rather than raising: the bucket
    is meant to hold both editions, so half the table being dropped is expected
    and only becomes suspicious if the count moves.

    A Java row that will not parse does raise. The blob is written by one wiki
    template, so a weight that is not a number or a group size that is not a
    range means the template changed under us.
    """
    kept, skipped = main_namespace(rows, source=source)
    entries: list[SpawnEntry] = []
    for row in kept:
        page = row_page_name(row, source=source)
        document = row_json(row, source=source)
        edition = optional_text(document, "Edition")
        mob = optional_text(document, "Spawned mob")
        if edition != JAVA_EDITION:
            skipped.append(
                SkippedRow(
                    page=page,
                    subject=mob,
                    reason=f"the row is {edition or 'no'} edition, not {JAVA_EDITION}",
                )
            )
            continue
        if mob is None:
            skipped.append(
                SkippedRow(page=page, subject=None, reason="the row names no spawned mob")
            )
            continue
        where = f"{source} row {page}/{mob}"
        mob_page = optional_text(row, "mob")
        entries.append(
            SpawnEntry(
                mob=mob,
                mob_page=mob_page if mob_page is not None else mob,
                biome=required_text(document, "Spawned in", source=where),
                biome_page=page,
                wiki_url=wiki_url(page),
                category=required_text(document, "Category", source=where),
                weight=_number(document, "Weight", source=where),
                total_weight=_number(document, "Total weight", source=where),
                group_size=parse_integer_range(
                    required_text(document, "Size", source=where), source=where
                ),
                note=optional_text(document, "Note"),
                note_name=optional_text(document, "Note name"),
            )
        )
    return SpawnIndex.build(entries, skipped)


def fetch_spawn_tables(
    *,
    revision: str,
    cache: ContentCache | None = None,
    transport: Transport | None = None,
) -> SpawnIndex:
    """Fetch the `spawn_table` bucket and return its Java spawns.

    No `where` clause. `Edition` is a field of the JSON column rather than a
    column of its own, and Bucket filters only on columns, so the Bedrock half
    has to arrive before it can be dropped.
    """
    rows = fetch_bucket_rows(
        BUCKET,
        COLUMNS,
        revision=revision,
        cache=cache,
        transport=transport,
    )
    return parse_spawn_tables(rows)
