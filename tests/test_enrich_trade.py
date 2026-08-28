"""Trades: the probability field that is kept, the one that is not, and the ranges.

`pipeline.enrich.trade` reads a bucket that carries both editions as two fields
of the same row. CLAUDE.md says to keep `java_probability` and drop
`bedrock_probability`, and this module proves the second is never read even when
it disagrees with the first.

`parse_trades` is pure, so nothing here opens a socket.
"""

import json
from typing import Any

import pytest

from pipeline.enrich import EnrichError, IntegerRange
from pipeline.enrich.trade import (
    TradeIndex,
    parse_probability,
    parse_trades,
)

SOURCE = "test"


def row(
    profession: str,
    *,
    level: str = "Novice",
    wanted: str = "Paper",
    wanted_quantity: str = "24",
    given: str = "Emerald",
    given_quantity: str = "1",
    java: str = "67%",
    bedrock: str = "100%",
    max_trades: str = "16",
    xp: str | None = "2",
    multiplier: str | None = "0.05",
    **extra: Any,
) -> dict[str, Any]:
    """Return one `trade` row, shaped the way the live API sends it."""
    document: dict[str, Any] = {
        "profession": profession,
        "level": level,
        "wanted_item": wanted,
        "wanted_quant": wanted_quantity,
        "given_item": given,
        "given_quant": given_quantity,
        "java_probability": java,
        "bedrock_probability": bedrock,
        "max_trades": max_trades,
        **extra,
    }
    if xp is not None:
        document["villager_xp_gain"] = xp
    if multiplier is not None:
        document["price_multiplier"] = multiplier
    return {"page_name": profession, "profession": profession, "json": json.dumps(document)}


def test_a_trade_reads_from_the_players_side() -> None:
    """The wiki names the fields from the villager's side; a page reads the other way.

    A librarian's first trade is 24 paper for one emerald, so `wanted` is the
    paper and `given` is the emerald.
    """
    index = parse_trades([row("Librarian")])

    trade = index.trades[0]
    assert trade.wanted[0].item == "Paper"
    assert trade.wanted[0].quantity == IntegerRange(minimum=24, maximum=24)
    assert trade.given.item == "Emerald"
    assert trade.given.quantity == IntegerRange(minimum=1, maximum=1)


def test_the_bedrock_probability_is_never_read() -> None:
    """The two fields disagree on most trades, and only one belongs in this project."""
    index = parse_trades([row("Librarian", java="67%", bedrock="100%")])

    probability = index.trades[0].java_probability
    assert probability is not None
    assert probability.text == "67%"
    assert probability.low == pytest.approx(0.67)
    assert "bedrock" not in index.trades[0].model_dump_json()


def test_a_trade_the_wiki_gives_no_java_chance_is_skipped() -> None:
    """A Java probability of zero means the trade belongs to the other edition."""
    index = parse_trades([row("Librarian", java="0%")])

    assert index.trades == ()
    assert "0%" in index.skipped[0].reason


def test_a_probability_can_be_a_span() -> None:
    """`50%–67%` appears on the live table; a single figure is a span with equal ends."""
    span = parse_probability("50%–67%", source=SOURCE)

    assert span.low == pytest.approx(0.5)
    assert span.high == pytest.approx(0.67)
    assert not span.is_fixed
    assert parse_probability("67%", source=SOURCE).is_fixed


def test_a_probability_above_one_hundred_percent_is_kept_as_written() -> None:
    """`133%–150%` is a wandering trader row; the wiki means offer counts there.

    Clamping it would replace a published oddity with a number this project
    invented, which is worse.
    """
    span = parse_probability("133%–150%", source=SOURCE)

    assert span.high == pytest.approx(1.5)
    assert span.text == "133%–150%"


def test_a_price_can_be_a_range() -> None:
    """An enchanted book costs `5–64` emeralds depending on the enchantment.

    A parser that typed quantities `int` would pass on every other trade and
    fail on this one, on a live build.
    """
    index = parse_trades([row("Librarian", wanted="Emerald", wanted_quantity="5–64")])

    assert index.trades[0].wanted[0].quantity == IntegerRange(minimum=5, maximum=64)


def test_a_trade_can_want_two_items() -> None:
    """13 live trades do: emeralds plus the item being enchanted or repaired."""
    index = parse_trades(
        [
            row(
                "Librarian",
                wanted="Emerald",
                wanted_quantity="5–64",
                wanted_item_2="Book",
                wanted_quant_2="1",
                given="Enchanted Book",
            )
        ]
    )

    assert [item.item for item in index.trades[0].wanted] == ["Emerald", "Book"]


def test_a_second_quantity_without_a_second_item_is_ignored() -> None:
    """`wanted_quant_2` is on all 280 rows; `wanted_item_2` is on 13.

    A quantity with nothing to count means nothing, so the item decides whether
    the pair exists.
    """
    index = parse_trades([row("Librarian", wanted_quant_2="1")])

    assert len(index.trades[0].wanted) == 1


def test_notes_are_kept_as_wikitext() -> None:
    """Resolving `[[links]]` needs the whole entity table, which this stage has not."""
    index = parse_trades(
        [
            row(
                "Librarian",
                given_note="librarian_enchant_book",
                given_note_text="A random [[enchantment]].",
            )
        ]
    )

    assert index.trades[0].given.note == "librarian_enchant_book"
    assert index.trades[0].given.note_text == "A random [[enchantment]]."


def test_trades_group_by_level_in_ladder_order() -> None:
    """This is the shape a profession page renders."""
    index = parse_trades(
        [
            row("Librarian", level="Master", given="Red Candle"),
            row("Librarian", level="Novice"),
            row("Librarian", level="Apprentice", given="Lantern"),
        ]
    )

    assert [level for level, _ in index.by_level("Librarian")] == [
        "Novice",
        "Apprentice",
        "Master",
    ]


def test_the_wandering_trader_has_its_own_ladder() -> None:
    """Its levels are Ordinary, Special, and Purchase, not Novice through Master."""
    index = parse_trades(
        [
            row("Wandering Trader", level="Purchase", xp=None, multiplier=None),
            row("Wandering Trader", level="Ordinary", xp=None, multiplier=None),
        ]
    )

    assert [level for level, _ in index.by_level("Wandering Trader")] == [
        "Ordinary",
        "Purchase",
    ]


def test_an_unknown_level_sorts_last_rather_than_dropping_the_trade() -> None:
    """A level this project has not seen is a new label, not a reason to lose data."""
    index = parse_trades(
        [row("Librarian", level="Legendary"), row("Librarian", level="Novice")]
    )

    assert [level for level, _ in index.by_level("Librarian")] == ["Novice", "Legendary"]


def test_a_profession_with_no_trades_gives_an_empty_grouping() -> None:
    """A caller that wants that reported can see the empty tuple."""
    assert parse_trades([]).by_level("Nitwit") == ()


def test_the_given_item_index_answers_the_question_an_item_page_asks() -> None:
    """"Who sells this?" is the direction an item page needs."""
    index = parse_trades([row("Librarian", given="Lantern")])

    assert index.by_given_item["Lantern"][0].profession == "Librarian"


def test_a_quantity_that_is_not_a_quantity_raises() -> None:
    """One template writes this blob, so a bad field means it moved."""
    with pytest.raises(EnrichError):
        parse_trades([row("Librarian", wanted_quantity="lots")])


def test_an_index_that_does_not_index_its_own_trades_is_refused() -> None:
    """The lookups are fields on a frozen model, so they are checked, not trusted."""
    trade = parse_trades([row("Librarian")]).trades[0]

    with pytest.raises(EnrichError, match="profession index"):
        TradeIndex(trades=(trade,), by_profession={}, by_given_item={})
