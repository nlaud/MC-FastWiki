"""The Bucket API client, and the three quiet failures that it must make loud.

`pipeline.fetch.bucket` is the one door to Tier B. Every later stage of Phase 2
reads its bucket through it, so a fault here reaches `droptable`,
`spawn_table`, `trade`, and the rest at once.

Three of its rules exist because the live API fails without saying so, and each
one was checked against `https://minecraft.wiki/api.php` on 2026-08-27:

* A failed query answers HTTP 200 with an `error` key and no `bucket` key. A
  reader that defaulted the missing key to an empty list would turn a misspelled
  field name into an empty table, and CLAUDE.md says an empty scrape result is a
  failure to report.
* `limit(6000)` answers 5000 rows and no warning, so a page loop written against
  the larger limit would call the truncated page the end of the table.
* A row omits a selected field whose value is null, so a caller must read a row
  as a mapping that may lack a key.

The fourth rule is this project's own. A wiki URL does not name immutable bytes,
so the cache key carries a caller revision. Without it the first build of a
bucket would be the last one, and the weekly wiki refresh of Phase 9 would read
its own first answer forever.

No test in this module opens a socket, and no test writes to the cache of the
repository. Every cache here is built on `tmp_path`.
"""

import json
import socket
from pathlib import Path
from types import FunctionType
from typing import Any

import pytest

from pipeline.fetch import FetchError, get_bytes
from pipeline.fetch.bucket import (
    BUCKET_API_URL,
    DEFAULT_TRANSPORT,
    MAX_ROWS,
    PAGE_SIZE,
    WHERE_OPERATORS,
    BucketQuery,
    fetch_bucket_rows,
    parse_bucket_answer,
)
from pipeline.fetch.cache import ContentCache
from pipeline.fetch.polite import RateLimiter

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "bucket_droptable_page.json"

# The source name that a test of the parser passes.
SOURCE = "test"


@pytest.fixture(autouse=True)
def refuse_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test of this module that opens a socket.

    This is the fixture of `tests/test_mcmeta.py`, and that module holds the
    long form of the reason. The short form: the failure is a `RuntimeError`
    because `get_bytes` maps every `OSError` to a `FetchError`, so an `OSError`
    here would be caught by the code under test. The test would then pass while
    it read the live wiki.
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise RuntimeError("this test tried to reach the network")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "gethostbyname", refuse)


def answer(rows: list[dict[str, Any]], *, query: str = "q") -> bytes:
    """Return the bytes of a good Bucket answer that holds `rows`."""
    return json.dumps({"bucketQuery": query, "bucket": rows}).encode("utf-8")


def page_of(count: int, *, start: int = 0) -> list[dict[str, Any]]:
    """Return `count` rows, each one telling which row it is."""
    return [{"item": f"row {index}"} for index in range(start, start + count)]


# --- The query builder -----------------------------------------------------


def test_a_query_becomes_the_documented_lua_statement() -> None:
    """The statement matches the form that CLAUDE.md records for this API."""
    query = BucketQuery(
        bucket="resource_location",
        select=("display_name", "resource_location"),
        where=(("edition", "java"),),
        limit=2,
    )
    assert query.to_lua() == (
        "bucket('resource_location')"
        ".select('display_name','resource_location')"
        ".where('edition','java')"
        ".limit(2)"
        ".run()"
    )


def test_a_three_part_condition_quotes_its_operator() -> None:
    """Checked live: a bare operator answers `unexpected symbol near '='`."""
    query = BucketQuery(
        bucket="resource_location",
        select=("display_name",),
        where=(("resource_location", "=", "dirt"),),
    )
    assert ".where('resource_location','=','dirt')." in query.to_lua()


def test_every_clause_appears_in_the_order_the_api_expects() -> None:
    """Bucket, select, where, orderBy, limit, offset, run."""
    query = BucketQuery(
        bucket="droptable",
        select=("item", "json"),
        where=(("item", "Bone"),),
        order_by=("item",),
        limit=5,
        offset=10,
    )
    assert query.to_lua() == (
        "bucket('droptable').select('item','json').where('item','Bone')"
        ".orderBy('item').limit(5).offset(10).run()"
    )


def test_a_query_with_no_limit_and_no_offset_omits_both_clauses() -> None:
    """An omitted clause is omitted, not written as a default."""
    query = BucketQuery(bucket="advancement", select=("title",))
    assert query.to_lua() == "bucket('advancement').select('title').run()"


def test_the_url_names_the_api_and_escapes_the_statement() -> None:
    """The statement holds quotes, commas, and brackets. Every one must survive."""
    query = BucketQuery(bucket="trade", select=("profession",), limit=1)
    url = query.url()
    assert url.startswith(f"{BUCKET_API_URL}?")
    assert "action=bucket" in url
    assert "format=json" in url
    assert "'" not in url
    assert "(" not in url


def test_the_url_can_name_another_api() -> None:
    """A test and a mirror both need to point the client elsewhere."""
    query = BucketQuery(bucket="trade", select=("profession",))
    assert query.url(api_url="https://example.test/api.php").startswith("https://example.test/")


def test_a_query_is_frozen() -> None:
    """The page loop builds one query for each page rather than editing one."""
    query = BucketQuery(bucket="trade", select=("profession",))
    with pytest.raises(ValueError, match="frozen"):
        query.offset = 5000  # type: ignore[misc]


@pytest.mark.parametrize(
    "name",
    ["Spawn table", "spawn table", "spawn_table'", "_spawn", "9lives", "", "spawn.table"],
)
def test_a_bucket_name_that_is_not_snake_case_is_refused(name: str) -> None:
    """CLAUDE.md records this as a rule learned the hard way.

    `Spawn table` is the wiki page name and `spawn_table` is the bucket name.
    The quote and the dot matter for a different reason: a name that could hold
    either could close the Lua string and write the rest of the statement.
    """
    with pytest.raises(FetchError, match="bucket name"):
        BucketQuery(bucket=name, select=("item",))


@pytest.mark.parametrize("field", ["display name", "item'", "item)", "1a", "", "a\\b", "a.b"])
def test_a_field_name_that_could_end_the_lua_string_is_refused(field: str) -> None:
    """A collection manifest is planned to carry a Bucket query, and that file is data."""
    with pytest.raises(FetchError, match="field name"):
        BucketQuery(bucket="droptable", select=(field,))


def test_an_uppercase_field_name_is_accepted() -> None:
    """A bucket schema is a wiki page, and a field name there is not this project's to fix.

    The pattern still bars every character that could leave the string, so
    accepting a capital costs nothing.
    """
    assert (
        BucketQuery(bucket="droptable", select=("Item",))
        .to_lua()
        .startswith("bucket('droptable').select('Item')")
    )


def test_an_order_by_field_is_checked_too() -> None:
    """`orderBy` takes an identifier and reaches the statement the same way."""
    with pytest.raises(FetchError, match="field name"):
        BucketQuery(bucket="droptable", select=("item",), order_by=("item'; drop",))


def test_a_query_must_select_a_field() -> None:
    """The API answers `select() is mandatory`. Say so before sending anything."""
    with pytest.raises(FetchError, match="at least one field"):
        BucketQuery(bucket="droptable", select=())


def test_a_where_value_is_escaped_rather_than_restricted() -> None:
    """A value is data. Wiki display names hold apostrophes, and those must work."""
    query = BucketQuery(
        bucket="resource_location",
        select=("resource_location",),
        where=(("display_name", "Miner's Hat"),),
    )
    assert ".where('display_name','Miner\\'s Hat')." in query.to_lua()


def test_a_backslash_in_a_where_value_is_escaped_first() -> None:
    """Otherwise the escape of the quote would itself be escaped away."""
    query = BucketQuery(
        bucket="resource_location",
        select=("resource_location",),
        where=(("display_name", "a\\b"),),
    )
    assert ".where('display_name','a\\\\b')." in query.to_lua()


@pytest.mark.parametrize("value", ["a\nb", "a\rb", "a\tb", "a\x00b", "a\x7fb"])
def test_a_control_character_in_a_where_value_is_refused(value: str) -> None:
    """No value of this API holds one, so one is a sign that the value was built wrongly."""
    with pytest.raises(FetchError, match="control character"):
        BucketQuery(bucket="droptable", select=("item",), where=(("item", value),))


def test_an_unknown_comparison_is_refused() -> None:
    """The operator reaches the statement as a whitelisted token, not as free text."""
    with pytest.raises(FetchError, match="not a Bucket comparison"):
        BucketQuery(bucket="droptable", select=("item",), where=(("item", "LIKE", "Bone"),))


@pytest.mark.parametrize("operator", sorted(WHERE_OPERATORS))
def test_every_whitelisted_comparison_is_accepted(operator: str) -> None:
    """The whitelist and the builder must agree, or the list is decoration."""
    query = BucketQuery(bucket="droptable", select=("item",), where=(("item", operator, "Bone"),))
    assert f".where('item','{operator}','Bone')." in query.to_lua()


@pytest.mark.parametrize("condition", [("item",), ("item", "=", "Bone", "extra"), ()])
def test_a_condition_of_the_wrong_length_is_refused(condition: tuple[str, ...]) -> None:
    """Two parts or three. Anything else is a caller that built the tuple wrongly."""
    with pytest.raises(FetchError, match="not a Bucket condition"):
        BucketQuery(bucket="droptable", select=("item",), where=(condition,))


def test_a_limit_above_the_cap_is_refused() -> None:
    """Checked live: `limit(6000)` answers 5000 rows and no warning.

    A loop that trusted the limit it asked for would read the truncated page,
    see a page shorter than 6000, call that the end of the table, and lose every
    row after the first 5000.
    """
    with pytest.raises(FetchError, match=f"cannot be above {PAGE_SIZE}"):
        BucketQuery(bucket="spritefile", select=("name",), limit=PAGE_SIZE + 1)


def test_a_limit_at_the_cap_is_accepted() -> None:
    """The cap is the page size, so the page loop must be able to ask for it."""
    assert BucketQuery(bucket="spritefile", select=("name",), limit=PAGE_SIZE).limit == PAGE_SIZE


@pytest.mark.parametrize("limit", [0, -1])
def test_a_limit_below_one_is_refused(limit: int) -> None:
    """A limit of zero returns nothing, which the page loop would read as the end."""
    with pytest.raises(FetchError, match="at least 1"):
        BucketQuery(bucket="spritefile", select=("name",), limit=limit)


def test_a_negative_offset_is_refused() -> None:
    """There is no row before the first one."""
    with pytest.raises(FetchError, match="cannot be negative"):
        BucketQuery(bucket="spritefile", select=("name",), offset=-1)


# --- The answer parser -----------------------------------------------------


def test_the_fixture_page_parses_into_rows() -> None:
    """The fixture is a live answer, so the parser is pinned against a real one."""
    rows = parse_bucket_answer(FIXTURE.read_bytes(), source=SOURCE)
    assert len(rows) == 3
    assert all("item" in row and "json" in row for row in rows)


def test_a_fixture_row_carries_the_java_and_bedrock_split() -> None:
    """CLAUDE.md records that `droptable` splits the editions inside its `json` column.

    The client returns the column undecoded, because the Java filter of
    non-negotiable 1 belongs to the stage that reads this bucket. This test
    records that the split is there to filter on, so the later item cannot be
    written against a shape that does not exist.
    """
    rows = parse_bucket_answer(FIXTURE.read_bytes(), source=SOURCE)
    drops = json.loads(rows[0]["json"])
    assert "java" in drops
    assert "bedrock" in drops


def test_an_error_at_http_200_is_raised_and_never_read_as_an_empty_table() -> None:
    """The trap this parser exists for.

    Checked live: `bucket('no_such_bucket')` answers HTTP 200 with this body.
    `get_bytes` sees a valid response and raises nothing, so this is the only
    place that can tell a failed query from an empty one.
    """
    payload = json.dumps(
        {
            "bucketQuery": "bucket('no_such_bucket').select('item').limit(1).run()",
            "error": "Bucket no_such_bucket does not exist.",
        }
    ).encode("utf-8")
    with pytest.raises(FetchError, match="does not exist"):
        parse_bucket_answer(payload, source=SOURCE)


def test_a_misspelled_field_name_is_raised() -> None:
    """Checked live against `spritefile`. The same trap, from the other direction."""
    payload = json.dumps(
        {
            "bucketQuery": "bucket('spritefile').select('sprite_id').limit(1).run()",
            "error": "Field sprite_id not found in bucket spritefile.",
        }
    ).encode("utf-8")
    with pytest.raises(FetchError, match="Field sprite_id not found"):
        parse_bucket_answer(payload, source=SOURCE)


def test_an_answer_with_no_bucket_key_is_raised() -> None:
    """A body that is JSON and is not an answer must not read as no rows."""
    payload = json.dumps({"bucketQuery": "q"}).encode("utf-8")
    with pytest.raises(FetchError, match="no 'bucket' key"):
        parse_bucket_answer(payload, source=SOURCE)


def test_an_answer_that_is_not_an_object_is_raised() -> None:
    """A proxy that answers a JSON array is not the wiki."""
    with pytest.raises(FetchError, match="not a Bucket answer"):
        parse_bucket_answer(b"[]", source=SOURCE)


def test_a_bucket_that_is_not_a_list_is_raised() -> None:
    """The rows arrive as a list. Anything else is a shape this client cannot read."""
    payload = json.dumps({"bucketQuery": "q", "bucket": {"item": "Bone"}}).encode("utf-8")
    with pytest.raises(FetchError, match="not a list"):
        parse_bucket_answer(payload, source=SOURCE)


def test_a_row_that_is_not_an_object_is_raised() -> None:
    """A caller reads a row as a mapping, so a row that is not one must not reach it."""
    payload = json.dumps({"bucketQuery": "q", "bucket": [{"item": "Bone"}, "Bone"]}).encode("utf-8")
    with pytest.raises(FetchError, match="row 1"):
        parse_bucket_answer(payload, source=SOURCE)


def test_a_body_that_is_not_json_names_its_source() -> None:
    """An HTML error page from a proxy must fail with the URL that read it."""
    with pytest.raises(FetchError, match=SOURCE):
        parse_bucket_answer(b"<html>503</html>", source=SOURCE)


def test_an_empty_table_is_returned_rather_than_raised() -> None:
    """An empty `bucket` list is an answer. An offset past the end gives one.

    The page loop reads it as the end of the table, so the parser must hand it
    back rather than treat it as the failure that a missing key is.
    """
    assert parse_bucket_answer(answer([]), source=SOURCE) == []


def test_a_row_may_lack_a_selected_field() -> None:
    """Checked live: the API omits a field whose value is null.

    `select('display_name','resource_location').orderBy('resource_location')`
    answers `{"display_name": "No displayed name"}` as its first row. No key is
    added to cover that, because only the stage reading the bucket knows what a
    missing field means for the entity it is building.
    """
    payload = answer([{"display_name": "No displayed name"}])
    assert parse_bucket_answer(payload, source=SOURCE) == [{"display_name": "No displayed name"}]


# --- The page loop ---------------------------------------------------------


class FakeWiki:
    """A wiki that answers pages of rows and records every URL it was asked for."""

    def __init__(self, pages: list[list[dict[str, Any]]]) -> None:
        self.pages = pages
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        index = len(self.urls) - 1
        rows = self.pages[index] if index < len(self.pages) else []
        return answer(rows)


def test_one_short_page_ends_the_loop(tmp_path: Path) -> None:
    """A page shorter than the page size is the last page."""
    wiki = FakeWiki([page_of(3)])
    rows = fetch_bucket_rows(
        "droptable",
        ("item",),
        revision="26.2",
        cache=ContentCache(tmp_path),
        transport=wiki,
        page_size=5,
    )
    assert rows == page_of(3)
    assert len(wiki.urls) == 1


def test_the_loop_reads_every_page_and_advances_the_offset(tmp_path: Path) -> None:
    """Two full pages and a short one. The offset moves by the page size each time."""
    wiki = FakeWiki([page_of(5), page_of(5, start=5), page_of(2, start=10)])
    rows = fetch_bucket_rows(
        "spritefile",
        ("name",),
        revision="26.2",
        cache=ContentCache(tmp_path),
        transport=wiki,
        page_size=5,
    )
    assert rows == page_of(12)
    assert len(wiki.urls) == 3
    assert "offset%285%29" in wiki.urls[1]
    assert "offset%2810%29" in wiki.urls[2]


def test_a_full_last_page_costs_one_more_request(tmp_path: Path) -> None:
    """A table whose size is a multiple of the page size ends with an empty page.

    Checked live: an offset past the end answers an empty list rather than an
    error, so this extra request is safe and it is the only way to know the
    table ended.
    """
    wiki = FakeWiki([page_of(5)])
    rows = fetch_bucket_rows(
        "droptable",
        ("item",),
        revision="26.2",
        cache=ContentCache(tmp_path),
        transport=wiki,
        page_size=5,
    )
    assert rows == page_of(5)
    assert len(wiki.urls) == 2


def test_a_page_longer_than_the_limit_is_refused(tmp_path: Path) -> None:
    """The server cannot answer more rows than the limit it was given.

    A longer page means the body is not the answer to this query, so reading it
    would put rows of unknown origin into the build.
    """
    wiki = FakeWiki([page_of(9)])
    with pytest.raises(FetchError, match="against a limit of 5"):
        fetch_bucket_rows(
            "droptable",
            ("item",),
            revision="26.2",
            cache=ContentCache(tmp_path),
            transport=wiki,
            page_size=5,
        )


def test_a_page_longer_than_the_limit_never_reaches_the_store(tmp_path: Path) -> None:
    """The replaced body must cost one failed build, not every build after it.

    A body that parses as rows is a body that `fetch_and_read` stores, so a
    length check made after it returned would leave the over-long page in the
    cache. The build would then fail with an error naming a URL that is fine, it
    would keep failing after the proxy was gone because the answer now comes
    from disk and costs no request, and the only repair would be to delete
    `data/.cache` by hand. So the check runs inside the reader.
    """
    cache = ContentCache(tmp_path)
    with pytest.raises(FetchError, match="against a limit of 5"):
        fetch_bucket_rows(
            "droptable",
            ("item",),
            revision="26.2",
            cache=cache,
            transport=FakeWiki([page_of(9)]),
            page_size=5,
        )
    assert not (tmp_path / "index.json").exists()

    healthy = FakeWiki([page_of(1)])
    rows = fetch_bucket_rows(
        "droptable", ("item",), revision="26.2", cache=cache, transport=healthy, page_size=5
    )
    assert rows == page_of(1)
    assert len(healthy.urls) == 1


def test_a_stored_page_longer_than_the_limit_is_fetched_again(tmp_path: Path) -> None:
    """An over-long page that arrived some other way must not fail the build forever.

    `fetch_and_read` drops a stored payload that the reader refuses, so the
    length check has to be one of the refusals for that recovery to cover it.
    """
    cache = ContentCache(tmp_path)
    query = BucketQuery(bucket="droptable", select=("item",), limit=5, offset=0)
    cache.write(f"bucket/26.2/{query.url()}", answer(page_of(9)))
    healthy = FakeWiki([page_of(1)])
    rows = fetch_bucket_rows(
        "droptable", ("item",), revision="26.2", cache=cache, transport=healthy, page_size=5
    )
    assert rows == page_of(1)
    assert len(healthy.urls) == 1


def test_a_loop_that_cannot_end_is_stopped(tmp_path: Path) -> None:
    """A server that ignored `offset()` would answer page one forever.

    Every page would be full, the short-page test would never fire, and the loop
    would run until the disk filled.
    """

    def always_full(url: str) -> bytes:
        return answer(page_of(5))

    with pytest.raises(FetchError, match="offset is not moving the window"):
        fetch_bucket_rows(
            "droptable",
            ("item",),
            revision="26.2",
            cache=ContentCache(tmp_path),
            transport=always_full,
            page_size=5,
            max_rows=20,
        )


def test_a_failed_query_stops_the_loop(tmp_path: Path) -> None:
    """A query the wiki refused must fail the build, not return the rows read so far."""

    def refuse(url: str) -> bytes:
        return json.dumps({"bucketQuery": "q", "error": "Bucket nope does not exist."}).encode()

    with pytest.raises(FetchError, match="does not exist"):
        fetch_bucket_rows(
            "droptable",
            ("item",),
            revision="26.2",
            cache=ContentCache(tmp_path),
            transport=refuse,
        )


def test_the_where_clause_reaches_every_page(tmp_path: Path) -> None:
    """A filter that only reached page one would let Bedrock rows in behind it."""
    wiki = FakeWiki([page_of(5), page_of(1, start=5)])
    fetch_bucket_rows(
        "resource_location",
        ("display_name", "resource_location"),
        revision="26.2",
        where=[["edition", "java"]],
        cache=ContentCache(tmp_path),
        transport=wiki,
        page_size=5,
    )
    assert len(wiki.urls) == 2
    assert all("where" in url for url in wiki.urls)


def test_a_page_size_above_the_cap_is_refused(tmp_path: Path) -> None:
    """The caller cannot raise the page size past what the server will answer."""
    with pytest.raises(FetchError, match="between 1 and"):
        fetch_bucket_rows(
            "droptable",
            ("item",),
            revision="26.2",
            cache=ContentCache(tmp_path),
            transport=FakeWiki([]),
            page_size=PAGE_SIZE + 1,
        )


def test_a_read_that_names_no_transport_uses_the_polite_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLAUDE.md asks that every network fetch be rate-limited, so the default must be.

    One `spritefile` read is forty requests. A default of the bare `get_bytes`
    would send them as fast as the socket allows, and nothing would fail or warn
    about it: a stage author would have to remember to pass a polite transport,
    and a rule that has to be remembered is a rule that gets forgotten.
    """
    wiki = FakeWiki([page_of(1)])
    monkeypatch.setattr("pipeline.fetch.bucket.DEFAULT_TRANSPORT", wiki)
    rows = fetch_bucket_rows(
        "droptable", ("item",), revision="26.2", cache=ContentCache(tmp_path), page_size=5
    )
    assert rows == page_of(1)
    assert len(wiki.urls) == 1


def test_the_default_transport_is_not_the_bare_get_bytes() -> None:
    """The default is the wrapped transport, and it is one object, not one per call.

    `pipeline.fetch.polite` says to build one transport for a whole build,
    because one transport holds one `RateLimiter` and two do not space each
    other. A default built inside the function would be a new limiter on every
    call, so the service would see no rate at all.
    """
    assert DEFAULT_TRANSPORT is not get_bytes
    assert isinstance(DEFAULT_TRANSPORT, FunctionType)
    held = DEFAULT_TRANSPORT.__closure__ or ()
    assert any(isinstance(cell.cell_contents, RateLimiter) for cell in held)


def test_the_default_page_size_and_row_ceiling_are_the_constants() -> None:
    """The cap and the ceiling are named once, not copied into the signature."""
    assert PAGE_SIZE == 5000
    assert MAX_ROWS == 200_000


# --- The cache key ---------------------------------------------------------


def test_a_second_read_of_one_revision_sends_no_request(tmp_path: Path) -> None:
    """The whole point of the cache: a rebuild of one version reads no network."""
    cache = ContentCache(tmp_path)
    wiki = FakeWiki([page_of(2)])
    first = fetch_bucket_rows(
        "droptable", ("item",), revision="26.2", cache=cache, transport=wiki, page_size=5
    )
    second = fetch_bucket_rows(
        "droptable", ("item",), revision="26.2", cache=cache, transport=wiki, page_size=5
    )
    assert first == second
    assert len(wiki.urls) == 1


def test_the_cache_key_carries_the_revision(tmp_path: Path) -> None:
    """The key that a bucket read writes must be readable as `bucket/<revision>/<url>`.

    A key of the URL alone would be the bug this rule exists to stop, and it
    would look exactly like this test passing.
    """
    cache = ContentCache(tmp_path)
    fetch_bucket_rows(
        "droptable",
        ("item",),
        revision="26.2",
        cache=cache,
        transport=FakeWiki([page_of(1)]),
        page_size=5,
    )
    keys = json.loads((tmp_path / "index.json").read_bytes())
    assert keys
    assert all(key.startswith("bucket/26.2/https://") for key in keys)


def test_a_new_revision_reads_the_wiki_again(tmp_path: Path) -> None:
    """The wiki is edited every day, so a corrected number must be able to land.

    Without this, the first build of a bucket would be the last one and the
    weekly wiki refresh of Phase 9 would read its own first answer forever.
    """
    cache = ContentCache(tmp_path)
    wiki = FakeWiki([page_of(2), page_of(2)])
    fetch_bucket_rows(
        "droptable", ("item",), revision="26.2", cache=cache, transport=wiki, page_size=5
    )
    fetch_bucket_rows(
        "droptable", ("item",), revision="26.3", cache=cache, transport=wiki, page_size=5
    )
    assert len(wiki.urls) == 2
    assert wiki.urls[0] == wiki.urls[1]


def test_two_revisions_of_one_payload_share_one_object(tmp_path: Path) -> None:
    """The store is content-addressed, so a bucket that did not change costs no space."""
    cache = ContentCache(tmp_path)
    for revision in ("26.2", "26.3"):
        fetch_bucket_rows(
            "droptable",
            ("item",),
            revision=revision,
            cache=cache,
            transport=FakeWiki([page_of(1)]),
            page_size=5,
        )
    keys = json.loads((tmp_path / "index.json").read_bytes())
    assert len(keys) == 2
    assert len(set(keys.values())) == 1


def test_a_stored_body_that_is_not_an_answer_is_fetched_again(tmp_path: Path) -> None:
    """A proxy page that reached the store must cost one request, not every build.

    `fetch_and_read` reads before it stores, so this can only happen to a store
    that was written by something else. The recovery still has to work.
    """
    cache = ContentCache(tmp_path)
    query = BucketQuery(bucket="droptable", select=("item",), limit=5, offset=0)
    cache.write(f"bucket/26.2/{query.url()}", b"<html>503</html>")
    wiki = FakeWiki([page_of(1)])
    rows = fetch_bucket_rows(
        "droptable", ("item",), revision="26.2", cache=cache, transport=wiki, page_size=5
    )
    assert rows == page_of(1)
    assert len(wiki.urls) == 1


def test_a_bad_answer_is_never_stored(tmp_path: Path) -> None:
    """A body that failed the parser must not be read back on the next build."""
    cache = ContentCache(tmp_path)

    def refuse(url: str) -> bytes:
        return json.dumps({"bucketQuery": "q", "error": "Bucket nope does not exist."}).encode()

    with pytest.raises(FetchError):
        fetch_bucket_rows(
            "droptable", ("item",), revision="26.2", cache=cache, transport=refuse, page_size=5
        )
    assert not (tmp_path / "index.json").exists()


@pytest.mark.parametrize("revision", ["", "26.2/extra", "a b", ".hidden", "26.2\n", "-x"])
def test_a_revision_that_is_not_a_plain_token_is_refused(tmp_path: Path, revision: str) -> None:
    """A revision names a cache generation, so a separator in one would collide two."""
    with pytest.raises(FetchError, match="cache revision"):
        fetch_bucket_rows(
            "droptable",
            ("item",),
            revision=revision,
            cache=ContentCache(tmp_path),
            transport=FakeWiki([]),
        )


@pytest.mark.parametrize("revision", ["26.2", "26.3-snapshot-9", "2026-08-27", "wiki_2026_08"])
def test_a_version_and_a_date_both_name_a_revision(tmp_path: Path, revision: str) -> None:
    """A build passes the Minecraft version. A wiki-only refresh passes a date."""
    rows = fetch_bucket_rows(
        "droptable",
        ("item",),
        revision=revision,
        cache=ContentCache(tmp_path),
        transport=FakeWiki([page_of(1)]),
        page_size=5,
    )
    assert rows == page_of(1)
