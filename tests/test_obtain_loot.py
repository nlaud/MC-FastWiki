"""`pipeline.obtain.loot`: block/chest loot tables inverted, and two Tier B indexes turned around.

The block/chest shapes here were verified live against `diamond_ore.json`,
`coal_ore.json`, and `simple_dungeon.json` on 2026-09-01, and they disagree
with this task's own implementation notes on two points -- see the module
docstring for the correction. These tests pin the corrected shapes down.
"""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from pipeline.enrich import IntegerRange
from pipeline.enrich.droptable import DropIndex, DropNote, LootingDrop, MobDrop, Ratio
from pipeline.enrich.resource_location import JoinTable, ResourceLocation
from pipeline.enrich.trade import TradeIndex, TradeItem, WikiTrade
from pipeline.obtain import ObtainError
from pipeline.obtain.chests import ChestSource
from pipeline.obtain.loot import (
    BLOCK_LOOT_DIRECTORY,
    CHEST_LOOT_DIRECTORY,
    SHEARS_NOTE,
    SILK_TOUCH_NOTE,
    SKIPPED_FAMILIES,
    _condition_gate,
    _predicate_index,
    extract_block_and_chest_loot,
    extract_loot,
    producers_from_drop_index,
    producers_from_trade_index,
    verify_loot_sources,
)
from pipeline.obtain.producer import ObtainMethod, Producer, ProducerOutput

# The committed snapshot of the pinned archive's tool gates. Rebuilt by hand with
# `python -m tests.fixtures.build_loot_gate_snapshot`; the name carries the version.
GATE_FIXTURE = "mcmeta_26_3_loot_gates.json"


def archive(*, blocks: Mapping[str, Any] = {}, chests: Mapping[str, Any] = {}) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for name, document in blocks.items():
        files[f"{BLOCK_LOOT_DIRECTORY}/{name}.json"] = json.dumps(document).encode()
    for name, document in chests.items():
        files[f"{CHEST_LOOT_DIRECTORY}/{name}.json"] = json.dumps(document).encode()
    return files


# `diamond_ore.json` with its silk-touch condition written inline. The real
# 26.3 file names `minecraft:tool/can_silk_touch` instead and the snapshot
# fixture carries that form; this one keeps the inline `minecraft:match_tool`
# object, because both spellings reach the reader and both must work.
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
                            "condition": {
                                "type": "minecraft:match_tool",
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
                            },
                        },
                        {
                            "type": "minecraft:item",
                            "name": "minecraft:diamond",
                            "modifier": [
                                {
                                    "type": "minecraft:apply_bonus",
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


def test_pool_level_silk_touch_gate_carries_note_and_retains_odds() -> None:
    """A pool-level silk-touch gate notes the requirement and retains its odds."""
    files = archive(
        blocks={
            "glass": {
                "type": "minecraft:block",
                "pools": [
                    {
                        "rolls": 1.0,
                        "condition": {
                            "type": "minecraft:match_tool",
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
                        },
                        "entries": [{"type": "minecraft:item", "name": "minecraft:glass"}],
                    }
                ],
            }
        }
    )
    result = extract_block_and_chest_loot(files)
    producer = result.producers[0]
    assert producer.output.item == "minecraft:glass"
    assert producer.note == "requires silk touch"
    assert producer.chance == 1.0
    assert producer.count_max == 1
    assert producer.per_attempt == 1.0


def test_pool_level_shears_gate_carries_shears_note() -> None:
    """A pool-level shears gate notes the shears requirement."""
    files = archive(
        blocks={
            "vine": {
                "type": "minecraft:block",
                "pools": [
                    {
                        "rolls": 1.0,
                        "condition": {
                            "type": "minecraft:match_tool",
                            "predicate": {"items": "minecraft:shears"},
                        },
                        "entries": [{"type": "minecraft:item", "name": "minecraft:vine"}],
                    }
                ],
            }
        }
    )
    result = extract_block_and_chest_loot(files)
    producer = result.producers[0]
    assert producer.output.item == "minecraft:vine"
    assert producer.note == "requires shears"
    assert producer.chance == 1.0


def test_ungated_pool_carries_no_gate_note() -> None:
    """An ordinary ungated block pool produces no tool gate note."""
    files = archive(
        blocks={
            "stone": {
                "type": "minecraft:block",
                "pools": [
                    {
                        "rolls": 1.0,
                        "entries": [{"type": "minecraft:item", "name": "minecraft:cobblestone"}],
                    }
                ],
            }
        }
    )
    result = extract_block_and_chest_loot(files)
    producer = result.producers[0]
    assert producer.note is None


def _gate_snapshot() -> dict[str, Any]:
    """Return the committed tool gate snapshot of the pinned archive.

    Read from disk, never fetched. `tests/fixtures/build_loot_gate_snapshot.py`
    is what opens the network, by hand, and its docstring holds the rebuild steps.
    """
    path = Path(__file__).parent / "fixtures" / GATE_FIXTURE
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


def _gate_files(snapshot: dict[str, Any]) -> dict[str, bytes]:
    """Return the snapshot's tables *and* its predicate registry, as a pack would hold them.

    The predicates travel in the snapshot because 26.3 stopped spelling a shared
    condition out in each table: 123 of them name `minecraft:tool/can_silk_touch`
    instead. A replay given the tables alone would read every one of those as
    ungated and still pass a test that only counted what it found, so the
    registry is part of the fixture rather than something the test invents.
    """
    files = {
        path: json.dumps(document).encode()
        for path, document in snapshot["tables"].items()
    }
    files.update(
        {
            path: json.dumps(document).encode()
            for path, document in snapshot.get("predicates", {}).items()
        }
    )
    return files


def test_the_gate_snapshot_names_the_archive_this_suite_pins() -> None:
    """A snapshot of another version answers another question, so the header is checked."""
    snapshot = _gate_snapshot()
    assert snapshot["version_id"] == "26.3"
    assert snapshot["tag"] == "26.3-data"
    assert snapshot["commit_sha"] == "538b2b167248c648b2198f2c0d56eced10dfc0cf"


def test_pool_level_tool_gates_across_the_pinned_archive() -> None:
    """76 block tables gate silk touch at the pool level, and 6 gate shears.

    The fault this pins is not that the gate was unreadable. It is that
    `_table_leaves` walked each pool's `entries` and never its own `conditions`,
    so every one of these 82 tables published an ungated, certain drop -- the site
    told a reader to break Glass and Bee Nest with their bare hands.
    """
    snapshot = _gate_snapshot()
    tables = snapshot["tables"]

    predicates = _predicate_index(_gate_files(snapshot))
    pool_silk = 0
    pool_shears = 0
    for document in tables.values():
        gates = {
            _condition_gate(pool.get("condition"), predicates)
            for pool in document.get("pools", [])
            if isinstance(pool, dict)
        }
        if SILK_TOUCH_NOTE in gates:
            pool_silk += 1
        elif SHEARS_NOTE in gates:
            pool_shears += 1

    assert pool_silk == snapshot["answer"]["poolSilkTouchTables"] == 76
    assert pool_shears == snapshot["answer"]["poolShearsTables"] == 6


def test_the_walk_notes_every_gated_drop_of_the_pinned_archive() -> None:
    """Replaying the real tables must reproduce the snapshot's note for every drop.

    This runs `extract_loot` over the committed documents rather than comparing two
    numbers the rebuild script wrote, so a walk that stops inheriting a pool gate
    into an `alternatives` child fails here.
    """
    snapshot = _gate_snapshot()
    result = extract_loot(_gate_files(snapshot))
    notes = {
        f"{producer.source_id}|{producer.output.item}": producer.note
        for producer in result.producers
    }
    assert notes == snapshot["answer"]["notes"]


def test_the_gated_drops_a_player_would_check_by_hand() -> None:
    """Spot checks against the game, so the snapshot is not only self-consistent."""
    snapshot = _gate_snapshot()
    by_source_and_item = {
        (p.source_id, p.output.item): p
        for p in extract_loot(_gate_files(snapshot)).producers
    }

    # Pool-level gate: the block drops itself only under silk touch.
    for name in ("bee_nest", "glass", "ice", "sculk"):
        src = f"{BLOCK_LOOT_DIRECTORY}/{name}.json"
        assert by_source_and_item[(src, f"minecraft:{name}")].note == SILK_TOUCH_NOTE

    # Pool-level shears gate.
    vine = (f"{BLOCK_LOOT_DIRECTORY}/vine.json", "minecraft:vine")
    assert by_source_and_item[vine].note == SHEARS_NOTE

    # An infested block drops its *host*, gated, and never the infested block.
    infested = f"{BLOCK_LOOT_DIRECTORY}/infested_stone.json"
    assert by_source_and_item[(infested, "minecraft:stone")].note == SILK_TOUCH_NOTE
    assert (infested, "minecraft:infested_stone") not in by_source_and_item

    # Entry-level gate inside `alternatives`: the shape that already worked.
    ore = f"{BLOCK_LOOT_DIRECTORY}/diamond_ore.json"
    assert by_source_and_item[(ore, "minecraft:diamond_ore")].note == SILK_TOUCH_NOTE
    assert by_source_and_item[(ore, "minecraft:diamond")].note is None

    # Entry-level shears gate: the grass keeps its note, the seeds beside it do not.
    grass = f"{BLOCK_LOOT_DIRECTORY}/short_grass.json"
    assert by_source_and_item[(grass, "minecraft:short_grass")].note == SHEARS_NOTE
    assert by_source_and_item[(grass, "minecraft:wheat_seeds")].note is None

    # Stone is the pair a player checks first: silk touch keeps the stone, and
    # breaking it plainly yields cobblestone with no requirement to state.
    stone = f"{BLOCK_LOOT_DIRECTORY}/stone.json"
    assert by_source_and_item[(stone, "minecraft:stone")].note == SILK_TOUCH_NOTE
    assert by_source_and_item[(stone, "minecraft:cobblestone")].note is None

    # A control table names no gate at all, so the walk must stay silent on it.
    dirt = (f"{BLOCK_LOOT_DIRECTORY}/dirt.json", "minecraft:dirt")
    assert by_source_and_item[dirt].note is None


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
                                "modifier": [
                                    {
                                        "type": "minecraft:set_count",
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


# --- Tier A: new loot table families ------------------------------------------


def test_archaeology_and_brush_emit_brushing_with_zero_inputs() -> None:
    files = {
        "loot_table/archaeology/desert_pyramid.json": json.dumps({
            "type": "minecraft:archaeology",
            "pools": [
                {
                    "rolls": 1.0,
                    "entries": [{"type": "minecraft:item", "name": "minecraft:diamond"}],
                }
            ],
        }).encode(),
        "loot_table/brush/armadillo.json": json.dumps({
            "type": "minecraft:entity_interact",
            "pools": [
                {
                    "rolls": 1.0,
                    "entries": [{"type": "minecraft:item", "name": "minecraft:armadillo_scute"}],
                }
            ],
        }).encode(),
    }
    result = extract_loot(files)
    assert len(result.producers) == 2
    for p in result.producers:
        assert p.method is ObtainMethod.BRUSHING
        assert p.inputs == ()
    assert result.tables_by_family["archaeology"] == 1
    assert result.tables_by_family["brush"] == 1


def test_carve_and_harvest_emit_harvesting_with_zero_inputs() -> None:
    files = {
        "loot_table/carve/pumpkin.json": json.dumps({
            "type": "minecraft:block_interact",
            "pools": [
                {
                    "rolls": 1.0,
                    "entries": [{"type": "minecraft:item", "name": "minecraft:pumpkin_seeds"}],
                }
            ],
        }).encode(),
        "loot_table/harvest/beehive.json": json.dumps({
            "type": "minecraft:block_interact",
            "pools": [
                {
                    "rolls": 1.0,
                    "entries": [{"type": "minecraft:item", "name": "minecraft:honeycomb"}],
                }
            ],
        }).encode(),
    }
    result = extract_loot(files)
    assert len(result.producers) == 2
    for p in result.producers:
        assert p.method is ObtainMethod.HARVESTING
        assert p.inputs == ()


def test_shearing_and_fishing_emit_respective_methods_with_zero_inputs() -> None:
    files = {
        "loot_table/shearing/sheep/white.json": json.dumps({
            "type": "minecraft:shearing",
            "pools": [
                {
                    "rolls": 1.0,
                    "entries": [{"type": "minecraft:item", "name": "minecraft:white_wool"}],
                }
            ],
        }).encode(),
        "loot_table/gameplay/fishing/treasure.json": json.dumps({
            "type": "minecraft:fishing",
            "pools": [
                {
                    "rolls": 1.0,
                    "entries": [{"type": "minecraft:item", "name": "minecraft:saddle"}],
                }
            ],
        }).encode(),
    }
    result = extract_loot(files)
    by_item = {p.output.item: p for p in result.producers}
    assert by_item["minecraft:white_wool"].method is ObtainMethod.SHEARING
    assert by_item["minecraft:white_wool"].inputs == ()
    assert by_item["minecraft:saddle"].method is ObtainMethod.FISHING
    assert by_item["minecraft:saddle"].inputs == ()


def test_barter_emits_bartering_with_zero_inputs_and_odds() -> None:
    files = {
        "loot_table/gameplay/piglin_bartering.json": json.dumps({
            "type": "minecraft:barter",
            "pools": [
                {
                    "rolls": 1.0,
                    "entries": [{"type": "minecraft:item", "name": "minecraft:ender_pearl"}],
                }
            ],
        }).encode()
    }
    result = extract_loot(files)
    assert len(result.producers) == 1
    p = result.producers[0]
    assert p.method is ObtainMethod.BARTERING
    assert p.inputs == ()
    # No note. The gold ingot a barter costs is not stated by the loot table,
    # and the panel now shows the odds in its place.
    assert p.note is None
    assert p.output.item == "minecraft:ender_pearl"
    # A pool of one entry is won every time, so the chance is certainty and the
    # yield is one item per gold ingot handed over.
    assert p.chance == 1.0
    assert p.count_max == 1
    assert p.per_attempt == 1.0


def test_gift_emits_gift_with_zero_inputs() -> None:
    files = {
        "loot_table/gameplay/chicken_lay.json": json.dumps({
            "type": "minecraft:gift",
            "pools": [
                {
                    "rolls": 1.0,
                    "entries": [{"type": "minecraft:item", "name": "minecraft:egg"}],
                }
            ],
        }).encode()
    }
    result = extract_loot(files)
    assert len(result.producers) == 1
    p = result.producers[0]
    assert p.method is ObtainMethod.GIFT
    assert p.inputs == ()
    assert p.output.item == "minecraft:egg"


def test_containers_dispensers_pots_spawners_emit_chest_loot() -> None:
    files = {
        "loot_table/dispensers/trial_chambers/chamber.json": json.dumps({
            "type": "minecraft:chest",
            "pools": [
                {
                    "rolls": 1.0,
                    "entries": [{"type": "minecraft:item", "name": "minecraft:arrow"}],
                }
            ],
        }).encode(),
        "loot_table/pots/trial_chambers/corridor.json": json.dumps({
            "type": "minecraft:chest",
            "pools": [
                {
                    "rolls": 1.0,
                    "entries": [{"type": "minecraft:item", "name": "minecraft:diamond"}],
                }
            ],
        }).encode(),
        "loot_table/spawners/trial_chamber/key.json": json.dumps({
            "type": "minecraft:chest",
            "pools": [
                {
                    "rolls": 1.0,
                    "entries": [{"type": "minecraft:item", "name": "minecraft:trial_key"}],
                }
            ],
        }).encode(),
    }
    result = extract_loot(files)
    assert len(result.producers) == 3
    for p in result.producers:
        assert p.method is ObtainMethod.CHEST_LOOT
        assert p.inputs == ()


def test_skipped_families_are_deliberately_not_read() -> None:
    files = {
        "loot_table/entities/zombie.json": json.dumps({
            "type": "minecraft:entity",
            "pools": [
                {
                    "rolls": 1.0,
                    "entries": [{"type": "minecraft:item", "name": "minecraft:rotten_flesh"}],
                }
            ],
        }).encode(),
        "loot_table/charged_creeper/creeper.json": json.dumps({
            "type": "minecraft:entity",
            "pools": [
                {
                    "rolls": 1.0,
                    "entries": [{"type": "minecraft:item", "name": "minecraft:creeper_head"}],
                }
            ],
        }).encode(),
        "loot_table/equipment/trial_chamber.json": json.dumps({
            "type": "minecraft:equipment",
            "pools": [
                {
                    "rolls": 1.0,
                    "entries": [{"type": "minecraft:item", "name": "minecraft:iron_sword"}],
                }
            ],
        }).encode(),
        # One valid table so the archive is not empty:
        "loot_table/brush/armadillo.json": json.dumps({
            "type": "minecraft:entity_interact",
            "pools": [
                {
                    "rolls": 1.0,
                    "entries": [{"type": "minecraft:item", "name": "minecraft:armadillo_scute"}],
                }
            ],
        }).encode(),
    }
    result = extract_loot(files)
    assert len(result.producers) == 1
    assert result.producers[0].output.item == "minecraft:armadillo_scute"
    for skipped_family in SKIPPED_FAMILIES:
        assert skipped_family not in result.tables_by_family


def test_unknown_loot_table_family_raises_obtain_error() -> None:
    files = {
        "loot_table/unknown_family/foo.json": json.dumps({
            "type": "minecraft:block",
            "pools": [
                {
                    "rolls": 1.0,
                    "entries": [{"type": "minecraft:item", "name": "minecraft:diamond"}],
                }
            ],
        }).encode()
    }
    with pytest.raises(ObtainError, match="unknown loot table family 'unknown_family'"):
        extract_loot(files)


def test_unknown_declared_type_raises_obtain_error() -> None:
    files = {
        "loot_table/archaeology/bad.json": json.dumps({
            "type": "minecraft:invalid_type",
            "pools": [
                {
                    "rolls": 1.0,
                    "entries": [{"type": "minecraft:item", "name": "minecraft:diamond"}],
                }
            ],
        }).encode()
    }
    with pytest.raises(
        ObtainError,
        match="declares unknown or missing loot table type 'minecraft:invalid_type'",
    ):
        extract_loot(files)


def test_verify_loot_sources_passes_and_fails_on_unmapped_table() -> None:
    curated = {
        "loot_table/brush/armadillo.json": ChestSource(
            structure="Armadillo", container="Armadillo"
        )
    }
    # Passes when all found tables are in curated
    verify_loot_sources(["loot_table/brush/armadillo.json"], curated)

    # Raises when a table is missing
    with pytest.raises(ObtainError, match="found 1 loot tables with no curated entry"):
        verify_loot_sources(
            ["loot_table/brush/armadillo.json", "loot_table/archaeology/missing.json"],
            curated,
        )


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


def mob_drop(mob: str, item: str, notes: tuple[DropNote, ...] = ()) -> MobDrop:
    return MobDrop(
        mob=mob,
        item=item,
        page=mob,
        wiki_url=f"https://minecraft.wiki/w/{mob}",
        notes=notes,
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


def test_unresolved_drop_expands_when_note_enumerates_resolvable_items() -> None:
    """The Creeper's "Music Disc" drop enumerates 12 discs in its random_disc note."""
    disc_resources = [
        resource("Music Disc 13", "music_disc_13", "item"),
        resource("Music Disc cat", "music_disc_cat", "item"),
        resource("Music Disc blocks", "music_disc_blocks", "item"),
        resource("Music Disc chirp", "music_disc_chirp", "item"),
        resource("Music Disc far", "music_disc_far", "item"),
        resource("Music Disc mall", "music_disc_mall", "item"),
        resource("Music Disc mellohi", "music_disc_mellohi", "item"),
        resource("Music Disc stal", "music_disc_stal", "item"),
        resource("Music Disc strad", "music_disc_strad", "item"),
        resource("Music Disc ward", "music_disc_ward", "item"),
        resource("Music Disc 11", "music_disc_11", "item"),
        resource("Music Disc wait", "music_disc_wait", "item"),
    ]
    table = join_table(resource("Creeper", "creeper", "entity"), *disc_resources)
    note_content = (
        "The disc is randomly selected from [[Music Disc 13|13]], [[Music Disc cat|cat]], "
        "[[Music Disc blocks|blocks]], [[Music Disc chirp|chirp]], [[Music Disc far|far]], "
        "[[Music Disc mall|mall]], [[Music Disc mellohi|mellohi]], [[Music Disc stal|stal]], "
        "[[Music Disc strad|strad]], [[Music Disc ward|ward]], [[Music Disc 11|11]], and "
        "[[Music Disc wait|wait]]."
    )
    drops = DropIndex.build(
        [
            mob_drop(
                "Creeper",
                "Music Disc",
                notes=(DropNote(name="random_disc", content=note_content),),
            )
        ]
    )
    producers, unresolved = producers_from_drop_index(drops, join_table=table)

    assert unresolved == ()
    assert len(producers) == 12
    assert {p.output.item for p in producers} == {
        f"minecraft:{r.resource_location}" for r in disc_resources
    }
    assert all(p.note == "dropped by Creeper" for p in producers)


def test_unresolved_drop_does_not_expand_if_any_enumerated_link_fails() -> None:
    """If one link in the note fails to resolve, expand none and report the drop."""
    table = join_table(
        resource("Creeper", "creeper", "entity"),
        resource("Music Disc 13", "music_disc_13", "item"),
    )
    note_content = "[[Music Disc 13|13]], [[Unknown Disc]]"
    drops = DropIndex.build(
        [
            mob_drop(
                "Creeper",
                "Music Disc",
                notes=(DropNote(name="random_disc", content=note_content),),
            )
        ]
    )
    producers, unresolved = producers_from_drop_index(drops, join_table=table)

    assert producers == ()
    assert len(unresolved) == 1
    assert unresolved[0].subject == "Music Disc"
    assert unresolved[0].reason == "the item name did not resolve"


# --- Odds: chance, count_max and per_attempt --------------------------------
#
# `Producer`'s docstring argues which shapes earn odds and which forfeit them.
# These pin that argument down against the two adapters that fill the fields.


def barter_table(entries: list[dict[str, Any]], rolls: Any = 1.0) -> dict[str, bytes]:
    """Return a one-pool barter archive, the simplest table that carries odds."""
    return {
        "loot_table/gameplay/piglin_bartering.json": json.dumps({
            "type": "minecraft:barter",
            "pools": [{"rolls": rolls, "entries": entries}],
        }).encode()
    }


def test_a_weighted_pool_divides_chance_by_the_total_weight() -> None:
    files = barter_table([
        {"type": "minecraft:item", "name": "minecraft:gravel", "weight": 20},
        {"type": "minecraft:item", "name": "minecraft:string", "weight": 20},
        {"type": "minecraft:item", "name": "minecraft:ender_pearl", "weight": 10},
    ])
    by_item = {p.output.item: p for p in extract_loot(files).producers}
    assert by_item["minecraft:gravel"].chance == pytest.approx(0.4)
    assert by_item["minecraft:string"].chance == pytest.approx(0.4)
    assert by_item["minecraft:ender_pearl"].chance == pytest.approx(0.2)
    assert sum(p.chance or 0.0 for p in by_item.values()) == pytest.approx(1.0)


def test_an_entry_with_no_weight_counts_as_one() -> None:
    """`fishing/treasure.json` names no weight at all, so its entries are even."""
    files = barter_table([
        {"type": "minecraft:item", "name": "minecraft:gravel"},
        {"type": "minecraft:item", "name": "minecraft:string"},
    ])
    by_item = {p.output.item: p for p in extract_loot(files).producers}
    assert by_item["minecraft:gravel"].chance == pytest.approx(0.5)
    assert by_item["minecraft:string"].chance == pytest.approx(0.5)


def test_the_denominator_counts_entries_this_walk_cannot_name() -> None:
    """A `loot_table` sibling still competes for the draw, so it stays in the total.

    Dropping it would turn the one item entry here into a certainty, which is
    the bug the real `gameplay/fishing.json` would have caused: junk 10,
    treasure 5 and fish 85 sum to 100, and none of the three is guaranteed.
    """
    files = barter_table([
        {"type": "minecraft:item", "name": "minecraft:gravel", "weight": 25},
        {"type": "minecraft:loot_table", "value": "minecraft:gameplay/fishing/fish", "weight": 75},
    ])
    producers = extract_loot(files).producers
    assert len(producers) == 1
    assert producers[0].chance == pytest.approx(0.25)


def test_a_count_range_carries_both_ends_and_the_expected_yield() -> None:
    """10-36 nuggets at one-in-four is a mean 23, a quarter of the time."""
    files = barter_table([
        {
            "type": "minecraft:item",
            "name": "minecraft:iron_nugget",
            "weight": 25,
            "modifier": [
                {
                    "type": "minecraft:set_count",
                    "count": {"type": "minecraft:uniform", "min": 10.0, "max": 36.0},
                }
            ],
        },
        {"type": "minecraft:item", "name": "minecraft:gravel", "weight": 75},
    ])
    nugget = next(
        p for p in extract_loot(files).producers if p.output.item == "minecraft:iron_nugget"
    )
    assert nugget.output.count == 10
    assert nugget.count_max == 36
    assert nugget.per_attempt == pytest.approx(0.25 * 23.0)


def test_more_rolls_multiply_the_expected_yield() -> None:
    once = barter_table([{"type": "minecraft:item", "name": "minecraft:gravel"}], rolls=1.0)
    thrice = barter_table([{"type": "minecraft:item", "name": "minecraft:gravel"}], rolls=3.0)
    assert extract_loot(once).producers[0].per_attempt == pytest.approx(1.0)
    assert extract_loot(thrice).producers[0].per_attempt == pytest.approx(3.0)


def test_a_uniform_roll_range_averages_its_ends() -> None:
    files = barter_table(
        [{"type": "minecraft:item", "name": "minecraft:gravel"}],
        rolls={"type": "minecraft:uniform", "min": 1.0, "max": 3.0},
    )
    assert extract_loot(files).producers[0].per_attempt == pytest.approx(2.0)


def test_an_entry_under_a_container_forfeits_its_odds() -> None:
    """The game picks an `alternatives` child by condition, not by weight."""
    files = archive(
        blocks={
            "diamond_ore": {
                "type": "minecraft:block",
                "pools": [
                    {
                        "rolls": 1.0,
                        "entries": [
                            {
                                "type": "minecraft:alternatives",
                                "children": [
                                    {"type": "minecraft:item", "name": "minecraft:diamond_ore"},
                                    {"type": "minecraft:item", "name": "minecraft:diamond"},
                                ],
                            }
                        ],
                    }
                ],
            }
        }
    )
    producers = extract_loot(files).producers
    assert len(producers) == 2
    for producer in producers:
        assert producer.chance is None
        assert producer.count_max is None
        assert producer.per_attempt is None


def test_a_conditioned_entry_forfeits_its_odds() -> None:
    """Weight times the odds of the condition holding is a number no table states."""
    files = barter_table([
        {
            "type": "minecraft:item",
            "name": "minecraft:gravel",
            "condition": {"type": "minecraft:random_chance", "chance": 0.5},
        },
        {"type": "minecraft:item", "name": "minecraft:string"},
    ])
    by_item = {p.output.item: p for p in extract_loot(files).producers}
    assert by_item["minecraft:gravel"].chance is None
    assert by_item["minecraft:gravel"].per_attempt is None
    assert by_item["minecraft:string"].chance == pytest.approx(0.5)


def looting_zero(
    minimum: int, maximum: int, chance: tuple[int, int], average: tuple[int, int]
) -> LootingDrop:
    """Return one looting-0 wiki row, the only level the odds are taken from."""
    return LootingDrop(
        looting_level=0,
        minimum=minimum,
        maximum=maximum,
        average=Ratio(numerator=average[0], denominator=average[1]),
        drop_chance=Ratio(numerator=chance[0], denominator=chance[1]),
        distribution={},
        quantity_text=f"{minimum}-{maximum}",
    )


def drop_with(row: LootingDrop) -> MobDrop:
    return MobDrop(
        mob="Zombie",
        item="Rotten Flesh",
        page="Zombie",
        wiki_url="https://minecraft.wiki/w/Zombie",
        notes=(),
        by_looting_level=(row,),
    )


def zombie_table() -> JoinTable:
    return join_table(
        resource("Zombie", "zombie", "entity"),
        resource("Rotten Flesh", "rotten_flesh", "item"),
    )


def test_a_mob_drop_takes_the_wikis_own_average_not_chance_times_count() -> None:
    """A `0-3` drop folds its own failure in, so multiplying would count it twice."""
    row = looting_zero(minimum=0, maximum=3, chance=(1, 2), average=(1, 4))
    producers, _ = producers_from_drop_index(
        DropIndex.build([drop_with(row)]), join_table=zombie_table()
    )
    producer = producers[0]
    assert producer.chance == pytest.approx(0.5)
    assert producer.count_max == 3
    # The wiki's own 1/4. Deriving it instead would give 0.5 * (1 + 3) / 2 = 1.0,
    # four times too high, which is exactly the error this field exists to avoid.
    assert producer.per_attempt == pytest.approx(0.25)
    # A `0` minimum becomes `1`: `chance` already says the drop may not happen,
    # and a range starting at zero would say it a second time.
    assert producer.output.count == 1


def test_a_mob_drop_with_no_looting_zero_row_carries_no_odds() -> None:
    drops = DropIndex.build([mob_drop("Zombie", "Rotten Flesh")])
    producers, _ = producers_from_drop_index(drops, join_table=zombie_table())
    assert producers[0].chance is None
    assert producers[0].count_max is None
    assert producers[0].per_attempt is None


def test_a_mob_drop_whose_average_is_zero_carries_no_odds() -> None:
    """A drop that yields nothing on an average kill states no useful rate."""
    row = looting_zero(minimum=0, maximum=0, chance=(1, 2), average=(0, 1))
    producers, _ = producers_from_drop_index(
        DropIndex.build([drop_with(row)]), join_table=zombie_table()
    )
    assert producers[0].chance is None
    assert producers[0].per_attempt is None


def test_the_three_odds_fields_cannot_be_set_apart() -> None:
    """One fact in three parts: a partial set describes a draw it cannot state."""
    with pytest.raises(ObtainError, match="one fact in three parts"):
        Producer(
            method=ObtainMethod.BARTERING,
            output=ProducerOutput(item="minecraft:gravel"),
            inputs=(),
            source_id="test",
            chance=0.5,
        )


# --- 26.3 condition and modifier spellings -----------------------------------

SILK_TOUCH_PREDICATE = {
    "type": "minecraft:match_tool",
    "predicate": {
        "predicates": {
            "minecraft:enchantments": [
                {"enchantments": "minecraft:silk_touch", "levels": {"min": 1}}
            ]
        }
    },
}
SHEARS_PREDICATE = {"type": "minecraft:match_tool", "predicate": {"items": "minecraft:shears"}}


def _with_predicates(files: dict[str, bytes]) -> dict[str, bytes]:
    """Return `files` plus the two tool predicates a 26.3 pack holds."""
    return files | {
        "predicate/tool/can_silk_touch.json": json.dumps(SILK_TOUCH_PREDICATE).encode(),
        "predicate/tool/can_shear.json": json.dumps(SHEARS_PREDICATE).encode(),
    }


def _one_block_pool(condition: Any) -> dict[str, bytes]:
    """Return a one-pool glass table whose pool carries `condition`."""
    return _with_predicates(
        archive(
            blocks={
                "glass": {
                    "type": "minecraft:block",
                    "pools": [
                        {
                            "rolls": 1.0,
                            "condition": condition,
                            "entries": [
                                {"type": "minecraft:item", "name": "minecraft:glass"}
                            ],
                        }
                    ],
                }
            }
        )
    )


def test_a_named_predicate_reference_is_followed_to_the_object_it_names() -> None:
    """26.3 tables name a shared condition instead of spelling it out.

    123 block tables carry the string `minecraft:tool/can_silk_touch` where 26.2
    carried the whole `match_tool` object. A reader that did not resolve the name
    would read every one of those drops as needing no tool at all -- it would tell
    someone to break Glass by hand.
    """
    result = extract_block_and_chest_loot(_one_block_pool("minecraft:tool/can_silk_touch"))
    assert result.producers[0].note == SILK_TOUCH_NOTE


def test_an_all_of_condition_is_read_as_the_list_that_26_2_wrote_by_hand() -> None:
    """`conditions: [a, b]` became `condition: {all_of, terms: [a, b]}`.

    Unwrapping `all_of` is what keeps a gate readable when the table also carries
    an ordinary condition beside it, which 26.2 expressed as a two-element list.
    """
    condition = {
        "type": "minecraft:all_of",
        "terms": ["minecraft:tool/can_silk_touch", {"type": "minecraft:survives_explosion"}],
    }
    result = extract_block_and_chest_loot(_one_block_pool(condition))
    assert result.producers[0].note == SILK_TOUCH_NOTE


def test_an_any_of_condition_names_no_single_tool() -> None:
    """"Shears or silk touch" is not "requires shears", and was never read as one.

    `acacia_leaves` is the real table: it drops the leaves under either tool. 26.2
    carried that as one `any_of` entry inside the conditions list and this reader
    matched none of it, so it stated no requirement. The 26.3 spelling must keep
    stating none rather than picking whichever term comes first.
    """
    condition = {
        "type": "minecraft:any_of",
        "terms": ["minecraft:tool/can_shear", "minecraft:tool/can_silk_touch"],
    }
    result = extract_block_and_chest_loot(_one_block_pool(condition))
    assert result.producers[0].note is None


def test_an_inverted_tool_condition_is_not_that_tool_s_gate() -> None:
    """A drop that happens *without* silk touch must not claim to require it."""
    condition = {"type": "minecraft:inverted", "term": "minecraft:tool/can_silk_touch"}
    result = extract_block_and_chest_loot(_one_block_pool(condition))
    assert result.producers[0].note is None


def test_a_modifier_written_as_one_object_reads_like_a_list_of_one() -> None:
    """26.3 lets `modifier` hold a single object as well as an array of them."""
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
                                "modifier": {
                                    "type": "minecraft:set_count",
                                    "count": {
                                        "type": "minecraft:uniform",
                                        "min": 2.0,
                                        "max": 5.0,
                                    },
                                },
                            }
                        ],
                    }
                ],
            }
        }
    )
    producer = extract_block_and_chest_loot(files).producers[0]
    assert producer.output.count == 2
    assert producer.count_max == 5
