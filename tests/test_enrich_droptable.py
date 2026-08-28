"""Mob drops: the edition split, the exact fractions, and the conditions.

`pipeline.enrich.droptable` reads a bucket whose JSON blob holds both editions
side by side. 67 of its 233 rows have no `java` key at all, and every one of
those is a drop that does not happen in the edition this project covers.

The rows below are shaped like the live ones, and `parse_drop_tables` is pure,
so nothing here opens a socket.
"""

import json
from typing import Any

import pytest

from pipeline.enrich import EnrichError
from pipeline.enrich.droptable import (
    DropIndex,
    MobDrop,
    Ratio,
    parse_drop_tables,
)


def level(
    *,
    minimum: int = 0,
    maximum: int = 2,
    chance: tuple[int, int] = (2, 3),
    average: tuple[int, int] = (1, 1),
    distribution: dict[str, tuple[int, int]] | None = None,
    text: str = "0&ndash;2",
) -> dict[str, Any]:
    """Return one looting level of a `java` object."""
    spread = distribution if distribution is not None else {"0": (1, 3), "1": (1, 3), "2": (1, 3)}
    return {
        "min": minimum,
        "max": maximum,
        "dropchance": {"numerator": chance[0], "denominator": chance[1]},
        "average": {"numerator": average[0], "denominator": average[1]},
        "distribution": {
            count: {"numerator": ratio[0], "denominator": ratio[1]}
            for count, ratio in spread.items()
        },
        "quantitytext": text,
    }


def row(
    page: str,
    item: str,
    *,
    java: dict[str, Any] | None = None,
    bedrock: dict[str, Any] | None = None,
    notes: Any = None,
    name: str | None = None,
) -> dict[str, Any]:
    """Return one `droptable` row, shaped the way the live API sends it.

    `notes` defaults to the empty list, because that is what the live rows carry
    when a drop has no condition: the wiki's notes are a PHP array, and PHP
    encodes an empty one as `[]` and a populated one as an object.
    """
    document: dict[str, Any] = {
        "name": name if name is not None else page,
        "notes": [] if notes is None else notes,
    }
    if java is not None:
        document["java"] = java
    if bedrock is not None:
        document["bedrock"] = bedrock
    return {"page_name": page, "item": item, "json": json.dumps(document)}


def test_a_java_drop_keeps_every_looting_level_in_order() -> None:
    """Looting is the whole reason a drop table is not one number."""
    index = parse_drop_tables(
        [
            row(
                "Skeleton",
                "Arrow",
                java={"3": level(maximum=5), "0": level(), "1": level(), "2": level()},
            )
        ]
    )

    drop = index.by_mob["Skeleton"][0]
    assert [entry.looting_level for entry in drop.by_looting_level] == [0, 1, 2, 3]
    looting_three = drop.at_looting(3)
    assert looting_three is not None
    assert looting_three.maximum == 5


def test_a_bedrock_only_drop_is_skipped_and_reported() -> None:
    """A row with no `java` key is a drop this edition does not have.

    67 of the 233 live rows are in this state -- the spider's spider eye among
    them. Reporting them is what separates "the wiki has 166 Java drops" from
    "the scrape lost a third of the table".
    """
    index = parse_drop_tables([row("Spider", "Spider Eye", bedrock={"0": level()})])

    assert index.drops == ()
    assert index.skipped[0].subject == "Spider Eye"
    assert "Bedrock Edition only" in index.skipped[0].reason


def test_the_bedrock_numbers_are_never_read_even_when_java_is_present() -> None:
    """The two editions disagree on the same drop, so one must not leak into the other."""
    index = parse_drop_tables(
        [
            row(
                "Skeleton",
                "Arrow",
                java={"0": level(chance=(2, 3))},
                bedrock={"0": level(chance=(1, 9))},
            )
        ]
    )

    drop = index.by_mob["Skeleton"][0]
    assert len(drop.by_looting_level) == 1
    assert drop.by_looting_level[0].drop_chance == Ratio(numerator=2, denominator=3)


def test_probabilities_stay_exact_fractions() -> None:
    """A third rendered as a rounded decimal is a number a player can see is wrong."""
    index = parse_drop_tables(
        [row("Zombie", "Rotten Flesh", java={"0": level(distribution={"1": (1, 3)})})]
    )

    chance = index.drops[0].by_looting_level[0].distribution[1]
    assert (chance.numerator, chance.denominator) == (1, 3)
    assert chance.value == pytest.approx(1 / 3)


def test_a_condition_on_a_drop_is_kept() -> None:
    """A zombie's iron ingot needs a player kill; without the note it reads as free."""
    index = parse_drop_tables(
        [
            row(
                "Zombie",
                "Iron Ingot",
                java={"0": level()},
                notes={
                    "1": {
                        "name": "player_or_pet",
                        "content": "Only when killed by a [[player]] or a tamed [[wolf]].",
                    }
                },
            )
        ]
    )

    note = index.drops[0].notes[0]
    assert note.name == "player_or_pet"
    assert note.content.startswith("Only when killed by a [[player]]")


def test_notes_are_ordered_by_their_number_not_by_their_text() -> None:
    """String order puts `10` before `9`, which is the wrong order to render."""
    index = parse_drop_tables(
        [
            row(
                "Zombie",
                "Carrot",
                java={"0": level()},
                notes={
                    "10": {"name": "tenth", "content": "tenth"},
                    "9": {"name": "ninth", "content": "ninth"},
                },
            )
        ]
    )

    assert [note.name for note in index.drops[0].notes] == ["ninth", "tenth"]


def test_an_empty_notes_list_means_no_condition() -> None:
    """PHP encodes an empty array as `[]`, so the field's JSON type changes with its contents."""
    index = parse_drop_tables([row("Zombie", "Rotten Flesh", java={"0": level()})])

    assert index.drops[0].notes == ()


def test_the_quantity_text_is_unescaped() -> None:
    """`0&ndash;2` is what the wiki sends and not what a page should show."""
    index = parse_drop_tables([row("Zombie", "Rotten Flesh", java={"0": level()})])

    assert index.drops[0].by_looting_level[0].quantity_text == "0–2"


def test_the_mob_name_comes_from_the_blob_not_the_page_title() -> None:
    """A page can document more than one mob, and the blob says which one dropped."""
    index = parse_drop_tables(
        [row("Zombie Villager", "Rotten Flesh", java={"0": level()}, name="Zombie Villager")]
    )

    assert index.drops[0].mob == "Zombie Villager"


def test_a_malformed_java_object_raises() -> None:
    """The blob is machine-written, so one bad row means the template moved."""
    with pytest.raises(EnrichError):
        parse_drop_tables([row("Zombie", "Rotten Flesh", java={"0": {"min": 0}})])


def test_a_looting_level_outside_the_enchantments_range_raises() -> None:
    """Looting III is the maximum, so a fourth level is a shape change, not data."""
    with pytest.raises(EnrichError, match="outside 0 to 3"):
        parse_drop_tables([row("Zombie", "Rotten Flesh", java={"7": level()})])


def test_a_ratio_with_a_zero_denominator_is_refused() -> None:
    """A fraction with no value would divide by zero the first time it rendered."""
    with pytest.raises(EnrichError, match="denominator"):
        Ratio(numerator=1, denominator=0)


def test_an_index_that_does_not_index_its_own_drops_is_refused() -> None:
    """The lookups are fields on a frozen model, so they are checked, not trusted."""
    drop = MobDrop(
        mob="Zombie",
        item="Rotten Flesh",
        page="Zombie",
        wiki_url="https://minecraft.wiki/w/Zombie",
        notes=(),
        by_looting_level=(),
    )
    with pytest.raises(EnrichError, match="mob index"):
        DropIndex(drops=(drop,), by_mob={}, by_item={})
