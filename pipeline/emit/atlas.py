"""Pack every sprite this build needs into one PNG, plus the JSON map that finds a sprite in it.

`pipeline.enrich.sprite.SpriteIndex` names which `File:` page holds each icon a build's entities
point at, and `pipeline.fetch.imageinfo`/`pipeline.fetch.sprites` turn a `File:` title into bytes.
Neither of those stops shipping data/dist as roughly 1,900 separate PNG requests -- one per
`Entity.icon` -- which is the exact thing `TODO.md`'s Phase 3 bullet names as a problem twice
over: Cloudflare's free plan caps a site at 20,000 files, and 1,900 requests to open one window is
not a "under two seconds" experience even before the cap ever binds. This module is the fix: it is
pure computation over bytes already sitting in memory, no network and no filesystem, so it can be
tested the same way `pipeline.emit.search_index` and `pipeline.emit.obtain` already are, over
fixtures built in the test process alone.

Three things happen here, in order, and each one earns its own section: decoding a sprite's bytes
to plain pixels (`decode_sprite`), deciding where every sprite's pixels land on one shared canvas
(`pack_atlas`'s shelf algorithm), and turning that canvas into PNG bytes (`encode_png`). A fourth
function, `collect_sprite_files`, is not part of the packing pipeline at all -- it is the pure
lookup `pipeline.cli.build.run_build` needs to turn a build's entities into the `File:` titles a
fetch stage should ask for, kept here because it reads the same `SpriteFile`/`SpriteIndex` shapes
this module already imports for the packer's own book-keeping.

## Decoding: Pillow in, and only in, one direction

`pyproject.toml` explains why Pillow is a runtime dependency for decoding: the wiki serves
palette, greyscale, RGB, and RGBA PNGs, and at least one real animated GIF (`File:Sculk JE1
BE1.gif`, which `pipeline.fetch.sprites`'s own module docstring names as a deliberate icon, not a
mistake upstream made). Writing a decoder for that whole matrix by hand would be a large amount of
subtle code to maintain for a problem a mature library already solves correctly. `decode_sprite`
converts every input to 8-bit RGBA regardless of its source mode, so the packer downstream never
has to branch on what kind of file a sprite arrived as -- every `DecodedSprite` is the same shape:
a width, a height, and `width * height * 4` bytes of interleaved RGBA, row-major, top row first.

A multi-frame GIF decodes to its first frame alone. `Image.open` already positions a newly opened
file at frame 0 without reading any later frame, so this is not an extra step this module adds; it
is the one frame this module ever asks Pillow to read. The choice itself is not a shortcut: one
atlas cell holds one still image, so a still frame is the only representation the shelf packer
below could place at all, and frame 0 is the only frame a caller can select with no per-file
judgement call about which frame "is" the icon.

## Packing: a shelf algorithm, deterministic by construction

`pack_atlas` places every distinct `File:` frame once -- `collect_sprite_files` and the caller
that drives this module together make sure of that, because several icon keys can share one file
(the `Sculk Block` alias `pipeline.enrich.sprite`'s own module docstring names is a live example),
and packing the same pixels twice would only grow the PNG for no reason.

Frames are placed in a fixed order: sorted by `(-height, -width, key)`, where `key` is the frame's
own dictionary key (the `File:` title). That is a total order over the input -- no two distinct
keys ever tie on all three components at once -- so two calls over identical input place every
sprite at the identical pixel, every time. This is not a nicety. `data/dist` is committed to the
repository, and Rule 1 of `pipeline.emit.write`'s own module docstring requires that rebuilding
from unchanged input leaves an empty `git diff`; a packer whose placement depended on dictionary
iteration order or on `sorted()`'s stability alone (true today, not guaranteed by this module's
own contract) would break that guarantee the first time two frames happened to tie on height and
width.

Placement itself is a shelf: sprites are laid left to right along one row (`shelf_y`, a fixed
height equal to the row's tallest member) until the next sprite would not fit the remaining width,
at which point a new row starts immediately below the last one. The finished canvas height is the
exact sum of every row's height -- no padding between sprites, no padding between rows, and no
rounding up to a power of two. Two reasons, and both are load-bearing rather than cosmetic. First,
the web app samples this atlas with CSS `image-rendering: pixelated` and never scales between
texels -- `TODO.md`'s Phase 8 bullet names the same rule for the renderer this feeds -- so there
is no bleed for a gutter to guard against: a renderer that draws exactly the source rectangle at
1:1 or an integer multiple never reads one pixel past the edge `pack_atlas` recorded. Second, this
is a plain PNG served over HTTP and read by an `<img>`/canvas, never a GPU texture bound for
sampling, so nothing downstream needs a power-of-two dimension; rounding up would only add empty
pixels to compress and download for no reader that cares.

A sprite wider than the atlas raises `EmitError` rather than being clipped or wrapped: this module
would otherwise have to choose between shipping a partial icon (silently wrong) or growing the
atlas width to fit one outlier (which would slim every other row's packing efficiency for one
sprite's sake). A build with no sprites at all raises `EmitError` too, for the same reason
`pipeline.normalize.merge` refuses an empty `MergeResult` and `pipeline.emit.shard` refuses a
`shard_size` below 1: an empty result here would silently produce a zero-byte atlas that no icon
could ever resolve against, which is a build that looks like it succeeded and did not.

`ATLAS_WIDTH` (512) is not a GPU-texture convention creeping in through habit -- see the
constant's own comment for the arithmetic that picked it.

## Encoding: a hand-written PNG writer, not `Image.save`

`encode_png` writes the finished canvas as an 8-bit RGBA (PNG colour type 6), non-interlaced,
single-`IDAT` PNG by hand: the 8-byte signature, one `IHDR`, one `IDAT` holding
`zlib.compress(raw, 9)`, and `IEND`, each chunk framed as length + type + data + a CRC32 over the
type and data together. This is deliberate, and it is the opposite bias from the decoding section
above. `data/dist/sprites.png` is committed to Git. `Image.save(..., format="PNG")` picks its own
per-row filter through an internal heuristic (Pillow's PNG encoder tries several filter types per
row and keeps whichever compresses smallest), a heuristic this project does not control and does
not pin -- a Pillow *version* upgrade could change which filter it picks for a row whose pixels
did not change at all, rewriting every byte of a committed binary and producing a diff on a
release pull request that has nothing to do with any Minecraft version change. Writing the encoder
here keeps Rule 1's determinism guarantee owned by this repository's own code, the same way
`pipeline.emit.write._encode` owns JSON's determinism with `sort_keys=True` rather than trusting
whatever a JSON library's default key order happens to be.

Every row is written under filter type 0 (`None`) for the identical reason: it is the one PNG
filter whose output is pixels copied verbatim, with no per-row choice at all for a future version
of anything to make differently. Pixel art such as this atlas -- large flat runs of identical or
near-identical bytes -- still compresses well under plain deflate with no filtering; the filter
types PNG offers beyond `None` exist to help photographic gradients, which nothing in this atlas
contains.
"""

import io
import struct
import zlib
from collections.abc import Mapping, Sequence

from PIL import Image
from pydantic import BaseModel, Field

from pipeline.emit import EmitError
from pipeline.enrich.sprite import SpriteIndex
from pipeline.normalize.entity import Entity

__all__ = [
    "ATLAS_IMAGE_NAME",
    "ATLAS_SCHEMA_VERSION",
    "ATLAS_WIDTH",
    "PNG_COLOR_TYPE_RGBA",
    "Atlas",
    "AtlasMap",
    "DecodedSprite",
    "SpriteFrame",
    "SpriteSelection",
    "collect_sprite_files",
    "decode_sprite",
    "encode_png",
    "pack_atlas",
]

# The constant `atlas.schema.json`'s `schemaVersion` pins, matching every other payload's own
# per-file version number -- see `pipeline.emit.search_index`'s own docstring for why the four
# (now five) payloads each version their own contract instead of sharing one number.
ATLAS_SCHEMA_VERSION = 1

# The name `pipeline.emit.write` writes the packed PNG under, and the value `pack_atlas` stamps
# into `AtlasMap.image` so the coordinate map names the exact file it describes. One constant
# rather than two matching string literals: `pipeline.emit.write` imports this name instead of
# writing `"sprites.png"` a second time, the same "one place owns the fact" rule
# `pipeline.emit.shard`'s own D2 section states for a shard's file name.
ATLAS_IMAGE_NAME = "sprites.png"

# The atlas canvas width. Not a GPU texture, so no power-of-two requirement binds it here -- the
# web app draws every sprite through a plain CSS `background-position`/`<canvas>` read against
# `image-rendering: pixelated`, never as a texture bound for GPU sampling, so nothing downstream
# cares whether this number is a power of two. It is chosen for the shelf packer's own arithmetic
# instead. Decision 3 of `TODO.md` records the two sizes measured live on the wiki: item icons are
# `Invicon <Name>.png` at 16x16, and effect/biome icons run 18x18. Those two sizes cover the large
# majority of this project's roughly 1,900 distinct icon keys (`InvSprite`, `ItemSprite`, and
# `BlockSprite` alone are 1,509 + 32 + 141 of them). 512 divides evenly into 32 icons of 16px, or
# close to 28 of 18px, per shelf row: wide enough that one row holds several dozen icons rather
# than spending most of its height on right-edge slack from a narrow canvas, narrow enough that the
# finished PNG stays compact rather than a wide, mostly-empty strip.
ATLAS_WIDTH = 512

# PNG's own colour type number for 8-bit truecolour with alpha. Named rather than written as a bare
# `6` in `encode_png`'s `IHDR`, so a reader of that call does not have to open the PNG specification
# to know what the literal means.
PNG_COLOR_TYPE_RGBA = 6

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_BIT_DEPTH = 8
_PNG_FILTER_NONE = 0


class DecodedSprite(BaseModel, frozen=True):
    """One sprite's pixels, decoded to 8-bit RGBA: a width, a height, and the raw bytes.

    `rgba` is always exactly `width * height * 4` bytes, interleaved red, green, blue, alpha per
    pixel, row-major with the top row first -- the same layout `Image.tobytes()` gives an `"RGBA"`
    mode image, and the same layout `encode_png` expects its own `pixels` argument in.
    """

    width: int = Field(gt=0)
    height: int = Field(gt=0)
    rgba: bytes


class SpriteFrame(BaseModel, frozen=True):
    """One sprite's rectangle within the packed atlas, in pixels."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(gt=0)
    h: int = Field(gt=0)


class AtlasMap(BaseModel, frozen=True, populate_by_name=True):
    """The whole `sprites.json` payload, mirroring `atlas.schema.json`.

    `sprites` is keyed by the icon key `Entity.icon` already carries (`"InvSprite:raw-iron"`), not
    by the `File:` title the pixels actually came from -- so the web app looks up an entity's own
    `icon` field directly, with no second join through `pipeline.enrich.sprite.SpriteIndex` at
    render time. Several icon keys may point at the identical rectangle, the same `File:` alias
    `pack_atlas`'s own docstring names.
    """

    schema_version: int = Field(default=ATLAS_SCHEMA_VERSION, alias="schemaVersion")
    image: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    sprites: Mapping[str, SpriteFrame]


class Atlas(BaseModel, frozen=True):
    """What one `pack_atlas` call produced: the finished PNG bytes, and the map that reads them.

    `frame_count` is the number of distinct `File:` frames actually placed on the canvas -- the
    length of `pack_atlas`'s own `sprites` argument -- which is usually smaller than
    `len(coordinates.sprites)`, the number of icon keys the map resolves, because more than one icon
    key can point at one packed frame.
    """

    png: bytes
    coordinates: AtlasMap
    frame_count: int = Field(ge=0)


class SpriteSelection(BaseModel, frozen=True):
    """Which `File:` titles one build's entities need, and which icon keys could not be resolved.

    Built by `collect_sprite_files`, purely from a build's entities and the same `SpriteIndex` the
    normalize stage already resolved every `Entity.icon` against. `file_titles` is what a fetch
    stage batches a read of; `icon_to_file` is what `pack_atlas` needs as its own `keys` argument,
    once every title of `file_titles` has been downloaded and decoded.
    """

    file_titles: tuple[str, ...]
    icon_to_file: Mapping[str, str]
    # Every `Entity.icon` whose `family:sprite_id` no longer resolves against `sprite_index` --
    # reported, not raised, matching `pipeline.normalize.merge`'s own missing-icon accounting: a
    # gap here is a build-time fact worth a report line, not a shape fault. In practice this stays
    # empty for a real build, because every `icon` reaching this function was set by
    # `pipeline.normalize.merge._resolve_entity_icon` from a lookup against this identical index;
    # it exists for the same reason `pipeline.normalize.reconcile` still reports a route it
    # expects to find nothing on -- a defended fact costs nothing and a silent one costs a
    # debugging session.
    unresolved_icons: tuple[str, ...]


def decode_sprite(payload: bytes, *, title: str) -> DecodedSprite:
    """Decode `payload` (an already-downloaded sprite file's bytes) to 8-bit RGBA, and return it.

    `title` names the `File:` page `payload` came from, for the one message this function can
    raise: `payload` failing to decode as an image at all, which `pipeline.fetch.sprites`'s own
    signature check already makes rare by the time bytes reach here, but not impossible -- a
    signature check proves the first few bytes are right, not that the whole body parses.

    See the module docstring's decoding section for why every source mode converts to RGBA
    uniformly, and why a multi-frame image decodes to its first frame alone.
    """
    try:
        source = Image.open(io.BytesIO(payload))
        converted = source.convert("RGBA")
    except (OSError, ValueError) as error:
        raise EmitError(f"{title} could not be decoded as an image: {error}") from error
    if converted.width <= 0 or converted.height <= 0:
        raise EmitError(
            f"{title} decoded to a {converted.width}x{converted.height} image, which an atlas "
            f"cannot place. This is a decode fault, not a real sprite."
        )
    return DecodedSprite(width=converted.width, height=converted.height, rgba=converted.tobytes())


def _chunk(chunk_type: bytes, data: bytes) -> bytes:
    """Return one length-prefixed, CRC-suffixed PNG chunk of `chunk_type` holding `data`."""
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data))
    )


def encode_png(pixels: bytes, *, width: int, height: int) -> bytes:
    """Return `pixels` (interleaved RGBA, row-major, top row first) as PNG bytes.

    See the module docstring's encoding section for why this is written by hand rather than
    through `Image.save`, and for why every row is written under filter type 0.

    Raises `EmitError` for a non-positive `width`/`height`, or for a `pixels` length that does not
    equal `width * height * 4` -- a caller error this function catches rather than one that would
    otherwise produce a PNG whose `IHDR` lies about its own pixel count.
    """
    if width <= 0 or height <= 0:
        raise EmitError(f"encode_png cannot write a {width}x{height} image.")
    expected = width * height * 4
    if len(pixels) != expected:
        raise EmitError(
            f"encode_png was given {len(pixels)} bytes for a {width}x{height} RGBA image, which "
            f"needs exactly {expected}."
        )

    row_stride = width * 4
    raw = bytearray()
    for row in range(height):
        raw.append(_PNG_FILTER_NONE)
        start = row * row_stride
        raw.extend(pixels[start : start + row_stride])

    ihdr = struct.pack(
        ">IIBBBBB", width, height, _PNG_BIT_DEPTH, PNG_COLOR_TYPE_RGBA, 0, 0, 0
    )
    idat = zlib.compress(bytes(raw), 9)
    return _PNG_SIGNATURE + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def pack_atlas(
    sprites: Mapping[str, DecodedSprite],
    keys: Mapping[str, str],
    *,
    width: int = ATLAS_WIDTH,
) -> Atlas:
    """Pack every frame of `sprites` onto one canvas, and return the finished `Atlas`.

    `sprites` is keyed by `File:` title, one entry per distinct frame this build downloaded and
    decoded. `keys` is the icon-key-to-file-title mapping `SpriteSelection.icon_to_file` already
    carries; every value of `keys` must name a key already present in `sprites`, because this
    function packs pixels and does not itself resolve a missing download -- a caller drops an icon
    key from `keys` (and reports the gap, per the module docstring's per-file philosophy) before
    ever reaching this call, rather than this function inventing a placeholder for it.

    See the module docstring's packing section for the shelf algorithm, the sort order that makes
    it deterministic, and the two conditions -- an empty `sprites`, or a frame wider than `width` --
    that raise `EmitError`.
    """
    if not sprites:
        raise EmitError(
            "pack_atlas was given no sprites to pack. An empty sprite set is a failed fetch, not "
            "a version of Minecraft with no icons."
        )

    ordered = sorted(
        sprites.items(), key=lambda entry: (-entry[1].height, -entry[1].width, entry[0])
    )

    placements: dict[str, SpriteFrame] = {}
    shelf_x = 0
    shelf_y = 0
    shelf_height = 0
    for title, sprite in ordered:
        if sprite.width > width:
            raise EmitError(
                f"{title} is {sprite.width}px wide, wider than the {width}px atlas. Clipping it "
                f"would ship a wrong icon rather than a missing one, so this build is refused "
                f"instead."
            )
        if shelf_x + sprite.width > width:
            shelf_y += shelf_height
            shelf_x = 0
            shelf_height = 0
        placements[title] = SpriteFrame(x=shelf_x, y=shelf_y, w=sprite.width, h=sprite.height)
        shelf_x += sprite.width
        shelf_height = max(shelf_height, sprite.height)
    total_height = shelf_y + shelf_height

    canvas = bytearray(width * total_height * 4)
    for title, sprite in ordered:
        frame = placements[title]
        row_stride = sprite.width * 4
        for row in range(sprite.height):
            src_start = row * row_stride
            dst_start = ((frame.y + row) * width + frame.x) * 4
            canvas[dst_start : dst_start + row_stride] = sprite.rgba[
                src_start : src_start + row_stride
            ]

    png = encode_png(bytes(canvas), width=width, height=total_height)

    sprite_map: dict[str, SpriteFrame] = {}
    for icon_key, file_title in keys.items():
        resolved = placements.get(file_title)
        if resolved is None:
            raise EmitError(
                f"pack_atlas's keys names {icon_key!r} -> {file_title!r}, but {file_title!r} was "
                f"not among the sprites this call packed."
            )
        sprite_map[icon_key] = resolved

    coordinates = AtlasMap(
        image=ATLAS_IMAGE_NAME, width=width, height=total_height, sprites=sprite_map
    )
    return Atlas(png=png, coordinates=coordinates, frame_count=len(ordered))


def collect_sprite_files(
    entities: Sequence[Entity],
    sprite_index: SpriteIndex,
    extra_icons: Mapping[str, str] | None = None,
) -> SpriteSelection:
    """Return the `File:` titles, and the icon-key-to-file mapping, one build's entities need.

    Pure: reads `entity.icon` and looks each one up in `sprite_index`, the same index
    `pipeline.normalize.merge` already resolved every icon against. An entity with no icon at all
    (219 of the real 26.2 build) contributes nothing here, matching that stage's own decision that
    an absent icon is not this pipeline's fault to raise over.

    `extra_icons` is `CuratedData.hud_sprites`: icon keys that belong to no entity and that the
    `spritefile` bucket does not carry, so they cannot be looked up in `sprite_index` at all. The
    hunger shanks the food section draws are the whole of it today. They are already `File:`
    titles a person verified, which is why they join `icon_to_file` directly rather than through
    a lookup, and why one that is wrong shows up as a download failure naming the title rather
    than as an `unresolved_icons` entry naming a key no index was ever asked about.

    See `SpriteSelection`'s own docstring for why an icon key that no longer resolves is reported
    in `unresolved_icons` rather than raised.
    """
    icon_to_file: dict[str, str] = dict(extra_icons or {})
    unresolved: list[str] = []
    for entity in entities:
        icon = entity.icon
        if icon is None:
            continue
        if icon in icon_to_file:
            # Already resolved, so there is nothing to look up. For a second entity
            # carrying an icon a previous one resolved, skipping only saves a repeated
            # lookup that would write back the same answer.
            #
            # For an `extra_icons` key it is a correctness fix. Those arrive as verified
            # `File:` titles precisely because the `spritefile` bucket cannot answer for
            # the family at all, so looking one up reports it in `unresolved_icons` while
            # it sits in the atlas -- a permanent phantom entry in the build's own failure
            # count. No entity references one today. The Food collection did for one
            # commit, which is how this surfaced, and it now borrows a 16x16 item icon
            # instead for reasons of size rather than resolution.
            continue
        family, separator, sprite_id = icon.partition(":")
        sprite = sprite_index.lookup(family, sprite_id) if separator else None
        if sprite is None:
            unresolved.append(icon)
            continue
        icon_to_file[icon] = sprite.file_title

    file_titles = tuple(sorted(set(icon_to_file.values())))
    return SpriteSelection(
        file_titles=file_titles,
        icon_to_file=icon_to_file,
        unresolved_icons=tuple(sorted(set(unresolved))),
    )
