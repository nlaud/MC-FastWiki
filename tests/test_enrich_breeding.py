"""Tests for `pipeline.enrich.breeding`.

Exercises the Breeding foods wikitable parser against valid, multi-mob,
edition-scoped, and malformed rows.
"""

import pytest

from pipeline.enrich import EnrichError
from pipeline.enrich.breeding import (
    BREEDING_COOLDOWN_SECONDS,
    DEFAULT_BABY_GROWTH_SECONDS,
    PAGE_TITLE,
    SLOW_GROWTH_SECONDS,
    fetch_breeding,
    parse_breeding,
)
from pipeline.fetch.cache import ContentCache
from pipeline.fetch.wikitext import build_wikitext_url

_VALID_TABLE = """
{| class="wikitable sortable" data-description="Breeding foods" border="1"
|-
!Mob
!Items
!Other
|-
|
*{{EntityLink|Horse}} (Tamed)
*{{EntityLink|Donkey}} (Tamed)
|
*{{ItemLink|Golden Apple}}
*{{ItemLink|Enchanted Golden Apple}}
*{{ItemLink|Golden Carrot}}
|Tamed by mounting.
|-
|
*{{EntityLink|Cow}}
*{{EntityLink|Goat}}
*{{EntityLink|Mooshroom}}
*{{EntityLink|Sheep}}
|
*{{ItemLink|Wheat}}
|Eats grass.
|-
|{{EntityLink|id=tamed-wolf|Wolf|Wolf}} (Tamed)
|
*{{ItemLink|Raw Beef}}
*{{ItemLink|Raw Chicken}}
*{{ItemLink|Raw Cod}} {{only|je|short=1}}
*{{ItemLink|Bedrock Exclusive Food}} {{only|be|short=1}}
|Tamed with bones.
|-
|
*{{EntityLink|Cat}} (Tamed)
*{{EntityLink|Ocelot}}
|
*{{ItemLink|Raw Cod}}
*{{ItemLink|Raw Salmon}}
|Tamed with fish.
|-
|{{EntityLink|Sniffer}}
|
*{{ItemLink|Torchflower Seeds}}
|Sniffers lay eggs.
|-
|{{EntityLink|Chicken}}
|
*{{ItemLink|Wheat Seeds}}
*{{ItemLink|Torchflower Seeds}}
|Chickens lay eggs.
|}
"""


def test_parse_breeding_happy_path() -> None:
    index = parse_breeding(_VALID_TABLE)
    assert len(index.by_mob) == 11
    assert index.skipped == ()

    cow = index.by_mob["Cow"]
    assert cow.mob == "Cow"
    assert cow.items == ("Wheat",)
    assert not cow.requires_taming

    horse = index.by_mob["Horse"]
    assert horse.mob == "Horse"
    assert horse.items == ("Golden Apple", "Enchanted Golden Apple", "Golden Carrot")
    assert horse.requires_taming


def test_multi_mob_row_shares_items() -> None:
    index = parse_breeding(_VALID_TABLE)
    assert index.by_mob["Cow"].items == ("Wheat",)
    assert index.by_mob["Goat"].items == ("Wheat",)
    assert index.by_mob["Mooshroom"].items == ("Wheat",)
    assert index.by_mob["Sheep"].items == ("Wheat",)


def test_taming_qualifier_is_per_mob() -> None:
    index = parse_breeding(_VALID_TABLE)
    # In the Cat + Ocelot row, Cat has (Tamed) and Ocelot does not
    assert index.by_mob["Cat"].requires_taming is True
    assert index.by_mob["Ocelot"].requires_taming is False


def test_wolf_breeding_items_exclude_bones_and_bedrock_items() -> None:
    index = parse_breeding(_VALID_TABLE)
    wolf = index.by_mob["Wolf"]
    assert wolf.requires_taming is True
    assert "Bone" not in wolf.items
    assert "Raw Beef" in wolf.items
    assert "Raw Chicken" in wolf.items
    assert "Raw Cod" in wolf.items  # marked {{only|je}}
    assert "Bedrock Exclusive Food" not in wolf.items  # marked {{only|be}}


def test_unreadable_rows_become_skipped() -> None:
    table_with_bad_rows = """
{| class="wikitable sortable" data-description="Breeding foods" border="1"
|-
!Mob
!Items
!Other
|-
|Just one cell
|-
|No entity link here
|{{ItemLink|Wheat}}
|-
|{{EntityLink|Pig}}
|No item templates here
|}
"""
    index = parse_breeding(table_with_bad_rows)
    assert len(index.by_mob) == 0
    assert len(index.skipped) == 3
    assert "fewer than 2 cells" in index.skipped[0].reason
    assert "no mob EntityLink" in index.skipped[1].reason
    assert "no Java breeding item" in index.skipped[2].reason


def test_missing_table_raises_enrich_error() -> None:
    with pytest.raises(EnrichError, match="contains no 'Breeding foods' table"):
        parse_breeding("Some random wikitext without the table.")


def test_empty_table_raises_enrich_error() -> None:
    empty_table = '{| data-description="Breeding foods"\n|}'
    with pytest.raises(EnrichError, match="empty 'Breeding foods' table"):
        parse_breeding(empty_table)


def test_fetch_breeding_over_transport(tmp_path: object) -> None:
    import json

    cache = ContentCache(tmp_path)  # type: ignore[arg-type]
    url = build_wikitext_url((PAGE_TITLE,))
    payload = json.dumps(
        {
            "batchcomplete": True,
            "query": {
                "pages": [
                    {
                        "pageid": 123,
                        "title": PAGE_TITLE,
                        "revisions": [{"slots": {"main": {"content": _VALID_TABLE}}}],
                    }
                ]
            },
        }
    ).encode("utf-8")

    def fake_transport(requested_url: str) -> bytes:
        if requested_url == url:
            return payload
        raise AssertionError(f"Unexpected fetch for {requested_url}")

    index = fetch_breeding(revision="26.2", cache=cache, transport=fake_transport)
    assert len(index.by_mob) == 11
    assert "Cow" in index.by_mob


def test_growth_time_is_keyed_on_the_mob_not_its_food() -> None:
    """A Sniffer grows in 40 minutes; a Chicken sharing its food still grows in 20."""
    index = parse_breeding(_VALID_TABLE)

    sniffer = index.by_mob["Sniffer"]
    chicken = index.by_mob["Chicken"]

    assert "Torchflower Seeds" in sniffer.items
    assert "Torchflower Seeds" in chicken.items

    assert sniffer.baby_growth_seconds == SLOW_GROWTH_SECONDS
    assert chicken.baby_growth_seconds == DEFAULT_BABY_GROWTH_SECONDS


def test_every_mob_carries_the_same_breeding_cooldown() -> None:
    """The page states one cooldown for all mobs, so every row carries it."""
    index = parse_breeding(_VALID_TABLE)

    assert index.by_mob
    assert all(m.cooldown_seconds == BREEDING_COOLDOWN_SECONDS for m in index.mobs)
