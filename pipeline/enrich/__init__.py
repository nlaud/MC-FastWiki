"""Turn Bucket rows into the models that the normalize stage merges.

`pipeline.fetch.bucket` returns what the wiki said and reads nothing. This
package reads. A module here takes the rows of one bucket and returns a model,
so every test of this package builds its rows in memory and opens no socket.

This is Tier B of the three tiers that CLAUDE.md names, and Tier B is the
presentation layer rather than the completeness layer. That difference decides
how a fault is handled here. Tier A raises and stops the build, because a
missing recipe is a wrong answer. A wiki row that cannot be read is usually a
page somebody is in the middle of editing, so a module here drops the row, says
why in a `SkippedRow`, and carries on. A fault in the *shape* of the answer --
a bucket that lost a column, a JSON blob that is not an object -- still raises
`EnrichError`, because that is the pipeline reading a table it no longer
understands.

Four rules apply to every bucket, and every one of them was learned from the
live data on 2026-08-27. They live here rather than in six copies.

**Java Edition only, and every bucket hides the edition somewhere else.**
Non-negotiable 1 of CLAUDE.md says a Bedrock number reaching the screen is a
correctness bug, and it says the filter belongs to the pipeline. There is no one
column to filter on. `resource_location` and `spawn_table` both carry an edition
field, but the first carries it as a real column that `where()` can filter and
the second carries it inside the JSON blob where `where()` cannot see it.
`droptable` splits the editions into two keys of its blob, so a Bedrock-only
drop is a row whose `java` key is absent. `trade` splits them across
`java_probability` and `bedrock_probability`. `advancement` and
`crafting_recipe` mark neither. So each module states its own filter and none of
them inherits one.

**`page_name` is a selectable column on every bucket, and it is the row's
provenance.** It appears in no `Bucket:` schema page, so it has to be found by
trying it. It names the wiki page the row was written on, which gives three
things at once: the `wikiUrl` that the licence obliges this project to show, the
grouping key for the buckets whose rows live on the page of the thing they
describe (`spawn_table` rows sit on biome pages, `trade` rows on profession
pages), and the namespace.

**The namespace filter is what makes the tables usable.** The buckets index
every page of the wiki, user sandboxes and translation projects included. Of the
3,690 Java `resource_location` rows, 966 come from `User:`, `Minecraft Wiki:`,
and `Forum:` pages: joke blocks, Hebrew and Toki Pona translations whose
`display_name` is the translated name, and abandoned drafts. Keeping them turns
`Bowl` into an entry that also answers to `poki moku` and leaves 25 display
names pointing at more than one registry ID. Dropping them leaves 2,724 rows,
which dedupe to 2,457 entries and 16 ambiguities, all of them real. A
main-namespace page name holds no colon, so that is the test.

**Text arrives HTML-escaped.** `Bottle o&#39; Enchanting` is a display name and
`0&ndash;3` is a quantity. Escaped text is not a join key -- it would never
match the same name written plainly -- so `clean_text` unescapes every string
that leaves this package, and it is applied in one place so that two buckets
cannot disagree about whether they did it.
"""

import html
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, model_validator

__all__ = [
    "EMPTY_MARKER",
    "JSON_COLUMN",
    "NAMESPACE_SEPARATOR",
    "PAGE_NAME_COLUMN",
    "WIKI_PAGE_URL",
    "EnrichError",
    "IntegerRange",
    "SkippedRow",
    "clean_text",
    "group_by",
    "is_main_namespace",
    "main_namespace",
    "optional_text",
    "parse_integer_range",
    "required_text",
    "row_json",
    "row_page_name",
    "text_or_none",
    "wiki_url",
]

# The column that names the wiki page a row was written on. Selectable on every
# bucket this pipeline reads, and named in no `Bucket:` schema page.
PAGE_NAME_COLUMN = "page_name"

# The column that holds the structured payload of a row, as a JSON string.
# Every bucket read here has one.
JSON_COLUMN = "json"

# What separates a MediaWiki namespace from a page title. A main-namespace title
# holds none, and every namespace this wiki uses puts one after the prefix.
NAMESPACE_SEPARATOR = ":"

# The wiki's article URL. CC BY-NC-SA 3.0 obliges this project to attribute, so
# every model built here keeps the page it came from.
WIKI_PAGE_URL = "https://minecraft.wiki/w/{page}"

# What the wiki writes in a field that has no value. It is an em dash, not an
# empty string, so a reader that tested for emptiness would take it as content.
EMPTY_MARKER = "—"

# How the wiki writes a whole number or a range of them: `4`, `2-4`, `5–64`.
# Both the ASCII hyphen and the en dash appear -- the en dash in hand-written
# table cells and the hyphen in template output -- and a parser that accepted
# only one would drop the other silently, so both are here.
INTEGER_RANGE = re.compile(r"(?P<minimum>\d+)\s*(?:[-–]\s*(?P<maximum>\d+))?\Z")


class EnrichError(Exception):
    """One read of a Bucket table failed.

    This is the shape-level fault, not the row-level one: a bucket that no
    longer has a column this pipeline selects, a JSON column that is not an
    object, a payload that is not JSON at all. It means the pipeline no longer
    understands the table, so the build stops rather than emitting a table with
    a hole in it.

    A single unreadable row is not this. That is a `SkippedRow`, because one
    half-edited wiki page must not stop a build.

    It mirrors `ExtractError` of the extract stage and `FetchError` of the fetch
    stage, and stays separate from both. The three names say which stage failed:
    `FetchError` points at the network or the cache, `ExtractError` at the
    vanilla data, and `EnrichError` at the wiki.
    """


class SkippedRow(BaseModel, frozen=True):
    """One row that a module read and did not keep, and the reason why.

    Every parser here returns these alongside its models. They are the report
    that CLAUDE.md asks for: an empty scrape result is a failure rather than an
    absence, and the only way to tell the two apart is to be able to say what
    was dropped and why. A Bedrock-only drop table is an expected skip; a
    display name the wiki left blank is not, and the difference is visible only
    in the reason.
    """

    page: str
    subject: str | None
    reason: str


class IntegerRange(BaseModel, frozen=True):
    """A whole number, or a span of them, as a wiki table cell writes it.

    Several fields of Tier B are ranges that look like scalars until one of them
    is not: a spawn group size is `4` in most biomes and `2-4` in some, and a
    villager's asking price is `1` for most trades and `5-64` for an enchanted
    book. A parser that read the first row of either field and typed it `int`
    would work until the day it met the second kind, then fail on a live build.
    A fixed number is the range where both ends are equal.
    """

    minimum: int
    maximum: int

    @model_validator(mode="after")
    def _minimum_cannot_exceed_the_maximum(self) -> "IntegerRange":
        """Refuse a range that runs backwards."""
        if self.minimum > self.maximum:
            raise EnrichError(f"a range cannot run from {self.minimum} to {self.maximum}.")
        return self

    @property
    def is_fixed(self) -> bool:
        """Return whether the range is a single number."""
        return self.minimum == self.maximum


def parse_integer_range(text: str, *, source: str) -> IntegerRange:
    """Return the range that `text` describes, or raise `EnrichError`.

    `4` gives 4 to 4 and `2-4` gives 2 to 4. Anything else is a shape the wiki
    has not used here, and inventing a number for it would put a quantity on a
    page that nothing wrote.
    """
    match = INTEGER_RANGE.fullmatch(text.strip())
    if match is None:
        raise EnrichError(f"{source} answered {text!r}, which is not a number or a range.")
    minimum = int(match["minimum"])
    maximum = int(match["maximum"]) if match["maximum"] is not None else minimum
    return IntegerRange(minimum=minimum, maximum=maximum)


def clean_text(value: str) -> str:
    """Return `value` with HTML entities resolved and the edges trimmed.

    Bucket answers carry wiki source text, which is HTML-escaped: a display name
    arrives as `Bottle o&#39; Enchanting` and a quantity as `0&ndash;3`. An
    escaped name is not a join key, because nothing else in the pipeline spells
    it that way, so unescaping happens once, here, for every string that leaves
    this package.
    """
    return html.unescape(value).strip()


def is_main_namespace(page: str) -> bool:
    """Return whether `page` is a main-namespace article.

    A main-namespace title holds no colon. Every other namespace on this wiki
    puts its name and a colon in front, and the ones the buckets reach are
    `User:`, `Minecraft Wiki:`, `Forum:`, and `Chaos Cubed:` -- sandboxes,
    translation projects, joke content, and drafts. The module docstring holds
    the count and what keeping them costs.
    """
    return NAMESPACE_SEPARATOR not in page


def wiki_url(page: str) -> str:
    """Return the article URL of `page`.

    A space is legal in a MediaWiki path and the wiki serves it, so the title
    goes in with only the space-to-underscore substitution that every internal
    link uses. Percent-encoding the whole title would break the anchor for
    anyone who reads the URL, and the title is not a query parameter.
    """
    return WIKI_PAGE_URL.format(page=page.replace(" ", "_"))


def row_page_name(row: Mapping[str, Any], *, source: str) -> str:
    """Return the `page_name` of `row`, or raise `EnrichError`.

    Missing means the caller did not select the column, or the wiki stopped
    serving it. Both are faults in the shape of the answer rather than in one
    row, so both raise: without provenance there is no attribution, no grouping
    key, and no namespace to filter on.
    """
    page = row.get(PAGE_NAME_COLUMN)
    if not isinstance(page, str) or not page:
        raise EnrichError(f"{source} answered a row with no {PAGE_NAME_COLUMN!r}: {dict(row)!r}")
    return page


def row_json(row: Mapping[str, Any], *, source: str) -> dict[str, Any]:
    """Return the decoded `json` column of `row`, or raise `EnrichError`.

    The column holds a JSON document as a string, so it is decoded a second time
    after the answer itself was decoded. A row that lacks it, or whose payload is
    not a JSON object, is a table this pipeline no longer understands.
    """
    payload = row.get(JSON_COLUMN)
    if not isinstance(payload, str):
        raise EnrichError(
            f"{source} answered a row with no {JSON_COLUMN!r} column: {dict(row)!r}"
        )
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as error:
        raise EnrichError(
            f"{source} answered a {JSON_COLUMN!r} column that is not JSON: {error}"
        ) from error
    if not isinstance(document, dict) or not all(isinstance(key, str) for key in document):
        raise EnrichError(
            f"{source} answered a {JSON_COLUMN!r} column that is not an object: {document!r}"
        )
    return document


def text_or_none(value: Any) -> str | None:
    """Return `value` as cleaned text, or `None` when it carries no content.

    Three things mean "no value" in a Bucket row and all three arrive as an
    ordinary field: the key is absent, because the API omits a null; the value is
    the empty string; and the value is the em dash the wiki writes in a field it
    has nothing for. A caller that tested only for absence would take an em dash
    as an advancement's parent.
    """
    if not isinstance(value, str):
        return None
    cleaned = clean_text(value)
    if not cleaned or cleaned == EMPTY_MARKER:
        return None
    return cleaned


def optional_text(document: Mapping[str, Any], field: str) -> str | None:
    """Return the cleaned text of `field`, or `None` when it carries no content."""
    return text_or_none(document.get(field))


def required_text(document: Mapping[str, Any], field: str, *, source: str) -> str:
    """Return the cleaned text of `field`, or raise `EnrichError`.

    For a field that every row of a bucket was observed to carry, and whose
    absence would mean the schema moved rather than that one page is incomplete.
    """
    value = optional_text(document, field)
    if value is None:
        raise EnrichError(f"{source} answered no {field!r}: {dict(document)!r}")
    return value


def group_by[T](items: Sequence[T], key: Callable[[T], str]) -> dict[str, tuple[T, ...]]:
    """Return `items` grouped by `key`, each group in the order it arrived.

    Every index this package exposes is built with this, and every index model
    also re-runs it in an `after` validator to check that the index it was
    handed is the index of its own items. A model that carries both a list and
    a lookup over that list can otherwise be constructed inconsistent, and it
    would then answer lookups its own contents do not support.
    """
    grouped: dict[str, list[T]] = {}
    for item in items:
        grouped.setdefault(key(item), []).append(item)
    return {name: tuple(group) for name, group in grouped.items()}


def main_namespace(
    rows: Iterable[Mapping[str, Any]], *, source: str
) -> tuple[list[Mapping[str, Any]], list[SkippedRow]]:
    """Split `rows` into the main-namespace ones and a report of the rest.

    Every module here starts with this call. `is_main_namespace` holds the
    reason it is not optional.
    """
    kept: list[Mapping[str, Any]] = []
    skipped: list[SkippedRow] = []
    for row in rows:
        page = row_page_name(row, source=source)
        if is_main_namespace(page):
            kept.append(row)
        else:
            namespace = page.split(NAMESPACE_SEPARATOR, 1)[0]
            skipped.append(
                SkippedRow(
                    page=page,
                    subject=None,
                    reason=f"the row is on a {namespace}: page, not a main-namespace article",
                )
            )
    return kept, skipped
