"""Sprite bytes, cached by the hash the wiki gave for them and checked for being an image.

`pipeline.fetch.imageinfo` answers a `File:` title with a `FileImage`: a URL, a
size, and a SHA-1. This module is the last hop: it turns that answer into the
bytes Phase 4's sprite atlas actually needs, and it does two things no plain
GET does on its own.

Read the Cloudflare Polish fact below before changing anything here. It is the
reason this module keys on a hash it deliberately does not verify, which reads
like a bug until the reason is known.

**It caches by content hash, not by URL.** `pipeline.fetch.imageinfo`'s module
docstring explains why the URL is the wrong key: it carries a cache-busting
query string that changes on every re-upload, `Invicon_Raw_Iron.png?d47d8`
today and a different suffix after the next edit, for a reason that has
nothing to do with whether the pixels changed. A URL-keyed cache would
re-download every one of the roughly 3,200 sprites this project draws on any
unrelated wiki churn -- a caption edited on the file's description page is
enough to rotate the query string. `sprite_cache_key` builds the key from
`sha1` instead, so a build re-downloads only the files whose content actually
changed. This is the "content-hash caching" `TODO.md` asks for.

**It checks that the answer is an image before the bytes reach the store.**
`fetch_and_read`'s own docstring gives the general reason: a proxy or a captive
portal can answer 200 with an HTML page, and a check made after storing lets
that page sit in the cache forever, failing every future build with an error
that names a URL that is fine. `pipeline.fetch.bucket`'s page-length guard is
the same shape of fix for the same shape of risk, applied to a bucket page
instead of a file body. Here the guard is the file signature and a size cap,
applied inside the reader passed to `fetch_and_read` so a body that is not an
image is never stored.

**The one thing this module must not do is verify `sha1` against the bytes it
receives, and this was learned the expensive way.** The obvious design is to
recompute the SHA-1 and refuse a mismatch, which is stricter than a signature
check and costs nothing. It fails against the live site. Measured on
2026-08-30, over the first 200 sprites of a real run, 94 of them "failed" that
check, and every one of them was a correct download.

minecraft.wiki is behind Cloudflare, and Cloudflare Polish recompresses images
at the edge. The response says so itself::

    cf-polished: ok, orig_size=222
    vary: accept, accept-encoding

`File:Invicon Raw Iron.png` is 222 bytes with SHA-1 `d4422a16...` according to
`prop=imageinfo`, and the bytes that arrive are a valid PNG of 209 bytes
hashing to `5d791ba6...`. Both numbers are right. They describe different
files: `imageinfo` reports the *original upload*, which is the artifact stored
in the wiki's own database, while the URL under `/images/` serves an optimized
derivative that no client ever receives in its original form. Polish is
lossless for PNG, so the pixels are identical and the smaller file is the one
this project wants -- there is nothing to fix and nothing to work around.

Two consequences follow, and both are load-bearing.

1. `sha1` stays the cache key and stops being an integrity check. It still
   names *which upstream revision* of a file this is, which is exactly the
   property `sprite_cache_key` needs, because the original changes whenever the
   file is reuploaded and only then. It simply says nothing about the bytes on
   the wire. The same goes for `size`: it is the original's length, so
   comparing it to `len(payload)` rejects every polished file.

2. **Never send an `Accept` header on a sprite request.** `vary: accept` is
   Cloudflare announcing that it will negotiate the image format, and a request
   advertising WebP gets WebP rather than the PNG the `File:` title names.
   `pipeline.fetch.build_request` sends `User-Agent` alone, which is what keeps
   the delivered format equal to the declared one, so the signature check below
   holds. Adding a default `Accept` header there would break this module
   silently, and the failure would look like a corrupt sprite atlas rather than
   like a header change.
"""

from collections.abc import Mapping, Sequence

from pydantic import BaseModel

from pipeline.fetch import FetchError, Transport, get_bytes
from pipeline.fetch.cache import ContentCache, fetch_and_read
from pipeline.fetch.imageinfo import SHA1_PATTERN, FileImage, MissingImage

__all__ = [
    "MAX_SPRITE_BYTES",
    "SPRITE_MIME_TYPES",
    "SPRITE_SIGNATURES",
    "SpriteDownloadReport",
    "download_sprite",
    "download_sprites",
    "sprite_cache_key",
]

# How many bytes one sprite may be before this module refuses it. Real icons
# measured from the live wiki run from about 67 bytes (`Cave Air`, a single
# transparent pixel) to a few kilobytes; 1 MiB leaves generous room for a
# large achievement or biome sprite while still catching a download that
# answered something other than a small icon, such as an HTML error page that
# `fetch_and_read`'s own read-before-store step did not already catch.
MAX_SPRITE_BYTES = 1024 * 1024

# The leading bytes each accepted MIME type must start with.
#
# This is the integrity check that replaced the SHA-1 comparison, for the
# Cloudflare Polish reason the module docstring gives at length. It is weaker
# than a hash and it is not nothing: the failure it exists to catch is a body
# that is not the image at all -- a captive portal's login page, a Cloudflare
# challenge, an HTML 404 served with a 200 -- and none of those begin with a
# PNG or GIF signature. Polish rewrites the interior of a PNG and leaves the
# signature alone, so this check passes for a polished file and fails for a
# substituted one, which is exactly the split that matters.
#
# GIF has two signatures because both versions of the format are in use. The
# wiki serves GIF87a nowhere that this project reads today, and accepting only
# GIF89a would make that an assumption rather than an observation.
SPRITE_SIGNATURES: Mapping[str, tuple[bytes, ...]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/gif": (b"GIF87a", b"GIF89a"),
}

# The MIME types a sprite download may answer. Checked live against the
# `spritefile` bucket on 2026-08-30: nearly every sprite is a PNG, but `Sculk
# Block` names `File:Sculk JE1 BE1.gif`, a real animated icon and not a
# mistake, so GIF is accepted alongside PNG rather than treated as a fault.
#
# Derived from `SPRITE_SIGNATURES` rather than written out again. A type this
# module accepts but has no signature for would pass the MIME check and then
# raise `KeyError` in the reader, which is a crash where a refusal belongs, so
# the two lists are one list.
SPRITE_MIME_TYPES = frozenset(SPRITE_SIGNATURES)


def sprite_cache_key(sha1: str) -> str:
    """Return the cache key that stores the sprite the wiki records under `sha1`.

    Keyed by content hash and not by URL. The module docstring explains why in
    full: the URL carries a cache-busting query string that changes on every
    re-upload for reasons that have nothing to do with the pixels, so a
    URL-keyed cache would re-download the whole sprite set on any unrelated
    wiki churn. A content key only ever changes when the content did.
    """
    if SHA1_PATTERN.fullmatch(sha1) is None:
        raise FetchError(f"{sha1!r} is not a 40-character lowercase sha1 digest.")
    return f"sprite/{sha1}"


def download_sprite(
    image: FileImage, *, cache: ContentCache, transport: Transport | None = None
) -> bytes:
    """Return the bytes of `image`, checked for being an image of the type it declares.

    Refuses `image.mime` outside `SPRITE_MIME_TYPES` before any request is
    made -- an SVG or a video the wiki catalogued under `spritefile` by mistake
    is not a shape this project's sprite atlas can use, and the refusal should
    name the file rather than the pixels of whatever the atlas builder made of
    it.

    Reads `cache.read(sprite_cache_key(image.sha1))` first. A hit does no I/O
    at all: `image.sha1` names one upstream revision of this file for all time,
    and the module docstring explains why that outlives the URL that produced
    it.

    On a miss, the transport fetches and the checks run inside the reader
    passed to `fetch_and_read`, the same place `pipeline.fetch.bucket` checks
    its page-length guard and for the same reason: a check made after
    `fetch_and_read` stores the payload would leave a bad body in the cache
    forever, and the only repair would be to delete `data/.cache` by hand.

    The checks are the file signature and `MAX_SPRITE_BYTES`. They are
    deliberately not a SHA-1 comparison and deliberately not a length
    comparison against `image.size`: Cloudflare Polish serves a recompressed
    derivative whose length and hash both differ from what `prop=imageinfo`
    reports, so either comparison rejects correct downloads in bulk -- 94 of
    200 on the run that found this. The module docstring carries the evidence.
    """
    if image.mime not in SPRITE_MIME_TYPES:
        accepted = ", ".join(sorted(SPRITE_MIME_TYPES))
        raise FetchError(
            f"{image.title} is a {image.mime!r} file, not one of the sprite types this project "
            f"reads: {accepted}."
        )
    key = sprite_cache_key(image.sha1)
    cached = cache.read(key)
    if cached is not None:
        return cached
    the_transport = get_bytes if transport is None else transport

    def read(payload: bytes) -> bytes:
        if len(payload) > MAX_SPRITE_BYTES:
            raise FetchError(
                f"{image.title} answered {len(payload)} bytes, over the {MAX_SPRITE_BYTES}-byte "
                f"limit for a sprite. This is not the small icon {image.title} names."
            )
        signatures = SPRITE_SIGNATURES[image.mime]
        if not payload.startswith(signatures):
            expected = " or ".join(repr(signature) for signature in signatures)
            raise FetchError(
                f"{image.title} answered {payload[:8]!r}, which does not begin a {image.mime} "
                f"file. A {image.mime} body begins {expected}, so this is not the image the "
                f"wiki named and it is never stored under it."
            )
        return payload

    return fetch_and_read(cache, image.url, transport=the_transport, read=read, key=key)


class SpriteDownloadReport(BaseModel, frozen=True):
    """What one batch of sprite downloads produced: the bytes, and the failures.

    A dictionary of bytes alone could not carry a failure, and CLAUDE.md's rule
    that an empty scrape is a failure to report applies here at the level of
    one file: `download_sprites` must not let one bad download -- a body that
    is not an image, an oversized body, a wrong MIME type -- abort a run of roughly
    3,200 files, so every failure is collected into `failed` and named by
    reason, mirroring `MissingImage`'s shape rather than inventing a new one.
    """

    images: dict[str, bytes]
    failed: tuple[MissingImage, ...] = ()


def download_sprites(
    images: Sequence[FileImage],
    *,
    cache: ContentCache,
    transport: Transport | None = None,
) -> SpriteDownloadReport:
    """Return the bytes of every image of `images`, and a report of what failed.

    A failure downloading one file is collected into the report rather than
    raised, for the reason `SpriteDownloadReport` explains in full: one bad
    file, such as a `File:` page that a redirect left pointing at something
    that is not an image, must not abort a run over the whole sprite set. A
    shape fault would already have stopped the build earlier, in
    `pipeline.fetch.imageinfo` or `pipeline.enrich.sprite`, so every exception
    this function catches is a `FetchError` that `download_sprite` raises about
    one specific file.
    """
    downloaded: dict[str, bytes] = {}
    failed: list[MissingImage] = []
    for image in images:
        try:
            downloaded[image.title] = download_sprite(image, cache=cache, transport=transport)
        except FetchError as error:
            failed.append(MissingImage(title=image.title, reason=str(error)))
    return SpriteDownloadReport(images=downloaded, failed=tuple(failed))
