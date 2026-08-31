"""The `spritefile` bucket reader, and the row shapes it must count or drop correctly.

`pipeline.enrich.sprite` is the join every icon Phase 6 draws goes through, so
a wrong entry here is a wrong icon on every window that shows it, and a wrong
count is a reconciliation report nobody can trust.

The rows below are shaped like the live ones. `parse_sprite_files` is pure, so
none of this opens a socket; the one fetch test drives a transport that returns
bytes from memory.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline.enrich import EnrichError
from pipeline.enrich.sprite import (
    BUCKET,
    FILE_NAMESPACE,
    VANILLA_FAMILIES,
    SpriteFile,
    SpriteIndex,
    fetch_sprite_index,
    parse_sprite_files,
)
from pipeline.fetch.cache import ContentCache


def row(
    family: str,
    sprite_id: str,
    file_title: str | None = None,
    *,
    page: str | None = None,
    deprecated: Any = None,
) -> dict[str, Any]:
    """Return one `spritefile` row, shaped the way the live API sends it.

    `file_title` defaults to `File:<family> <sprite_id>.png`, the ordinary
    shape most rows use. `deprecated` of `None` omits the column, matching how
    the API answers a field with no value.
    """
    default_file = f"{FILE_NAMESPACE}{family} {sprite_id}.png"
    resolved_file = file_title if file_title is not None else default_file
    built: dict[str, Any] = {
        # The live table almost always writes the row on the file's own page,
        # matching the sample data `pipeline.enrich.sprite`'s module docstring
        # quotes, so that is the default here too.
        "page_name": page if page is not None else resolved_file,
        "name": family,
        "id": sprite_id,
        "file": resolved_file,
    }
    if deprecated is not None:
        built["deprecated"] = deprecated
    return built


# --- The family filter -------------------------------------------------------


def test_a_vanilla_family_row_survives() -> None:
    """The ordinary case: a family this project reads, kept as an entry."""
    index = parse_sprite_files([row("InvSprite", "Raw Iron", "File:Invicon Raw Iron.png")])

    assert index.lookup("InvSprite", "Raw Iron") == SpriteFile(
        family="InvSprite",
        sprite_id="Raw Iron",
        file_title="File:Invicon Raw Iron.png",
        page="File:Invicon Raw Iron.png",
    )
    assert index.other_products == 0
    assert index.skipped == ()


@pytest.mark.parametrize(
    "family",
    ["DungeonsItemSprite", "LegendsSprite", "StoryModeItemSprite", "LegoSprite",
     "PersonaSprite", "MovieSprite", "SkinSprite", "LegacyBlockSprite", "LegacyEntitySprite"],
)
def test_a_non_vanilla_family_is_counted_and_not_reported(family: str) -> None:
    """Another product's family is content this project never wanted, not a fault it hit.

    It must not appear in `entries` and must not appear in `skipped` either --
    `other_products` is where it is counted, so a person reading the report is
    not shown six thousand identical lines that say nothing is wrong.
    """
    index = parse_sprite_files([row(family, "some-id")])

    assert index.entries == ()
    assert index.skipped == ()
    assert index.other_products == 1


def test_a_row_with_no_family_name_is_also_counted_as_out_of_scope() -> None:
    """A blank family cannot be one of `VANILLA_FAMILIES`, so it is filtered, not reported."""
    rows = [{"page_name": "File:Weird.png", "id": "x", "file": "File:Weird.png"}]
    index = parse_sprite_files(rows)

    assert index.entries == ()
    assert index.other_products == 1
    assert index.skipped == ()


def test_vanilla_families_are_exactly_the_nine_java_ones() -> None:
    """Pinned so a future edit to the set is a deliberate, reviewed change."""
    assert frozenset(
        {
            "InvSprite",
            "BlockSprite",
            "ItemSprite",
            "EntitySprite",
            "EnvSprite",
            "EffectSprite",
            "AchievementSprite",
            "BiomeSprite",
            "NewAchievementSprite",
        }
    ) == VANILLA_FAMILIES


# --- Row-level faults, within a vanilla family --------------------------------


def test_a_row_with_no_sprite_id_is_skipped_and_reported() -> None:
    """A vanilla-family row missing its id is content this project wanted and could not read."""
    rows = [{"page_name": "File:X.png", "name": "InvSprite", "file": "File:X.png"}]
    index = parse_sprite_files(rows)

    assert index.entries == ()
    assert index.other_products == 0
    assert index.skipped[0].reason == "the row has no sprite id"


def test_a_row_with_no_file_is_skipped_and_reported() -> None:
    rows = [{"page_name": "File:X.png", "name": "InvSprite", "id": "X"}]
    index = parse_sprite_files(rows)

    assert index.entries == ()
    assert index.skipped[0].reason == "the row has no file"


def test_a_file_outside_the_file_namespace_is_skipped_and_reported() -> None:
    """Nothing downstream can read a title in another namespace as an image."""
    index = parse_sprite_files([row("InvSprite", "X", "NotAFile.png")])

    assert index.entries == ()
    assert "does not start with" in index.skipped[0].reason


# --- Deduplication -------------------------------------------------------------


def test_an_exact_duplicate_row_is_dropped_quietly() -> None:
    """The bucket writes one row per wiki page that mentions the pair."""
    index = parse_sprite_files(
        [
            row("InvSprite", "Stone", "File:Invicon Stone.png", page="Stone"),
            row("InvSprite", "Stone", "File:Invicon Stone.png", page="Superflat"),
        ]
    )

    assert len(index.entries) == 1
    assert index.skipped == ()


def test_a_conflicting_duplicate_is_skipped_and_reported() -> None:
    """One sprite id naming two different files is a wiki fact in conflict with itself.

    `resolve_icon` is built to refuse guessing which icon is current, and this
    is where that refusal starts: the first file kept, the conflicting row
    reported rather than silently overwriting it.
    """
    index = parse_sprite_files(
        [
            row("InvSprite", "Stone", "File:Invicon Stone.png"),
            row("InvSprite", "Stone", "File:Invicon Stone Old.png"),
        ]
    )

    kept = index.lookup("InvSprite", "Stone")
    assert kept is not None
    assert kept.file_title == "File:Invicon Stone.png"
    assert len(index.skipped) == 1
    assert "already names" in index.skipped[0].reason


def test_two_different_ids_may_name_one_file_without_conflict() -> None:
    """`Acacia Wood Button` and `Acacia Button` both name the current button icon."""
    index = parse_sprite_files(
        [
            row("InvSprite", "Acacia Wood Button", "File:Invicon Acacia Button.png"),
            row("InvSprite", "Acacia Button", "File:Invicon Acacia Button.png"),
        ]
    )

    assert len(index.entries) == 2
    assert index.skipped == ()


# --- `deprecated` --------------------------------------------------------------


def test_an_absent_deprecated_field_reads_as_false() -> None:
    index = parse_sprite_files([row("InvSprite", "Raw Iron")])
    sprite = index.lookup("InvSprite", "Raw Iron")
    assert sprite is not None
    assert sprite.deprecated is False


def test_deprecated_as_the_lives_empty_string_reads_as_false() -> None:
    """The live table's only observed shape for a set `deprecated` field is `''`, which is falsy."""
    index = parse_sprite_files([row("InvSprite", "Sculk Block", deprecated="")])
    sprite = index.lookup("InvSprite", "Sculk Block")
    assert sprite is not None
    assert sprite.deprecated is False


def test_a_genuinely_truthy_deprecated_value_reads_as_true() -> None:
    """Not observed live, but the field is read generically rather than hardcoded to one shape."""
    index = parse_sprite_files([row("InvSprite", "Old Thing", deprecated=True)])
    sprite = index.lookup("InvSprite", "Old Thing")
    assert sprite is not None
    assert sprite.deprecated is True


# --- The empty-table guard ------------------------------------------------------


def test_an_empty_table_is_a_failure_to_report() -> None:
    """CLAUDE.md: an empty scrape result is a failure, never a silently empty return."""
    with pytest.raises(EnrichError, match="no rows"):
        parse_sprite_files([])


# --- `SpriteIndex` ---------------------------------------------------------------


def test_file_titles_returns_the_distinct_titles_sorted() -> None:
    """Several sprite ids can point at one file, such as `Blank.png`."""
    index = parse_sprite_files(
        [
            row("InvSprite", "Cave Air", "File:Blank.png"),
            row("InvSprite", "Void Air", "File:Blank.png"),
            row("BlockSprite", "acacia-button", "File:BlockSprite acacia-button.png"),
        ]
    )

    assert index.file_titles() == ("File:Blank.png", "File:BlockSprite acacia-button.png")


def test_lookup_of_an_unknown_family_or_id_is_none() -> None:
    index = parse_sprite_files([row("InvSprite", "Raw Iron")])
    assert index.lookup("BlockSprite", "Raw Iron") is None
    assert index.lookup("InvSprite", "Golden Apple") is None


def test_an_index_whose_family_lookup_disagrees_with_its_entries_is_refused() -> None:
    """The recomputing validator, matching `JoinTable._indexes_must_match_the_entries`."""
    entry = SpriteFile(
        family="InvSprite", sprite_id="Raw Iron", file_title="File:Invicon Raw Iron.png",
        page="File:Invicon Raw Iron.png",
    )
    with pytest.raises(EnrichError, match="family index"):
        SpriteIndex(entries=(entry,), by_family={})


# --- Fetching ------------------------------------------------------------------


def test_fetching_reads_the_whole_bucket_with_no_where_clause_and_caches(tmp_path: Path) -> None:
    """There is no `edition` column, so `fetch_sprite_index` sends no `where` clause.

    The transport counts its calls, so the second read proves the answer came
    from the cache rather than from a second request.
    """
    requested: list[str] = []

    def transport(url: str) -> bytes:
        requested.append(url)
        return json.dumps(
            {"bucketQuery": "q", "bucket": [row("InvSprite", "Raw Iron")]}
        ).encode()

    cache = ContentCache(root=tmp_path)
    index = fetch_sprite_index(revision="26.2", cache=cache, transport=transport)

    assert index.lookup("InvSprite", "Raw Iron") is not None
    assert f"bucket%28%27{BUCKET}%27%29" in requested[0]
    assert "where" not in requested[0]

    fetch_sprite_index(revision="26.2", cache=cache, transport=transport)
    assert len(requested) == 1
