"""The disk cache of the pipeline, addressed by the hash of what it holds.

CLAUDE.md asks for two things of every network read in this repository. A read
is cached on disk by content hash, and a rebuild does not fetch a payload that
did not change. This module is that cache.

The layout has two parts::

    data/.cache/index.json              a cache key -> the SHA-256 of its payload
    data/.cache/objects/ab/abcdef...    one payload, named by its own SHA-256

The split is what makes the store content-addressed rather than key-addressed.
mcmeta changes a few hundred files between two Minecraft versions and leaves
several thousand alone, so two builds of two versions name different keys for
the same bytes. A key-addressed store writes those bytes twice. This one writes
them once, and the second key points at the object that the first key made.

The object name is the whole guard against a bad path. A cache key here is a
URL, and a URL holds a slash, a colon, a question mark, and two dots. None of
that reaches the file system: only the 64 hexadecimal characters of a SHA-256
name a file, and the key lives in the JSON index, where any string is only a
string.

A read verifies the object against its own name before it returns. A file that
fails the check counts as a miss, so a truncated or edited object never reaches
a parser. This matters more here than in an ordinary cache. Non-negotiable 1 of
CLAUDE.md is correct Java Edition data, and a wrong Minecraft number looks
exactly like a right one on the screen.

Every write goes to a temporary file in the target directory, and then to
`Path.replace`, which is atomic on one file system. An interrupted build leaves
no half-written object and no half-written index.

The cache holds no expiry rule, and it needs none, because every key that this
pipeline writes names one immutable payload for all time. A key is immutable in
one of two ways. An mcmeta key carries the pinned commit SHA in its URL, and the
bytes at that URL cannot change; read `pipeline/fetch/mcmeta.py` for the reason
that the SHA is there. A wiki key carries a caller revision in front of the URL,
because the wiki is edited every day and its URL alone names different bytes
next week; read `pipeline/fetch/bucket.py` for the shape of that key.

The rule for any new caller follows from those two. Put something in the key
that changes when the payload may have changed. A key that cannot promise this
belongs in a different store, not in this one with an expiry bolted on.
"""

import hashlib
import json
import string
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pipeline.fetch import FetchError, Transport, get_bytes

__all__ = [
    "DEFAULT_CACHE_ROOT",
    "HASH_ALGORITHM",
    "INDEX_NAME",
    "OBJECTS_NAME",
    "SHARD_LENGTH",
    "ContentCache",
    "fetch_and_read",
]

# Where the pipeline keeps its intermediates. `.gitignore` holds `/data/.cache/`,
# and `tests/test_repo_invariants.py` fails when that rule goes missing.
DEFAULT_CACHE_ROOT = Path("data") / ".cache"

# The file that maps a cache key to the name of its object.
INDEX_NAME = "index.json"

# The directory that holds the objects.
OBJECTS_NAME = "objects"

# SHA-256, and no choice of algorithm. A second algorithm would mean two names
# for one payload, and the store would hold it twice.
HASH_ALGORITHM = "sha256"

# How many leading characters of the hash name the subdirectory. One directory
# of several thousand entries is slow to list on some file systems, and 256
# subdirectories spread the same entries thinly.
SHARD_LENGTH = 2

# The length of a SHA-256 in hexadecimal, and the character set of one.
DIGEST_LENGTH = hashlib.new(HASH_ALGORITHM).digest_size * 2
DIGEST_CHARACTERS = frozenset(string.hexdigits[:16])


def _digest(payload: bytes) -> str:
    """Return the SHA-256 of `payload` as lowercase hexadecimal."""
    return hashlib.new(HASH_ALGORITHM, payload).hexdigest()


def _encode_index(index: dict[str, str]) -> bytes:
    """Return the bytes of the index file for `index`.

    Sorted and indented so that two builds of one set of keys write one byte
    sequence, and so that a person reading the file can find a key in it.
    """
    return json.dumps(index, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _write_atomically(path: Path, payload: bytes) -> None:
    """Write `payload` to `path` in one step, or leave `path` as it was.

    A build can stop at any moment. CI kills a job, a developer presses Ctrl-C,
    and a disk fills. A plain `write_bytes` leaves a truncated file behind in
    each of those cases, and the next build reads it. So the bytes go to a
    temporary file first, and one rename publishes them.

    The temporary file goes in the target directory on purpose. `Path.replace`
    is atomic within one file system and is not atomic across two, and the
    system temporary directory is often a different file system.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115
        dir=path.parent, prefix=".tmp-", delete=False
    )
    temporary = Path(handle.name)
    try:
        with handle as open_file:
            open_file.write(payload)
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


class ContentCache:
    """One content-addressed store of fetched payloads, on disk.

    Build one for a whole pipeline run and pass it to each fetcher. A test
    builds one on `tmp_path`, so no test writes to the cache of the repository.
    """

    def __init__(self, root: Path | str = DEFAULT_CACHE_ROOT) -> None:
        self.root = Path(root)
        self.objects = self.root / OBJECTS_NAME
        self.index_path = self.root / INDEX_NAME
        self._index: dict[str, str] | None = None

    def object_path(self, digest: str) -> Path:
        """Return the file that holds the payload of `digest`.

        The name is checked, not trusted. The index is a file on disk, and a
        hand-edited index could name a path of dot segments where a hash
        belongs. A hexadecimal string of the right length cannot leave
        `self.objects`.
        """
        if len(digest) != DIGEST_LENGTH or not DIGEST_CHARACTERS.issuperset(digest):
            raise FetchError(
                f"{digest!r} is not a {HASH_ALGORITHM} digest, so it does not name a cache object."
            )
        return self.objects / digest[:SHARD_LENGTH] / digest

    def _load_index(self) -> dict[str, str]:
        """Return the index, reading it from disk the first time it is wanted.

        The result is held for the next call. `write` drops the held copy before
        it merges, so the file on disk decides what a write publishes and a read
        never has to pay for the file twice.

        A missing index and an unreadable index both give an empty one. That is
        deliberate. The cache is an optimization, and a build that cannot read
        the index must fetch again, not stop. Nothing is lost by the recovery:
        the objects stay on disk, and the next write puts their keys back.

        A corrupt object is the opposite case, and `read` treats it as one.
        """
        if self._index is None:
            try:
                document: Any = json.loads(self.index_path.read_bytes())
            except (OSError, ValueError):
                document = None
            if isinstance(document, dict) and all(
                isinstance(key, str) and isinstance(value, str) for key, value in document.items()
            ):
                self._index = dict(document)
            else:
                self._index = {}
        return self._index

    def read(self, key: str) -> bytes | None:
        """Return the cached payload of `key`, or `None` when there is no usable one.

        `None` covers every miss with one answer: the key is unknown, the object
        that the index names is gone, or the object does not hash to its own
        name. The caller then fetches, and `write` repairs the entry.
        """
        digest = self._load_index().get(key)
        if digest is None:
            return None
        try:
            path = self.object_path(digest)
        except FetchError:
            return None
        try:
            payload = path.read_bytes()
        except OSError:
            return None
        if _digest(payload) != digest:
            # The object does not hold what its name says. Treat the entry as a
            # miss rather than hand a parser bytes of unknown origin.
            return None
        return payload

    @staticmethod
    def _holds(path: Path, payload: bytes) -> bool:
        """Return whether `path` already holds exactly `payload`."""
        try:
            return path.read_bytes() == payload
        except OSError:
            return False

    def write(self, key: str, payload: bytes) -> str:
        """Store `payload`, point `key` at it, and return its digest.

        A failure to write raises `FetchError` rather than pass in silence. A
        cache that cannot write is not a slow build. It is a build that reads
        the network at every stage, and CLAUDE.md asks this pipeline to be a
        good citizen with the services that it reads.
        """
        digest = _digest(payload)
        path = self.object_path(digest)
        try:
            # Two keys can name the same bytes, and the second one needs no
            # second copy. The comparison is against the payload rather than
            # against the name of the file, so a corrupt object is repaired
            # here. Skipping on `exists` alone would leave a bad object in
            # place for all time: `read` would call it a miss on every build,
            # and `write` would decline to replace it on every build.
            if not self._holds(path, payload):
                _write_atomically(path, payload)
            # Read the index off the disk again before writing it back, and
            # merge rather than overwrite. Another `ContentCache` on this root
            # can have added keys since this instance last read the file, and
            # writing the copy in memory over the top would drop every one of
            # them: the key would be gone, the object it named would stay on
            # disk with nothing pointing at it, and the next build would fetch
            # a payload it already had.
            #
            # Two instances on one root is the ordinary case here, not an
            # exotic one. `fetch_summary_payload` and `fetch_data_files` each
            # build a transient `ContentCache()` whenever the caller passes
            # none, so a build that holds one cache of its own and calls either
            # of those without it has two.
            #
            # The merge is safe in either direction. A key of this store carries
            # an immutable identifier, such as a pinned mcmeta commit sha, so
            # one key names one payload for all time and two instances cannot
            # disagree about a digest.
            memo = dict(self._load_index())
            memo[key] = digest
            self._index = None
            on_disk = self._load_index()
            merged = on_disk | memo
            self._index = merged
            if merged != on_disk:
                _write_atomically(self.index_path, _encode_index(merged))
        except OSError as error:
            raise FetchError(f"the cache at {self.root} could not store {key}: {error}") from error
        return digest

    def fetch(self, url: str, *, transport: Transport = get_bytes) -> bytes:
        """Return the payload of `url`, from the cache when it is there.

        The URL is the cache key. Every URL that this pipeline caches carries an
        immutable identifier already, such as a pinned mcmeta commit SHA, so one
        key names one payload for all time.

        Pass `transport` to read the bytes from somewhere else. A test passes a
        callable of its own, so no test of this module opens a socket.
        """
        cached = self.read(url)
        if cached is not None:
            return cached
        payload = transport(url)
        self.write(url, payload)
        return payload


def fetch_and_read[T](
    store: ContentCache,
    url: str,
    *,
    transport: Transport,
    read: Callable[[bytes], T],
    key: str | None = None,
) -> T:
    """Return `read` of the payload of `url`, and store no payload that `read` refuses.

    `ContentCache.fetch` stores whatever the transport hands it. That is right
    for the store, which proves an object against its own name and so catches a
    file that changed after it was written. It cannot catch a body that was
    already wrong when it arrived, and only the caller knows what a right one
    looks like.

    The case that matters is a proxy or a captive portal that answers 200 with
    an HTML page. `get_bytes` sees a valid response, so the page reaches the
    store, and every later build reads it back and fails with an error that
    names a URL that is fine and never mentions the cache. The only repair is to
    delete `data/.cache` by hand, and nothing tells the reader to.

    So `read` runs first. A fresh payload that fails it is never stored. A
    stored payload that fails it is dropped for this build and fetched again,
    which costs one request and then either works or raises the truthful error
    of the fresh read.

    `key` names the cache entry when it must differ from the URL. It defaults to
    the URL, which is right for every upstream whose URL already names immutable
    bytes. The wiki is not one of those, so `pipeline.fetch.bucket` passes a key
    that carries a caller revision. The URL still decides what the transport
    reads; only the name of the cache entry moves.
    """
    cache_key = url if key is None else key
    cached = store.read(cache_key)
    if cached is not None:
        try:
            return read(cached)
        except FetchError:
            # The stored payload is not the payload. Say nothing here: the
            # fresh read below reports whatever is actually wrong.
            pass
    payload = transport(url)
    value = read(payload)
    store.write(cache_key, payload)
    return value
