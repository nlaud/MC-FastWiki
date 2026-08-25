"""The mcmeta tag resolver, and the rules that keep a build reproducible.

CLAUDE.md gives one rule for Tier A: pin to a version tag, never to a bare
branch head. A branch head moves under the build, and it carries snapshot data
within hours of a snapshot release. Both faults end at the same place: the build
reads the wrong version of the game, and a wrong Minecraft number looks exactly
like a right one on the screen. So every rule of `pipeline.fetch.mcmeta` is
pinned here, one test for each.

No test in this module opens a socket. The fixture is a copy of the live answer
for `26.2-summary`, the resolver takes its transport as an argument, and the
autouse fixture below fails any test that tries to reach the network anyway.
"""

import inspect
import json
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import pytest
from pydantic import ValidationError

from pipeline.fetch import FetchError, get_bytes
from pipeline.fetch.mcmeta import (
    GITHUB_REF_URL,
    MCMETA_BRANCHES,
    MCMETA_RAW_URL,
    MCMETA_REPOSITORY,
    McmetaTag,
    mcmeta_tag_name,
    parse_git_ref,
    resolve_mcmeta_tag,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mcmeta_ref_26_2_summary.json"

# The tag and the commit that the fixture records.
FIXTURE_TAG = "26.2-summary"
FIXTURE_SHA = "711a353b47d84e6cb592a1b72f682e5f44759284"
FIXTURE_URL = GITHUB_REF_URL.format(repository=MCMETA_REPOSITORY, tag=FIXTURE_TAG)

# The source name that `parse_git_ref` gets in a test that calls it directly.
SOURCE = "test"


@pytest.fixture(autouse=True)
def refuse_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test of this module that opens a socket.

    This is the fixture of `tests/test_version_manifest.py`, and that module
    holds the long form of the reason. The short form: the failure is a
    `RuntimeError` because `get_bytes` maps every `OSError` to a `FetchError`,
    so an `OSError` here would be caught by the code under test. The test would
    then pass while it read the live GitHub API.
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise RuntimeError("this test tried to reach the network")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "gethostbyname", refuse)


class RecordingTransport:
    """A transport that answers one body and keeps every URL that it got."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        return self.body


def _fixture_transport() -> RecordingTransport:
    """Return a transport that answers with the recorded live answer."""
    return RecordingTransport(FIXTURE.read_bytes())


def _document() -> dict[str, Any]:
    """Return the fixture as a mutable document."""
    parsed: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return parsed


def _payload(document: object) -> bytes:
    """Return one document as the bytes that a transport would deliver."""
    return json.dumps(document).encode("utf-8")


def test_the_fixture_records_the_shape_of_the_live_answer() -> None:
    """A fixture that drifts from the endpoint makes every test below a fiction."""
    document = _document()
    assert document["ref"] == f"refs/tags/{FIXTURE_TAG}"
    assert document["object"]["type"] == "commit"
    assert document["object"]["sha"] == FIXTURE_SHA
    assert len(FIXTURE_SHA) == 40


def test_the_resolver_returns_the_tag_and_the_commit_sha() -> None:
    """The one call that the rest of Phase 1 makes."""
    transport = _fixture_transport()

    resolved = resolve_mcmeta_tag("26.2", "summary", transport=transport)

    assert resolved.tag == FIXTURE_TAG
    assert resolved.commit_sha == FIXTURE_SHA
    assert resolved.version_id == "26.2"
    assert resolved.branch == "summary"


def test_the_resolver_reads_the_single_reference_endpoint() -> None:
    """The exact-match endpoint, and no other request.

    The tag list endpoint needs 42 pages for this repository, against an
    unauthenticated limit of 60 requests per hour. The prefix endpoint returns
    the pre-release tags that share the prefix. This test says which one the
    module uses, and it says that one resolve costs one request.
    """
    transport = _fixture_transport()

    resolve_mcmeta_tag("26.2", "summary", transport=transport)

    assert transport.urls == [
        "https://api.github.com/repos/misode/mcmeta/git/ref/tags/26.2-summary"
    ]


@pytest.mark.parametrize(
    "version_id",
    [
        "26.3-snapshot-10",
        "1.20-pre1",
        "1.20-pre-1",
        "1.20-rc1",
        "26w01a",
        "1.14.2 Pre-Release 4",
        # Weekly snapshots whose tail is not letters alone. Mojang shipped all
        # three. `23w13a_or_b` is the one that matters: it carries no
        # `snapshot`, `pre`, or `rc` marker, so the weekly shape is the only
        # thing that can catch it, and a letters-only tail stops at the
        # underscore and reads the whole ID as a release.
        "20w14infinite",
        "22w13oneblockatatime",
        "23w13a_or_b",
    ],
)
def test_the_resolver_refuses_a_prerelease_before_it_fetches(version_id: str) -> None:
    """A snapshot must never drive a release build, and it must cost no request.

    `VersionManifest` already refuses a snapshot in `latest.release`. This guard
    is the second layer, and it covers the version ID that arrives from a
    hand-written argument instead of from the manifest.

    The URL list proves the order of the two steps. A guard that ran after the
    fetch would still raise, and it would still spend one of the 60 requests
    that the hour holds.
    """
    transport = _fixture_transport()

    with pytest.raises(FetchError, match="names a pre-release of Minecraft"):
        resolve_mcmeta_tag(version_id, "summary", transport=transport)

    assert transport.urls == []


@pytest.mark.parametrize("version_id", ["26.2", "26.10", "1.21.4", "1.20", "1.7.10"])
def test_the_guard_passes_a_real_release_id(version_id: str) -> None:
    """The marker match must not fire on an ordinary release ID.

    A guard that refuses a release stops every build, and it stops it with a
    message about snapshots. That reads like an upstream fault rather than like
    a wrong pattern here.
    """
    tag = f"{version_id}-summary"
    document = _document()
    document["ref"] = f"refs/tags/{tag}"
    transport = RecordingTransport(_payload(document))

    resolved = resolve_mcmeta_tag(version_id, "summary", transport=transport)

    assert resolved.tag == tag
    assert transport.urls == [GITHUB_REF_URL.format(repository=MCMETA_REPOSITORY, tag=tag)]


def test_allow_prerelease_reads_a_snapshot_tag() -> None:
    """A developer can pin a snapshot on purpose. The default does not."""
    document = _document()
    document["ref"] = "refs/tags/26.3-snapshot-10-summary"
    transport = RecordingTransport(_payload(document))

    resolved = resolve_mcmeta_tag(
        "26.3-snapshot-10", "summary", allow_prerelease=True, transport=transport
    )

    assert resolved.tag == "26.3-snapshot-10-summary"
    assert resolved.commit_sha == FIXTURE_SHA


def test_the_parser_rejects_a_reference_that_is_not_the_requested_tag() -> None:
    """A near match must fail the build, not pin a tag that nobody asked for.

    The endpoint matches an exact name today. `tags/26.2-snapshot` answers 404,
    although 45 tags start with that text. This check keeps that behavior a
    checked fact rather than an assumption about a service that this project
    does not own.
    """
    document = _document()
    document["ref"] = "refs/tags/26.2-summary-json"

    with pytest.raises(FetchError, match="A near match must not pin a tag"):
        parse_git_ref(_payload(document), expected_tag=FIXTURE_TAG, source=SOURCE)


def test_the_parser_rejects_an_annotated_tag() -> None:
    """An annotated tag points at a tag object, and its SHA is not a commit SHA.

    A raw URL built from that SHA answers 404, one stage later and one URL away
    from the answer that produced it. mcmeta writes lightweight tags today, so
    the module refuses the other kind instead of carrying the second read that
    an annotated tag would need.
    """
    document = _document()
    document["object"]["type"] = "tag"

    with pytest.raises(FetchError, match="not 'commit'"):
        parse_git_ref(_payload(document), expected_tag=FIXTURE_TAG, source=SOURCE)


@pytest.mark.parametrize(
    "sha", ["", "711a353", FIXTURE_SHA.upper(), "x" * 40, f"{FIXTURE_SHA} "]
)
def test_the_parser_rejects_a_sha_that_is_not_a_full_object_name(sha: str) -> None:
    """The SHA goes straight into a raw URL. A partial name breaks that URL."""
    document = _document()
    document["object"]["sha"] = sha

    with pytest.raises(FetchError, match="not a full 40-character Git object name"):
        parse_git_ref(_payload(document), expected_tag=FIXTURE_TAG, source=SOURCE)


def test_the_parser_rejects_a_body_that_is_not_json() -> None:
    """GitHub answers an error page as HTML. It must not read as empty."""
    with pytest.raises(FetchError, match="did not return JSON"):
        parse_git_ref(b"<html>502 Bad Gateway</html>", expected_tag=FIXTURE_TAG, source=SOURCE)


def test_the_parser_rejects_a_json_document_that_is_not_an_object() -> None:
    """The prefix endpoint answers a list. This one answers an object.

    A caller that pointed the parser at the prefix endpoint by mistake would
    read row 0 of 153 rows, and row 0 can be a pre-release tag.
    """
    with pytest.raises(FetchError, match="returned list at the top level"):
        parse_git_ref(_payload([]), expected_tag=FIXTURE_TAG, source=SOURCE)


def test_the_parser_rejects_an_answer_with_no_object() -> None:
    """A shape change upstream must stop the build, not produce a partial model."""
    with pytest.raises(FetchError, match="not a usable Git reference"):
        parse_git_ref(
            _payload({"ref": f"refs/tags/{FIXTURE_TAG}"}),
            expected_tag=FIXTURE_TAG,
            source=SOURCE,
        )


def test_the_parser_names_the_source_in_its_error() -> None:
    """A build reads several upstreams. An error that names none of them is noise."""
    with pytest.raises(FetchError, match=FIXTURE_URL.replace(".", r"\.")):
        parse_git_ref(b"not json", expected_tag=FIXTURE_TAG, source=FIXTURE_URL)


def test_the_tag_name_rejects_an_unknown_branch() -> None:
    """A typo must fail with the accepted list, not with a 404 from GitHub."""
    with pytest.raises(FetchError, match="is not an mcmeta branch"):
        mcmeta_tag_name("26.2", "summaries")


def test_the_branch_set_holds_the_branches_that_claude_md_records() -> None:
    """One name for one branch. A stage cannot invent a seventh."""
    assert sorted(MCMETA_BRANCHES) == ["assets", "atlas", "data", "diff", "registries", "summary"]


@pytest.mark.parametrize("version_id", ["26.2/../other", "26.2?ref=main", "26.2 summary", ""])
def test_the_tag_name_rejects_a_version_id_that_a_url_path_reads_as_structure(
    version_id: str,
) -> None:
    """The version ID goes into a URL path, so its characters have to be plain.

    The manifest never sends one of these. A curated file and a hand-typed
    argument both can, and a build that fetched a different path than the one
    it named would be very hard to read.
    """
    with pytest.raises(FetchError, match="does not put in a URL path"):
        mcmeta_tag_name(version_id, "summary")


def _pinned_tag() -> McmetaTag:
    """Return the resolved tag that the fixture records."""
    return McmetaTag(version_id="26.2", branch="summary", tag=FIXTURE_TAG, commit_sha=FIXTURE_SHA)


def test_raw_url_pins_the_commit_sha() -> None:
    """Later stages read the commit, not the tag. A tag can move, a commit cannot."""
    assert _pinned_tag().raw_url("item_components/data.json") == (
        f"https://raw.githubusercontent.com/misode/mcmeta/{FIXTURE_SHA}/item_components/data.json"
    )


@pytest.mark.parametrize(
    "path",
    [
        "data.json",
        "item_components/data.json",
        "blocks/data.json",
        "recipe/crafting_table.json",
        "loot_table/blocks/oak_log.json",
        "tags/item/planks.json",
        "worldgen/biome/jungle.json",
        # A resource path may hold a dot, an underscore, and a hyphen. Only a
        # whole segment of dots is refused, never a dot inside a name.
        "advancement/story/root.json",
        "summary/item_components/data.v2.json",
        "registries/entity_type/data.json",
        "diff/26.1-26.2.json",
    ],
)
def test_raw_url_accepts_the_paths_that_the_pipeline_reads(path: str) -> None:
    """The guard must not refuse a path that Phase 1 of TODO.md actually fetches.

    A guard that stops a real read stops the whole build, and it stops it with a
    message about URL structure, which reads like a bug in the caller rather
    than like a wrong pattern here.
    """
    assert _pinned_tag().raw_url(path).endswith(f"/{FIXTURE_SHA}/{path}")


def test_raw_url_would_read_the_branch_head_through_a_dot_segment() -> None:
    """The concrete failure that the path guard closes, spelled out.

    This test asserts no behaviour of the module. It pins the fact that makes
    the guard necessary, so a later reader cannot dismiss the check as defensive
    noise: a `..` segment after the SHA resolves to the URL of the *branch
    head*, which moves under the build and carries snapshot data within hours of
    a snapshot release. `urljoin` here stands for every RFC 3986 reader between
    this module and the file, including the CDN in front of
    raw.githubusercontent.com.
    """
    pinned = f"https://raw.githubusercontent.com/{MCMETA_REPOSITORY}/{FIXTURE_SHA}/"

    resolved = urljoin(pinned, "../summary/item_components/data.json")

    assert resolved == (
        "https://raw.githubusercontent.com/misode/mcmeta/summary/item_components/data.json"
    )
    assert FIXTURE_SHA not in resolved


@pytest.mark.parametrize(
    "path",
    [
        # Walks back over the SHA and lands on the branch head.
        "../summary/item_components/data.json",
        "item_components/../../main/data.json",
        "..",
        # A no-op segment today, and one `..` away from the line above.
        "./data.json",
        "item_components/./data.json",
        # An empty segment: a leading, trailing, or doubled slash. `//` makes
        # the reader of a relative join treat what follows as a host.
        "/item_components/data.json",
        "item_components/",
        "item_components//data.json",
        "",
        # Ends the path early, so the read is not the file that was named.
        "data.json?ref=main",
        "data.json#main",
        "data%2f..%2fmain",
        # Not a path at all. A space or a control character reaches the socket
        # as a broken request line rather than as a fetch failure.
        "item components.json",
        "data.json\nHost: example.invalid",
        "data.json\r\n",
    ],
)
def test_raw_url_rejects_a_path_that_could_leave_the_pinned_commit(path: str) -> None:
    """The pin lives in one URL segment, and the path argument follows it.

    `mcmeta_tag_name` checks its version ID for exactly this class of fault, and
    `raw_url` is the function that a later stage actually calls, with a string
    built from upstream data. Both need the same rule.
    """
    with pytest.raises(FetchError, match="does not name one file inside a pinned commit"):
        _pinned_tag().raw_url(path)


@pytest.mark.parametrize("commit_sha", ["main", "", FIXTURE_SHA[:7], FIXTURE_SHA.upper()])
def test_the_tag_model_rejects_a_commit_sha_that_is_not_a_full_object_name(
    commit_sha: str,
) -> None:
    """A `McmetaTag` that was not built by `resolve_mcmeta_tag` gets the same rule.

    The next stage of Phase 1 caches by content hash, so this model gets written
    to disk and read back. A `commit_sha` of `main` in a rebuilt model is not a
    404 one stage later. It is a successful read of the branch head, which is
    the failure this module exists to prevent, and nothing downstream can tell
    the two apart.
    """
    with pytest.raises(ValidationError, match="not a full 40-character Git object name"):
        McmetaTag(version_id="26.2", branch="summary", tag=FIXTURE_TAG, commit_sha=commit_sha)


def test_the_url_templates_name_the_repository_that_claude_md_records() -> None:
    """Tier A comes from `misode/mcmeta`, and from no fork of it."""
    assert MCMETA_REPOSITORY == "misode/mcmeta"
    assert GITHUB_REF_URL.startswith("https://api.github.com/")
    assert MCMETA_RAW_URL.startswith("https://raw.githubusercontent.com/")


def test_the_resolver_defaults_to_the_guarded_transport() -> None:
    """Every rule of `pipeline.fetch` reaches production through this default.

    The resolver takes `transport` so that no test opens a socket, and every
    test above passes one. That leaves the default itself untested, and the
    default is what a build uses: swap it for a bare `urlopen` wrapper and the
    HTTPS rule, the User-Agent, and the status check all disappear from the real
    path while this module stays green.
    """
    assert inspect.signature(resolve_mcmeta_tag).parameters["transport"].default is get_bytes
