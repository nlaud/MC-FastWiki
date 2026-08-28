"""Mob drops, per looting level, Java only.

The `droptable` bucket is 233 rows and each one is one item that one mob drops.
The mob is the page the row sits on; the item is the `item` column; everything
that matters is inside the JSON blob.

**The edition split is the whole reason this module exists as its own stage.**
The blob has a `java` key and a `bedrock` key, and they hold different numbers
for the same drop. A skeleton's arrows are `0-3` in both editions, but the Java
distribution at looting 0 is 1/3 for each of 0, 1, and 2, and the Bedrock one is
not. Of the 233 rows, 166 have a `java` key and 67 do not: a spider's spider eye,
a wither skeleton's coal, a pufferfish's bone. Those 67 are Bedrock-only drops,
and CLAUDE.md is explicit that one of them reaching the screen is a correctness
bug, not a cosmetic one. So `bedrock` is never read here -- not into an unused
field, not into a comparison. The key is skipped and the row is reported.

**The numbers are exact fractions, and they are kept exact.** The wiki writes
every probability as `{"numerator": 2, "denominator": 6}` rather than as a
decimal, and an average as `{"numerator": 3, "denominator": 2}`. That is worth
preserving: `1/3` written as a float and then rendered rounds to something a
player can tell is wrong, and a drop chance is exactly the kind of number
someone checks mid-match. `Ratio` keeps both halves and offers `value` for the
one place that wants a float.

**A looting level is a key of the `java` object, not a field.** The four keys
are `"0"` through `"3"` -- looting 0 through looting III -- and each holds a
`distribution` of how many items drop with what probability, a `dropchance`
(the probability that anything drops at all), `min`, `max`, `average`, and a
`quantitytext` such as `0&ndash;3` that the wiki renders. All 166 Java rows
carry all four levels, but nothing here requires them to: an item that looting
does not affect would sensibly have one, and refusing to parse it would lose a
real drop over an assumption.

**`notes` carries the conditions.** A zombie's iron ingot is only dropped when a
player or a tamed wolf lands the kill, and that is in `notes`, keyed by a
number, with the text as wikitext. Dropping the notes would leave a drop table
that says a zombie drops iron with no conditions attached, which reads as a
better drop rate than the game gives.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, field_validator, model_validator

from pipeline.enrich import (
    EnrichError,
    SkippedRow,
    clean_text,
    group_by,
    main_namespace,
    optional_text,
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
    "JAVA_KEY",
    "MAX_LOOTING_LEVEL",
    "DropIndex",
    "DropNote",
    "LootingDrop",
    "MobDrop",
    "Ratio",
    "fetch_drop_tables",
    "parse_drop_tables",
]

BUCKET = "droptable"

# `item` is the dropped item's display name, which joins through the
# `resource_location` table. `page_name` is the mob's page, which is both the
# grouping key and the attribution URL.
COLUMNS = ("page_name", "item", "json")

# The key of the edition this project keeps. The sibling `bedrock` key is never
# read; see the module docstring.
JAVA_KEY = "java"

# Looting III is the highest level of the enchantment, so the wiki's per-level
# keys run 0 to 3. A key outside that range means the wiki changed shape, so it
# is reported rather than parsed into a level nothing can render.
MAX_LOOTING_LEVEL = 3


class Ratio(BaseModel, frozen=True):
    """An exact fraction, as the wiki writes every probability and average."""

    numerator: int
    denominator: int

    @field_validator("denominator")
    @classmethod
    def _denominator_cannot_be_zero(cls, value: int) -> int:
        """Refuse a fraction with no value."""
        if value == 0:
            raise EnrichError("a drop ratio cannot have a denominator of zero.")
        return value

    @property
    def value(self) -> float:
        """Return the fraction as a float, for the renderer that wants one."""
        return self.numerator / self.denominator


class DropNote(BaseModel, frozen=True):
    """One condition on a drop, as wikitext.

    `name` is the wiki's own key for the note, such as `player_or_pet`, and it
    repeats across mobs, so a renderer can group identical conditions. `content`
    is wikitext with `[[links]]` still in it; resolving those into `EntityRef`
    objects is the normalize stage's job, not this one's.
    """

    name: str | None
    content: str


class LootingDrop(BaseModel, frozen=True):
    """What one mob drops of one item at one looting level."""

    looting_level: int
    minimum: int
    maximum: int
    average: Ratio
    # The probability that the drop happens at all, as opposed to how many.
    drop_chance: Ratio
    # How many items drop, and with what probability. Keyed by the count, so
    # `{0: 1/3, 1: 1/3, 2: 1/3}` reads as an even split over none, one, and two.
    distribution: Mapping[int, Ratio]
    # The wiki's own rendering of the range, entity-decoded: `0-3`.
    quantity_text: str


class MobDrop(BaseModel, frozen=True):
    """One item that one mob drops, at every looting level the wiki records."""

    mob: str
    item: str
    page: str
    wiki_url: str
    notes: tuple[DropNote, ...]
    by_looting_level: tuple[LootingDrop, ...]

    def at_looting(self, level: int) -> LootingDrop | None:
        """Return the drop at `level`, or `None` when the wiki records none."""
        for drop in self.by_looting_level:
            if drop.looting_level == level:
                return drop
        return None


class DropIndex(BaseModel, frozen=True):
    """Every Java drop the wiki records, indexed by mob and by item."""

    drops: tuple[MobDrop, ...]
    by_mob: Mapping[str, tuple[MobDrop, ...]]
    by_item: Mapping[str, tuple[MobDrop, ...]]
    skipped: tuple[SkippedRow, ...] = ()

    @classmethod
    def build(
        cls, drops: Sequence[MobDrop], skipped: Sequence[SkippedRow] = ()
    ) -> "DropIndex":
        """Return an index over `drops`, with both lookups computed."""
        return cls(
            drops=tuple(drops),
            by_mob=group_by(drops, lambda drop: drop.mob),
            by_item=group_by(drops, lambda drop: drop.item),
            skipped=tuple(skipped),
        )

    @model_validator(mode="after")
    def _indexes_must_match_the_drops(self) -> "DropIndex":
        """Refuse an index that does not index its own drops."""
        if dict(self.by_mob) != group_by(self.drops, lambda drop: drop.mob):
            raise EnrichError("the mob index does not match the drops of this table.")
        if dict(self.by_item) != group_by(self.drops, lambda drop: drop.item):
            raise EnrichError("the item index does not match the drops of this table.")
        return self


def _ratio(value: Any, *, field: str, source: str) -> Ratio:
    """Return `value` as a `Ratio`, or raise `EnrichError`."""
    if not isinstance(value, Mapping):
        raise EnrichError(f"{source} answered {field!r} as {value!r}, not a fraction.")
    numerator = value.get("numerator")
    denominator = value.get("denominator")
    if not isinstance(numerator, int) or not isinstance(denominator, int):
        raise EnrichError(f"{source} answered {field!r} as {dict(value)!r}, not two integers.")
    return Ratio(numerator=numerator, denominator=denominator)


def _integer(document: Mapping[str, Any], field: str, *, source: str) -> int:
    """Return the integer at `field`, or raise `EnrichError`."""
    value = document.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise EnrichError(f"{source} answered {field!r} as {value!r}, not an integer.")
    return value


def _parse_level(level: str, payload: Any, *, source: str) -> LootingDrop:
    """Return one looting level of the `java` object, or raise `EnrichError`."""
    try:
        looting_level = int(level)
    except ValueError as error:
        raise EnrichError(f"{source} answered a looting level of {level!r}.") from error
    if not 0 <= looting_level <= MAX_LOOTING_LEVEL:
        raise EnrichError(
            f"{source} answered looting level {looting_level}, which is outside 0 to "
            f"{MAX_LOOTING_LEVEL}."
        )
    if not isinstance(payload, Mapping):
        raise EnrichError(f"{source} answered looting {level} as {payload!r}, not an object.")
    raw_distribution = payload.get("distribution")
    if not isinstance(raw_distribution, Mapping):
        raise EnrichError(f"{source} answered no distribution for looting {level}.")
    distribution: dict[int, Ratio] = {}
    for count, chance in raw_distribution.items():
        try:
            dropped = int(count)
        except ValueError as error:
            raise EnrichError(f"{source} answered a drop count of {count!r}.") from error
        distribution[dropped] = _ratio(chance, field=f"distribution[{count}]", source=source)
    quantity_text = optional_text(payload, "quantitytext")
    return LootingDrop(
        looting_level=looting_level,
        minimum=_integer(payload, "min", source=source),
        maximum=_integer(payload, "max", source=source),
        average=_ratio(payload.get("average"), field="average", source=source),
        drop_chance=_ratio(payload.get("dropchance"), field="dropchance", source=source),
        distribution=distribution,
        quantity_text=quantity_text if quantity_text is not None else "",
    )


def _parse_notes(payload: Any, *, source: str) -> tuple[DropNote, ...]:
    """Return the conditions on a drop, in the wiki's own numbered order.

    Three things mean "no condition", and the third is the one that catches a
    reader out: the key is absent, the value is an empty object, or the value is
    an empty *list*. The wiki's notes are a PHP array keyed by number, and PHP
    encodes an empty array as `[]` and a populated one as `{"1": ...}`, so the
    JSON type of this field changes with its contents. 190 of the 233 rows carry
    the list form.

    The keys are numbers written as strings and they decide the order the wiki
    shows the notes in, so they sort numerically rather than as text -- `10`
    after `9`, which string order would get backwards.
    """
    if payload is None:
        return ()
    if isinstance(payload, list):
        if payload:
            raise EnrichError(f"{source} answered notes as a non-empty list: {payload!r}.")
        return ()
    if not isinstance(payload, Mapping):
        raise EnrichError(f"{source} answered notes as {payload!r}, not an object.")

    def order(key: str) -> tuple[int, str]:
        try:
            return (int(key), "")
        except ValueError:
            return (0, key)

    notes = []
    for key in sorted(payload, key=order):
        note = payload[key]
        if not isinstance(note, Mapping):
            raise EnrichError(f"{source} answered note {key!r} as {note!r}, not an object.")
        content = optional_text(note, "content")
        if content is None:
            continue
        notes.append(DropNote(name=optional_text(note, "name"), content=content))
    return tuple(notes)


def parse_drop_tables(rows: Sequence[Mapping[str, Any]], *, source: str = BUCKET) -> DropIndex:
    """Return the Java drop tables of `rows`, and a report of what was dropped.

    Pure. A row is kept when it is on a main-namespace page, names an item, and
    has a `java` key. A row with only a `bedrock` key is a Bedrock-only drop:
    it is skipped and reported, because a build that silently produced 166 of
    233 rows and a build whose scrape half-failed look identical without the
    report.

    A row whose `java` object is malformed raises rather than skipping. The
    blob is machine-generated by a wiki template, so one row that does not parse
    means the template changed and the other 165 are suspect too.
    """
    kept, skipped = main_namespace(rows, source=source)
    drops: list[MobDrop] = []
    for row in kept:
        page = row_page_name(row, source=source)
        document = row_json(row, source=source)
        item = optional_text(row, "item")
        if item is None:
            skipped.append(SkippedRow(page=page, subject=None, reason="the row names no item"))
            continue
        java = document.get(JAVA_KEY)
        if java is None:
            skipped.append(
                SkippedRow(
                    page=page,
                    subject=item,
                    reason="the wiki records this drop for Bedrock Edition only",
                )
            )
            continue
        if not isinstance(java, Mapping):
            raise EnrichError(f"{source} answered {JAVA_KEY!r} as {java!r}, not an object.")
        where = f"{source} row {page}/{item}"
        levels = [_parse_level(level, payload, source=where) for level, payload in java.items()]
        # The mob's own name comes from the blob rather than from the page
        # title, because the two differ where a page covers several mobs.
        mob = optional_text(document, "name")
        drops.append(
            MobDrop(
                mob=mob if mob is not None else clean_text(page),
                item=item,
                page=page,
                wiki_url=wiki_url(page),
                notes=_parse_notes(document.get("notes"), source=where),
                by_looting_level=tuple(sorted(levels, key=lambda drop: drop.looting_level)),
            )
        )
    return DropIndex.build(drops, skipped)


def fetch_drop_tables(
    *,
    revision: str,
    cache: ContentCache | None = None,
    transport: Transport | None = None,
) -> DropIndex:
    """Fetch the `droptable` bucket and return its Java drop tables.

    No `where` clause: the edition lives inside the JSON column, which Bucket
    cannot filter on, so the whole table crosses the wire and the Java filter
    runs in `parse_drop_tables`. At 233 rows that is one request.
    """
    rows = fetch_bucket_rows(
        BUCKET,
        COLUMNS,
        revision=revision,
        cache=cache,
        transport=transport,
    )
    return parse_drop_tables(rows)
