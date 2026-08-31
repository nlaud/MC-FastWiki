"""The spritefile parser against Bucket rows the wiki actually sent.

Every other test of `pipeline.enrich.sprite` builds its rows in memory, one
trap per test. That proves the parser does what its author intended and
proves nothing about whether the intention matches the real table. This module
reads `tests/fixtures/wiki_sprite_rows.json`, which
`tests/fixtures/build_sprite_snapshot.py` captured from the live wiki, and
checks facts a person can verify against the wiki's own file pages.

It opens no socket. The rows are on disk.

**A failure here is a question, not a verdict.** The wiki has no version to pin
to -- it is edited continuously -- so an assertion that goes red means either
the parser changed or the wiki did, and the two are told apart by reading the
`File:` page named in the failing test. When it is the wiki, rebuild the
fixture, read the diff, and update the assertion. When it is the parser, the
fixture is doing its job.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline.enrich.sprite import SpriteIndex, parse_sprite_files

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "wiki_sprite_rows.json"


@pytest.fixture(scope="module")
def snapshot() -> dict[str, Any]:
    """Return the whole snapshot document."""
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


@pytest.fixture(scope="module")
def index(snapshot: dict[str, Any]) -> SpriteIndex:
    """Return the sprite index over the whole snapshot, parsed once and shared."""
    return parse_sprite_files(snapshot["rows"])


def test_the_snapshot_records_where_and_when_it_came_from(snapshot: dict[str, Any]) -> None:
    """There is no Minecraft version to pin here, so the date tells a reader how old a
    disagreement with the live wiki might be.
    """
    assert snapshot["captured"]
    assert "CC BY-NC-SA" in snapshot["note"]
    assert snapshot["rows"]


def test_raw_iron_follows_the_ordinary_pattern(index: SpriteIndex) -> None:
    """The plain `Invicon <Name>.png` shape that most `InvSprite` rows use."""
    sprite = index.lookup("InvSprite", "Raw Iron")
    assert sprite is not None
    assert sprite.file_title == "File:Invicon Raw Iron.png"
    assert sprite.deprecated is False


def test_pancake_stack_does_not_follow_the_ordinary_pattern(index: SpriteIndex) -> None:
    """One of the 115 `InvSprite` rows that does not follow `Invicon <Name>.png`.

    A parser that built a filename from the id instead of reading `file` would
    guess `File:Invicon Pancake Stack.png`, which is not a real file.
    """
    sprite = index.lookup("InvSprite", "Pancake Stack")
    assert sprite is not None
    assert sprite.file_title == "File:PancakeInvSprite.png"


def test_sculk_block_names_a_gif_and_reads_as_not_deprecated(index: SpriteIndex) -> None:
    """`Sculk Block` names a `.gif`, and it carries `deprecated` as an empty string.

    The empty string is falsy, matching the module docstring's fact that no
    live row reads as deprecated today, whether the field is absent or set to
    this value.
    """
    sprite = index.lookup("InvSprite", "Sculk Block")
    assert sprite is not None
    assert sprite.file_title == "File:Sculk JE1 BE1.gif"
    assert sprite.deprecated is False


def test_two_different_ids_may_share_one_file(index: SpriteIndex) -> None:
    """`Acacia Wood Button` and `Acacia Button` both name the same file.

    This is not the duplicate-key conflict `parse_sprite_files` refuses: the
    conflict is one `(family, sprite_id)` naming two files, not one file named
    by two different ids.
    """
    old = index.lookup("InvSprite", "Acacia Wood Button")
    current = index.lookup("InvSprite", "Acacia Button")
    assert old is not None
    assert current is not None
    assert old.file_title == current.file_title == "File:Invicon Acacia Button.png"
    assert old.deprecated is False


def test_a_dungeons_family_is_filtered_out_and_counted(index: SpriteIndex) -> None:
    """Minecraft Dungeons sprites are another product, not a malformed row.

    They must not appear in the index and must not appear in `skipped` either
    -- `other_products` is where they are counted.
    """
    assert index.lookup("DungeonsItemSprite", "burst-gust-bow") is None
    assert not any(row.page.startswith("File:DungeonsItemSprite") for row in index.skipped)


def test_a_legacy_family_is_filtered_out(index: SpriteIndex) -> None:
    """Legacy Console Edition sprites are out of scope alongside Bedrock."""
    assert index.lookup("LegacyBlockSprite", "sand-je1") is None


def test_a_skin_family_is_filtered_out(index: SpriteIndex) -> None:
    """A wiki editor persona skin is not a Minecraft Java Edition fact."""
    assert index.lookup("SkinSprite", "dragon-slayer") is None


def test_other_products_counts_every_filtered_row(
    snapshot: dict[str, Any], index: SpriteIndex
) -> None:
    """The three out-of-scope family samples in the fixture, and nothing else, are filtered."""
    out_of_scope_families = {"DungeonsItemSprite", "LegacyBlockSprite", "SkinSprite"}
    expected = sum(1 for row in snapshot["rows"] if row["name"] in out_of_scope_families)
    assert expected > 0
    assert index.other_products == expected


def test_every_vanilla_row_of_the_fixture_survived(
    snapshot: dict[str, Any], index: SpriteIndex
) -> None:
    """Nothing in the chosen vanilla rows should have been skipped."""
    assert index.skipped == ()
    out_of_scope_families = {"DungeonsItemSprite", "LegacyBlockSprite", "SkinSprite"}
    vanilla_rows = [row for row in snapshot["rows"] if row["name"] not in out_of_scope_families]
    assert len(index.entries) == len(vanilla_rows)


def test_common_families_this_project_reconciles_are_all_present(index: SpriteIndex) -> None:
    """One row of every family `pipeline.normalize.reconcile.ICON_RULES` reads must be present."""
    assert index.lookup("BlockSprite", "acacia-button") is not None
    assert index.lookup("ItemSprite", "iron-sword") is not None
    assert index.lookup("EntitySprite", "zombie-villager-desert-shepherd") is not None
    assert index.lookup("EffectSprite", "absorption") is not None
    assert index.lookup("BiomeSprite", "deep-ocean") is not None
