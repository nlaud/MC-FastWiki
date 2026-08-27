"""The Minecraft Wiki Bucket API: build one query, read every page of its rows.

Tier B of this project is the Minecraft Wiki. CLAUDE.md names the Bucket
extension as the primary wiki interface and says to prefer it over parsing
wikitext, because Bucket answers with structured rows instead of prose. Every
later stage of Phase 2 reads a bucket through this module: `resource_location`,
`droptable`, `spawn_table`, `crafting_recipe`, `advancement`, `trade`, and
`spritefile`.

The API takes a Lua statement in one query parameter::

    action=bucket&format=json&query=bucket('droptable').select('item','json').limit(500).run()

`BucketQuery` builds that statement, and `fetch_bucket_rows` walks the pages.
Neither one reads a row. What a row means belongs to the stage that asked for
it, and the Java Edition filter that non-negotiable 1 of CLAUDE.md demands
belongs there too: this module returns what the wiki said, and the caller of
each bucket decides which rows are Java.

Five facts about the live API shape this module. Three of them are traps, and
each one fails quietly rather than loudly, which is why each one has a guard
here. All five were checked against `https://minecraft.wiki/api.php` on
2026-08-27.

1. A good answer is `{"bucketQuery": "<the query>", "bucket": [<rows>]}`.

2. **A failed query answers HTTP 200 with an `error` key and no `bucket` key.**
   `bucket('no_such_bucket')` answers
   `{"bucketQuery": ..., "error": "Bucket no_such_bucket does not exist."}`, and
   selecting a field that a bucket does not hold answers
   `"error": "Field sprite_id not found in bucket spritefile."`. Nothing below
   this module can see that. `get_bytes` sees a valid 200 and raises nothing,
   and a reader that took `document.get("bucket", [])` would turn a misspelled
   field name into an empty table. CLAUDE.md is explicit that an empty scrape
   result is a failure to report, so `parse_bucket_answer` raises on it.

3. **A limit above the cap is truncated in silence.** `limit(6000)` answers 200
   with exactly 5000 rows and no warning. A page loop written against that limit
   would read its 5000-row page, see a page shorter than the 6000 it asked for,
   call that the end of the table, and lose every row after it. So `PAGE_SIZE`
   is the cap itself, and `BucketQuery` refuses a larger limit rather than let
   one be written by accident.

4. **A row omits a field whose value is null.** The query
   `select('display_name','resource_location').orderBy('resource_location')`
   returns `{"display_name": "No displayed name"}` as its first row, with no
   `resource_location` key at all. A caller must read a row as a mapping that
   may lack a selected key, and never index one blind.

5. An offset past the end returns an empty list rather than an error, so an
   empty page is the end of the table.

The cache key is the other thing worth reading before using this module. Every
other key of `ContentCache` is a URL that names immutable bytes, because it
carries a pinned mcmeta commit SHA. A wiki URL names whatever the wiki says
today. Keyed by the URL alone, the first build of a bucket would be the last
one: a corrected mob health would never be read again, and the weekly wiki
refresh that Phase 9 wants would return the rows of the first build for all
time.

So a Bucket key is `bucket/<revision>/<url>`, and `revision` is a required
argument with no default. A build passes the Minecraft version. The weekly
refresh passes a date. A new revision is a new key, so the fetch happens again,
while the objects of the old revision stay in the store and a rebuild of the old
revision still reads no network. This keeps the promise of `ContentCache`
whole -- one key names one payload for all time -- instead of adding an expiry
rule that would weaken it for every other caller. Staleness becomes something
the caller chooses rather than something it inherits.
"""

import re
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlencode

from pydantic import BaseModel, field_validator

from pipeline.fetch import FetchError, Transport, decode_json
from pipeline.fetch.cache import ContentCache, fetch_and_read
from pipeline.fetch.polite import polite_transport

__all__ = [
    "BUCKET_API_URL",
    "DEFAULT_TRANSPORT",
    "MAX_ROWS",
    "PAGE_SIZE",
    "WHERE_OPERATORS",
    "BucketQuery",
    "fetch_bucket_rows",
    "parse_bucket_answer",
]

# The one wiki endpoint of this project. CLAUDE.md records MediaWiki 1.45 with
# Weird Gloop's Bucket extension behind it.
BUCKET_API_URL = "https://minecraft.wiki/api.php"

# The row cap of one request, and the reason it is also the page size. See fact
# 3 in the module docstring: the server truncates a larger limit without saying
# so, and a loop that trusts its own limit then stops early.
PAGE_SIZE = 5000

# The most rows that one call will collect before it gives up.
#
# This is a guard against a loop that cannot end, not a limit on a table. The
# page loop stops when a page comes back short, so it depends on `offset()`
# moving the window. A server that ignored `offset()` would answer page one
# forever, every page would be full, and the loop would run until the disk
# filled. 200,000 rows is 40 pages, and the largest bucket that CLAUDE.md
# records is `spritefile` at about 4,900 rows.
MAX_ROWS = 200_000

# The transport that a bucket read uses when the caller names none.
#
# It is the polite one, not `get_bytes`. CLAUDE.md asks that every network fetch
# of this pipeline be rate-limited and that this project be a good citizen with
# the wiki API, which is a volunteer-run service, and a default that has to be
# remembered is a rule that will be forgotten: one full `spritefile` read is
# forty requests, and nothing fails or warns when they all go out at once.
#
# Built once, at import, so that every caller that takes the default shares one
# `RateLimiter` and the service sees one rate for the whole build. Two
# transports hold two limiters and do not space each other, which is why
# `pipeline.fetch.polite` says to build one and pass it everywhere. A stage that
# wants its own spacing still passes its own `polite_transport`, and a test
# passes a callable that reads no socket.
DEFAULT_TRANSPORT: Transport = polite_transport()

# A bucket name is lowercase snake_case. CLAUDE.md records this as a rule
# learned the hard way: `spawn_table` works and `Spawn table` does not.
BUCKET_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")

# A field name is looser. Every field observed on the live wiki is also
# lowercase snake_case, but the bucket schemas are wiki pages that anyone may
# add a field to, and a rejected field name that the server would have accepted
# is a wall with no way around it. The pattern still bars every character that
# could end the Lua string or open a call: a quote, a backslash, a bracket, a
# space, and a dot.
FIELD_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")

# A revision names a cache generation, so it must be readable in the index file
# and must hold no separator that would make two revisions collide. A Minecraft
# version ID such as `26.2` and a date such as `2026-08-27` both pass.
REVISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")

# The comparisons that `where()` accepts. A whitelist rather than a pattern:
# these reach the query as bare text, outside the quoting that a value gets.
WHERE_OPERATORS = frozenset({"=", "!=", "<", "<=", ">", ">="})

# How a Lua single-quoted literal escapes. A backslash first, so the escape of
# the quote is not escaped again.
LUA_ESCAPES = (("\\", "\\\\"), ("'", "\\'"))


def _checked_identifier(value: str, pattern: re.Pattern[str], noun: str) -> str:
    """Return `value` when it matches `pattern`, and raise `FetchError` when it does not.

    Every identifier of a query goes through here before it is joined into the
    Lua statement. The names arrive from the pipeline itself today, but a
    collection manifest in `/pipeline/collections` is planned to carry a Bucket
    query, and that file is data. An identifier from a data file that could hold
    a quote could close the string and write the rest of the statement.
    """
    if not pattern.fullmatch(value):
        raise FetchError(f"{value!r} is not a {noun} of the Bucket API.")
    return value


def _quoted(value: str) -> str:
    """Return `value` as a Lua single-quoted string literal.

    A `where` value is data, not an identifier: `resource_location` values hold
    names that a wiki editor chose. So it is escaped rather than restricted.

    A control character is refused instead of escaped. No value of this API
    holds one, a newline inside the query parameter is a fair sign that
    something built the value wrongly, and refusing is cheaper to reason about
    than a second escaping table.
    """
    if any(character < " " or character == "\x7f" for character in value):
        raise FetchError(f"{value!r} holds a control character, so it cannot go in a Bucket query.")
    escaped = value
    for character, replacement in LUA_ESCAPES:
        escaped = escaped.replace(character, replacement)
    return f"'{escaped}'"


class BucketQuery(BaseModel, frozen=True):
    """One Bucket query, and the Lua statement and URL that it becomes.

    The model is frozen and its methods are pure, so a test reads a query string
    without a socket, and the page loop below builds one query for each page
    instead of editing one in place.

    `where` holds a tuple for each condition. Both forms that the API accepts
    are allowed: `('edition', 'java')` compares for equality, and
    `('resource_location', '=', 'dirt')` names the comparison. Both were checked
    against the live API.
    """

    bucket: str
    select: tuple[str, ...]
    where: tuple[tuple[str, ...], ...] = ()
    order_by: tuple[str, ...] = ()
    limit: int | None = None
    offset: int | None = None

    @field_validator("bucket")
    @classmethod
    def _bucket_must_be_snake_case(cls, value: str) -> str:
        """Refuse a bucket name that is not lowercase snake_case."""
        return _checked_identifier(value, BUCKET_NAME, "bucket name")

    @field_validator("select", "order_by")
    @classmethod
    def _fields_must_be_identifiers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Refuse a field name that could end the Lua string."""
        return tuple(_checked_identifier(field, FIELD_NAME, "field name") for field in value)

    @field_validator("select")
    @classmethod
    def _select_must_name_a_field(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Refuse an empty `select`.

        The API refuses it too, with `select() is mandatory`. Refusing here
        turns that into an error that names the query rather than one that
        arrives after a request was already sent.
        """
        if not value:
            raise FetchError("a Bucket query must select at least one field.")
        return value

    @field_validator("where")
    @classmethod
    def _where_must_be_a_condition(
        cls, value: tuple[tuple[str, ...], ...]
    ) -> tuple[tuple[str, ...], ...]:
        """Refuse a condition that is not a field and a value, with an optional operator."""
        for condition in value:
            if len(condition) == 2:
                field, _ = condition
            elif len(condition) == 3:
                field, operator, _ = condition
                if operator not in WHERE_OPERATORS:
                    accepted = " ".join(sorted(WHERE_OPERATORS))
                    raise FetchError(
                        f"{operator!r} is not a Bucket comparison. Accepted: {accepted}."
                    )
            else:
                raise FetchError(
                    f"{condition!r} is not a Bucket condition. Pass (field, value) or "
                    f"(field, operator, value)."
                )
            _checked_identifier(field, FIELD_NAME, "field name")
            # Quote the value now and throw the result away. `to_lua` quotes it
            # again when it builds the statement, and this call is here so that a
            # value the quoting refuses fails where the query was built rather
            # than several stages later where the statement is rendered.
            _quoted(condition[-1])
        return value

    @field_validator("limit")
    @classmethod
    def _limit_must_be_within_the_cap(cls, value: int | None) -> int | None:
        """Refuse a limit above the row cap, and a limit below one.

        The cap is the guard for fact 3 of the module docstring. The server
        answers a larger limit with `PAGE_SIZE` rows and no warning, so a query
        that asks for more rows than the cap is already reading a truncated
        table, and the only honest place to say so is before the request.
        """
        if value is None:
            return None
        if value < 1:
            raise FetchError(f"a Bucket limit must be at least 1, not {value}.")
        if value > PAGE_SIZE:
            raise FetchError(
                f"a Bucket limit cannot be above {PAGE_SIZE}, and {value} is. The API answers a "
                f"larger limit with {PAGE_SIZE} rows and no warning, so paginate with offset()."
            )
        return value

    @field_validator("offset")
    @classmethod
    def _offset_cannot_be_negative(cls, value: int | None) -> int | None:
        """Refuse a negative offset."""
        if value is not None and value < 0:
            raise FetchError(f"a Bucket offset cannot be negative, and {value} is.")
        return value

    def to_lua(self) -> str:
        """Return the Lua statement that the `query` parameter carries."""
        selected = ",".join(_quoted(field) for field in self.select)
        parts = [f"bucket({_quoted(self.bucket)})", f"select({selected})"]
        for condition in self.where:
            # Every part is quoted, the operator included. Checked live: the
            # server accepts `where('resource_location','=','dirt')` and answers
            # `unexpected symbol near '='` for the same condition with the
            # operator bare. The whitelist above is still what keeps an operator
            # from being an arbitrary string; the quoting is what makes the
            # statement parse.
            arguments = ",".join(_quoted(part) for part in condition)
            parts.append(f"where({arguments})")
        for field in self.order_by:
            parts.append(f"orderBy({_quoted(field)})")
        if self.limit is not None:
            parts.append(f"limit({self.limit})")
        if self.offset is not None:
            parts.append(f"offset({self.offset})")
        parts.append("run()")
        return ".".join(parts)

    def url(self, *, api_url: str = BUCKET_API_URL) -> str:
        """Return the full API URL of this query.

        `urlencode` does the escaping. The Lua statement holds a quote, a comma,
        and a bracket, and every one of them must arrive at the server unchanged.
        """
        parameters = urlencode({"action": "bucket", "format": "json", "query": self.to_lua()})
        return f"{api_url}?{parameters}"


def parse_bucket_answer(payload: bytes, *, source: str) -> list[dict[str, Any]]:
    """Return the rows of one Bucket answer, or raise `FetchError`.

    This function is the guard for fact 2 of the module docstring. A failed
    query answers HTTP 200 with an `error` key, so nothing below this point can
    tell a failure from a table. Every shape that is not an answer full of rows
    raises here, and none of them returns an empty list.

    The rows come back as plain dictionaries. A row may lack a selected key,
    because the API omits a field whose value is null, and no key is added to
    cover that: a caller that reads a row must decide for itself what a missing
    field means for the entity it is building.
    """
    document = decode_json(payload, source=source)
    if not isinstance(document, dict):
        raise FetchError(f"{source} answered {type(document).__name__}, not a Bucket answer.")
    error = document.get("error")
    if error is not None:
        raise FetchError(f"{source} refused the query: {error}")
    rows = document.get("bucket")
    if rows is None:
        keys = ", ".join(sorted(map(str, document))) or "nothing"
        raise FetchError(f"{source} answered no 'bucket' key. It answered: {keys}.")
    if not isinstance(rows, list):
        raise FetchError(f"{source} answered a 'bucket' of {type(rows).__name__}, not a list.")
    parsed: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not all(isinstance(key, str) for key in row):
            raise FetchError(f"{source} answered row {index} as {row!r}, not an object of fields.")
        parsed.append(dict(row))
    return parsed


def fetch_bucket_rows(
    bucket: str,
    select: Sequence[str],
    *,
    revision: str,
    where: Sequence[Sequence[str]] = (),
    order_by: Sequence[str] = (),
    cache: ContentCache | None = None,
    transport: Transport | None = None,
    api_url: str = BUCKET_API_URL,
    page_size: int = PAGE_SIZE,
    max_rows: int = MAX_ROWS,
) -> list[dict[str, Any]]:
    """Return every row of `bucket`, over as many requests as it takes.

    `revision` names the cache generation and has no default. The module
    docstring holds the reason: the wiki changes, so a key of the URL alone
    would freeze the first build of a bucket forever. Pass the Minecraft version
    for a build, or a date for a wiki-only refresh.

    Pass `cache` to name the store, which every test does. Pass `transport` to
    read the bytes from somewhere else; a test passes a callable that opens no
    socket. `None` means `DEFAULT_TRANSPORT`, which already holds the rate limit
    and the retry that CLAUDE.md asks for, so a caller that names nothing is
    polite rather than fast. It is read here rather than written into the
    signature so that one name decides it for every caller.

    The rows arrive exactly as the wiki gave them. No row is filtered and no key
    is renamed. In particular the Java Edition filter of non-negotiable 1 is not
    applied here, because only the caller knows which column of its bucket
    carries the edition -- `resource_location` and `spawn_table` hold an
    `edition` field, while `droptable` splits the editions inside its `json`
    column and `trade` splits them across two probability fields.
    """
    _checked_identifier(revision, REVISION, "cache revision")
    if page_size < 1 or page_size > PAGE_SIZE:
        raise FetchError(f"a Bucket page size must be between 1 and {PAGE_SIZE}, not {page_size}.")
    store = ContentCache() if cache is None else cache
    the_transport = DEFAULT_TRANSPORT if transport is None else transport
    conditions = tuple(tuple(condition) for condition in where)
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        query = BucketQuery(
            bucket=bucket,
            select=tuple(select),
            where=conditions,
            order_by=tuple(order_by),
            limit=page_size,
            offset=offset,
        )
        url = query.url(api_url=api_url)

        def read(payload: bytes, source: str = url) -> list[dict[str, Any]]:
            page = parse_bucket_answer(payload, source=source)
            if len(page) > page_size:
                # The server cannot answer more rows than the limit it was given,
                # so a longer page is not the answer to this query. Something
                # between here and the wiki replaced the body, and reading it
                # would put rows of unknown origin into the build.
                #
                # The check belongs here, inside the reader, and not after
                # `fetch_and_read` returns. A body that parses as rows is a body
                # that `fetch_and_read` stores, so a check made afterwards would
                # leave the replaced body in the cache: the build would fail with
                # an error naming a URL that is fine, it would keep failing after
                # the proxy was gone because the answer now comes from disk and
                # costs no request, and the only repair would be to delete
                # `data/.cache` by hand. Refusing it here is what makes it a
                # payload the store never accepts.
                raise FetchError(
                    f"{source} answered {len(page)} rows against a limit of {page_size}. That is "
                    f"not an answer to this query."
                )
            return page

        page = fetch_and_read(
            store,
            url,
            transport=the_transport,
            read=read,
            key=f"bucket/{revision}/{url}",
        )
        rows.extend(page)
        if len(page) < page_size:
            return rows
        if len(rows) > max_rows:
            raise FetchError(
                f"{bucket!r} returned more than {max_rows} rows and every page was full. The "
                f"offset is not moving the window, so the page loop cannot end."
            )
        offset += page_size
