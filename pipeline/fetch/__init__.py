"""Upstream fetchers. Every network read of the pipeline starts here.

The pipeline is the only half of this repository that reads the network, and it
reads it at build time alone. The browser never talks to Mojang, to mcmeta, or
to the wiki. CLAUDE.md holds the reason.

This module holds what every fetcher needs: the User-Agent string, one GET over
`urllib.request`, one JSON decode, and one error class for both. A stage that
needs a payload calls `get_bytes` and hands the result to its own parser, so the
parser stays pure and its tests need no socket.
"""

import http.client
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from http import HTTPStatus
from typing import IO, Any
from urllib.parse import urlsplit

from pipeline import __version__

__all__ = [
    "ALLOWED_SCHEMES",
    "DEFAULT_TIMEOUT_SECONDS",
    "OPENER",
    "USER_AGENT",
    "FetchError",
    "HttpsOnlyRedirectHandler",
    "Transport",
    "build_request",
    "decode_json",
    "get_bytes",
]

# CLAUDE.md asks this pipeline to be a good citizen with the services it reads,
# and one of them is a volunteer-run wiki. A request that names the project and
# its repository lets an operator see where the traffic comes from and reach
# someone about it. The default `Python-urllib/3.12` says neither, and some
# hosts block it outright.
USER_AGENT = f"MC-FastWiki/{__version__} (+https://github.com/nlaud/MC-FastWiki)"

# A stalled read must fail the build, not hang it. CI has no keyboard.
DEFAULT_TIMEOUT_SECONDS = 30.0

# Every upstream of this project speaks HTTPS. `urlopen` also serves `file:`
# and `ftp:`, so a URL that arrives from a data file could read a local path
# under the name of a fetch. `build_request` closes that door for the URL the
# caller passes, and `HttpsOnlyRedirectHandler` below closes it again for every
# URL an upstream names in a `Location` header.
ALLOWED_SCHEMES = frozenset({"https"})

# What a fetcher takes in place of the real network. A test passes its own
# callable and returns bytes it wrote itself.
type Transport = Callable[[str], bytes]


class FetchError(Exception):
    """One upstream read failed, or its payload was not what the caller asked for.

    Every fault of a fetch arrives as this class: a refused connection, a
    timeout, a status code other than 200, a body that is not JSON, and a body
    whose shape the parser rejects. A caller then stops the build on one
    exception type instead of on the union of what `urllib`, `http.client`, and
    `json` raise.

    `status` and `retry_after` carry what the server said, for the one caller
    that must tell two faults apart. `pipeline.fetch.polite` retries a 429 and a
    5xx, and it must not retry a 404: the answer to a bad URL does not change,
    and a repeat only loads a service that this project reads as a guest. A
    fault with no status is a timeout or a refused connection, which a retry can
    fix, so `None` is the retryable value and not the safe one.

    `retry_after` is the `Retry-After` header, undecoded. RFC 9110 allows two
    forms there, a count of seconds and an HTTP date, and the policy that waits
    owns the choice between them. Both attributes default to `None`, so every
    caller that raises this class with a message alone keeps working.
    """

    def __init__(
        self,
        *args: object,
        status: int | None = None,
        retry_after: str | None = None,
    ) -> None:
        super().__init__(*args)
        self.status = status
        self.retry_after = retry_after


class HttpsOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Apply the HTTPS-only rule to every hop of a redirect chain, not just the first.

    `build_request` checks the URL that the caller passes, and that check alone
    is not the guard it reads as. `urlopen` follows a redirect on its own, and
    the scheme filter it applies while doing so is `urllib`'s, not this
    project's: `HTTPRedirectHandler.http_error_302` refuses `file:` but permits
    `http:` and `ftp:`. So an upstream that answers `301 Location: http://...`
    moves the whole read to cleartext, and `get_bytes` hands back the body with
    no error and no record that the transport changed.

    That is not a theoretical downgrade for this pipeline. `get_bytes` is the
    single door for every network read of the build, and the first thing it
    reads is the ID of the current Minecraft release. Anyone on the path of a
    cleartext hop can rewrite the manifest, and a manifest is easy to rewrite
    consistently: name a snapshot in `latest.release`, and give the same entry
    `"type": "release"` so the guard in `version_manifest.py` agrees. The build
    then runs against the wrong version of the game, and wrong Minecraft numbers
    look exactly like right ones on the screen.

    The refusal is an `HTTPError` because that is what `urllib` itself raises
    from `http_error_302` for a scheme it will not follow. It carries the
    response file object the same way, so the socket is released the same way,
    and `get_bytes` maps it to `FetchError` with every other transport fault.
    """

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        scheme = urlsplit(newurl).scheme
        if scheme not in ALLOWED_SCHEMES:
            raise urllib.error.HTTPError(
                newurl,
                code,
                f"{msg} - redirect to a {scheme!r} URL. This pipeline fetches HTTPS only.",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# One opener, built once, used by `get_bytes` for every read.
#
# `urllib.request.urlopen` builds its own opener from the default handlers, and
# the default redirect handler is the permissive one described above, so this
# module cannot call `urlopen`. `build_opener` drops a default handler that the
# given one subclasses, so naming `HttpsOnlyRedirectHandler` replaces
# `HTTPRedirectHandler` rather than adding a second one.
#
# Deliberately not passed to `install_opener`. That would rewrite the behaviour
# of `urlopen` for every library in the process, including code that has
# nothing to do with this pipeline.
OPENER = urllib.request.build_opener(HttpsOnlyRedirectHandler())


def build_request(url: str) -> urllib.request.Request:
    """Return the GET request that this project sends to `url`.

    The function is pure, so a test can read the headers without a socket.
    """
    scheme = urlsplit(url).scheme
    if scheme not in ALLOWED_SCHEMES:
        raise FetchError(f"{url} uses the scheme {scheme!r}. This pipeline fetches HTTPS only.")
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")


def get_bytes(url: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> bytes:
    """Send one GET and return the body.

    The body arrives as bytes, not as text and not as parsed JSON. The parser of
    each stage decides what its payload is, and a parser that reads bytes can be
    tested against a file on disk.
    """
    request = build_request(url)
    try:
        # `OPENER`, never `urlopen`: only this opener carries the redirect guard.
        with OPENER.open(request, timeout=timeout) as response:
            status = int(response.status)
            body: bytes = response.read()
    # `URLError`, `HTTPError`, and a timeout are all `OSError`. `HTTPException`
    # is not, and it covers a truncated or malformed response.
    except (OSError, http.client.HTTPException) as error:
        # Only an `HTTPError` carries a status and headers. Every other fault
        # here happened below HTTP, so it leaves both attributes at `None`, and
        # a retry policy reads that as "the server said nothing".
        if isinstance(error, urllib.error.HTTPError):
            raise FetchError(
                f"GET {url} failed: {error}",
                status=int(error.code),
                retry_after=error.headers.get("Retry-After"),
            ) from error
        raise FetchError(f"GET {url} failed: {error}") from error

    # The opener raises on a 4xx and a 5xx and follows a redirect, so this guard
    # catches the rest, such as a 204 with no body.
    if status != HTTPStatus.OK:
        raise FetchError(f"GET {url} returned status {status}, not 200.", status=status)
    return body


def decode_json(payload: bytes, *, source: str) -> Any:
    """Parse one JSON body. Name `source` so the error says which read failed.

    A bad payload raises `FetchError`. An upstream that answers with an error
    page or with a truncated body must stop the build loudly. It must not reach
    a parser as an empty result.
    """
    try:
        return json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FetchError(f"{source} did not return JSON: {error}") from error
