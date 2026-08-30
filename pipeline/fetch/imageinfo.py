"""The URL, size, and hash of a wiki-hosted file: `prop=imageinfo`, batched.

`pipeline.enrich.sprite` names which `File:` page holds each icon this project
draws. Nothing about that page's own title says where the bytes live or
whether they have changed since the last build, and the wiki does not put
either fact in a bucket. `prop=imageinfo` is the third action of the MediaWiki
API this pipeline reads, after `action=bucket` and `prop=extracts`::

    action=query&format=json&formatversion=2&prop=imageinfo
    &iiprop=url|size|sha1|mime&redirects=1&titles=File:A.png|File:B.png

`fetch_file_images` takes the titles and returns an `ImageInfoReport`, the same
shape `pipeline.fetch.extracts.ExtractReport` uses: the images it read, and the
titles it could not, each miss naming its reason.

Four facts about the live API shape this module. All four were checked against
`https://minecraft.wiki/api.php` on 2026-08-30.

1. **The cap is 50 titles, not the 20 of `prop=extracts`.** Both props share
   one server-side limit family, but `iiprop` is not `exlimit`: it has no
   analogue at all, because `imageinfo` answers one entry per requested file
   rather than a count the caller tunes. The 50-title ceiling is the general
   `titles` parameter limit for an unauthenticated request, which
   `pipeline.fetch.wikitext` also reads at 50 for the same reason. So
   `BATCH_SIZE = 50` here, not the 20 `pipeline.fetch.extracts.BATCH_SIZE`
   uses -- the two readers hit two different limits of the same API, and
   copying the wrong one would either waste requests or trip a wall.

2. **A missing file answers `"missing": true` with no `imageinfo` key at
   all**, the same shape `prop=extracts` uses for a missing page. One bad
   title -- a sprite the wiki catalogued and then deleted -- must not fail a
   read of several thousand files, so it becomes a `MissingImage` instead.

3. **The `url` carries a cache-busting query string that changes when the file
   is re-uploaded**: `Invicon_Raw_Iron.png?d47d8` today, a different suffix
   after the next edit. `pipeline.fetch.cache.ContentCache` is content-addressed
   by the SHA-256 of what it stores, and a URL that changes for a reason that
   has nothing to do with the pixels would break that promise here in a subtle
   way -- not by storing the wrong bytes, but by never reusing the right ones.
   So `pipeline.fetch.sprites.sprite_cache_key` builds its key from `sha1`, the
   field this module carries for exactly that reason, and never from `url`.

4. **`query.normalized` and `query.redirects` behave exactly as they do for
   `prop=extracts`**, because both props sit under the same `action=query` and
   share the same title-resolution step. `pipeline.fetch.mediawiki` is the
   shared home of that walk, used here unchanged rather than copied a third
   time -- see that module's docstring for why a third copy was the point at
   which copying stopped being the smaller change.

The `File:` namespace is namespace 6. This module checks it on the way in --
`build_imageinfo_url` reuses the ordinary title check that `extracts.py` and
`wikitext.py` both use, since a blank title, a `|`, and a control character are
exactly as wrong in a file title as in an article title -- and on the way out,
because a title that answers from another namespace names a page this reader
should never have been pointed at.

Cache key is `imageinfo/<revision>/<url>`, matching the rule `pipeline.fetch.bucket`
states in full: a wiki URL does not name immutable bytes, so the key carries a
caller revision, and `revision` is a required argument with no default.
"""

import re
from collections.abc import Iterable, Sequence
from typing import Any
from urllib.parse import urlencode

from pydantic import BaseModel, field_validator

from pipeline.fetch import WIKI_API_URL, FetchError, Transport, decode_json
from pipeline.fetch.cache import ContentCache, check_revision, fetch_and_read
from pipeline.fetch.mediawiki import api_error_text, checked_title, resolve_title, rewrite_map
from pipeline.fetch.polite import WIKI_TRANSPORT

__all__ = [
    "BATCH_SIZE",
    "DEFAULT_TRANSPORT",
    "FILE_NAMESPACE_ID",
    "IIPROP",
    "INVALID_TITLE",
    "MISSING_FILE",
    "NO_IMAGE_INFO",
    "OFF_FILE_NAMESPACE",
    "SHA1_PATTERN",
    "FileImage",
    "ImageInfoReport",
    "MissingImage",
    "build_imageinfo_url",
    "fetch_file_images",
    "parse_imageinfo_answer",
]

# The most titles one `prop=imageinfo` request names. See fact 1 of the module
# docstring: this is the general `titles` parameter ceiling, not an `iiprop`
# analogue of `exlimit`, and it is 50, not the 20 that `prop=extracts` caps at.
BATCH_SIZE = 50

# The `File:` namespace. Every title this module answers for should resolve
# inside it, because a redirect that left it would name some other page's
# imageinfo under a sprite's title.
FILE_NAMESPACE_ID = 6

# The imageinfo properties this module reads. `url` and `size` are what a
# sprite download needs; `sha1` is the content-hash cache key fact 3 of the
# module docstring explains; `mime` is what `pipeline.fetch.sprites` checks
# before it trusts a payload is an image at all.
IIPROP = "url|size|sha1|mime"

# Why a requested title carries no image. Each one is a report line, not an
# error, because one bad title must not fail a read of several thousand files.
MISSING_FILE = "the wiki holds no file of this title"
INVALID_TITLE = "the wiki reads this title as invalid"
NO_IMAGE_INFO = "the file answered no imageinfo entry"
OFF_FILE_NAMESPACE = "a redirect moved this title out of the File namespace"

# A SHA-1 digest: 40 lowercase hexadecimal characters. `pipeline.fetch.sprites`
# imports this pattern rather than writing its own, so a download's own hash
# check and this field's validation agree on what a usable digest looks like.
SHA1_PATTERN = re.compile(r"[0-9a-f]{40}\Z")

# The transport an imageinfo read uses when the caller names none.
#
# `WIKI_TRANSPORT`, and not a `polite_transport()` of this module, for the
# reason `pipeline.fetch.polite` gives in full: a rate limit belongs to a host,
# every wiki reader of this package reads `WIKI_API_URL`, and two limiters do
# not space each other. A read of the roughly 3,200 files this project draws
# icons from is over 60 requests at this module's batch size, and nothing
# fails or warns if they all leave the process without a shared limiter.
DEFAULT_TRANSPORT: Transport = WIKI_TRANSPORT


class FileImage(BaseModel, frozen=True):
    """One `File:` page's current upload: where it lives, and how to prove a copy matches it."""

    title: str
    url: str
    sha1: str
    size: int
    width: int
    height: int
    mime: str

    @field_validator("sha1")
    @classmethod
    def _sha1_must_be_a_full_digest(cls, value: str) -> str:
        """Refuse a `sha1` that is not 40 lowercase hexadecimal characters.

        Every later stage keys its cache on this string, so a short or
        malformed digest here becomes a lookup that appears to work and never
        matches anything: `pipeline.fetch.sprites.sprite_cache_key` would build
        a key from it, and no download would ever verify against it either.
        """
        if SHA1_PATTERN.fullmatch(value) is None:
            raise FetchError(f"{value!r} is not a 40-character lowercase sha1 digest.")
        return value

    @field_validator("size", "width", "height")
    @classmethod
    def _dimension_must_be_positive(cls, value: int) -> int:
        """Refuse a size, width, or height that is zero or negative.

        The wiki has never been observed to answer one, and a non-positive
        value could not describe a real image: a caller that guarded a
        division or an aspect ratio on this field must be able to trust it.
        """
        if value <= 0:
            raise FetchError(f"an image dimension must be positive, and {value} is not.")
        return value


class MissingImage(BaseModel, frozen=True):
    """One requested `File:` title that carries no usable image, and the reason for it."""

    title: str
    # One of `MISSING_FILE`, `INVALID_TITLE`, `NO_IMAGE_INFO`, or
    # `OFF_FILE_NAMESPACE`.
    reason: str


class ImageInfoReport(BaseModel, frozen=True):
    """What one read of the imageinfo API produced: the images, and the misses.

    The same trio shape as `pipeline.fetch.extracts.ExtractReport`: a merge
    across batches, and a lookup by the title a caller actually asked for.
    """

    images: tuple[FileImage, ...] = ()
    missing: tuple[MissingImage, ...] = ()

    @classmethod
    def merge(cls, reports: Sequence["ImageInfoReport"]) -> "ImageInfoReport":
        """Return one report over `reports`, in the order they were read."""
        return cls(
            images=tuple(entry for report in reports for entry in report.images),
            missing=tuple(entry for report in reports for entry in report.missing),
        )

    @property
    def by_title(self) -> dict[str, FileImage]:
        """Return the requested title of each image, mapped to the image.

        Built on each access, because a frozen model cannot memoize. Call it
        once and hold the result. A caller that wants the misses as well reads
        `missing` directly.
        """
        return {entry.title: entry for entry in self.images}


def build_imageinfo_url(titles: Sequence[str], *, api_url: str = WIKI_API_URL) -> str:
    """Return the URL that reads the imageinfo of every title of `titles`.

    Pure, so a test reads the URL without a socket. `checked_title` is the
    ordinary title check every title-batch reader of this package shares --
    see `pipeline.fetch.mediawiki` for why a `File:` title needs no check
    beyond it: the `File:` prefix is a fact this module tests on the answer,
    not a shape it enforces on the request.
    """
    if not titles:
        raise FetchError("an imageinfo request must name at least one title.")
    if len(titles) > BATCH_SIZE:
        raise FetchError(
            f"an imageinfo request cannot name more than {BATCH_SIZE} titles, and this one "
            f"names {len(titles)}."
        )
    checked = [checked_title(title) for title in titles]
    if len(set(checked)) != len(checked):
        raise FetchError("an imageinfo request names each title once. This one repeats a title.")
    parameters = urlencode(
        {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "prop": "imageinfo",
            "iiprop": IIPROP,
            # Follow a redirect page rather than answer it, matching
            # `pipeline.fetch.extracts` and `pipeline.fetch.wikitext`.
            "redirects": "1",
            "titles": "|".join(checked),
        }
    )
    return f"{api_url}?{parameters}"


def _left_the_file_namespace(page: dict[str, Any]) -> bool:
    """Return whether `page` answered from outside the `File:` namespace.

    `redirects=1` lets the wiki decide which page answers a request, the same
    obligation `pipeline.fetch.extracts._left_the_main_namespace` names in
    full. Every title asked for here already carries a `File:` prefix, so
    there is no bare-title case to fall back to the way that function does:
    `ns` is always in the answer for a real `File:` page, and a page that
    lacks it or holds another namespace's number was not the file this module
    asked for.
    """
    namespace = page.get("ns")
    if not isinstance(namespace, int) or isinstance(namespace, bool):
        return True
    return namespace != FILE_NAMESPACE_ID


def _file_image(entries: list[Any], *, title: str, source: str) -> FileImage:
    """Return the `FileImage` that the first of `entries` describes, or raise `FetchError`.

    Called only once the caller knows `entries` is a non-empty `imageinfo`
    list, so a missing key here is a shape fault -- the API changed what it
    answers -- rather than a per-title miss.
    """
    first = entries[0]
    if not isinstance(first, dict):
        raise FetchError(f"{source} answered an imageinfo entry of {first!r}, not an object.")
    try:
        return FileImage(
            title=title,
            url=first["url"],
            sha1=first["sha1"],
            size=first["size"],
            width=first["width"],
            height=first["height"],
            mime=first["mime"],
        )
    except KeyError as error:
        raise FetchError(
            f"{source} answered an imageinfo entry with no {error}: {first!r}"
        ) from error


def parse_imageinfo_answer(
    payload: bytes, *, source: str, titles: Sequence[str]
) -> ImageInfoReport:
    """Return the report that `payload` holds for `titles`, or raise `FetchError`.

    `titles` is what the caller asked for, and every one of them appears in the
    report exactly once, either as a `FileImage` or a `MissingImage` -- the
    same discipline `pipeline.fetch.extracts.parse_extracts_answer` keeps, so a
    title the answer forgot is loud rather than quietly absent.
    """
    document = decode_json(payload, source=source)
    if not isinstance(document, dict):
        raise FetchError(f"{source} answered {type(document).__name__}, not an API answer.")
    error = document.get("error")
    if error is not None:
        raise FetchError(f"{source} refused the query: {api_error_text(error)}")
    if "continue" in document:
        raise FetchError(
            f"{source} answered a 'continue' key, so it did not answer every title of this "
            f"batch. The imageinfo of the rest is absent from the answer with no error."
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

    images: list[FileImage] = []
    missing: list[MissingImage] = []
    for title in titles:
        page_title = resolve_title(title, rewrites, source=source)
        page = answered.get(page_title)
        if page is None:
            raise FetchError(f"{source} answered no page for {title!r}, which the request named.")
        if page.get("invalid"):
            missing.append(MissingImage(title=title, reason=INVALID_TITLE))
            continue
        if page.get("missing"):
            missing.append(MissingImage(title=title, reason=MISSING_FILE))
            continue
        if _left_the_file_namespace(page):
            missing.append(MissingImage(title=title, reason=OFF_FILE_NAMESPACE))
            continue
        entries = page.get("imageinfo")
        if not isinstance(entries, list) or not entries:
            missing.append(MissingImage(title=title, reason=NO_IMAGE_INFO))
            continue
        images.append(_file_image(entries, title=title, source=source))
    return ImageInfoReport(images=tuple(images), missing=tuple(missing))


def fetch_file_images(
    titles: Iterable[str],
    *,
    revision: str,
    cache: ContentCache | None = None,
    transport: Transport | None = None,
    api_url: str = WIKI_API_URL,
    batch_size: int = BATCH_SIZE,
) -> ImageInfoReport:
    """Return the imageinfo of every title of `titles`, over as many requests as it takes.

    `revision` names the cache generation and has no default, for the reason
    `pipeline.fetch.bucket` states in full: a key of the URL alone would freeze
    the first read of a file's imageinfo forever, and a re-uploaded sprite
    would never be seen again. Pass the Minecraft version for a build, or a
    date for a wiki-only refresh.

    The titles are deduplicated and sorted before they are cut into batches, so
    one set of titles produces one set of URLs whatever order the caller listed
    them in, matching `pipeline.fetch.extracts.fetch_page_extracts`.

    Pass `cache` to name the store, which every test does. Pass `transport` to
    read the bytes from somewhere else. `None` means `DEFAULT_TRANSPORT`, which
    already holds the rate limit and the retry that CLAUDE.md asks for.
    """
    check_revision(revision)
    if batch_size < 1 or batch_size > BATCH_SIZE:
        raise FetchError(f"an imageinfo batch holds 1 to {BATCH_SIZE} titles, not {batch_size}.")
    wanted = sorted({checked_title(title) for title in titles})
    store = ContentCache() if cache is None else cache
    the_transport = DEFAULT_TRANSPORT if transport is None else transport
    reports: list[ImageInfoReport] = []
    for start in range(0, len(wanted), batch_size):
        batch = tuple(wanted[start : start + batch_size])
        url = build_imageinfo_url(batch, api_url=api_url)

        def read(
            payload: bytes, source: str = url, asked: tuple[str, ...] = batch
        ) -> ImageInfoReport:
            return parse_imageinfo_answer(payload, source=source, titles=asked)

        reports.append(
            fetch_and_read(
                store,
                url,
                transport=the_transport,
                read=read,
                key=f"imageinfo/{revision}/{url}",
            )
        )
    return ImageInfoReport.merge(reports)
