"""Villager and wandering trader trades, grouped by profession and level. Java only.

280 rows, one per trade, each on the page of the profession that offers it. This
is the source for the villager-profession pages of Phase 6c -- typing `librarian`
should open that profession's trades grouped Novice through Master -- and for
the item side of the same fact, which is that a page for an item a villager sells
should say which villager sells it.

**The edition split is two fields, and only one of them is ever read here.**
`java_probability` and `bedrock_probability` sit side by side in every row and
disagree constantly: the librarian's first paper trade is 67% in Java and 100% in
Bedrock, and the bookshelf trade is 67% against 50%. CLAUDE.md says to keep the
first and drop the second, and this module does not so much as parse the second.
A trade the wiki gives a Java probability of 0% does not exist in Java and is
skipped with that reason.

**A probability is a range, and it can exceed 100%.** Most are a single figure
like `67%`, but `50%–67%`, `133%–150%`, and `150%–167%` all appear. The figures
above 100% are the wandering trader's, where the wiki is describing how many
offers of a kind appear rather than whether one does. They are kept as written
rather than clamped: a number this module invented would be worse than the odd
one the wiki published, and the raw text is kept beside the parsed range so a
renderer can show what the source said.

**A quantity is a range too.** Most trades want a fixed count, but an enchanted
book costs `5–64` emeralds depending on the enchantment and several others
carry spans like `7-21`. A parser that typed these `int` would work against the
first rows it met and fail on a live build, so every quantity here is an
`IntegerRange`.

**`level` means two different ladders.** Villagers have Novice, Apprentice,
Journeyman, Expert, and Master. The wandering trader, which is 97 of the 280
rows, has Ordinary, Special, and Purchase instead. `LEVEL_ORDER` puts them in
that order for display and leaves an unrecognised level at the end rather than
dropping the trade -- a level this project has not seen is a new label, not a
reason to lose a trade.

Note text is kept as wikitext, `[[links]]` intact. Resolving those into
`EntityRef` objects belongs to the normalize stage, which is the only stage that
has the whole entity table to resolve them against.
"""

import re
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
    "JAVA_PROBABILITY",
    "LEVEL_ORDER",
    "Probability",
    "TradeIndex",
    "TradeItem",
    "WikiTrade",
    "fetch_trades",
    "level_rank",
    "parse_probability",
    "parse_trades",
]

BUCKET = "trade"

COLUMNS = ("page_name", "profession", "json")

# The one probability field this module reads. Its Bedrock sibling is named here
# only so that a reader can see it is deliberately absent from everything below.
JAVA_PROBABILITY = "java_probability"
BEDROCK_PROBABILITY = "bedrock_probability"

# The display order of the two ladders: the five villager levels, then the three
# the wandering trader uses.
LEVEL_ORDER = (
    "Novice",
    "Apprentice",
    "Journeyman",
    "Expert",
    "Master",
    "Ordinary",
    "Special",
    "Purchase",
)

# A probability, as a percentage or a span of them. Both dashes appear.
PROBABILITY = re.compile(
    r"(?P<low>\d+(?:\.\d+)?)%(?:\s*[-–]\s*(?P<high>\d+(?:\.\d+)?)%)?\Z"
)


def level_rank(level: str) -> tuple[int, str]:
    """Return the sort key of a trade level.

    Known levels sort in `LEVEL_ORDER`. An unknown one sorts after all of them,
    alphabetically among its own kind, so a level the wiki adds appears at the
    end of a profession's page instead of vanishing from it.
    """
    if level in LEVEL_ORDER:
        return (LEVEL_ORDER.index(level), "")
    return (len(LEVEL_ORDER), level)


class Probability(BaseModel, frozen=True):
    """How likely a trade is to be offered, as the wiki writes it.

    `low` and `high` are fractions of one, so `67%` is 0.67. They are equal for
    a single figure. `text` is what the wiki actually published, kept because
    the parsed pair cannot represent everything a wiki editor might write next.
    """

    text: str
    low: float
    high: float

    @model_validator(mode="after")
    def _low_cannot_exceed_the_high(self) -> "Probability":
        """Refuse a span that runs backwards."""
        if self.low > self.high:
            raise EnrichError(f"a probability cannot run from {self.low} to {self.high}.")
        return self

    @property
    def is_fixed(self) -> bool:
        """Return whether the probability is a single figure rather than a span."""
        return self.low == self.high


class TradeItem(BaseModel, frozen=True):
    """One side of a trade: an item, how many, and any condition on it."""

    item: str
    quantity: IntegerRange
    # The wiki's key for the note, such as `librarian_enchant_price`, which
    # repeats across trades, and the note itself as wikitext.
    note: str | None = None
    note_text: str | None = None


class WikiTrade(BaseModel, frozen=True):
    """One trade a profession offers at one level.

    `wanted` is what the player hands over and `given` is what comes back. The
    wiki's field names read from the villager's side, so a librarian's first
    trade has `wanted` of 24 paper and `given` of one emerald.
    """

    profession: str
    page: str
    wiki_url: str
    level: str
    # One or two items. A second appears on 13 trades, all of them a book or a
    # tool paid for with emeralds and the item itself.
    wanted: tuple[TradeItem, ...]
    given: TradeItem
    java_probability: Probability | None
    max_trades: IntegerRange | None
    villager_xp: int | None
    price_multiplier: float | None

    @property
    def level_rank(self) -> tuple[int, str]:
        """Return the display rank of this trade's level."""
        return level_rank(self.level)


class TradeIndex(BaseModel, frozen=True):
    """Every Java trade the wiki records, indexed by profession and by item."""

    trades: tuple[WikiTrade, ...]
    by_profession: Mapping[str, tuple[WikiTrade, ...]]
    # Keyed by what the player receives, which is the direction an item page
    # asks in: "who sells this?"
    by_given_item: Mapping[str, tuple[WikiTrade, ...]]
    skipped: tuple[SkippedRow, ...] = ()

    @classmethod
    def build(
        cls, trades: Sequence[WikiTrade], skipped: Sequence[SkippedRow] = ()
    ) -> "TradeIndex":
        """Return an index over `trades`, with both lookups computed."""
        return cls(
            trades=tuple(trades),
            by_profession=group_by(trades, lambda trade: trade.profession),
            by_given_item=group_by(trades, lambda trade: trade.given.item),
            skipped=tuple(skipped),
        )

    @model_validator(mode="after")
    def _indexes_must_match_the_trades(self) -> "TradeIndex":
        """Refuse an index that does not index its own trades."""
        if dict(self.by_profession) != group_by(self.trades, lambda trade: trade.profession):
            raise EnrichError("the profession index does not match the trades of this table.")
        if dict(self.by_given_item) != group_by(self.trades, lambda trade: trade.given.item):
            raise EnrichError("the given-item index does not match the trades of this table.")
        return self

    def by_level(self, profession: str) -> tuple[tuple[str, tuple[WikiTrade, ...]], ...]:
        """Return one profession's trades grouped by level, in ladder order.

        This is the shape a profession page renders: Novice through Master for a
        villager, Ordinary through Purchase for the wandering trader. An unknown
        profession gives an empty result rather than raising -- a profession
        with no trades is a fact about the wiki, and the caller that wants it
        reported can see the empty tuple.
        """
        grouped = group_by(self.by_profession.get(profession, ()), lambda trade: trade.level)
        return tuple(
            (level, grouped[level]) for level in sorted(grouped, key=level_rank)
        )


def parse_probability(text: str, *, source: str) -> Probability:
    """Return the probability `text` describes, or raise `EnrichError`.

    `67%` gives 0.67 twice. `50%–67%` gives 0.5 and 0.67. Figures above 100% are
    accepted; the module docstring holds why.
    """
    match = PROBABILITY.fullmatch(text.strip())
    if match is None:
        raise EnrichError(f"{source} answered a probability of {text!r}.")
    low = float(match["low"]) / 100
    high = float(match["high"]) / 100 if match["high"] is not None else low
    return Probability(text=text.strip(), low=low, high=high)


def _integer(document: Mapping[str, Any], field: str, *, source: str) -> int | None:
    """Return the whole number at `field`, or `None` when the field is absent.

    Raises when the field is present and is not a whole number, because the
    fields read through here -- experience, and nothing else -- are counts that
    the wiki writes as digits, and a non-number means the template moved.
    """
    value = optional_text(document, field)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as error:
        raise EnrichError(f"{source} answered {field!r} as {value!r}, not a number.") from error


def _float(document: Mapping[str, Any], field: str, *, source: str) -> float | None:
    """Return the decimal at `field`, or `None` when the field is absent."""
    value = optional_text(document, field)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError as error:
        raise EnrichError(f"{source} answered {field!r} as {value!r}, not a number.") from error


def _trade_item(
    document: Mapping[str, Any],
    *,
    item_field: str,
    quantity_field: str,
    note_field: str,
    note_text_field: str,
    source: str,
) -> TradeItem | None:
    """Return one side of a trade, or `None` when the item is absent.

    The quantity defaults to one. `wanted_quant_2` is present on all 280 rows
    even though `wanted_item_2` is present on 13, so a quantity without an item
    means nothing and this returns `None` on the item rather than on the pair.
    """
    item = optional_text(document, item_field)
    if item is None:
        return None
    quantity = optional_text(document, quantity_field)
    return TradeItem(
        item=item,
        quantity=(
            parse_integer_range(quantity, source=source)
            if quantity is not None
            else IntegerRange(minimum=1, maximum=1)
        ),
        note=optional_text(document, note_field),
        note_text=optional_text(document, note_text_field),
    )


def parse_trades(rows: Sequence[Mapping[str, Any]], *, source: str = BUCKET) -> TradeIndex:
    """Return the Java trades of `rows`, and a report of what was dropped.

    Pure. A row is skipped, with a reason, when it is outside the main
    namespace, when it names no item on one side, and when its Java probability
    is zero, which is the wiki saying the trade is Bedrock's alone.

    A row that names its items but whose numbers will not parse raises: the
    blob comes from one template, so a quantity that is not a quantity means the
    template changed and every other row is suspect.
    """
    kept, skipped = main_namespace(rows, source=source)
    trades: list[WikiTrade] = []
    for row in kept:
        page = row_page_name(row, source=source)
        document = row_json(row, source=source)
        profession = optional_text(document, "profession") or optional_text(row, "profession")
        if profession is None:
            skipped.append(
                SkippedRow(page=page, subject=None, reason="the row names no profession")
            )
            continue
        where = f"{source} row {page}"
        given = _trade_item(
            document,
            item_field="given_item",
            quantity_field="given_quant",
            note_field="given_note",
            note_text_field="given_note_text",
            source=where,
        )
        first_wanted = _trade_item(
            document,
            item_field="wanted_item",
            quantity_field="wanted_quant",
            note_field="wanted_note",
            note_text_field="wanted_note_text",
            source=where,
        )
        if given is None or first_wanted is None:
            skipped.append(
                SkippedRow(
                    page=page,
                    subject=given.item if given is not None else None,
                    reason="the row names no item on one side of the trade",
                )
            )
            continue
        wanted = [first_wanted]
        second_wanted = _trade_item(
            document,
            item_field="wanted_item_2",
            quantity_field="wanted_quant_2",
            note_field="wanted_note_2",
            note_text_field="wanted_note_text_2",
            source=where,
        )
        if second_wanted is not None:
            wanted.append(second_wanted)

        raw_probability = optional_text(document, JAVA_PROBABILITY)
        probability = (
            parse_probability(raw_probability, source=where)
            if raw_probability is not None
            else None
        )
        if probability is not None and probability.high == 0:
            skipped.append(
                SkippedRow(
                    page=page,
                    subject=given.item,
                    reason="the wiki gives this trade a Java probability of 0%",
                )
            )
            continue
        max_trades = optional_text(document, "max_trades")
        trades.append(
            WikiTrade(
                profession=profession,
                page=page,
                wiki_url=wiki_url(page),
                level=required_text(document, "level", source=where),
                wanted=tuple(wanted),
                given=given,
                java_probability=probability,
                max_trades=(
                    parse_integer_range(max_trades, source=where)
                    if max_trades is not None
                    else None
                ),
                villager_xp=_integer(document, "villager_xp_gain", source=where),
                price_multiplier=_float(document, "price_multiplier", source=where),
            )
        )
    return TradeIndex.build(trades, skipped)


def fetch_trades(
    *,
    revision: str,
    cache: ContentCache | None = None,
    transport: Transport | None = None,
) -> TradeIndex:
    """Fetch the `trade` bucket and return its Java trades.

    No `where` clause: the edition is not a column here but a pair of fields
    inside the JSON blob, so the filter can only run once the rows are in hand.
    At 280 rows that is one request.
    """
    rows = fetch_bucket_rows(
        BUCKET,
        COLUMNS,
        revision=revision,
        cache=cache,
        transport=transport,
    )
    return parse_trades(rows)
