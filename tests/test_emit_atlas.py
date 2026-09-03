"""`pipeline.emit.atlas`: decoding, shelf packing, and the hand-written PNG encoder.

Every fixture image here is built in the test process with Pillow, matching the way every other
test in this repository builds its own fixtures rather than reading a binary file from disk --
`tests/test_fetch_sprites.py`'s own module docstring states the same rule for sprite bytes one
stage earlier. No test in this file opens a socket or reads a file from disk.
"""

import io
import struct
import zlib

import pytest
from PIL import Image

from pipeline.emit import EmitError
from pipeline.emit.atlas import (
    DecodedSprite,
    SpriteFrame,
    collect_sprite_files,
    decode_sprite,
    encode_png,
    pack_atlas,
)
from pipeline.enrich.sprite import SpriteFile, SpriteIndex
from pipeline.normalize.entity import Entity, EntityKind


def _png_bytes(width: int, height: int, color: tuple[int, int, int, int]) -> bytes:
    """Return a real PNG, encoded by Pillow, of one flat colour."""
    image = Image.new("RGBA", (width, height), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _sprite(
    width: int, height: int, color: tuple[int, int, int, int] = (1, 2, 3, 4)
) -> DecodedSprite:
    """Return a `DecodedSprite` of one flat colour, without going through `decode_sprite`."""
    pixel = bytes(color)
    return DecodedSprite(width=width, height=height, rgba=pixel * (width * height))


# --- `decode_sprite` -----------------------------------------------------------


def test_a_plain_png_decodes_to_its_own_dimensions_and_pixels() -> None:
    payload = _png_bytes(3, 2, (10, 20, 30, 255))
    decoded = decode_sprite(payload, title="File:Flat.png")
    assert (decoded.width, decoded.height) == (3, 2)
    assert decoded.rgba == bytes((10, 20, 30, 255)) * 6


def test_a_palette_png_still_decodes_to_rgba() -> None:
    """The wiki serves palette PNGs alongside RGBA ones; both must come out the same shape."""
    image = Image.new("P", (2, 2))
    image.putpalette([0, 0, 0, 255, 255, 255] + [0] * (256 * 3 - 6))
    image.putpixel((0, 0), 1)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    decoded = decode_sprite(buffer.getvalue(), title="File:Palette.png")
    assert decoded.width == 2
    assert decoded.height == 2
    assert len(decoded.rgba) == 2 * 2 * 4


def test_a_multi_frame_gif_decodes_to_frame_zero() -> None:
    """The real case this guards: `File:Sculk JE1 BE1.gif` is a genuine animated icon."""
    first = Image.new("RGB", (4, 4), (255, 0, 0))
    second = Image.new("RGB", (4, 4), (0, 255, 0))
    buffer = io.BytesIO()
    first.save(buffer, format="GIF", save_all=True, append_images=[second])

    decoded = decode_sprite(buffer.getvalue(), title="File:Sculk JE1 BE1.gif")

    assert (decoded.width, decoded.height) == (4, 4)
    # Every pixel is opaque red, frame 0's colour -- not frame 1's green.
    assert decoded.rgba == bytes((255, 0, 0, 255)) * 16


def test_bytes_that_are_not_an_image_are_refused() -> None:
    with pytest.raises(EmitError, match="could not be decoded"):
        decode_sprite(b"not an image at all", title="File:Bad.png")


# --- `encode_png` --------------------------------------------------------------


def test_encode_png_round_trips_through_pillow() -> None:
    """The hand-written encoder must produce a real, standards-shaped PNG."""
    width, height = 3, 2
    pixels = bytes(
        channel
        for pixel_index in range(width * height)
        for channel in (pixel_index * 10 % 256, pixel_index * 20 % 256, pixel_index * 30 % 256, 255)
    )

    png = encode_png(pixels, width=width, height=height)

    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    decoded = Image.open(io.BytesIO(png)).convert("RGBA")
    assert (decoded.width, decoded.height) == (width, height)
    assert decoded.tobytes() == pixels


def _png_chunks(png: bytes) -> dict[bytes, bytes]:
    """Return every top-level chunk of `png`, by its 4-byte type, walking length-prefixed chunks."""
    chunks: dict[bytes, bytes] = {}
    offset = 8  # past the fixed 8-byte signature
    while offset < len(png):
        (length,) = struct.unpack(">I", png[offset : offset + 4])
        chunk_type = png[offset + 4 : offset + 8]
        data = png[offset + 8 : offset + 8 + length]
        chunks[chunk_type] = data
        offset += 4 + 4 + length + 4  # length + type + data + crc
    return chunks


def test_encode_png_writes_colour_type_six_and_filter_none_every_row() -> None:
    """Pin the exact IHDR fields and the per-row filter byte, not only that Pillow can read it
    back -- a round trip alone would not catch a colour type or bit depth this module did not
    intend.
    """
    width, height = 2, 2
    pixels = bytes(range(width * height * 4))
    png = encode_png(pixels, width=width, height=height)

    chunks = _png_chunks(png)
    stored_width, stored_height, bit_depth, colour_type = struct.unpack(
        ">IIBB", chunks[b"IHDR"][:10]
    )
    assert (stored_width, stored_height, bit_depth, colour_type) == (width, height, 8, 6)

    # Decompress the one IDAT chunk and check every row's leading filter byte is 0.
    raw = zlib.decompress(chunks[b"IDAT"])
    row_stride = 1 + width * 4
    for row in range(height):
        assert raw[row * row_stride] == 0


def test_encode_png_refuses_a_pixel_count_that_does_not_match_the_dimensions() -> None:
    with pytest.raises(EmitError, match="needs exactly"):
        encode_png(b"\x00" * 3, width=2, height=2)


def test_encode_png_refuses_non_positive_dimensions() -> None:
    with pytest.raises(EmitError, match="cannot write"):
        encode_png(b"", width=0, height=1)


# --- `pack_atlas` ----------------------------------------------------------------


def test_an_empty_sprite_set_is_refused() -> None:
    with pytest.raises(EmitError, match="no sprites"):
        pack_atlas({}, {})


def test_a_sprite_wider_than_the_atlas_is_refused() -> None:
    sprites = {"File:Wide.png": _sprite(20, 4)}
    with pytest.raises(EmitError, match="wider than"):
        pack_atlas(sprites, {"Family:wide": "File:Wide.png"}, width=10)


def test_shelf_geometry_places_frames_and_starts_a_new_row_when_the_current_one_fills() -> None:
    sprites = {
        "A.png": _sprite(6, 4),
        "B.png": _sprite(5, 4),
        "C.png": _sprite(5, 2),
    }
    keys = {"Fam:a": "A.png", "Fam:b": "B.png", "Fam:c": "C.png"}

    atlas = pack_atlas(sprites, keys, width=10)

    assert atlas.coordinates.width == 10
    assert atlas.coordinates.height == 8  # two shelves of height 4 each
    assert atlas.coordinates.sprites["Fam:a"] == SpriteFrame(x=0, y=0, w=6, h=4)
    # B does not fit beside A (6 + 5 > 10), so it starts a new shelf at y=4.
    assert atlas.coordinates.sprites["Fam:b"] == SpriteFrame(x=0, y=4, w=5, h=4)
    # C fits beside B on the same shelf (5 + 5 == 10).
    assert atlas.coordinates.sprites["Fam:c"] == SpriteFrame(x=5, y=4, w=5, h=2)
    assert atlas.frame_count == 3


def test_the_packed_canvas_actually_holds_each_sprites_own_pixels() -> None:
    """Geometry alone does not prove the pixels landed where the map says they did."""
    sprites = {
        "A.png": _sprite(2, 2, color=(255, 0, 0, 255)),
        "B.png": _sprite(2, 2, color=(0, 255, 0, 255)),
    }
    keys = {"Fam:a": "A.png", "Fam:b": "B.png"}

    atlas = pack_atlas(sprites, keys, width=4)

    image = Image.open(io.BytesIO(atlas.png)).convert("RGBA")
    frame_a = atlas.coordinates.sprites["Fam:a"]
    frame_b = atlas.coordinates.sprites["Fam:b"]
    assert image.getpixel((frame_a.x, frame_a.y)) == (255, 0, 0, 255)
    assert image.getpixel((frame_b.x, frame_b.y)) == (0, 255, 0, 255)


def test_two_icon_keys_sharing_one_file_produce_one_frame_and_two_map_entries() -> None:
    sprites = {"File:Sculk.png": _sprite(4, 4)}
    keys = {"BlockSprite:sculk": "File:Sculk.png", "InvSprite:Sculk Block": "File:Sculk.png"}

    atlas = pack_atlas(sprites, keys, width=10)

    assert atlas.frame_count == 1
    assert len(atlas.coordinates.sprites) == 2
    assert (
        atlas.coordinates.sprites["BlockSprite:sculk"]
        == atlas.coordinates.sprites["InvSprite:Sculk Block"]
    )


def test_a_keys_entry_naming_an_unpacked_file_is_refused() -> None:
    sprites = {"File:A.png": _sprite(2, 2)}
    with pytest.raises(EmitError, match="not among the sprites"):
        pack_atlas(sprites, {"Fam:missing": "File:Does Not Exist.png"})


def test_pack_atlas_is_deterministic_across_two_calls_over_identical_input() -> None:
    sprites = {
        "Delta.png": _sprite(4, 4, color=(4, 4, 4, 255)),
        "Alpha.png": _sprite(4, 4, color=(1, 1, 1, 255)),
        "Charlie.png": _sprite(3, 5, color=(3, 3, 3, 255)),
        "Bravo.png": _sprite(4, 3, color=(2, 2, 2, 255)),
    }
    keys = {
        "Fam:delta": "Delta.png",
        "Fam:alpha": "Alpha.png",
        "Fam:charlie": "Charlie.png",
        "Fam:bravo": "Bravo.png",
    }

    first = pack_atlas(sprites, keys, width=10)
    # A fresh dict, keys inserted in a different order, to prove the result does not depend on
    # dictionary iteration order surviving from one call to the next.
    second = pack_atlas(dict(reversed(sprites.items())), dict(reversed(keys.items())), width=10)

    assert first.png == second.png
    assert first.coordinates == second.coordinates


# --- `collect_sprite_files` -----------------------------------------------------


def _entity(entity_id: str, icon: str | None) -> Entity:
    return Entity(
        id=entity_id,
        kind=EntityKind.ITEM,
        name=entity_id.split(":", 1)[-1],
        aliases=(),
        icon=icon,
        source_tiers={},
        sections=(),
    )


def test_collect_sprite_files_resolves_icons_and_reports_gaps() -> None:
    index = SpriteIndex.build(
        [
            SpriteFile(
                family="InvSprite", sprite_id="Raw Iron", file_title="File:Invicon Raw Iron.png",
                page="Raw Iron",
            ),
        ]
    )
    entities = (
        _entity("minecraft:raw_iron", "InvSprite:Raw Iron"),
        _entity("minecraft:no_icon", None),
        _entity("minecraft:ghost", "InvSprite:Nothing Here"),
    )

    selection = collect_sprite_files(entities, index)

    assert selection.file_titles == ("File:Invicon Raw Iron.png",)
    assert selection.icon_to_file == {"InvSprite:Raw Iron": "File:Invicon Raw Iron.png"}
    assert selection.unresolved_icons == ("InvSprite:Nothing Here",)


def test_collect_sprite_files_over_no_entities_returns_an_empty_selection() -> None:
    index = SpriteIndex.build([])
    selection = collect_sprite_files((), index)
    assert selection.file_titles == ()
    assert selection.icon_to_file == {}
    assert selection.unresolved_icons == ()
