"""Spawn tables: the edition inside the blob, and the variant the page does not name.

`pipeline.enrich.spawn_table` is the only source this project has for per-biome
mob lists, because mcmeta's biome `spawners` field is empty. Two of its traps are
easy to walk into: the edition is a JSON field rather than a column, so nothing
upstream can filter it, and the `mob` column names the wiki page rather than the
entity that actually spawns.

`parse_spawn_tables` is pure, so nothing here opens a socket.
"""

import json
from typing import Any

import pytest

from pipeline.enrich import EnrichError, IntegerRange
from pipeline.enrich.spawn_table import (
    JAVA_EDITION,
    SpawnEntry,
    SpawnIndex,
    parse_spawn_tables,
)


def row(
    biome: str,
    mob: str,
    *,
    spawned: str | None = None,
    edition: str = JAVA_EDITION,
    weight: float = 100,
    total: float = 515,
    size: str = "4",
    category: str = "Monster",
    note: str | None = None,
    note_name: str | None = None,
) -> dict[str, Any]:
    """Return one `spawn_table` row, shaped the way the live API sends it.

    `mob` is the column, which names a wiki page. `spawned` is the blob's
    `Spawned mob`, which names the entity; it defaults to the same value,
    because most rows agree.
    """
    document: dict[str, Any] = {
        "Spawned in": biome,
        "Spawned mob": spawned if spawned is not None else mob,
        "Size": size,
        "Category": category,
        "Weight": weight,
        "Total weight": total,
        "Edition": edition,
    }
    if note is not None:
        document["Note"] = note
    if note_name is not None:
        document["Note name"] = note_name
    return {"page_name": biome, "mob": mob, "json": json.dumps(document)}


def test_a_java_row_is_indexed_by_mob_and_by_biome() -> None:
    """Both directions are groupings, because the row sits on the biome's page."""
    index = parse_spawn_tables([row("Desert", "Creeper")])

    assert index.by_mob["Creeper"][0].biome == "Desert"
    assert index.by_biome["Desert"][0].mob == "Creeper"
    assert index.by_biome["Desert"][0].wiki_url == "https://minecraft.wiki/w/Desert"


def test_a_bedrock_row_is_skipped_and_reported() -> None:
    """`Edition` is inside the JSON column, so `where()` cannot reach it.

    The whole table crosses the wire and the filter runs here. Half the live
    bucket -- 789 of 1,602 rows -- is dropped by this, which is expected, and
    only the report makes it distinguishable from a scrape that half failed.
    """
    index = parse_spawn_tables(
        [row("Desert", "Creeper"), row("Desert", "Husk", edition="bedrock")]
    )

    assert [entry.mob for entry in index.entries] == ["Creeper"]
    assert index.skipped[0].reason == "the row is bedrock edition, not java"


def test_the_spawned_mob_wins_over_the_mob_column() -> None:
    """`Taiga` says `Chicken` in the column and `Cold Chicken` in the blob.

    122 live rows disagree this way. Taking the column would put plain chickens
    in every taiga and lose the variants; keeping both means the entity is right
    and the link still points at the page that documents it.
    """
    index = parse_spawn_tables([row("Taiga", "Chicken", spawned="Cold Chicken")])

    entry = index.entries[0]
    assert entry.mob == "Cold Chicken"
    assert entry.mob_page == "Chicken"
    assert "Cold Chicken" in index.by_mob


def test_a_group_size_can_be_fixed_or_a_range() -> None:
    """`4` means always four; `2-4` means between two and four."""
    index = parse_spawn_tables(
        [row("Desert", "Creeper", size="4"), row("Plains", "Cow", size="2-4")]
    )

    assert index.entries[0].group_size == IntegerRange(minimum=4, maximum=4)
    assert index.entries[1].group_size == IntegerRange(minimum=2, maximum=4)


def test_the_weight_share_is_what_a_renderer_should_show() -> None:
    """A weight on its own says nothing: 100 means different things per biome."""
    index = parse_spawn_tables([row("Desert", "Creeper", weight=100, total=400)])

    assert index.entries[0].share == pytest.approx(0.25)


def test_a_whole_weight_stays_a_whole_number() -> None:
    """Coercing to float would render `100.0` where the wiki renders `100`."""
    index = parse_spawn_tables([row("Desert", "Creeper", weight=100)])

    assert index.entries[0].weight == 100
    assert isinstance(index.entries[0].weight, int)


def test_a_conditional_spawn_keeps_its_note() -> None:
    """Slimes spawn in the desert only in slime chunks, which the note says."""
    index = parse_spawn_tables(
        [
            row(
                "Desert",
                "Slime",
                note="Spawn attempt succeeds only in slime chunks.",
                note_name="Slime",
            )
        ]
    )

    assert index.entries[0].note == "Spawn attempt succeeds only in slime chunks."
    assert index.entries[0].note_name == "Slime"


def test_a_java_row_with_a_weight_that_is_not_a_number_raises() -> None:
    """One template writes this blob, so a bad field means the template moved."""
    broken = row("Desert", "Creeper")
    document = json.loads(broken["json"])
    document["Weight"] = "many"
    broken["json"] = json.dumps(document)

    with pytest.raises(EnrichError, match="Weight"):
        parse_spawn_tables([broken])


def test_a_group_size_the_wiki_has_not_written_raises() -> None:
    """Inventing a number would put a made-up group size on a biome page."""
    with pytest.raises(EnrichError):
        parse_spawn_tables([row("Desert", "Creeper", size="a few")])


def test_an_index_that_does_not_index_its_own_entries_is_refused() -> None:
    """The lookups are fields on a frozen model, so they are checked, not trusted."""
    entry = SpawnEntry(
        mob="Creeper",
        mob_page="Creeper",
        biome="Desert",
        biome_page="Desert",
        wiki_url="https://minecraft.wiki/w/Desert",
        category="Monster",
        weight=100,
        total_weight=515,
        group_size=IntegerRange(minimum=4, maximum=4),
    )
    with pytest.raises(EnrichError, match="mob index"):
        SpawnIndex(entries=(entry,), by_mob={}, by_biome={})
