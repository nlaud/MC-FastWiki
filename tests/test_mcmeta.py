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
import io
import json
import re
import socket
import tarfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import pytest
from pydantic import ValidationError

import pipeline.fetch.mcmeta as mcmeta_module
from pipeline.fetch import FetchError, get_bytes
from pipeline.fetch.cache import ContentCache
from pipeline.fetch.mcmeta import (
    ARCHIVE_NAMESPACE_ROOT,
    DATA_GROUPS,
    GITHUB_REF_URL,
    MCMETA_ARCHIVE_URL,
    MCMETA_BRANCHES,
    MCMETA_RAW_URL,
    MCMETA_REPOSITORY,
    SUMMARY_PAYLOADS,
    McmetaTag,
    fetch_data_files,
    fetch_summary_payload,
    mcmeta_tag_name,
    parse_git_ref,
    read_data_archive,
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


# --------------------------------------------------------------------------
# The payload readers of Phase 1: the summary files, and the data archive.
# --------------------------------------------------------------------------

# The root directory that GitHub puts in front of every member of a commit
# archive from `codeload.github.com/<repository>/tar.gz/<sha>`.
ARCHIVE_ROOT = f"mcmeta-{FIXTURE_SHA}"

# A small stand-in for the live `data` branch. Four members are wanted, one for
# each group of `DATA_GROUPS`. Three are not: `structure` is a group this
# project does not read, `datapacks` is the experimental trade rebalance pack
# rather than the vanilla game, and `pack.mcmeta` sits outside the namespace.
ARCHIVE_MEMBERS: Mapping[str, bytes] = {
    "data/minecraft/advancement/story/root.json": b'{"parent": null}',
    "data/minecraft/loot_table/entities/creeper.json": b'{"pools": []}',
    "data/minecraft/recipe/oak_stairs.json": b'{"type": "minecraft:crafting_shaped"}',
    "data/minecraft/tags/item/planks.json": b'{"values": ["minecraft:oak_planks"]}',
    "data/minecraft/structure/village/plains/houses/small.nbt": b"not read",
    "data/minecraft/datapacks/trade_rebalance/data/minecraft/tags/item/x.json": b"not read",
    "pack.mcmeta": b'{"pack": {}}',
}

WANTED_MEMBERS = {
    "advancement/story/root.json": b'{"parent": null}',
    "loot_table/entities/creeper.json": b'{"pools": []}',
    "recipe/oak_stairs.json": b'{"type": "minecraft:crafting_shaped"}',
    "tags/item/planks.json": b'{"values": ["minecraft:oak_planks"]}',
}

ARCHIVE_SOURCE = "test-archive"


def _file_member(name: str, body: bytes) -> tuple[tarfile.TarInfo, bytes | None]:
    info = tarfile.TarInfo(name)
    info.type = tarfile.REGTYPE
    info.size = len(body)
    return info, body


def _directory_member(name: str) -> tuple[tarfile.TarInfo, bytes | None]:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    return info, None


def _symlink_member(name: str, target: str) -> tuple[tarfile.TarInfo, bytes | None]:
    info = tarfile.TarInfo(name)
    info.type = tarfile.SYMTYPE
    info.linkname = target
    return info, None


def _tar_gz(members: list[tuple[tarfile.TarInfo, bytes | None]]) -> bytes:
    """Return one gzip archive of the given members, built in memory."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for info, body in members:
            archive.addfile(info, io.BytesIO(body) if body is not None else None)
    return buffer.getvalue()


def _data_archive(
    members: Mapping[str, bytes] = ARCHIVE_MEMBERS, *, root: str = ARCHIVE_ROOT
) -> bytes:
    """Return an archive shaped like the one that GitHub serves for a commit."""
    entries = [_directory_member(root)]
    entries += [_file_member(f"{root}/{name}", body) for name, body in members.items()]
    return _tar_gz(entries)


def _summary_tag() -> McmetaTag:
    return McmetaTag(version_id="26.2", branch="summary", tag=FIXTURE_TAG, commit_sha=FIXTURE_SHA)


def _data_tag() -> McmetaTag:
    return McmetaTag(version_id="26.2", branch="data", tag="26.2-data", commit_sha=FIXTURE_SHA)


def test_the_summary_payloads_cover_the_groups_that_phase_one_reads() -> None:
    """Three of the seven payload groups of Phase 1 live on the `summary` branch.

    `registries` is here rather than on the `registries` branch on purpose. Both
    hold the same lists. The branch spreads them over 182 files, and this is one
    file that holds all 182.
    """
    assert set(SUMMARY_PAYLOADS) == {"blocks", "item_components", "registries"}
    assert SUMMARY_PAYLOADS["item_components"] == "item_components/data.json"


def test_every_summary_path_passes_the_pinned_path_rule() -> None:
    """A payload path must be one that `raw_url` accepts.

    `raw_url` refuses a path that could leave the pinned commit. A constant that
    it refused would fail at build time rather than here, one stage away from
    the table that holds it.
    """
    tag = _summary_tag()
    for path in SUMMARY_PAYLOADS.values():
        assert tag.raw_url(path).endswith(path)


def test_the_data_groups_cover_the_rest_of_phase_one() -> None:
    """The other four payload groups of Phase 1 live on the `data` branch."""
    assert DATA_GROUPS == ("advancement", "loot_table", "recipe", "tags")


def test_the_summary_fetcher_reads_the_pinned_raw_url(tmp_path: Path) -> None:
    """The read must name the commit sha, never the branch head."""
    transport = RecordingTransport(b'{"blocks": {}}')
    tag = _summary_tag()

    body = fetch_summary_payload(tag, "blocks", cache=ContentCache(tmp_path), transport=transport)

    assert body == b'{"blocks": {}}'
    assert transport.urls == [
        f"https://raw.githubusercontent.com/{MCMETA_REPOSITORY}/{FIXTURE_SHA}/blocks/data.json"
    ]


def test_the_summary_fetcher_reads_the_network_once_for_one_version(tmp_path: Path) -> None:
    """The cache is what keeps a rebuild off the network.

    CLAUDE.md asks this pipeline to be a good citizen with the services it
    reads. A second build of one Minecraft version must send no second request.
    """
    transport = RecordingTransport(b'{"blocks": {}}')
    tag = _summary_tag()

    fetch_summary_payload(tag, "blocks", cache=ContentCache(tmp_path), transport=transport)
    again = fetch_summary_payload(tag, "blocks", cache=ContentCache(tmp_path), transport=transport)

    assert again == b'{"blocks": {}}'
    assert len(transport.urls) == 1


def test_the_summary_fetcher_refuses_a_tag_of_another_branch() -> None:
    """A `data` tag names a commit with no `blocks/data.json` in it.

    Without this guard the read would answer 404 one stage later, and the error
    would name a URL rather than the mistake that built it.
    """
    with pytest.raises(FetchError, match="branch 'summary'"):
        fetch_summary_payload(_data_tag(), "blocks", transport=RecordingTransport(b"{}"))


def test_the_summary_fetcher_refuses_an_unknown_payload_name() -> None:
    """A typo must fail with the accepted list, not with a 404."""
    with pytest.raises(FetchError, match="not a summary payload"):
        fetch_summary_payload(_summary_tag(), "block", transport=RecordingTransport(b"{}"))


def test_the_data_fetcher_reads_one_archive_of_the_pinned_commit(tmp_path: Path) -> None:
    """5,422 files must cost one request, and that request must name the sha."""
    transport = RecordingTransport(_data_archive())

    files = fetch_data_files(_data_tag(), cache=ContentCache(tmp_path), transport=transport)

    assert files == WANTED_MEMBERS
    assert transport.urls == [
        f"https://codeload.github.com/{MCMETA_REPOSITORY}/tar.gz/{FIXTURE_SHA}"
    ]


def test_the_data_fetcher_refuses_a_tag_of_another_branch() -> None:
    """The vanilla data pack is on `data`, and the archive of `summary` is 351 MB."""
    with pytest.raises(FetchError, match="branch 'data'"):
        fetch_data_files(_summary_tag(), transport=RecordingTransport(b""))


def test_the_data_fetcher_refuses_a_group_that_this_project_does_not_read() -> None:
    """A typo must fail with the accepted list, before it downloads 2.7 MB."""
    transport = RecordingTransport(_data_archive())
    with pytest.raises(FetchError, match="not a data group"):
        fetch_data_files(_data_tag(), groups=["recipes"], transport=transport)
    assert transport.urls == []


def test_the_data_fetcher_takes_a_generator_of_groups(tmp_path: Path) -> None:
    """A group argument must survive being read twice inside the function."""
    transport = RecordingTransport(_data_archive())
    files = fetch_data_files(
        _data_tag(),
        groups=(group for group in DATA_GROUPS if group == "recipe"),
        cache=ContentCache(tmp_path),
        transport=transport,
    )
    assert set(files) == {"recipe/oak_stairs.json"}


def test_the_archive_url_names_codeload_and_carries_the_sha() -> None:
    """The archive must be pinned the same way that every other read is.

    `api.github.com/repos/<repository>/tarball/<sha>` answers the same question
    and names its root directory after the nearest tag rather than after the
    commit.
    """
    assert MCMETA_ARCHIVE_URL.startswith("https://codeload.github.com/")
    url = MCMETA_ARCHIVE_URL.format(repository=MCMETA_REPOSITORY, commit_sha=FIXTURE_SHA)
    assert url.endswith(FIXTURE_SHA)


def test_the_archive_reader_keeps_the_wanted_groups_and_drops_the_rest() -> None:
    """The key is the path under the namespace, and nothing else comes back."""
    files = read_data_archive(_data_archive(), source=ARCHIVE_SOURCE)
    assert files == WANTED_MEMBERS


def test_the_archive_reader_drops_the_experimental_datapack() -> None:
    """`datapacks/` holds the trade rebalance pack, which is not the vanilla game.

    Its members sit under `data/minecraft/datapacks/`, so the prefix test that
    keeps `data/minecraft/tags/` excludes them without a rule of their own. This
    test pins that, because a prefix of `data/minecraft/` would not.
    """
    files = read_data_archive(_data_archive(), source=ARCHIVE_SOURCE)
    assert not any("datapacks" in name for name in files)


def test_the_archive_reader_reads_one_group_when_asked_for_one() -> None:
    """A caller that wants recipes must not get loot tables as well."""
    files = read_data_archive(_data_archive(), groups=["recipe"], source=ARCHIVE_SOURCE)
    assert set(files) == {"recipe/oak_stairs.json"}


def test_the_archive_reader_refuses_a_member_that_is_not_a_regular_file() -> None:
    """mcmeta publishes files and directories, and nothing else.

    A symbolic link in an archive is the classic way to make an extractor write
    outside its target. This reader writes nothing, so the link cannot do that
    here. It still fails, because an archive that holds one is not the archive
    that this build asked for.
    """
    payload = _tar_gz(
        [
            _directory_member(ARCHIVE_ROOT),
            _file_member(f"{ARCHIVE_ROOT}/data/minecraft/recipe/a.json", b"{}"),
            _symlink_member(f"{ARCHIVE_ROOT}/data/minecraft/recipe/b.json", "/etc/passwd"),
        ]
    )
    with pytest.raises(FetchError, match="not a regular file"):
        read_data_archive(payload, source=ARCHIVE_SOURCE)


@pytest.mark.parametrize(
    "name",
    [
        "ROOT/../../../etc/passwd",
        "ROOT/data/minecraft/recipe/../../../../escape.json",
        "ROOT/data/minecraft/recipe/./a.json",
        "/etc/passwd",
        "C:/Windows/system32/drivers/etc/hosts",
        "ROOT\\data\\minecraft\\recipe\\a.json",
        "ROOT/data/minecraft/recipe/a?b.json",
        "ROOT/data/minecraft/recipe//a.json",
    ],
)
def test_the_archive_reader_refuses_a_member_name_that_lies(name: str) -> None:
    """A member name becomes a dictionary key, a cache key, and part of an entity ID.

    This reader keeps every file in memory, so none of these names writes
    anything. The rule is here because the names do not stop at this module, and
    the moment a name arrives is the cheapest moment to refuse it.
    """
    payload = _tar_gz(
        [_directory_member(ARCHIVE_ROOT), _file_member(name.replace("ROOT", ARCHIVE_ROOT), b"{}")]
    )
    with pytest.raises(FetchError):
        read_data_archive(payload, source=ARCHIVE_SOURCE)


def test_the_archive_reader_refuses_two_root_directories() -> None:
    """One commit archive wraps one directory, and the reader strips exactly one.

    A second root would mean the strip removed a real path segment from half the
    members, and the survivors would land under the wrong keys.
    """
    payload = _tar_gz(
        [
            _directory_member(ARCHIVE_ROOT),
            _file_member(f"{ARCHIVE_ROOT}/data/minecraft/recipe/a.json", b"{}"),
            _file_member("other-root/data/minecraft/recipe/b.json", b"{}"),
        ]
    )
    with pytest.raises(FetchError, match="two root directories"):
        read_data_archive(payload, source=ARCHIVE_SOURCE)


def test_the_archive_reader_refuses_a_file_outside_the_root_directory() -> None:
    """A top-level file means the layout changed, and the strip would eat a segment."""
    payload = _tar_gz([_directory_member(ARCHIVE_ROOT), _file_member("loose.json", b"{}")])
    with pytest.raises(FetchError, match="outside the root directory"):
        read_data_archive(payload, source=ARCHIVE_SOURCE)


def test_the_archive_reader_refuses_two_members_of_one_name() -> None:
    """A repeated name would let a later member replace an earlier one in silence."""
    name = f"{ARCHIVE_ROOT}/data/minecraft/recipe/a.json"
    payload = _tar_gz(
        [
            _directory_member(ARCHIVE_ROOT),
            _file_member(name, b'{"first": true}'),
            _file_member(name, b'{"second": true}'),
        ]
    )
    with pytest.raises(FetchError, match="two members named"):
        read_data_archive(payload, source=ARCHIVE_SOURCE)


@pytest.mark.parametrize(
    "payload",
    [b"", b"not a gzip archive at all", b"\x1f\x8b truncated"],
    ids=["empty", "text", "truncated-gzip"],
)
def test_the_archive_reader_refuses_a_body_that_is_not_an_archive(payload: bytes) -> None:
    """An error page or a truncated download must stop the build, not read as empty."""
    with pytest.raises(FetchError, match="not a readable gzip archive"):
        read_data_archive(payload, source=ARCHIVE_SOURCE)


def test_the_archive_reader_refuses_an_archive_with_no_wanted_file() -> None:
    """An empty read is a broken scrape, not a Minecraft version with no recipes.

    CLAUDE.md gives this rule for the wiki scrape, and it holds here for the
    same reason. mcmeta could rename a directory in a future version, and an
    empty dictionary would travel down the pipeline as data.
    """
    payload = _data_archive({"data/minecraft/structure/village/a.nbt": b"x"})
    with pytest.raises(FetchError, match="holds no file under"):
        read_data_archive(payload, source=ARCHIVE_SOURCE)


def test_the_archive_reader_stops_at_the_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """A compression bomb must fail the build rather than fill the memory of a runner.

    The reader adds up the size that each header declares, so it stops part-way
    through a bomb rather than after it.
    """
    monkeypatch.setattr(mcmeta_module, "MAX_ARCHIVE_BYTES", 4)
    with pytest.raises(FetchError, match="bytes of archive"):
        read_data_archive(_data_archive(), source=ARCHIVE_SOURCE)


def test_the_size_limit_counts_a_member_that_declares_no_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bomb of empty members must trip the limit that a content-only total misses.

    Every member costs one header block of the decompressed stream whatever its
    size, and `tarfile` keeps a `TarInfo` for each member it has walked. So an
    archive of a few hundred thousand empty members exhausts the memory of a
    runner while the content it declares stays at zero. Measured against the
    live shape: 200,000 empty members compress to 940 kB and expand to 102 MB of
    headers, which the shipped 256 MB limit reads as an empty archive when the
    total counts content alone.

    The limit is scaled down here rather than the archive scaled up, because
    building the real thing costs a hundred megabytes for one assertion. Every
    member of this archive declares zero bytes of content, so the total that
    trips the limit is made of headers and nothing else.
    """
    members = {f"data/minecraft/recipe/x{index}.json": b"" for index in range(2000)}
    monkeypatch.setattr(mcmeta_module, "MAX_ARCHIVE_BYTES", mcmeta_module.TAR_HEADER_BYTES * 100)
    with pytest.raises(FetchError, match="bytes of archive"):
        read_data_archive(_data_archive(members), source=ARCHIVE_SOURCE)


def test_the_header_block_is_the_size_that_tar_uses() -> None:
    """The per-member cost above must be a tar header block, not a guess."""
    assert mcmeta_module.TAR_HEADER_BYTES == tarfile.BLOCKSIZE


def test_the_archive_reader_names_the_source_in_its_error() -> None:
    """An error must say which read produced it, not only what went wrong."""
    with pytest.raises(FetchError, match=re.escape("https://example.test/archive")):
        read_data_archive(b"not an archive", source="https://example.test/archive")


def test_the_namespace_root_is_the_one_that_mcmeta_publishes() -> None:
    """mcmeta publishes one namespace, and every data file of it sits under this path."""
    assert ARCHIVE_NAMESPACE_ROOT == "data/minecraft"


def test_the_summary_reader_defaults_to_the_guarded_transport() -> None:
    """The default transport is what a build uses, and it carries the HTTPS guard."""
    assert inspect.signature(fetch_summary_payload).parameters["transport"].default is get_bytes


def test_the_data_reader_defaults_to_the_guarded_transport() -> None:
    """The default transport is what a build uses, and it carries the HTTPS guard."""
    assert inspect.signature(fetch_data_files).parameters["transport"].default is get_bytes


# --------------------------------------------------------------------------
# What may enter the cache: a payload the reader accepted, and nothing else.
# --------------------------------------------------------------------------


class SequenceTransport:
    """A transport that answers a different body for each call it gets."""

    def __init__(self, *bodies: bytes) -> None:
        self.bodies = list(bodies)
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        return self.bodies[min(len(self.urls) - 1, len(self.bodies) - 1)]


# What a captive portal or an intercepting proxy answers with, at status 200.
# `get_bytes` cannot tell it from a payload: the status is 200 and the body is
# bytes. Only the reader of the payload can.
INTERCEPTED_PAGE = b"<html><body>Sign in to continue</body></html>"


def test_a_body_that_is_not_an_archive_never_enters_the_cache(tmp_path: Path) -> None:
    """A bad body must cost one build, not every build after it.

    `ContentCache` proves an object against its own name, so it catches a file
    that changed after it was written. It cannot catch a body that was already
    wrong when it arrived. Storing one would fail every later build with an
    error naming a URL that is fine, and the only repair would be to delete
    `data/.cache` by hand, which nothing in the error tells the reader to do.
    """
    cache = ContentCache(tmp_path)
    transport = SequenceTransport(INTERCEPTED_PAGE)

    with pytest.raises(FetchError, match="not a readable gzip archive"):
        fetch_data_files(_data_tag(), cache=cache, transport=transport)

    # Nothing at all reached the store: no index entry, and no object either.
    assert list(tmp_path.rglob("*")) == []
    # The next build meets a working CDN and must succeed with no hand repair.
    good = RecordingTransport(_data_archive())
    assert fetch_data_files(_data_tag(), cache=cache, transport=good) == WANTED_MEMBERS


def test_a_stored_archive_that_no_longer_reads_costs_one_fetch(tmp_path: Path) -> None:
    """A cache written before this rule existed must repair itself, not stop the build."""
    cache = ContentCache(tmp_path)
    url = MCMETA_ARCHIVE_URL.format(repository=MCMETA_REPOSITORY, commit_sha=FIXTURE_SHA)
    cache.write(url, INTERCEPTED_PAGE)

    transport = SequenceTransport(_data_archive())
    assert fetch_data_files(_data_tag(), cache=cache, transport=transport) == WANTED_MEMBERS
    assert transport.urls == [url]
    assert ContentCache(tmp_path).read(url) == _data_archive()


def test_a_summary_body_that_is_not_json_never_enters_the_cache(tmp_path: Path) -> None:
    """The rule holds for the `summary` files too, and for the same reason.

    These come back undecoded because the extract stage owns the parsing. They
    are still decoded once on the way in, so an HTML page cannot take the place
    of `blocks/data.json` for every build that follows.
    """
    cache = ContentCache(tmp_path)
    transport = SequenceTransport(INTERCEPTED_PAGE)

    with pytest.raises(FetchError, match="did not return JSON"):
        fetch_summary_payload(_summary_tag(), "blocks", cache=cache, transport=transport)

    assert list(tmp_path.rglob("*")) == []
    good = RecordingTransport(b'{"blocks": {}}')
    body = fetch_summary_payload(_summary_tag(), "blocks", cache=cache, transport=good)
    assert body == b'{"blocks": {}}'


def test_a_stored_summary_body_that_is_not_json_costs_one_fetch(tmp_path: Path) -> None:
    """A summary payload already in the store must repair itself the same way."""
    cache = ContentCache(tmp_path)
    url = _summary_tag().raw_url(SUMMARY_PAYLOADS["blocks"])
    cache.write(url, INTERCEPTED_PAGE)

    transport = SequenceTransport(b'{"blocks": {}}')
    body = fetch_summary_payload(_summary_tag(), "blocks", cache=cache, transport=transport)
    assert body == b'{"blocks": {}}'
    assert transport.urls == [url]


def test_a_good_payload_is_read_from_the_store_without_a_second_request(tmp_path: Path) -> None:
    """The check on the way in must not cost the cache its whole purpose."""
    cache = ContentCache(tmp_path)
    transport = RecordingTransport(_data_archive())

    fetch_data_files(_data_tag(), cache=cache, transport=transport)
    again = fetch_data_files(_data_tag(), cache=cache, transport=transport)

    assert again == WANTED_MEMBERS
    assert len(transport.urls) == 1


def test_the_data_fetcher_refuses_an_empty_group_list() -> None:
    """A read of no group must fail before the request, not after 2.7 MB of it.

    `read_data_archive` refuses this too, and refusing it there alone means the
    archive is already downloaded by the time anyone says so.
    """
    transport = RecordingTransport(_data_archive())
    with pytest.raises(FetchError, match="at least one group"):
        fetch_data_files(_data_tag(), groups=[], transport=transport)
    assert transport.urls == []
