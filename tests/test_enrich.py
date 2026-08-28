"""The rules every Bucket reader of the enrich stage shares.

`pipeline.enrich` holds the four things that are true of every bucket: the
namespace filter that keeps translations and sandboxes out, the `page_name`
column that carries provenance, the HTML unescaping that makes a display name a
usable join key, and the three separate spellings of "no value" that a Bucket
row uses.

A fault in any of them reaches all six readers at once, which is why they are
tested here rather than six times over.

No test in this module opens a socket. Nothing it calls can.
"""

import pytest

from pipeline.enrich import (
    EMPTY_MARKER,
    EnrichError,
    IntegerRange,
    clean_text,
    group_by,
    is_main_namespace,
    main_namespace,
    optional_text,
    parse_integer_range,
    required_text,
    row_json,
    row_page_name,
    text_or_none,
    wiki_url,
)

SOURCE = "test"


# --- The namespace filter --------------------------------------------------


@pytest.mark.parametrize(
    "page",
    ["Stone", "Eye of Ender", "Piston/Technical components", "Java Edition 1.12"],
)
def test_a_main_namespace_article_is_kept(page: str) -> None:
    """A main-namespace title holds no colon, subpages included.

    The subpage case matters: `Piston/Technical components` is a real article
    that carries real blocks, so a filter written against the slash rather than
    the colon would drop it.
    """
    assert is_main_namespace(page)


@pytest.mark.parametrize(
    "page",
    [
        "User:Hipposgrumm/Memes/Bucketolotl",
        "Minecraft Wiki:Projects/Hebrew translation/חול",
        "Forum:Something",
        "Chaos Cubed:A recipe",
    ],
)
def test_a_page_outside_the_main_namespace_is_dropped(page: str) -> None:
    """Every namespace the buckets reach is one this project does not want."""
    assert not is_main_namespace(page)


def test_the_namespace_split_reports_what_it_dropped() -> None:
    """A dropped row is reported with the namespace that dropped it.

    An empty result and a filtered-away result look identical without the
    report, and CLAUDE.md treats an empty scrape as a failure to investigate.
    """
    rows = [
        {"page_name": "Stone", "json": "{}"},
        {"page_name": "User:Someone/Sandbox", "json": "{}"},
    ]
    kept, skipped = main_namespace(rows, source=SOURCE)

    assert [row["page_name"] for row in kept] == ["Stone"]
    assert len(skipped) == 1
    assert skipped[0].page == "User:Someone/Sandbox"
    assert "User: page" in skipped[0].reason


def test_a_row_with_no_page_name_raises() -> None:
    """Provenance is not optional: without it there is no filter and no URL."""
    with pytest.raises(EnrichError, match="page_name"):
        row_page_name({"display_name": "Stone"}, source=SOURCE)


# --- The JSON column -------------------------------------------------------


def test_the_json_column_is_decoded_a_second_time() -> None:
    """The column holds a JSON document as a string inside a JSON answer."""
    assert row_json({"json": '{"Edition": "java"}'}, source=SOURCE) == {"Edition": "java"}


@pytest.mark.parametrize(
    "row",
    [
        {"item": "Arrow"},
        {"json": None},
        {"json": "not json"},
        {"json": "[]"},
        {"json": '"a string"'},
    ],
)
def test_a_json_column_that_is_not_an_object_raises(row: dict[str, object]) -> None:
    """A table this pipeline no longer understands stops the build.

    This is the shape-level fault rather than the row-level one, so it raises
    instead of being skipped. `[]` is in the list because PHP encodes an empty
    array that way, and a reader that accepted it here would then have to guess
    what an empty list of fields meant.
    """
    with pytest.raises(EnrichError):
        row_json(row, source=SOURCE)


# --- Text ------------------------------------------------------------------


def test_html_entities_are_resolved() -> None:
    """An escaped name is not a join key, because nothing else spells it that way."""
    assert clean_text("Bottle o&#39; Enchanting") == "Bottle o' Enchanting"
    assert clean_text("0&ndash;3") == "0–3"


@pytest.mark.parametrize("value", [None, "", "   ", EMPTY_MARKER, 42])
def test_the_three_spellings_of_no_value_all_read_as_none(value: object) -> None:
    """Absent, empty, and the em dash the wiki writes all mean the same thing.

    The em dash is the one that catches a reader out. It is content, so a test
    for absence or emptiness passes it through, and it would then be rendered as
    an advancement's parent or as a description.
    """
    assert text_or_none(value) is None


def test_a_required_field_that_is_an_em_dash_raises() -> None:
    """`required_text` uses the same three rules, so the dash fails it too."""
    with pytest.raises(EnrichError, match="parent"):
        required_text({"parent": EMPTY_MARKER}, "parent", source=SOURCE)


def test_optional_text_returns_the_cleaned_value() -> None:
    """Present text comes back unescaped and trimmed."""
    assert optional_text({"name": "  Raw Iron  "}, "name") == "Raw Iron"


# --- URLs ------------------------------------------------------------------


def test_a_page_becomes_a_wiki_url() -> None:
    """Only the space-to-underscore substitution is applied.

    Percent-encoding the whole title would make the URL unreadable for the
    attribution link the licence requires, and the title is a path, not a query
    parameter.
    """
    assert wiki_url("Eye of Ender") == "https://minecraft.wiki/w/Eye_of_Ender"


# --- Grouping and ranges ---------------------------------------------------


def test_grouping_keeps_the_order_items_arrived_in() -> None:
    """Order is what makes an index reproducible across builds."""
    assert group_by(["ab", "ac", "bd"], lambda text: text[0]) == {
        "a": ("ab", "ac"),
        "b": ("bd",),
    }


@pytest.mark.parametrize(
    ("text", "minimum", "maximum"),
    [("4", 4, 4), ("2-4", 2, 4), ("5–64", 5, 64), (" 7 - 21 ", 7, 21)],
)
def test_a_range_reads_both_dashes(text: str, minimum: int, maximum: int) -> None:
    """The wiki writes ranges with a hyphen in some places and an en dash in others.

    A parser that took only one would drop the other silently, and both appear
    in fields this stage reads: `2-4` as a spawn group size, `5–64` as the
    emerald price of an enchanted book.
    """
    assert parse_integer_range(text, source=SOURCE) == IntegerRange(
        minimum=minimum, maximum=maximum
    )


def test_a_fixed_number_is_a_range_with_equal_ends() -> None:
    """Callers ask `is_fixed` rather than comparing the two fields themselves."""
    assert parse_integer_range("4", source=SOURCE).is_fixed
    assert not parse_integer_range("2-4", source=SOURCE).is_fixed


@pytest.mark.parametrize("text", ["", "many", "1-2-3", "-4", "4+"])
def test_a_quantity_the_wiki_has_not_written_raises(text: str) -> None:
    """Inventing a number would put a quantity on a page that nothing wrote."""
    with pytest.raises(EnrichError):
        parse_integer_range(text, source=SOURCE)


def test_a_range_that_runs_backwards_is_refused() -> None:
    """The model refuses it even when no parser would build it."""
    with pytest.raises(EnrichError, match="cannot run"):
        IntegerRange(minimum=9, maximum=2)
