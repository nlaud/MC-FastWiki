"""`run_build`: a whole build over a fake transport, plus `--offline`'s two faults.

No test in this module opens a socket. `_build_fixtures` answers exactly the
URLs one small, hand-built Minecraft version needs -- one mob (`Creeper`, with
a spawn egg so it classifies as `SPAWN_EGG`), one advancement (`story/root`),
and every Tier B bucket a build reads, most of them empty on purpose.
`_fake_transport` raises loudly for any URL this module did not anticipate,
so a wiring mistake in `run_build` fails here with a message naming the
missing URL rather than surfacing three stages later as a `NormalizeError`
about an empty index.

`load_curated` is not something a caller of `run_build` can redirect --
`pipeline.cli.build.CURATED_DIRECTORY` is a literal `Path("data") /
"curated"`, per the task this module was written against -- so every test
here that reaches the normalize stage targets Minecraft version `26.2`, the
version this repository's own `data/curated/*.json` files carry as their
`verifiedFor`. That is a real coupling to the repository's own committed
content, not a network read: `load_curated` touches no socket, and the
version is chosen to keep that coupling exact rather than merely close.
"""

import gzip
import io
import json
import tarfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from pipeline.cli import CliError
from pipeline.cli.build import CURATED_DIRECTORY, BuildOptions, run_build
from pipeline.enrich.advancement import COLUMNS as ADVANCEMENT_COLUMNS
from pipeline.enrich.droptable import COLUMNS as DROPTABLE_COLUMNS
from pipeline.enrich.effect import EFFECT_PAGE_TITLES
from pipeline.enrich.resource_location import COLUMNS as RESOURCE_LOCATION_COLUMNS
from pipeline.enrich.spawn_table import COLUMNS as SPAWN_TABLE_COLUMNS
from pipeline.enrich.sprite import COLUMNS as SPRITE_COLUMNS
from pipeline.enrich.trade import COLUMNS as TRADE_COLUMNS
from pipeline.fetch import FetchError, Transport
from pipeline.fetch.bucket import PAGE_SIZE, BucketQuery
from pipeline.fetch.cache import ContentCache
from pipeline.fetch.extracts import build_extracts_url
from pipeline.fetch.imageinfo import build_imageinfo_url
from pipeline.fetch.mcmeta import GITHUB_REF_URL, MCMETA_ARCHIVE_URL, MCMETA_REPOSITORY
from pipeline.fetch.version_manifest import VERSION_MANIFEST_URL
from pipeline.fetch.wikitext import build_wikitext_url
from pipeline.validate import ValidationError

VERSION = "26.2"
SUMMARY_SHA = "a" * 40
DATA_SHA = "b" * 40
SUMMARY_TAG = f"{VERSION}-summary"
DATA_TAG = f"{VERSION}-data"

BUILT_AT = datetime(2026, 9, 1, tzinfo=UTC)

# The Creeper sprite the sprite-atlas stage downloads and decodes. `sha1` only has to be a
# well-formed 40-character digest -- it is a cache key, never verified against the bytes, per
# `pipeline.fetch.sprites`'s own Cloudflare Polish section -- so a fixed digest is as good as a
# real one here.
CREEPER_SPRITE_SHA1 = "c" * 40
CREEPER_SPRITE_URL = "https://minecraft.wiki/images/Creeper.png?d47d8"


# The `File:` titles `data/curated/hud-sprites.json` names. Read from the
# curated file itself rather than repeated here, so adding a fifth HUD icon
# does not silently leave this fixture one short.
HUD_SPRITE_TITLES = tuple(
    json.loads(
        (CURATED_DIRECTORY / "hud-sprites.json").read_text(encoding="utf-8")
    )["icons"].values()
)


def _sprite_url(file_title: str) -> str:
    """Return the fixture image URL of one `File:` title."""
    if file_title == "File:Creeper.png":
        return CREEPER_SPRITE_URL
    slug = file_title.removeprefix("File:").replace(" ", "_")
    return f"https://minecraft.wiki/images/{slug}?d47d8"


def _creeper_sprite_png() -> bytes:
    """Return a small, real PNG, encoded by Pillow -- the sprite-atlas stage decodes this."""
    image = Image.new("RGBA", (2, 2), (0, 200, 0, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _tar_gz(members: Mapping[str, bytes], *, root: str) -> bytes:
    """Return one gzip archive shaped like `codeload.github.com`'s commit archive.

    Built with `mtime=0`, matching `tests/test_mcmeta.py`'s own archive
    helper, so two calls over identical content return identical bytes.
    """
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as archive:
        directory = tarfile.TarInfo(root)
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)
        for name, body in members.items():
            info = tarfile.TarInfo(f"{root}/{name}")
            info.type = tarfile.REGTYPE
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
    gzip_buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=gzip_buffer, mode="wb", mtime=0) as compressed:
        compressed.write(tar_buffer.getvalue())
    return gzip_buffer.getvalue()


def _bucket_url(
    bucket: str, select: tuple[str, ...], *, where: tuple[tuple[str, ...], ...] = ()
) -> str:
    """Return the exact URL `fetch_bucket_rows` builds for one whole-table page."""
    return BucketQuery(bucket=bucket, select=select, where=where, limit=PAGE_SIZE, offset=0).url()


def _bucket_answer(rows: list[dict[str, str]]) -> bytes:
    return json.dumps({"bucketQuery": "test", "bucket": rows}).encode("utf-8")


# A small, structurally valid stand-in for the real `Brewing` page's
# wikitext -- enough rows to clear `BrewingIndex`'s own too-short guard (10
# effect recipes, 3 base recipes), in the real section headings and cell
# shapes `pipeline.enrich.brewing` reads, but with no rowspan and no mixed
# editions: `tests/test_enrich_brewing.py` exercises those two traps
# directly against hand-built wikitext, so this fixture only has to prove
# the wiring from `run_build` down to a working `BrewingIndex`, not the
# parser's own edge cases a second time.
_BREWING_WIKITEXT = """
=== Effect ingredients ===
{| class="wikitable"
|-
! Name
! Icon
! Effect
! Effect when corrupted
|-
!{{anchor|Sugar}}[[Sugar]]
|{{Slot|Sugar}}
|[[Speed]]
|None
|-
!{{anchor|Rabbit's Foot}}[[Rabbit's Foot]]
|{{Slot|Rabbit's Foot}}
|[[Jump Boost]]
|None
|-
!{{anchor|Glistering Melon Slice}}[[Glistering Melon Slice]]
|{{Slot|Glistering Melon Slice}}
|[[Instant Health]]
|None
|-
!{{anchor|Spider Eye}}[[Spider Eye]]
|{{Slot|Spider Eye}}
|[[Poison]]
|None
|-
!{{anchor|Blaze Powder}}[[Blaze Powder]]
|{{Slot|Blaze Powder}}
|[[Strength]]
|None
|-
!{{anchor|Golden Carrot}}[[Golden Carrot]]
|{{Slot|Golden Carrot}}
|[[Night Vision]]
|None
|-
!{{anchor|Ghast Tear}}[[Ghast Tear]]
|{{Slot|Ghast Tear}}
|[[Regeneration]]
|None
|-
!{{anchor|Pufferfish}}[[Pufferfish (item)|Pufferfish]]
|{{Slot|Pufferfish}}
|[[Water Breathing]]
|None
|-
!{{anchor|Magma Cream}}[[Magma Cream]]
|{{Slot|Magma Cream}}
|[[Fire Resistance]]
|None
|-
!{{anchor|Turtle Shell}}[[Turtle Shell]]
|{{Slot|Turtle Shell}}
|[[Slowness]] + [[Resistance]]
|None
|-
!{{anchor|Fermented Spider Eye}}[[Fermented spider eye|Fermented Spider Eye]]
|{{Slot|Fermented Spider Eye}}
|[[Weakness]]
|None
|}

== Brewing recipes ==
=== Base potions ===
{| class="wikitable"
|-
! Potion
! Recipe(s)
! Precursor to
|-
!{{Inventory slot|Awkward Potion}}<br>Awkward potion
|{{Brewing Stand
 |Input= Nether Wart
 |Output2= Water Bottle
 }}
| Effect potions
|-
!{{Inventory slot|Mundane Potion}}<br>Mundane potion
|{{Brewing Stand
 |Input= Redstone Dust
 |Output2= Water Bottle
 }}
| None
|-
!{{Inventory slot|Thick Potion}}<br>Thick potion
|{{Brewing Stand
 |Input= Glowstone Dust
 |Output2= Water Bottle
 }}
| None
|}

==== Enhancement ====
Redstone extends, glowstone enhances.

==== Splash and lingering potions ====
By adding gunpowder, a drinking potion becomes a splash potion. Adding
dragon's breath to a splash potion makes a lingering potion.

=== Un-brewable potions ===
The ''[[uncraftable potion]]'' and ''[[potion of Luck]]{{only|java|short=JE}}'' cannot be brewed.
"""


def _build_fixtures() -> dict[str, bytes]:
    """Return every URL this test's small build reads, mapped to its canned answer."""
    fixtures: dict[str, bytes] = {}

    fixtures[VERSION_MANIFEST_URL] = json.dumps(
        {
            "latest": {"release": VERSION, "snapshot": VERSION},
            "versions": [{"id": VERSION, "type": "release"}],
        }
    ).encode("utf-8")

    fixtures[GITHUB_REF_URL.format(repository=MCMETA_REPOSITORY, tag=SUMMARY_TAG)] = json.dumps(
        {"ref": f"refs/tags/{SUMMARY_TAG}", "object": {"sha": SUMMARY_SHA, "type": "commit"}}
    ).encode("utf-8")
    fixtures[GITHUB_REF_URL.format(repository=MCMETA_REPOSITORY, tag=DATA_TAG)] = json.dumps(
        {"ref": f"refs/tags/{DATA_TAG}", "object": {"sha": DATA_SHA, "type": "commit"}}
    ).encode("utf-8")

    registries = {
        "entity_type": ["creeper"],
        "item": ["creeper_spawn_egg"],
        "block": [],
        "mob_effect": [],
        "worldgen/biome": [],
        "enchantment": [],
    }
    summary_url = (
        f"https://raw.githubusercontent.com/{MCMETA_REPOSITORY}/{SUMMARY_SHA}/registries/data.json"
    )
    fixtures[summary_url] = json.dumps(registries).encode("utf-8")

    # `item_components/data.json`, the second summary payload a build reads.
    # Its keys are unprefixed, matching the real branch, and the one item here
    # is food so that the fixture exercises `pipeline.extract.food` rather than
    # tripping its "an empty read is a broken fetch" guard.
    item_components = {
        "creeper_spawn_egg": {"minecraft:max_stack_size": 64},
        "apple": {"minecraft:food": {"nutrition": 4, "saturation": 2.4}},
    }
    item_components_url = (
        f"https://raw.githubusercontent.com/{MCMETA_REPOSITORY}/{SUMMARY_SHA}"
        f"/item_components/data.json"
    )
    fixtures[item_components_url] = json.dumps(item_components).encode("utf-8")

    recipe_json = json.dumps(
        {
            "type": "minecraft:crafting_shapeless",
            "ingredients": ["minecraft:stick"],
            "result": {"id": "minecraft:creeper_spawn_egg"},
        }
    ).encode("utf-8")
    block_loot_json = json.dumps(
        {
            "type": "minecraft:block",
            "pools": [
                {
                    "rolls": 1.0,
                    "entries": [{"type": "minecraft:item", "name": "minecraft:creeper_spawn_egg"}],
                }
            ],
        }
    ).encode("utf-8")

    data_url = MCMETA_ARCHIVE_URL.format(repository=MCMETA_REPOSITORY, commit_sha=DATA_SHA)
    fixtures[data_url] = _tar_gz(
        {
            "data/minecraft/advancement/story/root.json": b"{}",
            "data/minecraft/loot_table/entities/creeper.json": b"{}",
            "data/minecraft/recipe/dummy.json": recipe_json,
            "data/minecraft/loot_table/blocks/dummy.json": block_loot_json,
            "data/minecraft/tags/block/mineable/pickaxe.json": b'{"values":["minecraft:stone"]}',
            "data/minecraft/tags/block/mineable/axe.json": b'{"values":[]}',
            "data/minecraft/tags/block/mineable/shovel.json": b'{"values":[]}',
            "data/minecraft/tags/block/mineable/hoe.json": b'{"values":[]}',
            "data/minecraft/tags/block/needs_stone_tool.json": b'{"values":[]}',
            "data/minecraft/tags/block/needs_iron_tool.json": b'{"values":[]}',
            "data/minecraft/tags/block/needs_diamond_tool.json": b'{"values":[]}',
        },
        root=f"mcmeta-{DATA_SHA}",
    )

    resource_location_row = {
        "page_name": "Creeper",
        "edition": "java",
        "display_name": "Creeper",
        "resource_location": "creeper",
        "json": json.dumps({"Edition": "java", "Type": "entity"}),
    }
    resource_location_url = _bucket_url(
        "resource_location", RESOURCE_LOCATION_COLUMNS, where=(("edition", "java"),)
    )
    fixtures[resource_location_url] = _bucket_answer([resource_location_row])

    sprite_row = {
        "page_name": "Creeper",
        "name": "EntitySprite",
        "id": "creeper",
        "file": "File:Creeper.png",
    }
    fixtures[_bucket_url("spritefile", SPRITE_COLUMNS)] = _bucket_answer([sprite_row])

    # The sprite-atlas stage: `Creeper`'s icon key is `EntitySprite:creeper`, which resolves to
    # `File:Creeper.png` through the bucket row above, so a build needs that file's imageinfo and
    # its bytes.
    #
    # The four hunger shanks join it. They belong to no entity and reach the
    # atlas through `data/curated/hud-sprites.json`, which this build reads
    # from the real curated directory, so an atlas fixture that named only
    # `File:Creeper.png` would fail the moment that file existed.
    sprite_titles = ["File:Creeper.png", *sorted(HUD_SPRITE_TITLES)]
    imageinfo_url = build_imageinfo_url(sprite_titles)
    fixtures[imageinfo_url] = json.dumps(
        {
            "batchcomplete": True,
            "query": {
                "pages": [
                    {
                        "ns": 6,
                        "title": title,
                        "imageinfo": [
                            {
                                "url": _sprite_url(title),
                                "sha1": CREEPER_SPRITE_SHA1,
                                "size": 250,
                                "width": 2,
                                "height": 2,
                                "mime": "image/png",
                            }
                        ],
                    }
                    for title in sprite_titles
                ]
            },
        }
    ).encode("utf-8")
    for title in sprite_titles:
        fixtures[_sprite_url(title)] = _creeper_sprite_png()

    fixtures[_bucket_url("droptable", DROPTABLE_COLUMNS)] = _bucket_answer([])
    fixtures[_bucket_url("spawn_table", SPAWN_TABLE_COLUMNS)] = _bucket_answer([])
    fixtures[_bucket_url("trade", TRADE_COLUMNS)] = _bucket_answer([])
    advancement_url = _bucket_url(
        "advancement", ADVANCEMENT_COLUMNS, where=(("page_name", "Advancement"),)
    )
    fixtures[advancement_url] = _bucket_answer([])

    fixtures[build_extracts_url(["Creeper"])] = json.dumps(
        {
            "batchcomplete": True,
            "query": {
                "pages": [
                    {
                        "pageid": 1,
                        "ns": 0,
                        "title": "Creeper",
                        "extract": "A hissing creature that explodes.",
                    }
                ]
            },
        }
    ).encode("utf-8")

    fixtures[build_wikitext_url(["Brewing"])] = json.dumps(
        {
            "batchcomplete": True,
            "query": {
                "pages": [
                    {
                        "pageid": 2,
                        "ns": 0,
                        "title": "Brewing",
                        "revisions": [{"slots": {"main": {"content": _BREWING_WIKITEXT}}}],
                    }
                ]
            },
        }
    ).encode("utf-8")

    breeding_table = (
        '{| class="wikitable sortable" data-description="Breeding foods"\n'
        "|-\n"
        "! Mob\n"
        "! Items\n"
        "! Other\n"
        "|-\n"
        "| {{EntityLink|Creeper}}\n"
        "| {{ItemLink|Stick}}\n"
        "| None\n"
        "|}"
    )
    fixtures[build_wikitext_url(["Breeding"])] = json.dumps(
        {
            "batchcomplete": True,
            "query": {
                "pages": [
                    {
                        "pageid": 3,
                        "ns": 0,
                        "title": "Breeding",
                        "revisions": [{"slots": {"main": {"content": breeding_table}}}],
                    }
                ]
            },
        }
    ).encode("utf-8")

    infobox_text = "{{Infobox entity\n| health = {{hp|20}}\n}}"
    fixtures[build_wikitext_url(["Creeper"])] = json.dumps(
        {
            "batchcomplete": True,
            "query": {
                "pages": [
                    {
                        "pageid": 1,
                        "ns": 0,
                        "title": "Creeper",
                        "revisions": [{"slots": {"main": {"content": infobox_text}}}],
                    }
                ]
            },
        }
    ).encode("utf-8")

    effect_pages = []
    for pid, title in enumerate(EFFECT_PAGE_TITLES, start=10):
        slug = title.lower().replace(" ", "_")
        content = (
            f"{{{{Infobox effect\n| title = {title}\n| type = Positive\n| id = {slug}\n}}}}\n"
            f"{title} effect description.\n\n"
            f"== Effects ==\n{title} effect behaviour.\n\n"
            f"== Causes ==\n"
            f'{{| class="wikitable"\n! Cause\n! Potency\n! Length\n! Notes\n'
            f"|-\n| {{{{ItemLink|Apple}}}}\n| I\n| 1:00\n| Test note.\n|}}\n"
        )
        effect_pages.append(
            {
                "pageid": pid,
                "ns": 0,
                "title": title,
                "revisions": [{"slots": {"main": {"content": content}}}],
            }
        )
    fixtures[build_wikitext_url(EFFECT_PAGE_TITLES)] = json.dumps(
        {"batchcomplete": True, "query": {"pages": effect_pages}}
    ).encode("utf-8")

    return fixtures


def _fake_transport(fixtures: Mapping[str, bytes]) -> Transport:
    def transport(url: str) -> bytes:
        try:
            return fixtures[url]
        except KeyError:
            raise FetchError(f"no fixture registered for {url}") from None

    return transport


def _base_options(tmp_path: Path) -> BuildOptions:
    return BuildOptions(
        minecraft_version=VERSION,
        dist=tmp_path / "dist",
        cache=tmp_path / "cache",
        reports=tmp_path / "reports",
        quiet=True,
    )


def test_a_whole_build_produces_the_expected_entities_and_writes_dist(tmp_path: Path) -> None:
    fixtures = _build_fixtures()
    transport = _fake_transport(fixtures)
    cache = ContentCache(tmp_path / "cache")

    outcome = run_build(_base_options(tmp_path), transport=transport, cache=cache, now=BUILT_AT)

    assert outcome.minecraft_version == VERSION
    assert outcome.mcmeta_summary_ref == SUMMARY_TAG
    assert outcome.mcmeta_data_ref == DATA_TAG
    # The mob, its spawn egg item, and the one advancement of the fixture.
    assert outcome.entity_count == 3
    assert outcome.pages_without_infobox == ()

    dist = tmp_path / "dist"
    assert (dist / "manifest.json").is_file()
    assert (dist / "index.json").is_file()
    assert (dist / "obtain.json").is_file()
    assert (dist / "sprites.png").is_file()
    sprites_map = json.loads((dist / "sprites.json").read_text(encoding="utf-8"))
    assert sprites_map["sprites"]["EntitySprite:creeper"] == {"x": 0, "y": 0, "w": 2, "h": 2}
    # One creeper sprite plus the four curated hunger shanks.
    assert outcome.emit_report.atlas_frame_count == 5
    assert outcome.emit_report.atlas_png_bytes > 0

    mob_shard = json.loads((dist / "entities" / "mob-0.json").read_text(encoding="utf-8"))
    ids = {entity["id"] for entity in mob_shard["entities"]}
    assert ids == {"minecraft:creeper"}
    creeper = next(e for e in mob_shard["entities"] if e["id"] == "minecraft:creeper")
    assert creeper["name"] == "Creeper"
    assert creeper["icon"] == "EntitySprite:creeper"
    assert creeper["blurb"] == "A hissing creature that explodes."

    item_shard = json.loads((dist / "entities" / "item-0.json").read_text(encoding="utf-8"))
    assert {e["id"] for e in item_shard["entities"]} == {"minecraft:creeper_spawn_egg"}

    advancement_shard = json.loads(
        (dist / "entities" / "advancement-0.json").read_text(encoding="utf-8")
    )
    assert {e["id"] for e in advancement_shard["entities"]} == {"minecraft:story/root"}

    # Stage 7.5 ran: a clean `tmp_path` has no committed `data/dist` of its own to compare
    # against, so this is the "no baseline" case -- it must pass, not fail, and the report
    # must say so rather than silently looking like every check trivially passed.
    assert outcome.validation_report.regression.has_baseline is False
    assert outcome.validation_report.regression.checks == ()
    assert outcome.validation_report.conformance.failures == ()


def test_reports_land_in_the_reports_directory(tmp_path: Path) -> None:
    fixtures = _build_fixtures()
    transport = _fake_transport(fixtures)
    cache = ContentCache(tmp_path / "cache")

    outcome = run_build(_base_options(tmp_path), transport=transport, cache=cache, now=BUILT_AT)

    reports_dir = tmp_path / "reports"
    expected = {
        "tier-reconciliation.json",
        "merge-report.json",
        "unparsed-report.json",
        "emit-report.json",
        "pages-without-infobox.json",
        "obtain-report.json",
        "validation.json",
        "generation-report.json",
    }
    assert {path.name for path in reports_dir.iterdir()} == expected
    assert {path.name for path in outcome.report_paths} == expected
    for path in outcome.report_paths:
        assert path.is_file()
        # Every report is valid JSON with a trailing newline, matching every
        # other `write_report` function's own shape.
        text = path.read_text(encoding="utf-8")
        assert text.endswith("\n")
        json.loads(text)


def test_two_runs_with_the_same_pinned_now_write_byte_identical_files(tmp_path: Path) -> None:
    """A rebuild from the same cache and the same clock reading changes nothing on disk."""
    fixtures = _build_fixtures()
    transport = _fake_transport(fixtures)
    cache = ContentCache(tmp_path / "cache")

    options_a = _base_options(tmp_path).model_copy(
        update={"dist": tmp_path / "dist-a", "reports": tmp_path / "reports-a"}
    )
    options_b = _base_options(tmp_path).model_copy(
        update={"dist": tmp_path / "dist-b", "reports": tmp_path / "reports-b"}
    )
    run_build(options_a, transport=transport, cache=cache, now=BUILT_AT)
    run_build(options_b, transport=transport, cache=cache, now=BUILT_AT)

    dist_a = tmp_path / "dist-a"
    dist_b = tmp_path / "dist-b"
    files_a = sorted(
        path.relative_to(dist_a).as_posix() for path in dist_a.rglob("*") if path.is_file()
    )
    files_b = sorted(
        path.relative_to(dist_b).as_posix() for path in dist_b.rglob("*") if path.is_file()
    )
    assert files_a == files_b
    assert files_a  # the comparison is not vacuously true over an empty build
    for relative in files_a:
        assert (dist_a / relative).read_bytes() == (dist_b / relative).read_bytes()


def test_offline_with_no_minecraft_version_raises_cli_error(tmp_path: Path) -> None:
    options = _base_options(tmp_path).model_copy(
        update={"minecraft_version": None, "offline": True}
    )

    with pytest.raises(CliError, match="--offline"):
        run_build(options)


def test_offline_with_a_cold_cache_raises_naming_the_url(tmp_path: Path) -> None:
    options = _base_options(tmp_path).model_copy(update={"offline": True})

    with pytest.raises(FetchError) as excinfo:
        run_build(options, cache=ContentCache(tmp_path / "cache"))

    assert VERSION_MANIFEST_URL in str(excinfo.value)
    assert "--offline" in str(excinfo.value)


def test_offline_completes_a_whole_build_against_a_cache_one_online_build_primed(
    tmp_path: Path,
) -> None:
    """The case that makes `--offline` a working flag rather than a documented one.

    Every network read of a build now goes through the store: the wiki buckets
    and page reads always did, `resolve_mcmeta_tag` takes a cache, and
    `fetch_version_manifest` takes one whenever the caller already named the
    version -- which `--offline` requires it to. So one online build of a
    version warms every entry the same version needs, and the offline build
    that follows opens no socket at all.

    Two runs make the claim, because neither one makes it alone. The first
    sets `offline=True`, which is the flag a person types; `run_build`
    substitutes `_offline_transport` for whatever transport it was handed, so
    that run finishing proves the flag works but says nothing about what the
    passed transport would have done. The second passes a transport that
    raises on any call and leaves the flag *off*, which proves the underlying
    property the flag depends on: every read of a build of an already-built
    version is served by the store, with no offline special case involved at
    all.
    """
    fixtures = _build_fixtures()
    cache = ContentCache(tmp_path / "cache")
    online = _base_options(tmp_path).model_copy(
        update={"dist": tmp_path / "dist-online", "reports": tmp_path / "reports-online"}
    )
    run_build(online, transport=_fake_transport(fixtures), cache=cache, now=BUILT_AT)

    def refuse(url: str) -> bytes:
        raise AssertionError(f"the offline build read {url} from the network")

    offline = _base_options(tmp_path).model_copy(
        update={
            "offline": True,
            "dist": tmp_path / "dist-offline",
            "reports": tmp_path / "reports-offline",
        }
    )
    outcome = run_build(offline, cache=cache, now=BUILT_AT)

    assert outcome.entity_count == 3

    # The second run: no `--offline` at all, and a transport that refuses. The
    # store alone has to carry the whole build for this to return.
    no_flag = _base_options(tmp_path).model_copy(
        update={"dist": tmp_path / "dist-cached", "reports": tmp_path / "reports-cached"}
    )
    assert run_build(no_flag, transport=refuse, cache=cache, now=BUILT_AT).entity_count == 3

    # And the payload is the payload the online build wrote, byte for byte.
    # A cache that answered with something else would still have produced a
    # build; only this comparison says it produced the *same* build.
    online_dist = tmp_path / "dist-online"
    offline_dist = tmp_path / "dist-offline"
    written = sorted(
        path.relative_to(online_dist).as_posix()
        for path in online_dist.rglob("*")
        if path.is_file()
    )
    assert written
    for relative in written:
        assert (online_dist / relative).read_bytes() == (offline_dist / relative).read_bytes()


# --- Stage 7.5, the validation gate's regression half, wired through --allow-regression ------


def _seed_inflated_baseline(dist: Path, *, item_count: int) -> None:
    """Write a `data/dist` shaped like a previous build with far more items than the small
    fixture build in this module ever produces, so a build over that fixture regresses hard
    enough to trip the total-count and per-kind checks in one step.
    """
    entities_dir = dist / "entities"
    entities_dir.mkdir(parents=True)
    entities = [
        {
            "id": f"minecraft:baseline-item-{i}",
            "kind": "item",
            "name": f"Baseline Item {i}",
            "aliases": [],
            "sourceTiers": {},
            "sections": [],
        }
        for i in range(item_count)
    ]
    (entities_dir / "item-0.json").write_text(
        json.dumps({"schemaVersion": 1, "entities": entities}), encoding="utf-8"
    )


def test_a_regression_against_a_seeded_baseline_raises_and_writes_nothing(tmp_path: Path) -> None:
    fixtures = _build_fixtures()
    transport = _fake_transport(fixtures)
    cache = ContentCache(tmp_path / "cache")
    options = _base_options(tmp_path)
    _seed_inflated_baseline(options.dist, item_count=100)
    before = (options.dist / "entities" / "item-0.json").read_bytes()

    with pytest.raises(ValidationError):
        run_build(options, transport=transport, cache=cache, now=BUILT_AT)

    # The gate refused before emit_build wrote anything -- the seeded baseline must be
    # completely untouched, not partially overwritten by the refused build.
    assert (options.dist / "entities" / "item-0.json").read_bytes() == before
    assert not (options.dist / "entities" / "mob-0.json").exists()


def test_allow_regression_completes_the_build_and_still_records_every_downgraded_failure(
    tmp_path: Path,
) -> None:
    fixtures = _build_fixtures()
    transport = _fake_transport(fixtures)
    cache = ContentCache(tmp_path / "cache")
    options = _base_options(tmp_path).model_copy(update={"allow_regression": True})
    _seed_inflated_baseline(options.dist, item_count=100)

    outcome = run_build(options, transport=transport, cache=cache, now=BUILT_AT)

    assert outcome.entity_count == 3
    blocking = outcome.validation_report.regression.blocking_failures
    assert blocking == ()

    downgraded = [
        check for check in outcome.validation_report.regression.checks if check.downgraded
    ]
    assert downgraded
    assert any(check.name == "total entity count" for check in downgraded)

    # The downgraded findings are still written to validation.json in full, not only held on
    # the in-memory outcome.
    validation_document = json.loads(
        (options.reports / "validation.json").read_text(encoding="utf-8")
    )
    written_downgraded = [
        check
        for check in validation_document["regression"]["checks"]
        if check["downgraded"]
    ]
    assert written_downgraded
    assert {check["name"] for check in written_downgraded} == {check.name for check in downgraded}

    # And the build actually completed: the new, much smaller build is what is on disk now.
    item_shard = json.loads((options.dist / "entities" / "item-0.json").read_text(encoding="utf-8"))
    assert {e["id"] for e in item_shard["entities"]} == {"minecraft:creeper_spawn_egg"}


def test_the_progress_line_names_downgraded_checks_rather_than_reading_as_clean(
    tmp_path: Path,
) -> None:
    """A build run with `--allow-regression` has zero blocking failures by construction.

    Reporting only that number would print a line that reads as completely clean for the one build
    that most needs a second look, and the reader would have to open `validation.json` to learn
    that anything failed at all.
    """
    fixtures = _build_fixtures()
    transport = _fake_transport(fixtures)
    cache = ContentCache(tmp_path / "cache")
    options = _base_options(tmp_path).model_copy(
        update={"allow_regression": True, "quiet": False}
    )
    _seed_inflated_baseline(options.dist, item_count=100)

    stream = io.StringIO()
    run_build(options, transport=transport, cache=cache, now=BUILT_AT, stream=stream)

    validate_line = next(
        line for line in stream.getvalue().splitlines() if line.startswith("validate:")
    )
    assert "0 blocking regression failures" in validate_line
    assert "downgraded by --allow-regression" in validate_line


def test_the_progress_line_stays_quiet_about_downgrades_when_there_are_none(
    tmp_path: Path,
) -> None:
    fixtures = _build_fixtures()
    transport = _fake_transport(fixtures)
    cache = ContentCache(tmp_path / "cache")
    options = _base_options(tmp_path).model_copy(update={"quiet": False})

    stream = io.StringIO()
    run_build(options, transport=transport, cache=cache, now=BUILT_AT, stream=stream)

    validate_line = next(
        line for line in stream.getvalue().splitlines() if line.startswith("validate:")
    )
    assert "downgraded" not in validate_line


# --- Stage 7b, the sprite atlas -----------------------------------------------------------


def test_the_sprite_atlas_progress_line_names_every_count(tmp_path: Path) -> None:
    fixtures = _build_fixtures()
    transport = _fake_transport(fixtures)
    cache = ContentCache(tmp_path / "cache")
    options = _base_options(tmp_path).model_copy(update={"quiet": False})

    stream = io.StringIO()
    run_build(options, transport=transport, cache=cache, now=BUILT_AT, stream=stream)

    atlas_line = next(
        line for line in stream.getvalue().splitlines() if line.startswith("sprite atlas:")
    )
    # Five, not one: the creeper's own icon plus the four hunger shanks that
    # `data/curated/hud-sprites.json` adds to every build's atlas.
    assert "5 icon keys requested" in atlas_line
    assert "5 files resolved" in atlas_line
    assert "5 sprites downloaded" in atlas_line
    assert "5 frames packed" in atlas_line
    assert "0 failures" in atlas_line
