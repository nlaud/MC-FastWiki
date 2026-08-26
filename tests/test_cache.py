"""The content-addressed disk cache, and the rules that keep a bad object out.

CLAUDE.md asks that every network read of this pipeline is cached on disk by
content hash. `pipeline.fetch.cache` is that cache, and this module pins each of
its rules.

Two of those rules carry the weight. An object is named by the SHA-256 of its
own content, so nothing but a hexadecimal digest ever names a file, and a cache
key of `https://host/a/../b?x=1` cannot reach the file system. A read verifies
the object against its name, so a truncated or edited file counts as a miss
rather than as data. Non-negotiable 1 of CLAUDE.md is correct Java Edition data,
and cache corruption that reaches a parser looks exactly like a Minecraft
change.

No test in this module opens a socket, and no test writes to the cache of the
repository. Every cache here is built on `tmp_path`.
"""

import hashlib
import inspect
import json
import socket
from pathlib import Path

import pytest

import pipeline.fetch.cache as cache_module
from pipeline.fetch import FetchError, get_bytes
from pipeline.fetch.cache import (
    DEFAULT_CACHE_ROOT,
    HASH_ALGORITHM,
    INDEX_NAME,
    OBJECTS_NAME,
    SHARD_LENGTH,
    ContentCache,
)

URL = "https://raw.githubusercontent.com/misode/mcmeta/" + "a" * 40 + "/blocks/data.json"
PAYLOAD = b'{"item": ["apple", "stone"]}'
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


@pytest.fixture(autouse=True)
def refuse_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test of this module that opens a socket.

    `tests/test_version_manifest.py` holds the long form of the reason. The
    short form: a test that reaches the live network passes for the wrong
    reason, and it passes only while the network is up.
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise RuntimeError("this test tried to reach the network")

    monkeypatch.setattr(socket, "socket", refuse)


class RecordingTransport:
    """A transport that answers with fixed bytes and counts its calls."""

    def __init__(self, body: bytes = PAYLOAD) -> None:
        self.body = body
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        return self.body


def _cache(tmp_path: Path) -> ContentCache:
    return ContentCache(tmp_path / "cache")


def test_the_default_root_is_the_directory_that_gitignore_holds() -> None:
    """The cache must write where `.gitignore` already excludes.

    `tests/test_repo_invariants.py` pins the `/data/.cache/` rule of
    `.gitignore`. A cache that wrote anywhere else would put several megabytes
    of upstream JSON into `git status` on the first build.
    """
    assert DEFAULT_CACHE_ROOT.parts == ("data", ".cache")


def test_a_miss_fetches_once_and_a_hit_fetches_never(tmp_path: Path) -> None:
    """The second read of one key must not reach the transport."""
    cache = _cache(tmp_path)
    transport = RecordingTransport()

    first = cache.fetch(URL, transport=transport)
    second = cache.fetch(URL, transport=transport)

    assert first == PAYLOAD
    assert second == PAYLOAD
    assert transport.urls == [URL]


def test_a_new_instance_reads_the_cache_that_a_past_run_wrote(tmp_path: Path) -> None:
    """A cache is a cache between builds, not within one build.

    The hit above could come from memory. This one cannot: the second instance
    shares no state with the first, so the answer comes off the disk.
    """
    transport = RecordingTransport()
    _cache(tmp_path).fetch(URL, transport=transport)

    later = ContentCache(tmp_path / "cache")
    assert later.fetch(URL, transport=transport) == PAYLOAD
    assert transport.urls == [URL]


def test_the_object_is_named_by_the_hash_of_its_content(tmp_path: Path) -> None:
    """The file name must be the digest, and the shard must be its first characters."""
    cache = _cache(tmp_path)
    cache.fetch(URL, transport=RecordingTransport())

    path = tmp_path / "cache" / OBJECTS_NAME / DIGEST[:SHARD_LENGTH] / DIGEST
    assert path.read_bytes() == PAYLOAD
    assert hashlib.new(HASH_ALGORITHM, path.read_bytes()).hexdigest() == path.name


def test_the_index_maps_the_key_to_the_digest(tmp_path: Path) -> None:
    """The index must hold the URL as written, with no escaping and no rewriting."""
    cache = _cache(tmp_path)
    cache.fetch(URL, transport=RecordingTransport())

    index = json.loads((tmp_path / "cache" / INDEX_NAME).read_bytes())
    assert index == {URL: DIGEST}


def test_two_keys_of_one_payload_share_one_object(tmp_path: Path) -> None:
    """A content-addressed store must write identical bytes one time.

    This is the reason the store is content-addressed rather than key-addressed.
    mcmeta leaves several thousand files alone between two Minecraft versions,
    and a key-addressed store would hold a second copy of each one.
    """
    cache = _cache(tmp_path)
    other = "https://codeload.github.com/misode/mcmeta/tar.gz/" + "a" * 40
    cache.fetch(URL, transport=RecordingTransport())
    cache.fetch(other, transport=RecordingTransport())

    objects = sorted((tmp_path / "cache" / OBJECTS_NAME).rglob("*"))
    assert [path.name for path in objects if path.is_file()] == [DIGEST]
    index = json.loads((tmp_path / "cache" / INDEX_NAME).read_bytes())
    assert index == {URL: DIGEST, other: DIGEST}


def test_an_object_that_does_not_hash_to_its_name_is_a_miss(tmp_path: Path) -> None:
    """A corrupt object must never reach a parser.

    This is the rule that separates this cache from a plain file cache. A
    truncated write, a bad disk, or a hand edit gives bytes that no longer match
    the name. Returning them would feed a parser data of unknown origin, and a
    wrong Minecraft number looks exactly like a right one on the screen.
    """
    cache = _cache(tmp_path)
    cache.fetch(URL, transport=RecordingTransport())

    path = tmp_path / "cache" / OBJECTS_NAME / DIGEST[:SHARD_LENGTH] / DIGEST
    path.write_bytes(b'{"item": ["apple", "diamond"]}')

    assert cache.read(URL) is None

    repaired = RecordingTransport()
    assert ContentCache(tmp_path / "cache").fetch(URL, transport=repaired) == PAYLOAD
    assert repaired.urls == [URL]
    assert path.read_bytes() == PAYLOAD


def test_a_missing_object_is_a_miss(tmp_path: Path) -> None:
    """An index entry whose object is gone must fetch again, not raise."""
    cache = _cache(tmp_path)
    cache.fetch(URL, transport=RecordingTransport())
    (tmp_path / "cache" / OBJECTS_NAME / DIGEST[:SHARD_LENGTH] / DIGEST).unlink()

    assert ContentCache(tmp_path / "cache").read(URL) is None


def test_an_unknown_key_is_a_miss(tmp_path: Path) -> None:
    """A key that the index does not hold returns `None`, not an error."""
    assert _cache(tmp_path).read(URL) is None


@pytest.mark.parametrize(
    "body",
    [
        b"not json at all",
        b"[]",
        b'{"key": 3}',
        b'{"key": null}',
        b"",
    ],
    ids=["not-json", "not-an-object", "value-not-a-string", "value-null", "empty"],
)
def test_an_unreadable_index_costs_a_fetch_and_not_the_build(tmp_path: Path, body: bytes) -> None:
    """A damaged index must recover, because a cache is an optimization.

    The objects survive a damaged index, and the next write puts the keys back.
    A build that stopped here would fail for a reason that has nothing to do
    with the data it is building.
    """
    root = tmp_path / "cache"
    root.mkdir()
    (root / INDEX_NAME).write_bytes(body)

    transport = RecordingTransport()
    assert ContentCache(root).fetch(URL, transport=transport) == PAYLOAD
    assert transport.urls == [URL]
    assert json.loads((root / INDEX_NAME).read_bytes()) == {URL: DIGEST}


@pytest.mark.parametrize(
    "digest",
    [
        "../../../../etc/passwd",
        "..",
        ".",
        "",
        "main",
        DIGEST[:16],
        DIGEST + "0",
        DIGEST.upper(),
        DIGEST[:-1] + "g",
        "ab/" + DIGEST,
    ],
)
def test_object_path_refuses_a_name_that_is_not_a_digest(tmp_path: Path, digest: str) -> None:
    """Only a digest may name a file, because the index is a file that anyone can edit.

    The cache key is a URL and never reaches the file system. The digest does,
    so the digest is the one string that needs this rule.
    """
    with pytest.raises(FetchError, match="digest"):
        _cache(tmp_path).object_path(digest)


def test_a_hand_edited_index_that_names_a_path_is_a_miss(tmp_path: Path) -> None:
    """The path rule must hold on the read path, not only on `object_path`.

    A `read` that raised here would stop a build over a damaged cache. A `read`
    that followed the name would open a file outside the store.
    """
    root = tmp_path / "cache"
    root.mkdir()
    (root / INDEX_NAME).write_bytes(json.dumps({URL: "../../secret"}).encode("utf-8"))

    assert ContentCache(root).read(URL) is None


def test_a_write_leaves_no_temporary_file(tmp_path: Path) -> None:
    """An atomic write must publish one name and clean up after itself."""
    cache = _cache(tmp_path)
    cache.fetch(URL, transport=RecordingTransport())

    leftovers = [path.name for path in (tmp_path / "cache").rglob(".tmp-*")]
    assert leftovers == []


def test_a_store_that_cannot_write_stops_the_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cache that silently fails to write is a build that fetches every time.

    CLAUDE.md asks this pipeline to be a good citizen with the services it
    reads. A cache that never stores would read the whole of mcmeta at every
    stage of every build and report nothing.
    """

    def refuse(path: Path, payload: bytes) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(cache_module, "_write_atomically", refuse)
    with pytest.raises(FetchError, match="could not store"):
        _cache(tmp_path).write(URL, PAYLOAD)


def test_write_returns_the_digest_and_repeats_without_a_second_copy(tmp_path: Path) -> None:
    """A second write of one key and one payload must not rewrite the object."""
    cache = _cache(tmp_path)
    assert cache.write(URL, PAYLOAD) == DIGEST

    path = tmp_path / "cache" / OBJECTS_NAME / DIGEST[:SHARD_LENGTH] / DIGEST
    written_at = path.stat().st_mtime_ns

    assert cache.write(URL, PAYLOAD) == DIGEST
    assert path.stat().st_mtime_ns == written_at


def test_the_fetch_default_is_the_guarded_transport() -> None:
    """`fetch` must default to `get_bytes`, which carries the HTTPS-only guard.

    A default of `urlopen` would drop the redirect guard of
    `pipeline/fetch/__init__.py`, and a redirect to cleartext would then pass
    unnoticed.
    """
    default = inspect.signature(ContentCache.fetch).parameters["transport"].default
    assert default is get_bytes


def test_a_second_instance_does_not_drop_the_keys_of_the_first(tmp_path: Path) -> None:
    """Two caches on one root must both keep their keys.

    `fetch_summary_payload` and `fetch_data_files` build a transient
    `ContentCache()` whenever the caller passes none, so a build that holds a
    cache of its own and calls either of those without it has two instances on
    one root. Each holds the index it read, and a write that put its own copy
    back over the file would drop every key the other had added since. The
    object would stay on disk with nothing pointing at it, and the next build
    would fetch a payload it already had.
    """
    root = tmp_path / "cache"
    first = ContentCache(root)
    second = ContentCache(root)

    first.write("https://host/a", b"a")
    second.write("https://host/b", b"b")
    # `first` last read the index when it held neither key. Writing again must
    # merge with the file rather than publish that stale copy.
    first.write("https://host/c", b"c")

    index = json.loads((root / INDEX_NAME).read_bytes())
    assert sorted(index) == ["https://host/a", "https://host/b", "https://host/c"]

    later = ContentCache(root)
    assert later.read("https://host/a") == b"a"
    assert later.read("https://host/b") == b"b"
    assert later.read("https://host/c") == b"c"


def test_a_write_leaves_no_object_that_the_index_does_not_name(tmp_path: Path) -> None:
    """Every object on disk must have a key, or the store leaks on every build.

    An orphan is the visible half of the bug above: the bytes stay, the key
    goes, and nothing ever reads or removes the file again.
    """
    root = tmp_path / "cache"
    first = ContentCache(root)
    second = ContentCache(root)
    first.write("https://host/a", b"a")
    second.write("https://host/b", b"b")
    first.write("https://host/c", b"c")

    named = set(json.loads((root / INDEX_NAME).read_bytes()).values())
    on_disk = {path.name for path in (root / OBJECTS_NAME).rglob("*") if path.is_file()}
    assert on_disk == named


def test_a_write_reports_the_keys_that_another_instance_added(tmp_path: Path) -> None:
    """A merge must reach the copy in memory too, not the file alone.

    A write that fixed the file but left the instance holding its stale copy
    would answer `None` for a key that is on disk, and the build would fetch it
    again.
    """
    root = tmp_path / "cache"
    first = ContentCache(root)
    second = ContentCache(root)

    first.write("https://host/a", b"a")
    second.write("https://host/b", b"b")
    first.write("https://host/c", b"c")

    assert first.read("https://host/b") == b"b"
