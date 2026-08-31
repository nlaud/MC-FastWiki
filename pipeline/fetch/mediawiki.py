"""Shared reading of the MediaWiki Action API: title checks, rewrites, and errors.

Three readers of Tier B ask a title-keyed action of `WIKI_API_URL` and all three
meet the same MediaWiki conventions on the way back. `pipeline.fetch.extracts`
asks `prop=extracts`, `pipeline.fetch.wikitext` asks `prop=revisions`, and
`pipeline.fetch.imageinfo` asks `prop=imageinfo` over the `File:` namespace.
Every one of them follows the same two-step title rewrite -- `query.normalized`
first, then `query.redirects` -- refuses the same shapes of title before a
request goes out, and reads the same `error` object when the server refuses the
query outright.

That logic used to live twice. `pipeline.fetch.wikitext` carried its own
`_checked_title`, `_rewrite_map`, `_resolve_title`, and `_api_error_text`, each
one a near-verbatim copy of `pipeline.fetch.extracts`'s private function of the
same name -- its docstrings said as much, admitting "Identical to
`pipeline.fetch.extracts._resolve_title`" rather than importing it. Adding a
third reader for `imageinfo` was the point at which copying a fourth time
stopped being the smaller change, so this module is the one home for all four
functions, and `extracts.py` and `wikitext.py` now import from here instead of
defining their own.

`checked_title` is used by the two title-batch readers, `extracts.py` and
`wikitext.py`. `imageinfo.py` also reuses it as-is: a `File:` title is still an
ordinary title as far as blank text, the `|` separator, and control characters
are concerned, and the rule that a file title must actually start with `File:`
is a fact about the *answer*'s namespace, not the request, so `imageinfo.py`
checks that itself. `rewrite_map`, `resolve_title`, and `api_error_text` are
shared unchanged by all three, because every one of them walks the same
two-key rewrite and reads the same error shape.
"""

from typing import Any

from pipeline.fetch import FetchError

__all__ = [
    "MAX_REWRITE_HOPS",
    "TITLE_SEPARATOR",
    "api_error_text",
    "checked_title",
    "resolve_title",
    "rewrite_map",
]

# What the API reads as the boundary between two titles.
TITLE_SEPARATOR = "|"

# How many rewrites `resolve_title` follows before it gives up. A rewrite chain
# of the wiki is one normalization and at most one redirect, so four is
# generous. The limit is here to end a loop that a cyclic map would otherwise
# run forever.
MAX_REWRITE_HOPS = 4


def checked_title(title: str) -> str:
    """Return `title` when it can name one wiki page, or raise `FetchError`.

    A blank title asks for nothing. A title that holds the separator asks for
    two pages under one name -- checked live against `prop=extracts`, which
    read `Weird|Title` as two separate pages. A control character is a sign
    that the caller built the title wrongly.
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


def rewrite_map(query: dict[str, Any], name: str, *, source: str) -> dict[str, str]:
    """Return the `from` to `to` map of `query[name]`, or an empty one.

    `normalized` and `redirects` have the same shape and the same job on every
    action of this API: each one records that the wiki answered a title other
    than the one that was asked for. An absent key means the wiki rewrote
    nothing.
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


def resolve_title(title: str, rewrites: dict[str, str], *, source: str) -> str:
    """Return the title that the answer holds for the requested `title`.

    A request can be rewritten twice: `creepers` is normalized to `Creepers`
    and then redirected to `Creeper`. So the walk repeats until the map stops
    moving the title.

    The range is `MAX_REWRITE_HOPS + 1` because a hop and a look are not the
    same step. Following `n` hops takes `n` reads of the map to move the title
    and one more to see that it has stopped moving, so a plain
    `range(MAX_REWRITE_HOPS)` would follow one hop fewer than the constant
    names and would refuse a chain of exactly `MAX_REWRITE_HOPS` with a message
    saying it was rewritten more times than it was.
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


def api_error_text(error: Any) -> str:
    """Return what the `error` key of a MediaWiki answer says, as one line."""
    if isinstance(error, dict):
        code = error.get("code")
        info = error.get("info")
        if code is not None or info is not None:
            return f"{code}: {info}"
    return str(error)
