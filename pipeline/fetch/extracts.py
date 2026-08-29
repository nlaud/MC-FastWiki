"""The intro blurb of a wiki page: TextExtracts, batched, joined back to the title asked for.

Every entity that has a wiki page carries a blurb, and the blurb is the first
thing a window shows. No bucket holds it. The wiki serves it through the
TextExtracts extension instead, so Tier B needs a second reader beside
`pipeline.fetch.bucket`::

    action=query&format=json&formatversion=2&prop=extracts&exintro=1&explaintext=1
    &exlimit=20&redirects=1&titles=Creeper|Zombie

`fetch_page_extracts` takes the titles and returns an `ExtractReport`. The
report holds the blurbs it read and the titles it could not read, and each miss
names its reason. It is a report and not a bare mapping because CLAUDE.md says
an empty scrape result is a failure to report, and a page with no blurb is such
a result.

Five facts about the live API shape this module. Three of them fail without an
error, so each one has a guard here. All five were checked against
`https://minecraft.wiki/api.php` on 2026-08-28.

1. `exlimit` caps at 20. A larger value answers a warning, not an error, so
   nothing stops a caller from asking for more.

2. **A request for more titles than the cap answers every page and only 20
   extracts.** 25 titles answer 25 pages, of which five carry no `extract` key
   at all. The answer holds a `continue` key and no `batchcomplete` key, and
   that is the only sign of the loss. A reader that trusted the page list would
   record five entities with no blurb and say nothing. So `BATCH_SIZE` is the
   cap itself, and `parse_extracts_answer` refuses an answer that carries
   `continue` or lacks `batchcomplete`.

3. A page that the wiki does not hold answers `"missing": true` and no
   `extract`. A page whose title cannot exist answers `"invalid": true`. Both
   become a miss in the report, because one bad title must not fail a build of
   1,658 entities.

4. **The wiki rewrites a requested title in two ways, and a caller must follow
   both.** `query.normalized` maps `creeper` to `Creeper`, which is the wiki
   capitalizing the first letter. `query.redirects` maps `Creepers` to
   `Creeper`, which is the wiki following a redirect page. The answered page
   carries the final title alone, so a reader that matched the requested title
   against `pages[].title` would find nothing for either of those requests.
   `_resolve_title` walks both maps, and `PageExtract` keeps both titles.

5. **A `|` inside a title splits that title into two.** The character is the
   title separator of this API, and the server accepted `Weird|Title` as two
   pages. So a title that holds one is refused before the request.

`redirects=1` carries one obligation with it. The wiki decides which page
answers a request, so a redirect can answer a main-namespace title from a user
sandbox or a translation project -- the namespaces that CLAUDE.md says must be
filtered out, because a row from one of them is well-formed and therefore
dangerous. A blurb that arrived that way would read as the entity's own intro
text with nothing marking it, so `_left_the_main_namespace` refuses it here, at
the pipeline stage, and the report names it as a miss.

`formatversion=2` is not an option here. Version 1 answers `pages` as an object
keyed by page ID, and it gives every missing page the key `-1`, so two missing
titles in one batch collide and one of them disappears. Version 2 answers a
list, and each entry carries its own title.

The cache key is `extracts/<revision>/<url>`, which is the rule that
`pipeline.fetch.bucket` states in full. A wiki URL does not name immutable
bytes, so the key carries a caller revision. A build passes the Minecraft
version. The weekly wiki refresh of Phase 9 passes a date.

This module reads what the wiki said and nothing more. It writes no entity, and
it joins no blurb to a registry ID. `pipeline.enrich.resource_location` owns
that join, and the normalize stage owns the entity.
"""

from collections.abc import Iterable, Sequence
from typing import Any
from urllib.parse import urlencode

from pydantic import BaseModel

from pipeline.fetch import WIKI_API_URL, FetchError, Transport, decode_json
from pipeline.fetch.cache import ContentCache, check_revision, fetch_and_read
from pipeline.fetch.polite import WIKI_TRANSPORT

__all__ = [
    "BATCH_SIZE",
    "DEFAULT_TRANSPORT",
    "INVALID_TITLE",
    "MAIN_NAMESPACE",
    "MAX_REWRITE_HOPS",
    "MISSING_PAGE",
    "NO_EXTRACT",
    "OFF_MAIN_NAMESPACE",
    "TITLE_SEPARATOR",
    "ExtractReport",
    "MissingExtract",
    "PageExtract",
    "build_extracts_url",
    "fetch_page_extracts",
    "parse_extracts_answer",
]

# How many titles go in one request. See fact 2 in the module docstring: this is
# the `exlimit` cap of the extension, and an answer to more titles than the cap
# drops the extracts of the rest without an error.
BATCH_SIZE = 20

# What the API reads as the boundary between two titles.
TITLE_SEPARATOR = "|"

# How many rewrites `_resolve_title` follows before it gives up. A rewrite chain
# of the wiki is one normalization and at most one redirect, so four is
# generous. The limit is here to end a loop that a cyclic map would otherwise
# run forever.
MAX_REWRITE_HOPS = 4

# The wiki namespace that holds the article about a Minecraft thing.
#
# CLAUDE.md: the wiki indexes the whole site, user sandboxes and translation
# projects included, and a row from one of those is dangerous because it is
# well-formed. The rule there is written for the Bucket tables, and it holds
# here for the same reason -- see `_left_the_main_namespace` below.
MAIN_NAMESPACE = 0

# Why a requested title carries no blurb. Each one is a report line, not an
# error, because one bad title must not stop a build.
MISSING_PAGE = "the wiki holds no page of this title"
INVALID_TITLE = "the wiki reads this title as invalid"
NO_EXTRACT = "the page holds no intro extract"
OFF_MAIN_NAMESPACE = "a redirect moved this title out of the main namespace"

# The transport that an extracts read uses when the caller names none.
#
# It is the polite one, for the reason that `pipeline.fetch.bucket` gives in
# full: CLAUDE.md asks that every network read of this pipeline be rate-limited,
# and a default that has to be remembered is a rule that will be forgotten. One
# blurb read of 1,658 entities is 83 requests.
#
# It is `WIKI_TRANSPORT`, the same object that `bucket.py` defaults to, because
# a rate limit belongs to a host and both modules read `WIKI_API_URL`. A
# `polite_transport()` of this module would be a second `RateLimiter` on that
# one host, and two limiters do not space each other: a build that took both
# defaults would send twice the intended rate while each reader believed it was
# keeping to one.
DEFAULT_TRANSPORT: Transport = WIKI_TRANSPORT


class PageExtract(BaseModel, frozen=True):
    """One intro blurb, and both titles that name the page it came from."""

    # The title that the caller asked for.
    requested_title: str
    # The title that the wiki answered. The two differ when the wiki
    # capitalized the request or followed a redirect. Both are kept, because a
    # redirect can move a title to a page about something else: `Invalid`
    # redirects to `Bug tracker` on this wiki, and only the answered title shows
    # that move.
    page_title: str
    # The page ID of the wiki. `None` when the answer omits it.
    page_id: int | None
    # The blurb, as plain text, with the trailing blank lines removed.
    extract: str


class MissingExtract(BaseModel, frozen=True):
    """One requested title that carries no blurb, and the reason for it."""

    requested_title: str
    # The title that the answer named, which is the requested title after any
    # rewrite the wiki applied.
    page_title: str
    # One of `MISSING_PAGE`, `INVALID_TITLE`, `NO_EXTRACT`, or
    # `OFF_MAIN_NAMESPACE`.
    reason: str


class ExtractReport(BaseModel, frozen=True):
    """What one read of the extracts API produced: the blurbs, and the misses.

    The misses are half of the answer, not a footnote. CLAUDE.md asks this
    pipeline to report an entity that a scrape produced nothing for, and this
    model is what carries that report out of the fetch stage.
    """

    extracts: tuple[PageExtract, ...] = ()
    misses: tuple[MissingExtract, ...] = ()

    @classmethod
    def merge(cls, reports: Sequence["ExtractReport"]) -> "ExtractReport":
        """Return one report over `reports`, in the order they were read."""
        return cls(
            extracts=tuple(entry for report in reports for entry in report.extracts),
            misses=tuple(entry for report in reports for entry in report.misses),
        )

    def blurbs(self) -> dict[str, str]:
        """Return the requested title of each blurb, mapped to the blurb.

        The mapping is built on each call, because a frozen model cannot
        memoize. Call it once and hold the result. A caller that wants the
        misses as well reads `misses` directly.
        """
        return {entry.requested_title: entry.extract for entry in self.extracts}


def _checked_title(title: str) -> str:
    """Return `title` when it can name one wiki page, or raise `FetchError`.

    A blank title asks for nothing. A title that holds the separator asks for
    two pages under one name, which is fact 5 of the module docstring. A control
    character is a sign that the caller built the title wrongly, the way it is
    in `pipeline.fetch.bucket`.
    """
    if not title.strip():
        raise FetchError("a wiki title cannot be blank.")
    if TITLE_SEPARATOR in title:
        raise FetchError(
            f"{title!r} holds a {TITLE_SEPARATOR!r}, which this API reads as the boundary "
            f"between two titles. The request would ask for two pages under one name."
        )
    if any(character < " " or character == "\x7f" for character in title):
        raise FetchError(f"{title!r} holds a control character, so it cannot name a wiki page.")
    return title


def build_extracts_url(titles: Sequence[str], *, api_url: str = WIKI_API_URL) -> str:
    """Return the URL that reads the intro blurb of every title of `titles`.

    The function is pure, so a test reads the URL without a socket.

    `exlimit` goes out as the cap rather than as the count of titles. The two
    are the same for a full batch, and for a short one the cap is still the
    honest number: it is what the server will answer, and asking for less would
    make a short batch behave differently from a full one for no reason.
    """
    if not titles:
        raise FetchError("an extracts request must name at least one title.")
    if len(titles) > BATCH_SIZE:
        raise FetchError(
            f"an extracts request cannot name more than {BATCH_SIZE} titles, and this one names "
            f"{len(titles)}. The API answers the extra pages with no extract and no error."
        )
    checked = [_checked_title(title) for title in titles]
    if len(set(checked)) != len(checked):
        raise FetchError("an extracts request names each title once. This one repeats a title.")
    parameters = urlencode(
        {
            "action": "query",
            "format": "json",
            # Fact 2 of the module docstring, and not a preference. Version 1
            # keys `pages` by page ID and gives every missing page the key `-1`.
            "formatversion": "2",
            "prop": "extracts",
            # The intro alone, as plain text. The blurb sits above the first
            # heading of the page, and the renderer of Phase 6 takes text.
            "exintro": "1",
            "explaintext": "1",
            "exlimit": str(BATCH_SIZE),
            # Follow a redirect page rather than answer it. `query.redirects`
            # then records the move, and `_resolve_title` reads that record.
            "redirects": "1",
            "titles": TITLE_SEPARATOR.join(checked),
        }
    )
    return f"{api_url}?{parameters}"


def _rewrite_map(query: dict[str, Any], name: str, *, source: str) -> dict[str, str]:
    """Return the `from` to `to` map of `query[name]`, or an empty one.

    `normalized` and `redirects` have the same shape and the same job: each one
    records that the wiki answered a title other than the one that was asked
    for. An absent key means the wiki rewrote nothing.
    """
    entries = query.get(name)
    if entries is None:
        return {}
    if not isinstance(entries, list):
        raise FetchError(f"{source} answered a {name!r} of {type(entries).__name__}, not a list.")
    rewrites: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise FetchError(f"{source} answered a {name!r} entry of {entry!r}, not an object.")
        moved_from = entry.get("from")
        moved_to = entry.get("to")
        if not isinstance(moved_from, str) or not isinstance(moved_to, str):
            raise FetchError(f"{source} answered a {name!r} entry with no 'from' and 'to' pair.")
        rewrites[moved_from] = moved_to
    return rewrites


def _resolve_title(title: str, rewrites: dict[str, str], *, source: str) -> str:
    """Return the title that the answer holds for the requested `title`.

    This walks fact 4 of the module docstring. A request can be rewritten twice:
    `creepers` is normalized to `Creepers` and then redirected to `Creeper`. So
    the walk repeats until the map stops moving the title.

    The range is `MAX_REWRITE_HOPS + 1` because a hop and a look are not the
    same step. Following `n` hops takes `n` reads of the map to move the title
    and one more to see that it has stopped moving, so a plain
    `range(MAX_REWRITE_HOPS)` would follow one hop fewer than the constant names
    and would refuse a chain of exactly `MAX_REWRITE_HOPS` with a message saying
    it was rewritten more times than it was.
    """
    seen = {title}
    current = title
    for _ in range(MAX_REWRITE_HOPS + 1):
        moved_to = rewrites.get(current)
        if moved_to is None or moved_to == current:
            return current
        if moved_to in seen:
            raise FetchError(f"{source} rewrote {title!r} in a circle, so it names no page.")
        seen.add(moved_to)
        current = moved_to
    raise FetchError(
        f"{source} rewrote {title!r} more than {MAX_REWRITE_HOPS} times, so the walk was stopped."
    )


def _api_error_text(error: Any) -> str:
    """Return what the `error` key of a MediaWiki answer says, as one line."""
    if isinstance(error, dict):
        code = error.get("code")
        info = error.get("info")
        if code is not None or info is not None:
            return f"{code}: {info}"
    return str(error)


def _left_the_main_namespace(requested: str, answered: str, page: dict[str, Any]) -> bool:
    """Return whether a main-namespace request was answered from outside it.

    `redirects=1` is what makes this reachable. A caller asks for the article
    about a Minecraft thing, and the wiki is free to answer from wherever the
    redirect points: `Bricks` can be turned into a redirect to
    `User:Someone/Bricks draft` by one edit, and the answer would then carry
    that sandbox's lead paragraph under the requested title, with nothing in the
    page to say the namespace changed.

    CLAUDE.md draws that line for the Bucket tables -- the wiki indexes user
    sandboxes and translation projects beside the articles, a row from one of
    them is well-formed and therefore dangerous, and the filter belongs at the
    pipeline stage rather than at render time. A blurb is the same kind of fact
    arriving through a different action, so it gets the same test here, at the
    stage, rather than shipping and being noticed on a window.

    `ns` decides it when the answer carries one, because that is the wiki
    saying which namespace it used. A page with no `ns` falls back to the test
    that CLAUDE.md writes down: a main-namespace title holds no colon.

    A request that already names a namespace is left alone. The caller asked for
    that page by name and got it, and nothing was moved.
    """
    if ":" in requested:
        return False
    namespace = page.get("ns")
    if isinstance(namespace, int) and not isinstance(namespace, bool):
        return namespace != MAIN_NAMESPACE
    return ":" in answered


def parse_extracts_answer(payload: bytes, *, source: str, titles: Sequence[str]) -> ExtractReport:
    """Return the report that `payload` holds for `titles`, or raise `FetchError`.

    `titles` is what the caller asked for, and every one of them appears in the
    report exactly once, either as an extract or as a miss. That is what makes a
    lost page loud: the answer is read against the request, never on its own.

    A fault in the shape of the answer raises. A single page that the wiki does
    not hold becomes a miss. The line between the two is whether the build can
    trust the rest of the answer.
    """
    document = decode_json(payload, source=source)
    if not isinstance(document, dict):
        raise FetchError(f"{source} answered {type(document).__name__}, not an API answer.")
    error = document.get("error")
    if error is not None:
        raise FetchError(f"{source} refused the query: {_api_error_text(error)}")
    # The guard for fact 2. An answer that carries `continue` left pages
    # unread, and an answer with no `batchcomplete` did not finish the batch.
    # Neither one says which extracts are missing, so neither one can be read.
    if "continue" in document:
        raise FetchError(
            f"{source} answered a 'continue' key, so it did not answer every title of this "
            f"batch. The extracts of the rest are absent from the answer with no error."
        )
    if not document.get("batchcomplete"):
        raise FetchError(f"{source} answered no 'batchcomplete', so the batch is not complete.")
    query = document.get("query")
    if not isinstance(query, dict):
        raise FetchError(f"{source} answered no 'query' object, so it holds no pages.")
    pages = query.get("pages")
    if not isinstance(pages, list):
        raise FetchError(f"{source} answered no 'pages' list, so it holds no pages.")

    rewrites = _rewrite_map(query, "normalized", source=source)
    rewrites |= _rewrite_map(query, "redirects", source=source)

    answered: dict[str, dict[str, Any]] = {}
    for index, page in enumerate(pages):
        if not isinstance(page, dict):
            raise FetchError(f"{source} answered page {index} as {page!r}, not an object.")
        page_title = page.get("title")
        if not isinstance(page_title, str):
            raise FetchError(f"{source} answered page {index} with no title.")
        answered[page_title] = page

    extracts: list[PageExtract] = []
    misses: list[MissingExtract] = []
    for title in titles:
        page_title = _resolve_title(title, rewrites, source=source)
        page = answered.get(page_title)
        if page is None:
            # Every requested title is echoed by this API, rewritten or not. A
            # title with no page and no rewrite is an answer to some other
            # request, so nothing in it can be joined to this one.
            raise FetchError(f"{source} answered no page for {title!r}, which the request named.")
        if page.get("invalid"):
            misses.append(
                MissingExtract(requested_title=title, page_title=page_title, reason=INVALID_TITLE)
            )
            continue
        if page.get("missing"):
            misses.append(
                MissingExtract(requested_title=title, page_title=page_title, reason=MISSING_PAGE)
            )
            continue
        if _left_the_main_namespace(title, page_title, page):
            # The page exists and holds a blurb. It is still a miss, because the
            # blurb is not about the thing that was asked for. Reporting it is
            # what keeps a sandbox draft or a translation page from arriving on
            # a window as an entity's intro text with nothing marking it.
            misses.append(
                MissingExtract(
                    requested_title=title, page_title=page_title, reason=OFF_MAIN_NAMESPACE
                )
            )
            continue
        extract = page.get("extract")
        # The live answer ends a blurb with two newlines, so the text is
        # stripped before anything measures it. A page that holds only those
        # newlines holds no blurb.
        text = extract.strip() if isinstance(extract, str) else ""
        if not text:
            misses.append(
                MissingExtract(requested_title=title, page_title=page_title, reason=NO_EXTRACT)
            )
            continue
        page_id = page.get("pageid")
        extracts.append(
            PageExtract(
                requested_title=title,
                page_title=page_title,
                page_id=page_id if isinstance(page_id, int) else None,
                extract=text,
            )
        )
    return ExtractReport(extracts=tuple(extracts), misses=tuple(misses))


def fetch_page_extracts(
    titles: Iterable[str],
    *,
    revision: str,
    cache: ContentCache | None = None,
    transport: Transport | None = None,
    api_url: str = WIKI_API_URL,
    batch_size: int = BATCH_SIZE,
) -> ExtractReport:
    """Return the intro blurb of every title of `titles`, over as many requests as it takes.

    `revision` names the cache generation and has no default, for the reason
    that `pipeline.fetch.bucket` holds: a key of the URL alone would freeze the
    first read of a blurb forever. Pass the Minecraft version for a build, or a
    date for a wiki-only refresh.

    The titles are deduplicated and sorted before they are cut into batches. One
    set of titles then produces one set of URLs, whatever order the caller
    listed them in, so a rebuild reads the cache instead of the wiki.

    Pass `cache` to name the store, which every test does. Pass `transport` to
    read the bytes from somewhere else. `None` means `DEFAULT_TRANSPORT`, which
    already holds the rate limit and the retry that CLAUDE.md asks for.
    """
    check_revision(revision)
    if batch_size < 1 or batch_size > BATCH_SIZE:
        raise FetchError(f"an extracts batch holds 1 to {BATCH_SIZE} titles, not {batch_size}.")
    wanted = sorted({_checked_title(title) for title in titles})
    store = ContentCache() if cache is None else cache
    the_transport = DEFAULT_TRANSPORT if transport is None else transport
    reports: list[ExtractReport] = []
    for start in range(0, len(wanted), batch_size):
        batch = tuple(wanted[start : start + batch_size])
        url = build_extracts_url(batch, api_url=api_url)

        def read(
            payload: bytes, source: str = url, asked: tuple[str, ...] = batch
        ) -> ExtractReport:
            return parse_extracts_answer(payload, source=source, titles=asked)

        reports.append(
            fetch_and_read(
                store,
                url,
                transport=the_transport,
                read=read,
                key=f"extracts/{revision}/{url}",
            )
        )
    return ExtractReport.merge(reports)
