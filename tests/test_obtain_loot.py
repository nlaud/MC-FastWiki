"""`pipeline.obtain.loot`: block/chest loot tables inverted, and two Tier B indexes turned around.

The block/chest shapes here were verified live against `diamond_ore.json`,
`coal_ore.json`, and `simple_dungeon.json` on 2026-09-01, and they disagree
with this task's own implementation notes on two points -- see the module
docstring for the correction. These tests pin the corrected shapes down.
"""

import json
from collections.abc import Mapping
from typing import Any

import pytest

from pipeline.enrich import IntegerRange
from pipeline.enrich.droptable import DropIndex, MobDrop
from pipeline.enrich.resource_location import JoinTable, ResourceLocation
from pipeline.enrich.trade import TradeIndex, TradeItem, WikiTrade
from pipeline.obtain import ObtainError
from pipeline.obtain.loot import (
    BLOCK_LOOT_DIRECTORY,
    CHEST_LOOT_DIRECTORY,
    extract_block_and_chest_loot,
    producers_from_drop_index,
    producers_from_trade_index,
)
from pipeline.obtain.producer import ObtainMethod


def archive(*, blocks: Mapping[str, Any] = {}, chests: Mapping[str, Any] = {}) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for name, document in blocks.items():
        files[f"{BLOCK_LOOT_DIRECTORY}/{name}.json"] = json.dumps(document).encode()
    for name, document in chests.items():
        files[f"{CHEST_LOOT_DIRECTORY}/{name}.json"] = json.dumps(document).encode()
    return files


# The real shape of `diamond_ore.json`, verified live 2026-09-01: silk touch
# gates the "drop the block itself" branch through `minecraft:match_tool`,
# never through `minecraft:tool/can_silk_touch`.
DIAMOND_ORE = {
    "type": "minecraft:block",
    "pools": [
        {
            "rolls": 1.0,
            "entries": [
                {
                    "type": "minecraft:alternatives",
                    "children": [
                        {
                            "type": "minecraft:item",
                            "name": "minecraft:diamond_ore",
                            "conditions": [
                                {
                                    "condition": "minecraft:match_tool",
                                    "predicate": {
                                        "predicates": {
                                            "minecraft:enchantments": [
                                                {
                                                    "enchantments": "minecraft:silk_touch",
                                                    "levels": {"min": 1},
                                                }
                                            ]
                                        }
                                    },
                                }
                            ],
                        },
                        {
                            "type": "minecraft:item",
                            "name": "minecraft:diamond",
                            "functions": [
                                {
                                    "function": "minecraft:apply_bonus",
                                    "enchantment": "minecraft:fortune",
                                    "formula": "minecraft:ore_drops",
                                }
                            ],
                        },
                    ],
                }
            ],
        }
    ],
}


def test_the_silk_touch_branch_of_a_real_ore_table_carries_the_note() -> None:
    files = archive(blocks={"diamond_ore": DIAMOND_ORE})
    result = extract_block_and_chest_loot(files)
    by_item = {p.output.item: p for p in result.producers}
    assert by_item["minecraft:diamond_ore"].note == "requires silk touch"
    assert by_item["minecraft:diamond"].note is None


def test_both_branches_of_an_alternatives_block_input_the_block_itself() -> None:
    files = archive(blocks={"diamond_ore": DIAMOND_ORE})
    result = extract_block_and_chest_loot(files)
    for producer in result.producers:
        assert producer.method is ObtainMethod.BLOCK_DROP
        assert [i.item for i in producer.inputs] == ["minecraft:diamond_ore"]


def test_set_count_reads_the_uniform_minimum_not_a_modifier_field() -> None:
    """The real shape is `entry.functions[]`, never a bare `entry.modifier`."""
    files = archive(
        blocks={
            "gravel": {
                "type": "minecraft:block",
                "pools": [
                    {
                        "rolls": 1.0,
                        "entries": [
                            {
                                "type": "minecraft:item",
                                "name": "minecraft:flint",
                                "functions": [
                                    {
                                        "function": "minecraft:set_count",
                                        "count": {
                                            "type": "minecraft:uniform",
                                            "min": 2.0,
                                            "max": 5.0,
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        }
    )
    result = extract_block_and_chest_loot(files)
    assert result.producers[0].output.count == 2


def test_chest_loot_carries_no_inputs_and_the_weight_is_ignored() -> None:
    files = archive(
        chests={
            "simple_dungeon": {
                "type": "minecraft:chest",
                "pools": [
                    {
                        "rolls": {"type": "minecraft:uniform", "min": 1.0, "max": 3.0},
                        "entries": [
                            {"type": "minecraft:item", "name": "minecraft:name_tag", "weight": 20},
                        ],
                    }
                ],
            }
        }
    )
    result = extract_block_and_chest_loot(files)
    producer = result.producers[0]
    assert producer.method is ObtainMethod.CHEST_LOOT
    assert producer.inputs == ()
    assert producer.output.item == "minecraft:name_tag"


def test_an_entry_type_that_names_no_concrete_item_is_skipped_and_reported() -> None:
    files = archive(
        blocks={
            "shulker_box": {
                "type": "minecraft:block",
                "pools": [{"rolls": 1.0, "entries": [{"type": "minecraft:dynamic", "name": "x"}]}],
            }
        }
    )
    result = extract_block_and_chest_loot(files)
    assert result.producers == ()
    assert result.skipped[0].entry_type == "minecraft:dynamic"


def test_nested_group_and_sequence_containers_are_walked_too() -> None:
    files = archive(
        blocks={
            "nested": {
                "type": "minecraft:block",
                "pools": [
                    {
                        "rolls": 1.0,
                        "entries": [
                            {
                                "type": "minecraft:group",
                                "children": [
                                    {
                                        "type": "minecraft:sequence",
                                        "children": [
                                            {"type": "minecraft:item", "name": "minecraft:stick"}
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        }
    )
    result = extract_block_and_chest_loot(files)
    assert result.producers[0].output.item == "minecraft:stick"


def test_no_block_or_chest_file_at_all_raises() -> None:
    with pytest.raises(ObtainError, match="broken scrape"):
        extract_block_and_chest_loot({})


# The real shape of `loot_table/blocks/budding_amethyst.json`, verified live
# 2026-09-01: a `type` and a `random_sequence`, and no `pools` key at all,
# because breaking budding amethyst by hand yields nothing.
BUDDING_AMETHYST = {
    "type": "minecraft:block",
    "random_sequence": "minecraft:blocks/budding_amethyst",
}

# An ordinary one-item block table, for the half of the case that must still
# produce a drop while the pool-less table beside it produces none.
STICK_BLOCK = {
    "type": "minecraft:block",
    "pools": [{"rolls": 1.0, "entries": [{"type": "minecraft:item", "name": "minecraft:stick"}]}],
}


def test_a_block_table_with_no_pools_key_drops_nothing_rather_than_raising() -> None:
    """A missing `pools` is the game's answer, not a broken read.

    This is the case the first real end-to-end build of this stage died on.
    Every unit test until now built its own tables and gave all of them a
    `pools`, so nothing exercised the shape mcmeta actually ships for a block
    that drops no item, and a whole build failed on the first one it met.
    """
    files = archive(blocks={"budding_amethyst": BUDDING_AMETHYST, "stick_block": STICK_BLOCK})
    result = extract_block_and_chest_loot(files)

    outputs = {producer.output.item for producer in result.producers}
    assert "minecraft:stick" in outputs
    assert not any("budding_amethyst" in producer.source_id for producer in result.producers)


def test_a_pools_that_is_present_but_not_a_list_still_raises() -> None:
    """The absence of a key and a malformed value are different faults.

    Reading a missing `pools` as "drops nothing" must not also swallow a
    `pools` mcmeta has never shipped, which would mean the archive changed
    shape under the pipeline.
    """
    files = archive(blocks={"broken": {"type": "minecraft:block", "pools": {"not": "a list"}}})
    with pytest.raises(ObtainError, match="not a list"):
        extract_block_and_chest_loot(files)


# --- Tier B inversion: mob loot -----------------------------------------------


def join_table(*rows: ResourceLocation) -> JoinTable:
    return JoinTable.build(rows)


def resource(name: str, path: str, kind: str) -> ResourceLocation:
    """One join-table row. `path` is unprefixed, matching `resource_location`'s own shape."""
    return ResourceLocation(
        display_name=name,
        resource_location=path,
        kind=kind,
        page=name,
        wiki_url=f"https://minecraft.wiki/w/{name}",
    )


def mob_drop(mob: str, item: str) -> MobDrop:
    return MobDrop(
        mob=mob,
        item=item,
        page=mob,
        wiki_url=f"https://minecraft.wiki/w/{mob}",
        notes=(),
        by_looting_level=(),
    )


def test_a_resolvable_mob_drop_becomes_a_producer_with_no_inputs() -> None:
    drops = DropIndex.build([mob_drop("Zombie", "Rotten Flesh")])
    table = join_table(
        resource("Zombie", "zombie", "entity"),
        resource("Rotten Flesh", "rotten_flesh", "item"),
    )
    producers, unresolved = producers_from_drop_index(drops, join_table=table)
    assert unresolved == ()
    assert len(producers) == 1
    producer = producers[0]
    assert producer.method is ObtainMethod.MOB_LOOT
    assert producer.output.item == "minecraft:rotten_flesh"
    assert producer.inputs == ()
    assert producer.note == "dropped by Zombie"


def test_an_unresolvable_mob_name_is_reported_and_the_drop_is_dropped() -> None:
    drops = DropIndex.build([mob_drop("Sharing", "Rotten Flesh")])
    table = join_table(resource("Rotten Flesh", "rotten_flesh", "item"))
    producers, unresolved = producers_from_drop_index(drops, join_table=table)
    assert producers == ()
    assert unresolved[0].subject == "Sharing"
    assert unresolved[0].reason == "the mob name did not resolve"


def test_a_raw_chicken_item_does_not_resolve_through_the_chicken_mobs_row() -> None:
    """The `join_kinds` narrowing this module mirrors from `pipeline.normalize.merge.WIKI_KIND`.

    Both an item and an entity row share the display name `Chicken` on the
    live wiki; a narrowed lookup must not let the entity row answer for the
    item.
    """
    drops = DropIndex.build([mob_drop("Chicken", "Chicken")])
    table = join_table(
        resource("Chicken", "chicken", "entity"),
        resource("Chicken", "chicken", "item"),
    )
    producers, _unresolved = producers_from_drop_index(drops, join_table=table)
    assert len(producers) == 1
    assert producers[0].output.item == "minecraft:chicken"


# --- Tier B inversion: trades --------------------------------------------------


def trade_item(name: str, count: int = 1) -> TradeItem:
    return TradeItem(item=name, quantity=IntegerRange(minimum=count, maximum=count))


def test_a_resolvable_trade_becomes_a_producer_with_the_wanted_items_as_inputs() -> None:
    trade = WikiTrade(
        profession="Librarian",
        page="Librarian",
        wiki_url="https://minecraft.wiki/w/Librarian",
        level="Novice",
        wanted=(trade_item("Emerald", 5),),
        given=trade_item("Enchanted Book"),
        java_probability=None,
        max_trades=None,
        villager_xp=None,
        price_multiplier=None,
    )
    trades = TradeIndex.build([trade])
    table = join_table(
        resource("Emerald", "emerald", "item"),
        resource("Enchanted Book", "enchanted_book", "item"),
    )
    producers, unresolved = producers_from_trade_index(trades, join_table=table)
    assert unresolved == ()
    producer = producers[0]
    assert producer.method is ObtainMethod.TRADE
    assert producer.output.item == "minecraft:enchanted_book"
    assert producer.station == "villager"
    assert [i.item for i in producer.inputs] == ["minecraft:emerald"]
    assert producer.inputs[0].count == 5


def test_a_trade_whose_given_item_does_not_resolve_is_dropped_and_reported() -> None:
    trade = WikiTrade(
        profession="Librarian",
        page="Librarian",
        wiki_url="https://minecraft.wiki/w/Librarian",
        level="Novice",
        wanted=(trade_item("Emerald"),),
        given=trade_item("Mystery Item"),
        java_probability=None,
        max_trades=None,
        villager_xp=None,
        price_multiplier=None,
    )
    trades = TradeIndex.build([trade])
    table = join_table(resource("Emerald", "emerald", "item"))
    producers, unresolved = producers_from_trade_index(trades, join_table=table)
    assert producers == ()
    assert unresolved[0].reason == "the given item did not resolve"


# --- Display-name resolution: the two narrower routes --------------------------


def resource_on_page(
    page: str, name: str, path: str, kind: str
) -> ResourceLocation:
    """One join-table row whose wiki page title differs from its display name."""
    return ResourceLocation(
        display_name=name,
        resource_location=path,
        kind=kind,
        page=page,
        wiki_url=f"https://minecraft.wiki/w/{page}",
    )


def test_a_display_name_shared_by_two_items_resolves_through_its_own_page() -> None:
    """The live "Potato" collision, which a plain display-name lookup loses.

    26.2's join table maps the display name "Potato" onto the crop block
    `potatoes`, the item `potato`, and `snektato` -- an April Fools item on
    the page "Venomous Potato" whose display name is also "Potato". Narrowing
    by kind removes the block and still leaves two items, so the lookup gave
    up, and four real potato drops and trades went missing from the first
    full build of this stage. The row whose page title *is* the name being
    looked up is the one the wiki treats as canonical for that name.
    """
    table = join_table(
        resource_on_page("Potato", "Potatoes", "potatoes", "block"),
        resource_on_page("Potato", "Potato", "potato", "item"),
        resource_on_page("Venomous Potato", "Potato", "snektato", "item"),
    )
    drops = DropIndex.build([mob_drop("Zombie", "Potato")])
    producers, unresolved = producers_from_drop_index(
        drops, join_table=join_table(*table.entries, resource("Zombie", "zombie", "entity"))
    )

    assert unresolved == ()
    assert [p.output.item for p in producers] == ["minecraft:potato"]


def test_a_disambiguated_page_title_resolves_even_though_it_is_nobody_s_display_name() -> None:
    """The `trade` bucket asks for "Pufferfish (item)"; the display name is the bare word.

    The wiki suffixes the page of an item that shares its name with a mob, so
    the name arriving from Tier B matches no display name at all and only the
    page title can answer it.
    """
    table = join_table(
        resource("Guardian", "guardian", "entity"),
        resource_on_page("Pufferfish", "Pufferfish", "pufferfish", "entity"),
        resource_on_page("Pufferfish (item)", "Pufferfish", "pufferfish", "item"),
    )
    drops = DropIndex.build([mob_drop("Guardian", "Pufferfish (item)")])
    producers, unresolved = producers_from_drop_index(drops, join_table=table)

    assert unresolved == ()
    assert [p.output.item for p in producers] == ["minecraft:pufferfish"]


def test_a_name_that_is_a_variant_group_is_still_reported_rather_than_guessed_at() -> None:
    """"Any color Wool" names 16 registry IDs. Picking one of them would be a wrong answer."""
    table = join_table(
        resource("Sheep", "sheep", "entity"),
        resource_on_page("Wool", "White Wool", "white_wool", "block"),
        resource_on_page("Wool", "Orange Wool", "orange_wool", "block"),
    )
    drops = DropIndex.build([mob_drop("Sheep", "Any color Wool")])
    producers, unresolved = producers_from_drop_index(drops, join_table=table)

    assert producers == ()
    assert [u.subject for u in unresolved] == ["Any color Wool"]
