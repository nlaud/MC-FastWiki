"""Sprite bytes, and the two guards a plain download does not give for free.

`pipeline.fetch.sprites` is the last hop between a `FileImage` and pixels this
project can put in a sprite atlas, and it exists because a plain GET does not
cache by content, and does not prove the body it received is an image at all.
Every test here is one of those two guards, or the report that lets one bad
download not abort a run over several thousand files.

The case worth reading first is
`test_a_polished_body_shorter_than_imageinfo_said_is_accepted`. It is the
regression test for the bug that a full run against the live wiki found and
that no amount of synthetic bytes could have: minecraft.wiki sits behind
Cloudflare Polish, which recompresses images at the edge, so the body that
arrives is a valid PNG whose length and SHA-1 both differ from what
`prop=imageinfo` reported for the same file. Verifying either one rejects 94
correct downloads out of 200. The module docstring carries the measurement.

No test opens a socket. Every download is driven by a fake transport that
returns bytes from memory.
"""

import hashlib
from pathlib import Path

import pytest

from pipeline.fetch import FetchError
from pipeline.fetch.cache import ContentCache
from pipeline.fetch.imageinfo import FileImage
from pipeline.fetch.sprites import (
    MAX_SPRITE_BYTES,
    SPRITE_MIME_TYPES,
    SPRITE_SIGNATURES,
    download_sprite,
    download_sprites,
    sprite_cache_key,
)

VALID_SHA1 = "d4422a162a07edffea60d134d639c5bca3ab4d20"

# A body has to begin with the real signature of its declared type to get past
# the guard, so the helper below prepends one rather than each case spelling it
# out. The bytes after it are never read: nothing here decodes an image.
SIGNATURE = {mime: signatures[0] for mime, signatures in SPRITE_SIGNATURES.items()}


def body(payload: bytes, *, mime: str = "image/png") -> bytes:
    """Return `payload` behind a valid file signature for `mime`."""
    return SIGNATURE[mime] + payload


def image(
    payload: bytes,
    *,
    title: str = "File:Invicon Raw Iron.png",
    mime: str = "image/png",
    sha1: str | None = None,
    size: int | None = None,
) -> FileImage:
    """Return a `FileImage` describing `payload`.

    `sha1` and `size` default to values that are merely well-formed, not to the
    real hash and length of `payload`. That is not laziness: the live wiki does
    exactly this, reporting the original upload's numbers for a body that
    Cloudflare has since recompressed, so a helper that made them agree would
    describe a response this project never actually receives.

    The default `sha1` is derived from `title` rather than fixed, because it is
    also the cache key. One constant for every file would give two different
    sprites one key, and the second download of a pair would silently read the
    first one's bytes back out of the store.
    """
    return FileImage(
        title=title,
        url=f"https://minecraft.wiki/images/{title}?d47d8",
        sha1=sha1 if sha1 is not None else hashlib.sha1(title.encode()).hexdigest(),
        size=size if size is not None else len(payload) + 13,
        width=16,
        height=16,
        mime=mime,
    )


# --- `sprite_cache_key` -------------------------------------------------------


def test_the_cache_key_is_built_from_the_hash_not_the_url() -> None:
    """The whole reason this module exists: the URL's query string rotates on every reupload."""
    assert sprite_cache_key(VALID_SHA1) == f"sprite/{VALID_SHA1}"


def test_a_malformed_sha1_is_refused() -> None:
    with pytest.raises(FetchError, match="sha1"):
        sprite_cache_key("not-a-hash")


# --- `download_sprite` --------------------------------------------------------


def test_a_good_download_is_stored_and_returned(tmp_path: Path) -> None:
    payload = body(b"fake but small")
    picture = image(payload)
    cache = ContentCache(tmp_path)
    requested: list[str] = []

    def transport(url: str) -> bytes:
        requested.append(url)
        return payload

    result = download_sprite(picture, cache=cache, transport=transport)
    assert result == payload
    assert requested == [picture.url]
    assert cache.read(sprite_cache_key(picture.sha1)) == payload


def test_a_cache_hit_does_no_io_at_all(tmp_path: Path) -> None:
    payload = body(b"already cached")
    picture = image(payload)
    cache = ContentCache(tmp_path)
    cache.write(sprite_cache_key(picture.sha1), payload)

    def refuse(url: str) -> bytes:
        raise AssertionError("a cache hit must not call the transport")

    assert download_sprite(picture, cache=cache, transport=refuse) == payload


def test_a_mime_type_outside_the_accepted_set_is_refused_before_any_request(tmp_path: Path) -> None:
    """Refused before the network, so a bad catalogue entry costs nothing to reject."""
    picture = image(b"whatever", mime="image/svg+xml")
    cache = ContentCache(tmp_path)

    def refuse(url: str) -> bytes:
        raise AssertionError("a bad mime type must be refused before any request")

    with pytest.raises(FetchError, match="image/svg\\+xml"):
        download_sprite(picture, cache=cache, transport=refuse)


@pytest.mark.parametrize("mime", sorted(SPRITE_MIME_TYPES))
def test_both_accepted_mime_types_are_allowed(tmp_path: Path, mime: str) -> None:
    """PNG is the ordinary case; `Sculk Block` names a real GIF, not a mistake."""
    payload = body(b"bytes", mime=mime)
    picture = image(payload, mime=mime)
    cache = ContentCache(tmp_path)
    assert download_sprite(picture, cache=cache, transport=lambda url: payload) == payload


def test_a_body_that_is_not_an_image_is_refused_and_never_stored(tmp_path: Path) -> None:
    """The guard this module exists for: a captive portal's HTML must not enter the cache.

    Stored-or-not is half the assertion and not a flourish. `fetch_and_read`
    stores whatever its reader accepts, so a check made after the call would
    leave the login page in the cache forever, every later build would fail
    against a URL that is perfectly fine, and the only repair would be deleting
    `data/.cache` by hand.
    """
    picture = image(b"unused")
    cache = ContentCache(tmp_path)

    def transport(url: str) -> bytes:
        return b"<!doctype html><title>Sign in to the network</title>"

    with pytest.raises(FetchError, match="does not begin a image/png file"):
        download_sprite(picture, cache=cache, transport=transport)
    assert cache.read(sprite_cache_key(picture.sha1)) is None


def test_a_gif_body_under_a_png_declaration_is_refused() -> None:
    """The signature is checked against the declared type, not against images in general."""
    picture = image(b"unused", mime="image/png")
    cache = ContentCache(root="unused")

    with pytest.raises(FetchError, match="does not begin a image/png file"):
        download_sprite(picture, cache=cache, transport=lambda url: body(b"x", mime="image/gif"))


def test_a_polished_body_shorter_than_imageinfo_said_is_accepted(tmp_path: Path) -> None:
    """The regression test for Cloudflare Polish. Read the module docstring before changing it.

    `prop=imageinfo` reports the original upload: 222 bytes hashing to
    `d4422a16...` for `File:Invicon Raw Iron.png`. Cloudflare serves a
    losslessly recompressed 209-byte derivative hashing to something else
    entirely. Both are correct, and they describe different files, so a
    download that disagrees with `size` and `sha1` is the normal case here
    rather than a fault. Verifying either one rejected 94 of the first 200
    sprites of a real run, every one of them a good download.
    """
    delivered = body(b"polished, and shorter than the original upload")
    picture = image(delivered, sha1=VALID_SHA1, size=len(delivered) + 13)
    cache = ContentCache(tmp_path)

    assert download_sprite(picture, cache=cache, transport=lambda url: delivered) == delivered
    assert cache.read(sprite_cache_key(VALID_SHA1)) == delivered


def test_a_body_over_the_maximum_size_is_refused() -> None:
    payload = body(b"x" * MAX_SPRITE_BYTES)
    picture = image(payload)
    cache = ContentCache(root="unused")

    with pytest.raises(FetchError, match="limit"):
        download_sprite(picture, cache=cache, transport=lambda url: payload)


def test_the_default_transport_reads_get_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = body(b"default transport bytes")
    picture = image(payload)
    calls: list[str] = []

    def fake_get_bytes(url: str, *, timeout: float = 30.0) -> bytes:
        calls.append(url)
        return payload

    monkeypatch.setattr("pipeline.fetch.sprites.get_bytes", fake_get_bytes)
    cache = ContentCache(tmp_path)
    assert download_sprite(picture, cache=cache) == payload
    assert calls == [picture.url]


# --- `download_sprites` -------------------------------------------------------


def test_one_bad_file_does_not_abort_the_rest(tmp_path: Path) -> None:
    """A run over thousands of files must not stop at the first bad one."""
    good = image(body(b"good bytes"), title="File:Good.png")
    bad = image(b"unused", title="File:Bad.png")
    cache = ContentCache(tmp_path)

    def transport(url: str) -> bytes:
        return body(b"good bytes") if "Good" in url else b"a Cloudflare challenge page"

    report = download_sprites([good, bad], cache=cache, transport=transport)

    assert report.images == {"File:Good.png": body(b"good bytes")}
    assert len(report.failed) == 1
    assert report.failed[0].title == "File:Bad.png"


def test_every_file_succeeding_reports_no_failures(tmp_path: Path) -> None:
    first = image(body(b"one"), title="File:One.png")
    second = image(body(b"two"), title="File:Two.png")
    cache = ContentCache(tmp_path)

    def transport(url: str) -> bytes:
        return body(b"one") if "One" in url else body(b"two")

    report = download_sprites([first, second], cache=cache, transport=transport)
    assert report.images == {"File:One.png": body(b"one"), "File:Two.png": body(b"two")}
    assert report.failed == ()


def test_an_empty_list_downloads_nothing(tmp_path: Path) -> None:
    report = download_sprites([], cache=ContentCache(tmp_path))
    assert report.images == {}
    assert report.failed == ()
