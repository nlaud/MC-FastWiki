"""Raw page source of a wiki page: batched, joined back to the title asked for.

`pipeline.fetch.bucket` reads structured rows and `pipeline.fetch.extracts`
reads the intro blurb, but neither carries the infobox fields Phase 2 needs --
`health`, `damage`, `size`, and the rest live only in the page's own wikitext.
This module is the third reader of Tier B, and it takes the plainest possible
shape: ask for the current revision's source of a batch of titles::

    action=query&format=json&formatversion=2&prop=revisions
    &rvprop=content&rvslots=main&redirects=1&titles=Creeper|Zombie|...

`fetch_page_wikitext` takes the titles and returns a `WikitextReport`, which
holds the pages it read and the titles it could not read, each miss naming its
reason -- the same shape `pipeline.fetch.extracts` uses, for the same reason:
CLAUDE.md says an empty scrape result is a failure to report.

Seven facts about the live API shape this module. Two of them are the opposite
of what `pipeline.fetch.extracts` teaches about this endpoint, so a reader who
knows that module first needs to unlearn a rule here rather than reuse it. All
seven were checked against `https://minecraft.wiki/api.php` on 2026-08-30.

1. **51 titles is a hard error, not a silent truncation.** This is the trap
   `pipeline.fetch.extracts` warns about, inverted. There, `exlimit` caps at
   20 and asking for more answers every page with only 20 extracts and no
   error -- the loss is silent. Here, 51 titles answers HTTP 200 with
   `{"error": {"code": "toomanyvalues", "info": "Too many values supplied for
   parameter \\"titles\\". The limit is 50.", "limit": 50, ...}}` and no
   `query` key at all. So `BATCH_SIZE = 50` is a courtesy that keeps a caller
   from tripping the wall, not a guard against a loss nothing else would show.
   The parser still refuses the `error` key the way `parse_bucket_answer` and
   `parse_extracts_answer` both do, because the trap this module actually
   guards against is fact 7 below.

2. **Two rewrite maps, both must be followed, exactly as `extracts.py` reads
   them.** `query.normalized` maps `creeper` to `Creeper` (the wiki
   capitalizing the request); `query.redirects` maps `Creepers` to `Creeper`
   (the wiki following a redirect page). `_resolve_title` below is the same
   walk `pipeline.fetch.extracts` uses, because the trap is identical: the
   answered page carries only the final title, so a reader that matched on the
   requested title would find nothing for either kind of rewrite.

3. **The join is many-to-one.** Requesting `creeper` and `Creepers` in one
   batch answers exactly one page object titled `Creeper`. A join that read
   `pages` as one entry per requested title would lose one of the two.

4. **Namespace answers as a number, and that is strictly better than the
   string heuristic `extracts.py` is forced into.** `Talk:Creeper` answers
   `"ns": 1`; a main-namespace article answers `"ns": 0`. `extracts.py` falls
   back to "no colon in the title" only because some of its answers omit `ns`
   entirely; every revisions answer checked here carries it, so this module
   tests `ns == 0` outright and needs no fallback.

5. **Missing and invalid are both a miss, never a build failure.** A title the
   wiki does not hold answers `{"missing": true}` with no `revisions` key. A
   title that cannot exist answers `{"invalid": true}` and no `ns`. One bad
   title among the roughly 80 mob pages a build asks for must not stop it.

6. **The content sits three keys deep, and a page can lack the outer two.**
   `page["revisions"][0]["slots"]["main"]["content"]` is the wikitext. A page
   with no `revisions` key at all -- checked live by asking for a title that
   exists but naming no `rvslots` would not happen here since this module
   always asks for one, but a stub or a page the API otherwise declines to
   answer content for is still possible -- is its own kind of miss, distinct
   from `missing` and `invalid`.

7. **A good answer carries `batchcomplete` and no `continue`.** This is the
   same signal `pipeline.fetch.extracts` guards, fact 2 of that module's
   docstring, and it means the same thing here: an answer that carries
   `continue` left some of the batch unread, and nothing in the shape says
   which titles lost their content. Refusing it is the only honest option.

Cache key is `wikitext/<revision>/<url>`, exactly as `pipeline.fetch.bucket`
states the rule in full: a wiki URL does not name immutable bytes, so the key
carries a caller revision, and `revision` is a required argument with no
default. Default transport is `WIKI_TRANSPORT` from `pipeline.fetch.polite`,
the one rate limiter every wiki reader of this package shares -- see that
module for why a second `polite_transport()` here would double the request
rate the wiki actually sees.

This module reads what the wiki said and nothing more. It resolves no
template, strips no markup, and applies no edition filter.
`pipeline.enrich.markup` and `pipeline.enrich.infobox` do that reading.
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
    "NO_CONTENT",
    "TITLE_SEPARATOR",
    "MissingWikitext",
    "PageWikitext",
    "WikitextReport",
    "build_wikitext_url",
    "fetch_page_wikitext",
    "parse_wikitext_answer",
]

# The most titles one request names. See fact 1: unlike `pipeline.fetch.extracts`,
# where the cap is a loss that arrives with no error, this cap is a wall. 51
# titles answers `toomanyvalues` and nothing else, so this constant is a
# courtesy that keeps a caller from writing a request the server would refuse.
BATCH_SIZE = 50

# What the API reads as the boundary between two titles.
TITLE_SEPARATOR = "|"

# How many rewrites `_resolve_title` follows before it gives up. Copied from
# `pipeline.fetch.extracts`, which explains the `+ 1` in the range below: a
# rewrite chain of the wiki is one normalization and at most one redirect, and
# a hop and a look are not the same step.
MAX_REWRITE_HOPS = 4

# The wiki namespace that holds the article about a Minecraft thing. Fact 4:
# every answer this module reads carries `ns`, so the test is the number
# itself rather than the string fallback `pipeline.fetch.extracts` needs.
MAIN_NAMESPACE = 0

# Why a requested title carries no wikitext. Each one is a report line, not an
# error, because one bad title must not stop a build of roughly 80 mob pages.
MISSING_PAGE = "the wiki holds no page of this title"
INVALID_TITLE = "the wiki reads this title as invalid"
NO_CONTENT = "the page answered no revision content"

# The transport a wikitext read uses when the caller names none. `WIKI_TRANSPORT`
# and not a `polite_transport()` built here, for the reason
# `pipeline.fetch.polite` gives in full: a rate limit belongs to the host, all
# three wiki readers of this package read `WIKI_API_URL`, and two limiters do
# not space each other.
DEFAULT_TRANSPORT: Transport = WIKI_TRANSPORT


class PageWikitext(BaseModel, frozen=True):
    """One page's raw wikitext source, and both titles that name the page it came from."""

    # The title that the caller asked for.
    requested_title: str
    # The title that the wiki answered. Differs from `requested_title` when the
    # wiki capitalized the request or followed a redirect.
    page_title: str
    page_id: int | None
    # The raw wikitext of the current revision, unparsed.
    content: str


class MissingWikitext(BaseModel, frozen=True):
    """One requested title that carries no wikitext, and the reason for it."""

    requested_title: str
    page_title: str
    # One of `MISSING_PAGE`, `INVALID_TITLE`, or `NO_CONTENT`.
    reason: str


class WikitextReport(BaseModel, frozen=True):
    """What one read of the wikitext API produced: the pages, and the misses."""

    pages: tuple[PageWikitext, ...] = ()
    misses: tuple[MissingWikitext, ...] = ()

    @classmethod
    def merge(cls, reports: Sequence["WikitextReport"]) -> "WikitextReport":
        """Return one report over `reports`, in the order they were read."""
        return cls(
            pages=tuple(entry for report in reports for entry in report.pages),
            misses=tuple(entry for report in reports for entry in report.misses),
        )

    def contents(self) -> dict[str, str]:
        """Return the requested title of each page, mapped to its wikitext.

        Built on each call, because a frozen model cannot memoize. Call it once
        and hold the result.
        """
        return {entry.requested_title: entry.content for entry in self.pages}


def _checked_title(title: str) -> str:
    """Return `title` when it can name one wiki page, or raise `FetchError`.

    Identical to `pipeline.fetch.extracts._checked_title`: a blank title asks
    for nothing, a title holding the separator asks for two pages under one
    name, and a control character is a sign the caller built the title wrongly.
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


def build_wikitext_url(titles: Sequence[str], *, api_url: str = WIKI_API_URL) -> str:
    """Return the URL that reads the current wikitext of every title of `titles`.

    The function is pure, so a test reads the URL without a socket. `BATCH_SIZE`
    is refused above rather than left to the server, even though fact 1 of the
    module docstring says the server would refuse it too: a caller of this
    function should see the fault at the point that built the request, with a
    message that explains why, rather than a bare `toomanyvalues` from the wiki.
    """
    if not titles:
        raise FetchError("a wikitext request must name at least one title.")
    if len(titles) > BATCH_SIZE:
        raise FetchError(
            f"a wikitext request cannot name more than {BATCH_SIZE} titles, and this one names "
            f"{len(titles)}. The API answers a larger batch with an error and no pages at all."
        )
    checked = [_checked_title(title) for title in titles]
    if len(set(checked)) != len(checked):
        raise FetchError("a wikitext request names each title once. This one repeats a title.")
    parameters = urlencode(
        {
            "action": "query",
            "format": "json",
            # `formatversion=2` keys `pages` as a list, each entry carrying its
            # own title. Version 1 keys by page ID and collides every missing
            # page on `-1` -- `pipeline.fetch.extracts` explains this in full.
            "formatversion": "2",
            "prop": "revisions",
            # The wikitext of the current revision, from the main slot. Every
            # page this pipeline reads is unversioned single-slot content, so
            # there is exactly one slot to name.
            "rvprop": "content",
            "rvslots": "main",
            # Follow a redirect page rather than answer it, matching
            # `pipeline.fetch.extracts`. `query.redirects` then records the
            # move, and `_resolve_title` reads that record.
            "redirects": "1",
            "titles": TITLE_SEPARATOR.join(checked),
        }
    )
    return f"{api_url}?{parameters}"


def _rewrite_map(query: dict[str, Any], name: str, *, source: str) -> dict[str, str]:
    """Return the `from` to `to` map of `query[name]`, or an empty one.

    Identical in shape and purpose to `pipeline.fetch.extracts._rewrite_map`.
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

    Identical to `pipeline.fetch.extracts._resolve_title`; see that function
    for why the loop runs `MAX_REWRITE_HOPS + 1` times rather than
    `MAX_REWRITE_HOPS`.
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


def _page_content(page: dict[str, Any], *, source: str) -> str | None:
    """Return the wikitext of `page`, or `None` when it carries none.

    Fact 6 of the module docstring: the content sits three keys under
    `revisions`, and a page can lack any of them. `None` here becomes
    `NO_CONTENT` in the report rather than an empty string reaching a parser,
    because an infobox parser that read an empty string would report every
    field of that page as unparsed with no reason pointing at the real cause.
    """
    revisions = page.get("revisions")
    if not isinstance(revisions, list) or not revisions:
        return None
    first = revisions[0]
    if not isinstance(first, dict):
        raise FetchError(f"{source} answered a revision of {first!r}, not an object.")
    slots = first.get("slots")
    if not isinstance(slots, dict):
        return None
    main = slots.get("main")
    if not isinstance(main, dict):
        return None
    content = main.get("content")
    return content if isinstance(content, str) else None


def parse_wikitext_answer(payload: bytes, *, source: str, titles: Sequence[str]) -> WikitextReport:
    """Return the report that `payload` holds for `titles`, or raise `FetchError`.

    `titles` is what the caller asked for, and every one of them appears in the
    report exactly once, either as a page or as a miss -- the same discipline
    `pipeline.fetch.extracts.parse_extracts_answer` keeps, and for the same
    reason: the answer is read against the request, never on its own, so a
    title the answer forgot is loud rather than quietly absent.
    """
    document = decode_json(payload, source=source)
    if not isinstance(document, dict):
        raise FetchError(f"{source} answered {type(document).__name__}, not an API answer.")
    error = document.get("error")
    if error is not None:
        raise FetchError(f"{source} refused the query: {_api_error_text(error)}")
    # Fact 7. An answer that carries `continue` left some of the batch unread,
    # and nothing in the shape says which titles lost their content.
    if "continue" in document:
        raise FetchError(
            f"{source} answered a 'continue' key, so it did not answer every title of this "
            f"batch. The content of the rest is absent from the answer with no error."
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

    found: list[PageWikitext] = []
    misses: list[MissingWikitext] = []
    for title in titles:
        page_title = _resolve_title(title, rewrites, source=source)
        page = answered.get(page_title)
        if page is None:
            raise FetchError(f"{source} answered no page for {title!r}, which the request named.")
        if page.get("invalid"):
            misses.append(
                MissingWikitext(requested_title=title, page_title=page_title, reason=INVALID_TITLE)
            )
            continue
        if page.get("missing"):
            misses.append(
                MissingWikitext(requested_title=title, page_title=page_title, reason=MISSING_PAGE)
            )
            continue
        content = _page_content(page, source=source)
        if content is None:
            misses.append(
                MissingWikitext(requested_title=title, page_title=page_title, reason=NO_CONTENT)
            )
            continue
        page_id = page.get("pageid")
        found.append(
            PageWikitext(
                requested_title=title,
                page_title=page_title,
                page_id=page_id if isinstance(page_id, int) else None,
                content=content,
            )
        )
    return WikitextReport(pages=tuple(found), misses=tuple(misses))


def fetch_page_wikitext(
    titles: Iterable[str],
    *,
    revision: str,
    cache: ContentCache | None = None,
    transport: Transport | None = None,
    api_url: str = WIKI_API_URL,
    batch_size: int = BATCH_SIZE,
) -> WikitextReport:
    """Return the wikitext of every title of `titles`, over as many requests as it takes.

    `revision` names the cache generation and has no default, for the reason
    `pipeline.fetch.bucket` states in full: a key of the URL alone would freeze
    the first read of a page's source forever. Pass the Minecraft version for a
    build, or a date for a wiki-only refresh.

    The titles are deduplicated and sorted before they are cut into batches, so
    one set of titles produces one set of URLs whatever order the caller listed
    them in, and a rebuild reads the cache instead of the wiki.

    Pass `cache` to name the store, which every test does. Pass `transport` to
    read the bytes from somewhere else. `None` means `DEFAULT_TRANSPORT`, which
    already holds the rate limit and the retry that CLAUDE.md asks for.
    """
    check_revision(revision)
    if batch_size < 1 or batch_size > BATCH_SIZE:
        raise FetchError(f"a wikitext batch holds 1 to {BATCH_SIZE} titles, not {batch_size}.")
    wanted = sorted({_checked_title(title) for title in titles})
    store = ContentCache() if cache is None else cache
    the_transport = DEFAULT_TRANSPORT if transport is None else transport
    reports: list[WikitextReport] = []
    for start in range(0, len(wanted), batch_size):
        batch = tuple(wanted[start : start + batch_size])
        url = build_wikitext_url(batch, api_url=api_url)

        def read(
            payload: bytes, source: str = url, asked: tuple[str, ...] = batch
        ) -> WikitextReport:
            return parse_wikitext_answer(payload, source=source, titles=asked)

        reports.append(
            fetch_and_read(
                store,
                url,
                transport=the_transport,
                read=read,
                key=f"wikitext/{revision}/{url}",
            )
        )
    return WikitextReport.merge(reports)
