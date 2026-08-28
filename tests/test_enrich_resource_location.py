"""The join table, and the four kinds of row that must never enter it.

`pipeline.enrich.resource_location` is what every other Tier B reader joins
through, so a wrong entry here becomes a wrong registry ID on a mob's drop, a
villager's trade, and a recipe's output at the same time.

The rows below are shaped like the live ones. `parse_resource_locations` is
pure, so none of this opens a socket; the one fetch test drives a transport that
returns bytes from memory.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline.enrich import EnrichError
from pipeline.enrich.resource_location import (
    JAVA_EDITION,
    NO_DISPLAY_NAME,
    JoinTable,
    ResourceLocation,
    fetch_join_table,
    parse_resource_locations,
)
from pipeline.fetch.cache import ContentCache


def row(
    display_name: str,
    location: str | None = None,
    *,
    page: str | None = None,
    kind: str | None = "item",
    edition: str = JAVA_EDITION,
) -> dict[str, Any]:
    """Return one `resource_location` row, shaped the way the live API sends it.

    `location` of `None` omits the column rather than sending a null, which is
    what the API does: a field whose value is null is simply absent.
    """
    document: dict[str, Any] = {"Display name": display_name, "Edition": edition}
    if kind is not None:
        document["Type"] = kind
    built: dict[str, Any] = {
        "page_name": page if page is not None else display_name,
        "display_name": display_name,
        "edition": edition,
        "json": json.dumps(document),
    }
    if location is not None:
        built["resource_location"] = location
    return built


def test_a_java_row_becomes_a_namespaced_entry() -> None:
    """The bucket stores an unprefixed path; every ID downstream is namespaced."""
    table = parse_resource_locations([row("Diamond", "diamond")])

    assert table.resolve("Diamond") == "minecraft:diamond"
    assert table.entries[0].resource_location == "diamond"
    assert table.entries[0].wiki_url == "https://minecraft.wiki/w/Diamond"


def test_a_bedrock_row_is_dropped_and_reported() -> None:
    """Non-negotiable 1: the filter is the pipeline's, and it runs in the parser.

    The fetch function also sends `where('edition','java')`, but that is a
    bandwidth saving. This is the filter of record, so a caller that assembles
    rows by hand -- or a server that ignored the clause -- still cannot get a
    Bedrock ID into the table.
    """
    table = parse_resource_locations(
        [row("Stone", "stone"), row("Stone", "stone", edition="bedrock")]
    )

    assert len(table.entries) == 1
    assert [skip.reason for skip in table.skipped] == ["the row is bedrock edition, not java"]


def test_a_translation_page_never_reaches_the_table() -> None:
    """A translated display name is a well-formed row and a wrong join key.

    `poki moku` maps to `bowl` on the Toki Pona translation page. Nothing in the
    row says it is a translation; only its namespace does.
    """
    table = parse_resource_locations(
        [
            row("Bowl", "bowl"),
            row("poki moku", "bowl", page="Minecraft Wiki:Projects/Toki Pona translation/Bowl"),
        ]
    )

    assert set(table.by_display_name) == {"Bowl"}


def test_a_row_with_no_resource_location_is_dropped_and_reported() -> None:
    """The API omits a null field, so removed content arrives with nothing to join."""
    table = parse_resource_locations([row("Horse Saddle")])

    assert table.entries == ()
    assert table.skipped[0].reason == "the row has no resource_location to join to"


def test_the_wikis_no_display_name_placeholder_is_not_a_name() -> None:
    """`No displayed name` is content, so `text_or_none` cannot catch it."""
    table = parse_resource_locations([row(NO_DISPLAY_NAME, "tree", kind="env")])

    assert table.entries == ()
    assert "no display name" in table.skipped[0].reason


def test_the_same_pair_written_on_many_pages_becomes_one_entry() -> None:
    """`Stone` maps to `stone` on 14 pages. Fourteen entries would read as ambiguous.

    The page kept is the one named after the display name, because that is the
    article the entity's own page will be.
    """
    table = parse_resource_locations(
        [
            row("Stone", "stone", page="Cobblestone", kind="block"),
            row("Stone", "stone", page="Stone", kind="block"),
            row("Stone", "stone", page="Blast Furnace", kind="block"),
        ]
    )

    assert len(table.entries) == 1
    assert table.entries[0].page == "Stone"


def test_a_repeated_pair_with_no_page_of_its_own_takes_the_first_page_in_order() -> None:
    """The answer must not depend on the order the API happened to return rows."""
    forwards = parse_resource_locations(
        [
            row("Stone", "stone", page="Cobblestone", kind="block"),
            row("Stone", "stone", page="Blast Furnace", kind="block"),
        ]
    )
    backwards = parse_resource_locations(
        [
            row("Stone", "stone", page="Blast Furnace", kind="block"),
            row("Stone", "stone", page="Cobblestone", kind="block"),
        ]
    )

    assert forwards.entries[0].page == backwards.entries[0].page == "Blast Furnace"


def test_kind_separates_a_name_that_is_both_an_item_and_an_entity() -> None:
    """`Eye of Ender` is the item `ender_eye` and the entity `eye_of_ender`."""
    table = parse_resource_locations(
        [
            row("Eye of Ender", "ender_eye", kind="item"),
            row("Eye of Ender", "eye_of_ender", kind="entity"),
        ]
    )

    assert table.resolve("Eye of Ender", kind="item") == "minecraft:ender_eye"
    assert table.resolve("Eye of Ender", kind="entity") == "minecraft:eye_of_ender"


def test_resolving_an_ambiguous_name_raises_rather_than_choosing() -> None:
    """A guessed registry ID is the failure this table exists to prevent.

    `Air` is both `air` and `air_block`, and both are blocks, so `kind` cannot
    separate them either.
    """
    table = parse_resource_locations(
        [row("Air", "air", kind="block"), row("Air", "air_block", kind="block")]
    )

    with pytest.raises(EnrichError, match="more than one registry ID"):
        table.resolve("Air")
    assert table.ambiguous_names() == {"Air": ("minecraft:air", "minecraft:air_block")}


def test_resolving_a_name_the_table_does_not_hold_raises() -> None:
    """A bucket writing a name this table lacks is a broken join, not an absence."""
    table = parse_resource_locations([row("Diamond", "diamond")])

    with pytest.raises(EnrichError, match="not a display name"):
        table.resolve("Diamnod")


def test_an_escaped_display_name_is_unescaped_before_it_becomes_a_key() -> None:
    """`Bottle o&#39; Enchanting` would match nothing else in the pipeline."""
    table = parse_resource_locations([row("Bottle o&#39; Enchanting", "experience_bottle")])

    assert table.resolve("Bottle o' Enchanting") == "minecraft:experience_bottle"


def test_the_registry_index_answers_the_other_direction() -> None:
    """The Tier A/Tier B reconciliation walks IDs, not names."""
    table = parse_resource_locations([row("Diamond", "diamond")])

    assert [entry.display_name for entry in table.by_registry_id["minecraft:diamond"]] == [
        "Diamond"
    ]


def test_a_table_whose_index_does_not_match_its_entries_is_refused() -> None:
    """A frozen model cannot memoize, so the indexes are fields and are checked.

    Without this a table built by hand could answer lookups its own entries do
    not support, and every later stage would believe it.
    """
    entry = ResourceLocation(
        display_name="Diamond",
        resource_location="diamond",
        kind="item",
        page="Diamond",
        wiki_url="https://minecraft.wiki/w/Diamond",
    )
    with pytest.raises(EnrichError, match="display-name index"):
        JoinTable(entries=(entry,), by_display_name={}, by_registry_id={})


def test_fetching_narrows_to_java_and_caches_under_the_revision(tmp_path: Path) -> None:
    """The query filters by edition on the wire and the parser filters again.

    The transport here counts its calls, so the second read proves the answer
    came from the cache rather than from a second request -- which is what the
    revision in the cache key is for.
    """
    requested: list[str] = []

    def transport(url: str) -> bytes:
        requested.append(url)
        return json.dumps({"bucketQuery": "q", "bucket": [row("Diamond", "diamond")]}).encode()

    cache = ContentCache(root=tmp_path)
    table = fetch_join_table(revision="26.2", cache=cache, transport=transport)

    assert table.resolve("Diamond") == "minecraft:diamond"
    assert "where%28%27edition%27%2C%27java%27%29" in requested[0]

    fetch_join_table(revision="26.2", cache=cache, transport=transport)
    assert len(requested) == 1
