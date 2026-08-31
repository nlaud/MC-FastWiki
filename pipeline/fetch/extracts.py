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
   `pipeline.fetch.mediawiki.resolve_title` walks both maps, and `PageExtract`
   keeps both titles.

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

The title check, the two-step rewrite walk, and the `error`-object reader below
used to live here as private functions. `pipeline.fetch.mediawiki` is where
they live now, because `pipeline.fetch.wikitext` needed the same four functions
and had copied them near-verbatim rather than import a private name, and
`pipeline.fetch.imageinfo` needed three of the four as a third reader of this
same API. This module re-exports `MAX_REWRITE_HOPS` and `TITLE_SEPARATOR` under
its own name for the callers and tests that already read them from here.
"""

from collections.abc import Iterable, Sequence
from typing import Any
from urllib.parse import urlencode

from pydantic import BaseModel

from pipeline.fetch import WIKI_API_URL, FetchError, Transport, decode_json
from pipeline.fetch.cache import ContentCache, check_revision, fetch_and_read
from pipeline.fetch.mediawiki import (
    MAX_REWRITE_HOPS,
    TITLE_SEPARATOR,
    api_error_text,
    checked_title,
    resolve_title,
    rewrite_map,
)
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
    checked = [checked_title(title) for title in titles]
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
            # then records the move, and `resolve_title` reads that record.
            "redirects": "1",
            "titles": TITLE_SEPARATOR.join(checked),
        }
    )
    return f"{api_url}?{parameters}"


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
        raise FetchError(f"{source} refused the query: {api_error_text(error)}")
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

    rewrites = rewrite_map(query, "normalized", source=source)
    rewrites |= rewrite_map(query, "redirects", source=source)

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
        page_title = resolve_title(title, rewrites, source=source)
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
    wanted = sorted({checked_title(title) for title in titles})
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
