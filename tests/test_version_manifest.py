"""The version manifest reader, and the rule that keeps a snapshot out of a build.

`python -m pipeline check` asks Mojang for the ID of the current release. One
wrong answer there sends every later stage at the wrong version of the game, and
wrong Minecraft numbers look exactly like right ones on the screen. So the rules
that the parser holds are pinned here, one test for each.

No test in this module opens a socket. The fixture is a trimmed copy of the live
manifest, the fetcher takes its transport as an argument, and the autouse
fixture below fails any test that tries to reach the network anyway.
"""

import http.client
import inspect
import io
import json
import socket
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.response import addinfourl

import pytest

from pipeline.fetch import (
    DEFAULT_TIMEOUT_SECONDS,
    OPENER,
    USER_AGENT,
    FetchError,
    HttpsOnlyRedirectHandler,
    build_request,
    decode_json,
    get_bytes,
)
from pipeline.fetch.cache import ContentCache
from pipeline.fetch.version_manifest import (
    VERSION_MANIFEST_URL,
    fetch_latest_release_id,
    fetch_version_manifest,
    parse_version_manifest,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "version_manifest_v2.json"

# The four values that the `type` field of an entry takes.
VERSION_TYPES = {"release", "snapshot", "old_beta", "old_alpha"}


@pytest.fixture(autouse=True)
def refuse_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test of this module that opens a socket.

    A test that reaches Mojang is slow, and it goes red when the network is down
    or when Mojang publishes a new release. The failure is a `RuntimeError` on
    purpose: `get_bytes` turns every `OSError` into a `FetchError`, so an
    `OSError` here would be caught by the code under test, and the test would
    then pass while it read the live service.

    Name resolution is refused along with the connection. `socket.socket` and
    `socket.create_connection` are the two doors `http.client` uses, and
    stopping there leaves the resolver open: `urllib.request.FTPHandler.ftp_open`
    calls `socket.gethostbyname` before it opens anything, so a test that
    followed a redirect to an `ftp:` URL sent a real DNS query and then failed
    with `getaddrinfo failed`, which reads like a broken network rather than
    like a test that escaped its harness. `getaddrinfo` goes with it, since
    every other resolver path in the standard library goes through one or the
    other.
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise RuntimeError("this test tried to reach the network")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "gethostbyname", refuse)


@pytest.mark.parametrize("url", ["https://example.invalid/x", "ftp://example.invalid/x"])
def test_the_harness_refuses_the_network(url: str) -> None:
    """Pin the fixture above, one door per scheme.

    A harness that only looks airtight is worse than none: the tests it guards
    go green while they read the live service, and they go red later for a
    reason that has nothing to do with the code. `https:` reaches the network
    through `socket.create_connection` and `ftp:` reaches it through
    `socket.gethostbyname`, so both have to raise, and both have to raise the
    `RuntimeError` that no `except OSError` in `urllib` or in `get_bytes` will
    swallow.

    `.invalid` is reserved by RFC 2606 and resolves nowhere, so a regression
    here costs one failed lookup rather than a request to a real host.
    """
    with pytest.raises(RuntimeError, match="tried to reach the network"):
        OPENER.open(url, timeout=1)


def _document() -> dict[str, Any]:
    """Return the fixture as a mutable document."""
    parsed: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return parsed


def _payload(document: object) -> bytes:
    """Return one document as the bytes that a transport would deliver."""
    return json.dumps(document).encode("utf-8")


class ScriptedResponse(addinfourl):
    """`addinfourl` with the `msg` that a real response carries.

    `HTTPErrorProcessor` reads `code`, `msg`, and `info()` off a response before
    it routes a 3xx to the redirect handler. `addinfourl` sets the first and the
    third and leaves `msg` unset, so a bare one raises `AttributeError` inside
    the opener rather than exercising the guard.
    """

    def __init__(self, body: bytes, headers: http.client.HTTPMessage, url: str, code: int) -> None:
        super().__init__(io.BytesIO(body), headers, url, code)
        self.msg = HTTPStatus(code).phrase


@dataclass(frozen=True)
class Hop:
    """One scripted answer from an upstream: a status, a `Location`, a body."""

    status: int
    location: str | None = None
    body: bytes = b""


@dataclass
class ScriptedHost:
    """A scripted upstream, patched in below the opener rather than over it.

    The earlier shape of these tests replaced `urllib.request.urlopen` outright.
    That hid the part of `get_bytes` that has to be right: which opener it uses.
    `urlopen` builds its own opener from the default handlers, and the default
    redirect handler follows a `Location` into cleartext, so a `get_bytes` that
    called `urlopen` would pass every test written against a patched `urlopen`
    and still downgrade the transport in production.

    So the patch goes at the handler instead. `HTTPSHandler.https_open` and
    `HTTPHandler.http_open` are the last step before a socket, which leaves the
    whole opener chain of the module under test in the path: the redirect guard,
    the error processor, and the timeout that `OpenerDirector.open` records on
    the request.

    `http_open` is scripted as well as `https_open` on purpose. Without it, a
    regression in the guard would fail as a refused socket, which reads like an
    unrelated fault. With it, the cleartext hop is answerable, so a regression
    fails as what it is: a body fetched over `http:`.
    """

    hops: list[Hop]
    requests: list[urllib.request.Request] = field(default_factory=list)

    @property
    def urls(self) -> list[str]:
        """The URL of every request that reached a handler, in order."""
        return [request.full_url for request in self.requests]

    def answer(self, request: urllib.request.Request) -> addinfourl:
        self.requests.append(request)
        if not self.hops:
            raise AssertionError(f"{request.full_url} was fetched, and the script has no answer")
        hop = self.hops.pop(0)
        headers = http.client.HTTPMessage()
        if hop.location is not None:
            headers["Location"] = hop.location
        return ScriptedResponse(hop.body, headers, request.full_url, hop.status)


@pytest.fixture
def scripted_host(monkeypatch: pytest.MonkeyPatch) -> Callable[..., ScriptedHost]:
    """Return a factory that scripts the answers of every upstream in this test."""

    def script(*hops: Hop) -> ScriptedHost:
        host = ScriptedHost(list(hops))

        def handler_open(_handler: object, request: urllib.request.Request) -> addinfourl:
            return host.answer(request)

        monkeypatch.setattr(urllib.request.HTTPSHandler, "https_open", handler_open)
        monkeypatch.setattr(urllib.request.HTTPHandler, "http_open", handler_open)
        return host

    return script


def test_the_fixture_covers_every_version_type() -> None:
    """A fixture of releases alone would make the snapshot rule untestable."""
    document = _document()
    assert {entry["type"] for entry in document["versions"]} == VERSION_TYPES
    assert document["latest"]["release"] == "26.2"
    assert document["latest"]["snapshot"] == "26.3-snapshot-10"


def test_the_parser_returns_the_current_release_id() -> None:
    manifest = parse_version_manifest(FIXTURE.read_bytes())
    assert manifest.latest_release_id == "26.2"
    assert len(manifest.versions) == 8


def test_the_parser_rejects_a_release_that_no_entry_names() -> None:
    """`latest.release` must point at an entry, or its type cannot be checked.

    A manifest that names a release it does not list is broken upstream. Reading
    the string anyway would skip the one guard this module has.
    """
    document = _document()
    document["latest"]["release"] = "26.9"
    with pytest.raises(FetchError, match="no entry of the versions list has that id"):
        parse_version_manifest(_payload(document))


def test_the_parser_rejects_a_snapshot_named_as_the_release() -> None:
    """The Java Edition rule: a snapshot must never drive a build.

    This is the failure that the whole module exists to stop. The manifest below
    is well formed, and `latest.release` reads like an ordinary version string.
    Only the type of the entry it names says that the build would run against a
    snapshot.
    """
    document = _document()
    document["latest"]["release"] = "26.3-snapshot-10"
    with pytest.raises(FetchError, match="the type 'snapshot', not 'release'"):
        parse_version_manifest(_payload(document))


def test_the_parser_rejects_a_body_that_is_not_json() -> None:
    """An error page from a proxy is HTML, not JSON. It must not read as empty."""
    with pytest.raises(FetchError, match="did not return JSON"):
        parse_version_manifest(b"<html>503 Service Unavailable</html>")


def test_the_parser_rejects_a_json_document_that_is_not_an_object() -> None:
    with pytest.raises(FetchError, match="returned list at the top level"):
        parse_version_manifest(_payload([]))


def test_the_parser_rejects_a_manifest_with_no_versions_list() -> None:
    """A shape change upstream must stop the build, not produce a partial model."""
    with pytest.raises(FetchError, match="not a usable version manifest"):
        parse_version_manifest(_payload({"latest": {"release": "26.2", "snapshot": "26.3"}}))


def test_the_parser_names_the_source_in_its_error() -> None:
    """A build reads several upstreams. An error that names none of them is noise."""
    with pytest.raises(FetchError, match=VERSION_MANIFEST_URL.replace(".", r"\.")):
        parse_version_manifest(b"not json")


def test_the_request_carries_the_project_user_agent() -> None:
    """CLAUDE.md asks the pipeline to be a good citizen with the services it reads."""
    request = build_request(VERSION_MANIFEST_URL)
    assert request.full_url == VERSION_MANIFEST_URL
    assert request.get_method() == "GET"
    assert request.get_header("User-agent") == USER_AGENT
    assert "MC-FastWiki" in USER_AGENT


def test_the_request_rejects_a_scheme_that_is_not_https() -> None:
    """`urlopen` also serves `file:`, which would read a local path as a fetch."""
    with pytest.raises(FetchError, match="HTTPS only"):
        build_request("file:///etc/passwd")


def test_get_bytes_returns_the_body(scripted_host: Callable[..., ScriptedHost]) -> None:
    host = scripted_host(Hop(200, body=b'{"latest": {}}'))

    assert get_bytes(VERSION_MANIFEST_URL) == b'{"latest": {}}'
    assert host.urls == [VERSION_MANIFEST_URL]
    assert host.requests[0].get_header("User-agent") == USER_AGENT
    assert host.requests[0].timeout == DEFAULT_TIMEOUT_SECONDS


def test_get_bytes_maps_a_transport_fault_to_a_fetch_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One error class for every fault, so a caller stops the build on one name."""

    def handler_open(_handler: object, request: urllib.request.Request) -> addinfourl:
        raise urllib.error.URLError("name or service not known")

    monkeypatch.setattr(urllib.request.HTTPSHandler, "https_open", handler_open)

    with pytest.raises(FetchError, match="failed"):
        get_bytes(VERSION_MANIFEST_URL)


def test_get_bytes_maps_a_protocol_fault_to_a_fetch_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A truncated response raises `HTTPException`, which is not an `OSError`.

    `get_bytes` names both families in its `except` clause. Only this test says
    the second name is load-bearing: drop it, and a body that stops halfway
    leaves the pipeline through a class no caller catches.
    """

    def handler_open(_handler: object, request: urllib.request.Request) -> addinfourl:
        raise http.client.IncompleteRead(b"{", 4096)

    monkeypatch.setattr(urllib.request.HTTPSHandler, "https_open", handler_open)

    with pytest.raises(FetchError, match="failed"):
        get_bytes(VERSION_MANIFEST_URL)


def test_get_bytes_rejects_a_status_that_is_not_200(
    scripted_host: Callable[..., ScriptedHost],
) -> None:
    """A 204 carries no body. Parsing it would report a shape fault, not the truth."""
    scripted_host(Hop(204))

    with pytest.raises(FetchError, match="status 204"):
        get_bytes(VERSION_MANIFEST_URL)


def test_the_opener_replaces_the_permissive_redirect_handler() -> None:
    """The opener of this module must carry exactly one redirect handler: the guard.

    `build_opener` drops a default handler that the given one subclasses, so a
    correct build leaves `HttpsOnlyRedirectHandler` alone in the chain. Two
    handlers, or a bare `HTTPRedirectHandler`, means the permissive one is still
    in the path and the guard below is decoration.
    """
    # `handlers` is real and undocumented, so typeshed does not declare it.
    # `warn_unused_ignores` is on, so this line reports itself if that changes.
    installed: list[urllib.request.BaseHandler] = OPENER.handlers  # type: ignore[attr-defined]
    redirect_handlers = [
        handler for handler in installed if isinstance(handler, urllib.request.HTTPRedirectHandler)
    ]
    assert len(redirect_handlers) == 1
    assert isinstance(redirect_handlers[0], HttpsOnlyRedirectHandler)


@pytest.mark.parametrize("target", ["http://evil.example/manifest.json", "ftp://evil.example/m"])
def test_get_bytes_refuses_a_redirect_that_leaves_https(
    scripted_host: Callable[..., ScriptedHost], target: str
) -> None:
    """A `Location` header must not move the read off HTTPS.

    `build_request` checks the URL the caller passes and nothing else, so the
    scheme rule of this project holds for the first hop alone unless the opener
    enforces it too. The scheme filter that `urllib` applies while following a
    redirect is its own: `HTTPRedirectHandler.http_error_302` refuses `file:`
    but permits `http:` and `ftp:`.

    The failure that leaves is silent and total. Mojang answers
    `301 Location: http://...`, `urllib` repeats the GET in cleartext, and
    `get_bytes` returns whatever comes back with no error and no record that the
    transport changed. Anyone on the path of that hop writes the manifest, and a
    manifest is easy to write consistently: name a snapshot in `latest.release`
    and mark the same entry `"type": "release"`, and the guard in
    `version_manifest.py` agrees. Every later stage then reads the wrong version
    of the game, where wrong numbers look exactly like right ones on the screen.

    The second hop is scripted so that the `http:` case shows the damage rather
    than hiding behind a refused socket: revert the guard and this test does not
    fail on a connection, it fails because `get_bytes` returned
    `b"ATTACKER BODY"`.
    """
    host = scripted_host(Hop(301, location=target), Hop(200, body=b"ATTACKER BODY"))

    with pytest.raises(FetchError, match="HTTPS only"):
        get_bytes(VERSION_MANIFEST_URL)

    # The cleartext hop was never sent, not merely rejected after the fact.
    assert host.urls == [VERSION_MANIFEST_URL]


def test_get_bytes_still_follows_a_redirect_that_stays_on_https(
    scripted_host: Callable[..., ScriptedHost],
) -> None:
    """The guard must refuse a scheme change, not redirects as such.

    Mojang and the wiki both answer some paths with a 3xx. A guard that refused
    every redirect would break the fetch it is meant to protect.
    """
    host = scripted_host(
        Hop(302, location="https://piston-meta.mojang.com/manifest.json"),
        Hop(200, body=b'{"latest": {}}'),
    )

    assert get_bytes(VERSION_MANIFEST_URL) == b'{"latest": {}}'
    assert host.urls == [VERSION_MANIFEST_URL, "https://piston-meta.mojang.com/manifest.json"]
    assert host.requests[1].get_header("User-agent") == USER_AGENT


def test_decode_json_returns_the_document() -> None:
    assert decode_json(b'{"release": "26.2"}', source="test") == {"release": "26.2"}


def test_decode_json_rejects_a_body_that_is_not_utf8() -> None:
    """A body cut inside a multi-byte character raises `UnicodeDecodeError`.

    That class is not a `JSONDecodeError`, so `decode_json` has to name it
    separately, and this is the only test that says so. A connection dropped
    mid-response is the ordinary way to reach it.
    """
    with pytest.raises(FetchError, match="did not return JSON"):
        decode_json('{"name": "café'.encode()[:-1], source="test")


def test_the_fetcher_reads_the_manifest_url_through_the_transport() -> None:
    """The URL is the one that CLAUDE.md records, and nothing else is fetched."""
    asked: list[str] = []

    def transport(url: str) -> bytes:
        asked.append(url)
        return FIXTURE.read_bytes()

    manifest = fetch_version_manifest(transport=transport)

    assert asked == [VERSION_MANIFEST_URL]
    assert manifest.latest_release_id == "26.2"


def test_fetch_latest_release_id_returns_the_id() -> None:
    """The one function that `python -m pipeline check` will call."""

    def transport(url: str) -> bytes:
        return FIXTURE.read_bytes()

    assert fetch_latest_release_id(transport=transport) == "26.2"


@pytest.mark.parametrize("function", [fetch_version_manifest, fetch_latest_release_id])
def test_the_fetchers_default_to_the_guarded_transport(function: Callable[..., object]) -> None:
    """Every rule of `pipeline.fetch` reaches production through this default.

    Both fetchers take `transport` so that no test opens a socket, and every
    test above passes one. That leaves the default itself untested, and the
    default is what a build uses: swap it for a bare `urlopen` wrapper and the
    HTTPS rule, the User-Agent, and the status check all disappear from the real
    path while this module stays green.
    """
    assert inspect.signature(function).parameters["transport"].default is get_bytes


def test_the_fetcher_reads_a_second_time_from_the_cache(tmp_path: Path) -> None:
    """A cache plus a revision serves the second read without a request.

    This is the manifest's other question. A build that already knows it targets
    26.2 reads this document for `versions` alone -- the release history that
    `pipeline.normalize.curated.load_curated` dates a curated file against --
    and that history does not change for a version already published. The
    revision keys the entry, so `python -m pipeline build --offline
    --minecraft-version 26.2` can read it back with no network.
    """
    cache = ContentCache(tmp_path)
    asked: list[str] = []

    def transport(url: str) -> bytes:
        asked.append(url)
        return FIXTURE.read_bytes()

    first = fetch_version_manifest(cache=cache, revision="26.2", transport=transport)
    second = fetch_version_manifest(cache=cache, revision="26.2", transport=transport)

    assert asked == [VERSION_MANIFEST_URL]
    assert [entry.id for entry in first.versions] == [entry.id for entry in second.versions]


def test_a_second_revision_does_not_read_the_first_revision_s_answer(tmp_path: Path) -> None:
    """The revision is part of the key, so it genuinely separates two builds.

    Without this the cache would hold one manifest forever under one name, and
    the revision argument would be decoration rather than the thing that makes
    storing this document safe at all.
    """
    cache = ContentCache(tmp_path)
    asked: list[str] = []

    def transport(url: str) -> bytes:
        asked.append(url)
        return FIXTURE.read_bytes()

    fetch_version_manifest(cache=cache, revision="26.2", transport=transport)
    fetch_version_manifest(cache=cache, revision="26.1", transport=transport)

    assert asked == [VERSION_MANIFEST_URL, VERSION_MANIFEST_URL]


def test_the_fetcher_reads_the_network_every_time_with_no_cache() -> None:
    """The default is unchanged, and that is the whole point of the default.

    "What is the current release" is the question this module exists to answer,
    and a stored answer to it is a stale answer. Every caller that asks it
    passes no cache, so this behaviour is the one that must not drift.
    """
    asked: list[str] = []

    def transport(url: str) -> bytes:
        asked.append(url)
        return FIXTURE.read_bytes()

    fetch_version_manifest(transport=transport)
    fetch_version_manifest(transport=transport)

    assert asked == [VERSION_MANIFEST_URL, VERSION_MANIFEST_URL]


def test_a_cache_without_a_revision_is_refused(tmp_path: Path) -> None:
    """The combination that would freeze "what is current" forever is unreachable.

    Keying this URL alone would make the first answer this project ever read the
    last one it ever read. Refusing the pair keeps that trap out of reach rather
    than merely documented, which is the same standard `ContentCache.object_
    path` applies to a digest it did not build itself.
    """
    with pytest.raises(FetchError, match="cache and no revision"):
        fetch_version_manifest(cache=ContentCache(tmp_path))


def test_a_revision_without_a_cache_is_refused() -> None:
    """The mirror of the rule above: a revision names an entry in a store.

    Accepting it silently would read the network while the caller believed it
    had asked for a cached read, which is the failure mode that looks like it
    worked.
    """
    with pytest.raises(FetchError, match="revision and no cache"):
        fetch_version_manifest(revision="26.2", transport=lambda url: FIXTURE.read_bytes())
