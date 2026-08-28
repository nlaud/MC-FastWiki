"""The enrich stage against rows the wiki actually sent.

Every other test of this stage builds its rows in memory, one trap per test. That
proves the parsers do what their authors intended and proves nothing about
whether the intention matches the live table. This module reads
`tests/fixtures/wiki_bucket_rows.json`, which
`tests/fixtures/build_bucket_row_snapshot.py` captured from the Bucket API, and
checks facts a person can verify against the game and against the wiki page.

It opens no socket. The rows are on disk.

**A failure here is a question, not a verdict.** The wiki has no version to pin
to -- it is edited continuously -- so an assertion that goes red means either
the parser changed or the wiki did, and the two are told apart by reading the
page named in the failing test. When it is the wiki, rebuild the fixture, read
the diff, and update the assertion. When it is the parser, the fixture is doing
its job.
"""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from pipeline.enrich.advancement import parse_advancements
from pipeline.enrich.crafting_recipe import parse_crafting_recipes
from pipeline.enrich.droptable import parse_drop_tables
from pipeline.enrich.resource_location import parse_resource_locations
from pipeline.enrich.spawn_table import parse_spawn_tables
from pipeline.enrich.trade import parse_trades

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "wiki_bucket_rows.json"


@pytest.fixture(scope="module")
def snapshot() -> dict[str, Any]:
    """Return the whole snapshot document."""
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def rows_of(snapshot: dict[str, Any], bucket: str) -> list[dict[str, Any]]:
    """Return every row the snapshot holds for `bucket`, slices concatenated.

    The slices exist to keep the fixture small and reviewable, not to be read
    separately: a parser sees one table, so the tests give it one.
    """
    slices: dict[str, Sequence[dict[str, Any]]] = snapshot["buckets"][bucket]
    return [row for rows in slices.values() for row in rows]


def test_the_snapshot_records_where_and_when_it_came_from(snapshot: dict[str, Any]) -> None:
    """A fixture of live data is only interpretable with its provenance.

    There is no Minecraft version to pin here, so the date is what tells a
    reader how old a disagreement with the live wiki might be.
    """
    assert snapshot["api_url"] == "https://minecraft.wiki/api.php"
    assert snapshot["captured"]
    assert "CC BY-NC-SA" in snapshot["note"]


# --- resource_location -----------------------------------------------------


def test_the_join_table_holds_only_java_main_namespace_rows(snapshot: dict[str, Any]) -> None:
    """The slice carries a Bedrock row of Stone and a meme page, and neither survives."""
    table = parse_resource_locations(rows_of(snapshot, "resource_location"))

    assert table.resolve("Stone") == "minecraft:stone"
    assert "Bucketolotl" not in table.by_display_name
    reasons = {skip.reason for skip in table.skipped}
    assert "the row is bedrock edition, not java" in reasons
    assert any("User: page" in reason for reason in reasons)


def test_the_ambiguous_eye_of_ender_is_separated_by_kind(snapshot: dict[str, Any]) -> None:
    """The item is `ender_eye` and the entity is `eye_of_ender`. Verifiable in game."""
    table = parse_resource_locations(rows_of(snapshot, "resource_location"))

    assert table.resolve("Eye of Ender", kind="item") == "minecraft:ender_eye"
    assert table.resolve("Eye of Ender", kind="entity") == "minecraft:eye_of_ender"


def test_an_escaped_name_from_the_live_api_becomes_a_usable_key(
    snapshot: dict[str, Any],
) -> None:
    """The wiki really does send `Bottle o&#39; Enchanting`."""
    raw = rows_of(snapshot, "resource_location")
    assert any("&#39;" in str(row.get("display_name", "")) for row in raw)

    table = parse_resource_locations(raw)
    assert table.resolve("Bottle o' Enchanting") == "minecraft:experience_bottle"


# --- droptable -------------------------------------------------------------


def test_the_skeletons_arrow_keeps_four_looting_levels(snapshot: dict[str, Any]) -> None:
    """Looting III takes the arrow drop from 0-2 to 0-5. Verifiable in game."""
    index = parse_drop_tables(rows_of(snapshot, "droptable"))

    arrow = next(drop for drop in index.by_mob["Skeleton"] if drop.item == "Arrow")
    assert [entry.looting_level for entry in arrow.by_looting_level] == [0, 1, 2, 3]

    unenchanted = arrow.at_looting(0)
    looting_three = arrow.at_looting(3)
    assert unenchanted is not None
    assert looting_three is not None
    assert (unenchanted.minimum, unenchanted.maximum) == (0, 2)
    assert (looting_three.minimum, looting_three.maximum) == (0, 5)


def test_the_zombies_iron_ingot_keeps_its_player_kill_condition(
    snapshot: dict[str, Any],
) -> None:
    """Without the note the drop reads as free, which is a better rate than the game gives."""
    index = parse_drop_tables(rows_of(snapshot, "droptable"))

    iron = next(drop for drop in index.by_mob["Zombie"] if drop.item == "Iron Ingot")
    assert [note.name for note in iron.notes] == ["player_or_pet"]
    assert "player" in iron.notes[0].content


def test_the_spiders_bedrock_only_spider_eye_row_is_dropped(snapshot: dict[str, Any]) -> None:
    """The wiki writes the spider eye twice, once per edition. Non-negotiable 1.

    The two rows are the clearest case in the whole bucket: same page, same
    item, one with a `java` key and one with only a `bedrock` key. A reader that
    ignored the split would keep both and show the drop twice with two different
    sets of numbers.
    """
    raw = [row for row in rows_of(snapshot, "droptable") if row["item"] == "Spider Eye"]
    assert len(raw) == 2

    index = parse_drop_tables(rows_of(snapshot, "droptable"))
    assert [drop.item for drop in index.by_mob["Spider"]] == ["String", "Spider Eye"]
    assert index.skipped[0].subject == "Spider Eye"
    assert "Bedrock Edition only" in index.skipped[0].reason


# --- spawn_table -----------------------------------------------------------


def test_the_taiga_spawns_the_cold_chicken_not_the_chicken(snapshot: dict[str, Any]) -> None:
    """The `mob` column says `Chicken` and the blob says `Cold Chicken`.

    The variant is what actually spawns, so the entry is filed under it, and the
    page link still points at `Chicken`, which is the article that documents it.
    """
    index = parse_spawn_tables(rows_of(snapshot, "spawn_table"))

    chicken = next(entry for entry in index.by_biome["Taiga"] if "Chicken" in entry.mob)
    assert chicken.mob == "Cold Chicken"
    assert chicken.mob_page == "Chicken"


def test_the_deserts_bedrock_rows_are_dropped(snapshot: dict[str, Any]) -> None:
    """`Edition` is inside the JSON column, so this filter is the pipeline's alone."""
    index = parse_spawn_tables(rows_of(snapshot, "spawn_table"))

    assert index.skipped
    assert all(skip.reason.endswith("edition, not java") for skip in index.skipped)
    assert "Husk" in {entry.mob for entry in index.by_biome["Desert"]}


def test_a_desert_spawn_carries_a_weight_share(snapshot: dict[str, Any]) -> None:
    """The share is the number worth rendering; a bare weight says nothing."""
    index = parse_spawn_tables(rows_of(snapshot, "spawn_table"))

    creeper = next(entry for entry in index.by_biome["Desert"] if entry.mob == "Creeper")
    assert creeper.share is not None
    assert 0 < creeper.share < 1


# --- crafting_recipe -------------------------------------------------------


def test_the_live_wooden_pickaxe_row_pins_the_grid_orientation(
    snapshot: dict[str, Any],
) -> None:
    """Planks across the top, sticks down the middle. Verifiable in game."""
    index = parse_crafting_recipes(rows_of(snapshot, "crafting_recipe"))

    pickaxe = index.by_output["Wooden Pickaxe"][0]
    assert pickaxe.trimmed_grid == (
        ("Any Planks", "Any Planks", "Any Planks"),
        (None, "Stick", None),
        (None, "Stick", None),
    )


def test_the_live_torch_row_packs_coal_and_charcoal(snapshot: dict[str, Any]) -> None:
    """One row, two recipes, four torches each. Verifiable in game."""
    index = parse_crafting_recipes(rows_of(snapshot, "crafting_recipe"))

    torches = index.by_output["Torch"]
    assert [recipe.trimmed_grid for recipe in torches] == [
        (("Coal",), ("Stick",)),
        (("Charcoal",), ("Stick",)),
    ]
    assert {recipe.output.count for recipe in torches} == {4}


def test_the_live_fence_row_stays_collapsed(snapshot: dict[str, Any]) -> None:
    """Decision 9: one row reading "any plank type" rather than thirteen rows."""
    index = parse_crafting_recipes(rows_of(snapshot, "crafting_recipe"))

    fence = index.by_output["Matching Wooden Fence"][0]
    assert fence.is_collapsed
    assert fence.output.count == 3
    assert "Matching Planks" in fence.ingredients


def test_the_live_glow_stick_and_map_be_rows_are_dropped(snapshot: dict[str, Any]) -> None:
    """Two different Bedrock marks: the prose one and the output-name one."""
    index = parse_crafting_recipes(rows_of(snapshot, "crafting_recipe"))

    assert "Map BE" not in index.by_output
    assert not any("Glow Stick" in name for name in index.by_output)
    reasons = {skip.reason for skip in index.skipped}
    assert "the description marks this recipe Bedrock Edition only" in reasons
    assert "the output is named as the Bedrock Edition variant" in reasons


def test_the_live_map_row_that_does_not_line_up_is_reported(snapshot: dict[str, Any]) -> None:
    """One of the nine live rows whose packed columns are ragged.

    It is reported rather than guessed at, because a guess would attach a real
    ingredient to the wrong recipe.
    """
    index = parse_crafting_recipes(rows_of(snapshot, "crafting_recipe"))

    assert any("do not line up" in skip.reason for skip in index.skipped)


# --- advancement -----------------------------------------------------------


def test_the_live_advancement_page_has_five_roots_and_no_duplicate_ids(
    snapshot: dict[str, Any],
) -> None:
    """One root per tab, which is what the game's advancement screen shows."""
    tree = parse_advancements(rows_of(snapshot, "advancement"))

    assert set(tree.roots) == {
        "story/root",
        "nether/root",
        "end/root",
        "adventure/root",
        "husbandry/root",
    }
    assert len(tree.by_id) == len(tree.advancements)


def test_the_2017_snapshot_rows_are_dropped(snapshot: dict[str, Any]) -> None:
    """They carry internal IDs that collide with the live ones.

    The fixture holds three of them from `Java Edition 17w13a`. Without the page
    filter one of them would win the `story/root` key.
    """
    tree = parse_advancements(rows_of(snapshot, "advancement"))

    assert tree.skipped
    assert all("not on Advancement" in skip.reason for skip in tree.skipped)
    assert tree.by_id["story/root"].title == "Minecraft"


def test_a_live_advancement_keeps_its_title_parent_and_reward(
    snapshot: dict[str, Any],
) -> None:
    """`story/iron_tools` is `Isn't It Iron Pick`, under `Acquire Hardware`."""
    tree = parse_advancements(rows_of(snapshot, "advancement"))

    pick = tree.by_id["story/iron_tools"]
    assert pick.title == "Isn't It Iron Pick"
    assert pick.parent_id == "story/smelt_iron"
    assert next(iter(tree.ancestry("story/iron_tools"))).internal_id == "story/root"


def test_at_least_one_live_advancement_rewards_experience(snapshot: dict[str, Any]) -> None:
    """The number is buried in rendered HTML beside a sprite class that looks like it."""
    tree = parse_advancements(rows_of(snapshot, "advancement"))

    rewards = [entry.experience for entry in tree.advancements if entry.experience is not None]
    assert rewards
    assert all(reward > 0 for reward in rewards)


# --- trade -----------------------------------------------------------------


def test_the_live_librarian_trades_group_into_the_villager_ladder(
    snapshot: dict[str, Any],
) -> None:
    """Novice through Master, in that order, which is how the page reads."""
    index = parse_trades(rows_of(snapshot, "trade"))

    levels = [level for level, _ in index.by_level("Librarian")]
    assert levels == ["Novice", "Apprentice", "Journeyman", "Expert", "Master"]


def test_the_live_enchanted_book_trade_wants_two_items_and_a_price_range(
    snapshot: dict[str, Any],
) -> None:
    """5-64 emeralds and a book. The range is why a quantity cannot be an `int`."""
    index = parse_trades(rows_of(snapshot, "trade"))

    book = index.by_given_item["Enchanted Book"][0]
    assert [item.item for item in book.wanted] == ["Emerald", "Book"]
    assert book.wanted[0].quantity.minimum == 5
    assert book.wanted[0].quantity.maximum == 64


def test_the_live_trades_keep_java_probabilities_and_no_bedrock_ones(
    snapshot: dict[str, Any],
) -> None:
    """The raw rows carry both fields; nothing parsed carries the Bedrock one."""
    raw = rows_of(snapshot, "trade")
    assert all("bedrock_probability" in row["json"] for row in raw)

    index = parse_trades(raw)
    assert all(trade.java_probability is not None for trade in index.trades)
    assert "bedrock" not in json.dumps(
        [trade.model_dump(mode="json") for trade in index.trades]
    )
