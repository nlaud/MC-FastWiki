"""The main deliverable: `merge_entities`, built entirely from in-memory Tier A/B/C fixtures.

Every index below is built the way its own test suite builds it --
`parse_resource_locations`/`parse_sprite_files` for the two join tables, via
the same `rl_row`/`sprite_row` shape `tests/test_normalize_reconcile.py`
uses, and a direct constructor call for the five Tier B tables, since those
are plain frozen models with a public `.build()` classmethod. No test here
opens a socket.

One scenario runs through most of this file: a `Creeper` (mob) that drops
`Gunpowder` (resolved item) and an item the wiki has no row for at all, spawns
in `Jungle` (resolved biome), plus a `Chicken` whose ID sits in two registries,
`minecraft:poplar_boat` with no wiki row (the D1 shape), two items sharing one
ambiguous wiki display name, an `Emerald` a librarian trades for, and a small
advancement tree. It is one scenario rather than many tiny ones because the
five sections, the multi-registry precedence, and the ambiguous-join report
all interact through the same `JoinTable`, and building them separately would
either hide that interaction or duplicate the whole fixture five times.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from pipeline.enrich import IntegerRange as WikiIntegerRange
from pipeline.enrich import breeding as enrich_breeding
from pipeline.enrich.advancement import AdvancementTree, WikiAdvancement
from pipeline.enrich.droptable import DropIndex, LootingDrop, MobDrop
from pipeline.enrich.droptable import Ratio as DropRatio
from pipeline.enrich.infobox import EntityInfobox, HealthValue, InfoboxReport
from pipeline.enrich.infobox import Measure as InfoboxMeasure
from pipeline.enrich.resource_location import parse_resource_locations
from pipeline.enrich.spawn_table import SpawnEntry, SpawnIndex
from pipeline.enrich.sprite import SpriteIndex, parse_sprite_files
from pipeline.enrich.trade import Probability, TradeIndex, TradeItem, WikiTrade
from pipeline.extract.entity_class import EntityClass, EntityClassification
from pipeline.extract.harvest import BlockHarvest, HarvestTier, HarvestTool
from pipeline.fetch.extracts import ExtractReport, PageExtract
from pipeline.normalize import NormalizeError
from pipeline.normalize.curated import CuratedData, EntityOverride, StaleDocument
from pipeline.normalize.entity import BreedingInfo, EntityKind, HarvestInfo, SourceTier
from pipeline.normalize.merge import MergeResult, merge_entities, write_report

# --- Fixture builders -------------------------------------------------------


def rl_row(display_name: str, resource_location: str, kind: str = "item") -> dict[str, object]:
    return {
        "page_name": display_name,
        "display_name": display_name,
        "resource_location": resource_location,
        "json": json.dumps({"Edition": "java", "Type": kind}),
    }


def sprite_row(family: str, sprite_id: str, file_title: str | None = None) -> dict[str, object]:
    resolved = file_title if file_title is not None else f"File:{family} {sprite_id}.png"
    return {"page_name": resolved, "name": family, "id": sprite_id, "file": resolved}


REGISTRIES: dict[str, list[str]] = {
    # `acacia_boat` sits in `entity_type` and in `item`, and the wiki
    # documents only the item. That combination is the one that broke the
    # first live merge -- see the regression test near the bottom of this
    # file -- so it is in the shared fixture rather than a private one.
    #
    # `arrow`, `tnt`, and `lightning_bolt` exercise the demotion rule of
    # `pipeline.extract.entity_class`: all three classify as `NEITHER` below,
    # and none of the three has a wiki row that names it, so nothing but the
    # demotion decides where each one lands -- `arrow` into `item` (it also
    # sits there), `tnt` into `block` (it also sits there), and
    # `lightning_bolt` into the new `EntityKind.ENTITY` (it sits nowhere
    # else). `undecided_default` and `undecided_overridden` exercise clause 2:
    # both classify as `LOOT_TABLE_ONLY` and sit in no other registry, so
    # both default to `kind="mob"` unless a curated override says otherwise.
    "entity_type": [
        "creeper",
        "chicken",
        "acacia_boat",
        "ender_pearl",
        "arrow",
        "tnt",
        "lightning_bolt",
        "undecided_default",
        "undecided_overridden",
    ],
    "block": ["tnt", "wheat"],
    "item": [
        "gunpowder",
        "emerald",
        "poplar_boat",
        "chicken",
        "acacia_boat",
        "ender_pearl",
        "jigsaw",
        "widget_a",
        "widget_b",
        "mystery_thing",
        "arrow",
        "wheat",
    ],
    "mob_effect": [],
    "worldgen/biome": ["jungle"],
    "enchantment": ["efficiency"],
    # Potions enumerate outside the six-registry union entirely -- see the
    # potion section near the end of this file. `awkward` has a wiki page
    # in `JOIN_TABLE` below; `long_weakness` does not, which is the shape
    # every `long_`/`strong_` variant takes on the live wiki.
    "potion": ["awkward", "long_weakness"],
}

# Every `entity_type` path of `REGISTRIES` must appear here, or
# `merge_entities` raises `NormalizeError` for a classifier gone out of sync
# with the registries payload -- see the shape-fault tests near the bottom of
# this file. `creeper` and `chicken` are real mobs with a spawn egg.
# `acacia_boat` and `ender_pearl` are `LOOT_TABLE_ONLY` here on purpose, not
# `NEITHER`: both already resolve to `item` through the wiki-name-match
# mechanism `_registry_the_wiki_names_the_id_under` applies (see the
# regression tests below), so classifying them `NEITHER` as the real 26.2
# data does would make the demotion a silent no-op in this fixture and hide
# whether the name-match mechanism still works on its own. `arrow`, `tnt`,
# and `lightning_bolt` carry no matching wiki row at all, so they are the
# fixture's proof that the demotion does real work with no help from a name
# match.
ENTITY_CLASSIFICATION = EntityClassification(
    by_path={
        "creeper": EntityClass.SPAWN_EGG,
        "chicken": EntityClass.SPAWN_EGG,
        "acacia_boat": EntityClass.LOOT_TABLE_ONLY,
        "ender_pearl": EntityClass.LOOT_TABLE_ONLY,
        "arrow": EntityClass.NEITHER,
        "tnt": EntityClass.NEITHER,
        "lightning_bolt": EntityClass.NEITHER,
        "undecided_default": EntityClass.LOOT_TABLE_ONLY,
        "undecided_overridden": EntityClass.LOOT_TABLE_ONLY,
    }
)

ADVANCEMENT_IDS = ("story/root", "story/mine_stone", "adventure/nothing_here")

JOIN_TABLE = parse_resource_locations(
    [
        rl_row("Creeper", "creeper", "entity"),
        rl_row("Chicken", "chicken", "entity"),
        rl_row("Raw Chicken", "chicken", "item"),
        rl_row("Gunpowder", "gunpowder", "item"),
        rl_row("Emerald", "emerald", "item"),
        rl_row("Jungle", "jungle", "biome"),
        rl_row("Widget", "widget_a", "item"),
        rl_row("Widget", "widget_b", "item"),
        # An `item` row and no `entity` row, for an ID that sits in both
        # registries. The wiki documents boats as items on one `Boat` page.
        rl_row("Acacia Boat", "acacia_boat", "item"),
        # Both registries carry a row, and only the item's row names the ID.
        # `entity_type` has precedence; the name match must beat it.
        rl_row("Ender Pearl", "ender_pearl", "item"),
        rl_row("Thrown Ender Pearl", "ender_pearl", "entity"),
        rl_row("Wheat Crops", "wheat", "block"),
        rl_row("Wheat", "wheat", "item"),
        # Two names for one ID, neither of which normalises to `jigsaw` and
        # neither of which is shared with another ID. Every tie-break in
        # `_own_row` declines this on purpose, so the entity has no page.
        rl_row("Jigsaw Block", "jigsaw", "item"),
        rl_row("Jigsaw structure Jigsaw", "jigsaw", "item"),
        # poplar_boat and mystery_thing carry no row at all -- the D1 shape.
        # Every potion page shares one registry_id, `minecraft:potion` --
        # this is the one row for `awkward`; `long_weakness` gets none.
        rl_row("Awkward Potion", "potion", "item"),
    ]
)

SPRITE_INDEX = parse_sprite_files(
    [
        sprite_row("EntitySprite", "creeper"),
        sprite_row("EntitySprite", "chicken"),
        sprite_row("InvSprite", "Gunpowder"),
        sprite_row("BiomeSprite", "jungle"),
        # The id route, which needs no wiki row at all. This is what gave
        # `acacia_boat` a Tier B field while its name lookup was failing.
        sprite_row("EntitySprite", "acacia-boat"),
        # emerald and poplar_boat get no sprite at all -- both should be
        # reported missing, since `item` is not exempt. `efficiency` also
        # gets none, and must NOT be reported, since `enchantment` is exempt.
    ]
)

INFOBOX_REPORT = InfoboxReport.build(
    [
        EntityInfobox(
            page="Creeper",
            wiki_url="https://minecraft.wiki/w/Creeper",
            health=(
                HealthValue(
                    labels=(), value=InfoboxMeasure(minimum=Decimal(20), maximum=Decimal(20))
                ),
            ),
            damage=(),
            size=(),
            usable_items=(),
            armor=(),
            behavior=(),
            mob_type=("Monster",),
            speed=(),
            knockback_resistance=(),
        )
    ]
)

SPAWN_INDEX = SpawnIndex.build(
    [
        SpawnEntry(
            mob="Creeper",
            mob_page="Creeper",
            biome="Jungle",
            biome_page="Jungle",
            wiki_url="https://minecraft.wiki/w/Jungle",
            category="Monster",
            weight=100,
            total_weight=1000,
            group_size=WikiIntegerRange(minimum=4, maximum=4),
            note=None,
            note_name=None,
        )
    ]
)

DROP_INDEX = DropIndex.build(
    [
        MobDrop(
            mob="Creeper",
            item="Gunpowder",
            page="Creeper",
            wiki_url="https://minecraft.wiki/w/Creeper",
            notes=(),
            by_looting_level=(
                LootingDrop(
                    looting_level=0,
                    minimum=0,
                    maximum=2,
                    average=DropRatio(numerator=1, denominator=1),
                    drop_chance=DropRatio(numerator=1, denominator=1),
                    distribution={
                        0: DropRatio(numerator=1, denominator=3),
                        1: DropRatio(numerator=1, denominator=3),
                        2: DropRatio(numerator=1, denominator=3),
                    },
                    quantity_text="0-2",
                ),
            ),
        ),
        MobDrop(
            mob="Creeper",
            item="Nonexistent Thing",
            page="Creeper",
            wiki_url="https://minecraft.wiki/w/Creeper",
            notes=(),
            by_looting_level=(),
        ),
    ]
)

TRADE_INDEX = TradeIndex.build(
    [
        WikiTrade(
            profession="Librarian",
            page="Librarian",
            wiki_url="https://minecraft.wiki/w/Librarian",
            level="Novice",
            wanted=(TradeItem(item="Paper", quantity=WikiIntegerRange(minimum=24, maximum=24)),),
            given=TradeItem(item="Emerald", quantity=WikiIntegerRange(minimum=1, maximum=1)),
            java_probability=Probability(text="100%", low=1.0, high=1.0),
            max_trades=None,
            villager_xp=2,
            price_multiplier=0.05,
        ),
        WikiTrade(
            profession="Librarian",
            page="Librarian",
            wiki_url="https://minecraft.wiki/w/Librarian",
            level="Novice",
            wanted=(TradeItem(item="Paper", quantity=WikiIntegerRange(minimum=5, maximum=5)),),
            given=TradeItem(item="Widget", quantity=WikiIntegerRange(minimum=1, maximum=1)),
            java_probability=Probability(text="100%", low=1.0, high=1.0),
            max_trades=None,
            villager_xp=None,
            price_multiplier=None,
        ),
        # `Jigsaw Block` names exactly one registry ID, so forward resolution
        # succeeds -- but that ID's own row never resolves, so the entity has
        # no page to credit. The section must be dropped and reported rather
        # than attached.
        WikiTrade(
            profession="Librarian",
            page="Librarian",
            wiki_url="https://minecraft.wiki/w/Librarian",
            level="Master",
            wanted=(TradeItem(item="Emerald", quantity=WikiIntegerRange(minimum=8, maximum=8)),),
            given=TradeItem(item="Jigsaw Block", quantity=WikiIntegerRange(minimum=1, maximum=1)),
            java_probability=None,
            max_trades=None,
            villager_xp=None,
            price_multiplier=None,
        ),
    ]
)

ADVANCEMENT_TREE = AdvancementTree.build(
    [
        WikiAdvancement(
            internal_id="story/root",
            title="Minecraft",
            description="The heart and story of the game",
            game_description=None,
            parent_title=None,
            parent_id=None,
            icon="Grass Block",
            background="minecraft:textures/block/stone.png",
            experience=None,
            reward=None,
            page="Advancement",
            wiki_url="https://minecraft.wiki/w/Advancement",
        ),
        WikiAdvancement(
            internal_id="story/mine_stone",
            title="Stone Age",
            description="Mine stone with your new pickaxe",
            game_description=None,
            parent_title="Minecraft",
            parent_id="story/root",
            icon="Stone Pickaxe",
            background=None,
            experience=None,
            reward=None,
            page="Advancement",
            wiki_url="https://minecraft.wiki/w/Advancement",
        ),
    ]
)

EXTRACT_REPORT = ExtractReport(
    extracts=(
        PageExtract(
            requested_title="Gunpowder",
            page_title="Gunpowder",
            page_id=1,
            extract="Gunpowder is an item obtained from creepers, ghasts, and witches.",
        ),
    ),
    misses=(),
)

CURATED = CuratedData(
    aliases={"minecraft:gunpowder": ("gp",)},
    overrides={
        "minecraft:gunpowder": EntityOverride(
            name="Gunpowder!!",
            icon="custom:icon",
            blurb="Custom blurb.",
            wiki_url="https://minecraft.wiki/w/Gunpowder",
        ),
        "minecraft:mystery_thing": EntityOverride(kind=EntityKind.BLOCK),
        "minecraft:does_not_exist": EntityOverride(name="Ghost"),
        # Beats the clause-2 default of `kind="mob"` for an undecided
        # `entity_type` ID, the same way `data/curated/overrides.json`
        # itself beats it for `minecraft:armor_stand` and `minecraft:player`.
        "minecraft:undecided_overridden": EntityOverride(kind=EntityKind.ITEM),
    },
    stale=(StaleDocument(document="aliases.json", verified_for="26.1", current="26.2"),),
)


def run_merge() -> MergeResult:
    return merge_entities(
        registries=REGISTRIES,
        advancement_ids=ADVANCEMENT_IDS,
        join_table=JOIN_TABLE,
        sprite_index=SPRITE_INDEX,
        infobox_report=INFOBOX_REPORT,
        spawn_index=SPAWN_INDEX,
        drop_index=DROP_INDEX,
        trade_index=TRADE_INDEX,
        advancement_tree=ADVANCEMENT_TREE,
        extract_report=EXTRACT_REPORT,
        curated=CURATED,
        entity_classification=ENTITY_CLASSIFICATION,
    )


# --- Enumeration and precedence ----------------------------------------------


def test_an_id_in_two_registries_becomes_one_entity_with_the_precedence_kind() -> None:
    result = run_merge()
    boat = result.by_id["minecraft:acacia_boat"]
    assert boat.kind is EntityKind.ITEM
    assert boat.name == "Acacia Boat"

    entry = next(m for m in result.report.multi_registry if m.id == "minecraft:acacia_boat")
    assert entry.registries == ("item", "entity_type")
    assert entry.kind is EntityKind.ITEM


def test_clashing_entity_type_id_splits_into_item_and_mob() -> None:
    result = run_merge()
    item = result.by_id["minecraft:chicken"]
    assert item.kind is EntityKind.ITEM
    assert item.name == "Raw Chicken"

    mob = result.by_id["minecraft:entity_type/chicken"]
    assert mob.kind is EntityKind.MOB
    assert mob.name == "Chicken"
    assert "minecraft:chicken" in result.report.split_ids


def test_wheat_displays_as_wheat_not_wheat_crops() -> None:
    result = run_merge()
    wheat = result.by_id["minecraft:wheat"]
    assert wheat.kind is EntityKind.ITEM
    assert wheat.name == "Wheat"


def test_a_tier_a_id_with_no_wiki_row_gets_the_fallback_name_and_still_validates() -> None:
    result = run_merge()
    poplar_boat = result.by_id["minecraft:poplar_boat"]
    assert poplar_boat.name == "Poplar Boat"
    assert poplar_boat.wiki_url is None
    assert poplar_boat.blurb is None
    assert SourceTier.B not in poplar_boat.source_tiers.values()


def test_an_ambiguous_display_name_attaches_nothing_and_is_reported() -> None:
    result = run_merge()
    widget_a = result.by_id["minecraft:widget_a"]
    widget_b = result.by_id["minecraft:widget_b"]
    assert not any(section.type == "TradeTable" for section in widget_a.sections)
    assert not any(section.type == "TradeTable" for section in widget_b.sections)

    unplaced = [row for row in result.report.unplaced if row.subject == "Widget"]
    assert len(unplaced) == 1
    assert unplaced[0].table == "trade"
    assert "ambiguous" in unplaced[0].reason


# --- entity_type classification: the three clauses, and the demotion -------------


def test_clause_one_spawn_egg_keeps_entity_type_precedence() -> None:
    """`SPAWN_EGG` is a mob outright, and `entity_type` never moves for it."""
    result = run_merge()
    creeper = result.by_id["minecraft:creeper"]
    assert creeper.kind is EntityKind.MOB


def test_clause_two_undecided_defaults_to_mob_and_is_named_in_the_report() -> None:
    """An `entity_type` ID with a loot table but no spawn egg defaults to `mob`.

    `undecided_default` sits in no other registry, so nothing but the clause
    2 default decides its kind. The report names it, the same way
    `multi_registry` names every ID whose registry membership took a
    decision -- see `MergeReport.undecided_entity_types`'s own docstring.
    """
    result = run_merge()
    entity = result.by_id["minecraft:undecided_default"]
    assert entity.kind is EntityKind.MOB

    entry = next(
        u for u in result.report.undecided_entity_types if u.id == "minecraft:undecided_default"
    )
    assert entry.kind is EntityKind.MOB


def test_a_curated_override_beats_the_clause_two_default() -> None:
    """A curated override changes the kind clause 2 would otherwise default to.

    `data/curated/overrides.json` does exactly this live, for
    `minecraft:armor_stand` (to `item`) and `minecraft:player` (to `entity`).
    `undecided_overridden` is the synthetic stand-in.
    """
    result = run_merge()
    entity = result.by_id["minecraft:undecided_overridden"]
    assert entity.kind is EntityKind.ITEM

    # The report names the kind the ID actually ended up with, not the
    # clause 2 default it would have gotten without the override.
    entry = next(
        u for u in result.report.undecided_entity_types if u.id == "minecraft:undecided_overridden"
    )
    assert entry.kind is EntityKind.ITEM


def test_clause_three_demotion_lets_an_item_registry_membership_win() -> None:
    """`arrow` carries no wiki row at all, so only the demotion decides it.

    Unlike `acacia_boat` and `ender_pearl` below, nothing about `arrow`'s
    wiki row could have picked `item` for it -- there is no row to match.
    The demotion is the only mechanism doing anything here.
    """
    result = run_merge()
    arrow = result.by_id["minecraft:arrow"]
    assert arrow.kind is EntityKind.ITEM


def test_clause_three_demotion_lets_a_block_registry_membership_win() -> None:
    result = run_merge()
    tnt = result.by_id["minecraft:tnt"]
    assert tnt.kind is EntityKind.BLOCK


def test_clause_three_demotion_with_no_other_registry_becomes_kind_entity() -> None:
    """`lightning_bolt` sits in no registry but `entity_type`, and classifies `NEITHER`.

    Demoting `entity_type` to the bottom of a one-element list still leaves
    it at the top, so the demotion alone cannot place this ID anywhere else
    -- `EntityKind.ENTITY` is what an `entity_type` ID gets when it is
    demoted and there was nowhere else to land.
    """
    result = run_merge()
    lightning_bolt = result.by_id["minecraft:lightning_bolt"]
    assert lightning_bolt.kind is EntityKind.ENTITY


def test_clause_one_fires_before_the_demotion_so_a_mob_with_an_item_form_stays_a_mob() -> None:
    """`chicken` must never be reopened by the demotion logic.

    `minecraft:chicken` has a spawn egg, so it classifies `SPAWN_EGG` and the
    demotion step in `_registries_of_id` never runs for it at all --
    `entity_class is EntityClass.NEITHER` is false before it is ever
    reached. `pipeline.normalize.merge`'s module docstring records this as
    the safety property the demotion must never violate: `chicken`, `cod`,
    `salmon`, `pufferfish`, `tropical_fish`, and `rabbit` are all real mobs
    that also share their registry ID with a raw-meat item, and resolving
    one of them through the item's wiki row is the wrong-answer failure
    `_own_row`'s own docstring records as a real past failure.
    """
    result = run_merge()
    chicken = result.by_id["minecraft:entity_type/chicken"]
    assert chicken.kind is EntityKind.MOB
    assert chicken.name == "Chicken"


# --- The five sections ---------------------------------------------------------


def test_stat_block_attaches_from_the_infobox_report() -> None:
    creeper = run_merge().by_id["minecraft:creeper"]
    stat_block = next(section for section in creeper.sections if section.type == "StatBlock")
    assert stat_block.health[0].value.minimum == 20
    assert stat_block.mob_type == ("Monster",)


def test_spawn_info_attaches_and_resolves_the_biome_ref() -> None:
    creeper = run_merge().by_id["minecraft:creeper"]
    spawn_info = next(section for section in creeper.sections if section.type == "SpawnInfo")
    assert spawn_info.entries[0].biome == "Jungle"
    assert spawn_info.entries[0].biome_ref is not None
    assert spawn_info.entries[0].biome_ref.id == "minecraft:jungle"


def test_drop_table_attaches_and_resolves_a_ref_only_where_it_can() -> None:
    creeper = run_merge().by_id["minecraft:creeper"]
    drop_table = next(section for section in creeper.sections if section.type == "DropTable")
    by_item = {drop.item: drop for drop in drop_table.drops}

    assert by_item["Gunpowder"].item_ref is not None
    assert by_item["Gunpowder"].item_ref.id == "minecraft:gunpowder"
    assert by_item["Nonexistent Thing"].item_ref is None


def test_trade_table_attaches_to_the_given_item() -> None:
    emerald = run_merge().by_id["minecraft:emerald"]
    trade_table = next(section for section in emerald.sections if section.type == "TradeTable")
    assert len(trade_table.trades) == 1
    trade = trade_table.trades[0]
    assert trade.profession == "Librarian"
    assert trade.given.name == "Emerald"
    # "Paper" has no resource_location row in this fixture, so it stays a name.
    assert trade.wanted[0].name == "Paper"
    assert trade.wanted[0].ref is None
    assert trade.profession_ref is None


def test_advancement_info_attaches_with_a_resolved_parent_and_children() -> None:
    result = run_merge()
    root = result.by_id["minecraft:story/root"]
    child = result.by_id["minecraft:story/mine_stone"]

    root_info = next(s for s in root.sections if s.type == "AdvancementInfo")
    assert root_info.parent is None
    assert len(root_info.children) == 1
    assert root_info.children[0].id == "minecraft:story/mine_stone"

    child_info = next(s for s in child.sections if s.type == "AdvancementInfo")
    assert child_info.parent is not None
    assert child_info.parent.id == "minecraft:story/root"
    assert child_info.parent_title == "Minecraft"


def test_an_advancement_with_no_wiki_row_still_enumerates() -> None:
    result = run_merge()
    orphan = result.by_id["minecraft:adventure/nothing_here"]
    assert orphan.kind is EntityKind.ADVANCEMENT
    assert orphan.name == "Adventure/Nothing Here"
    assert not any(s.type == "AdvancementInfo" for s in orphan.sections)
    assert orphan.wiki_url is None


# --- Provenance ------------------------------------------------------------------


def test_provenance_is_recorded_for_every_field_actually_written() -> None:
    creeper = run_merge().by_id["minecraft:creeper"]
    assert creeper.source_tiers["name"] is SourceTier.B
    assert creeper.source_tiers["icon"] is SourceTier.B
    assert creeper.source_tiers["sections.StatBlock"] is SourceTier.B
    assert creeper.source_tiers["sections.SpawnInfo"] is SourceTier.B
    assert creeper.source_tiers["sections.DropTable"] is SourceTier.B


def test_no_provenance_is_recorded_for_a_field_never_written() -> None:
    poplar_boat = run_merge().by_id["minecraft:poplar_boat"]
    assert "icon" not in poplar_boat.source_tiers
    assert "blurb" not in poplar_boat.source_tiers
    assert "wikiUrl" not in poplar_boat.source_tiers


# --- Icon and blurb reports -----------------------------------------------------


def test_a_missing_icon_is_reported_for_a_registry_that_is_not_exempt() -> None:
    report = run_merge().report
    assert any(m.id == "minecraft:poplar_boat" for m in report.missing_icons)
    assert any(m.id == "minecraft:emerald" for m in report.missing_icons)


def test_an_advancement_missing_an_icon_is_reported_in_missing_icons() -> None:
    report = run_merge().report
    assert any(m.id == "minecraft:story/root" for m in report.missing_icons)
    assert any(m.id == "minecraft:adventure/nothing_here" for m in report.missing_icons)


def test_an_advancement_with_resolved_icon_sets_tier_b() -> None:
    join_table = parse_resource_locations([rl_row("Grass Block", "grass_block", "block")])
    sprite_index = parse_sprite_files([sprite_row("BlockSprite", "grass-block")])
    result = merge_entities(
        registries=REGISTRIES,
        advancement_ids=("story/root",),
        join_table=join_table,
        sprite_index=sprite_index,
        infobox_report=INFOBOX_REPORT,
        spawn_index=SPAWN_INDEX,
        drop_index=DROP_INDEX,
        trade_index=TRADE_INDEX,
        advancement_tree=ADVANCEMENT_TREE,
        extract_report=EXTRACT_REPORT,
        curated=CURATED,
        entity_classification=ENTITY_CLASSIFICATION,
    )
    story_root = result.by_id["minecraft:story/root"]
    assert story_root.icon == "BlockSprite:grass-block"
    assert story_root.source_tiers["icon"] is SourceTier.B
    assert not any(m.id == "minecraft:story/root" for m in result.report.missing_icons)


def test_an_enchantment_with_no_icon_is_never_reported() -> None:
    report = run_merge().report
    assert not any(m.id == "minecraft:efficiency" for m in report.missing_icons)


def test_a_resolved_row_with_no_extract_is_reported_missing_blurb() -> None:
    report = run_merge().report
    assert any(m.id == "minecraft:creeper" and m.page == "Creeper" for m in report.missing_blurbs)


def test_a_resolved_extract_is_not_reported_missing() -> None:
    # Tier C overrides `blurb` in the merged result -- see the override test
    # below -- so this checks the raw Tier B contribution through the report
    # instead of the final entity.
    report = run_merge().report
    assert not any(m.id == "minecraft:gunpowder" for m in report.missing_blurbs)


# --- Curated overrides -----------------------------------------------------------


def test_a_curated_override_wins_over_tier_b_for_every_field_it_names() -> None:
    gunpowder = run_merge().by_id["minecraft:gunpowder"]
    assert gunpowder.name == "Gunpowder!!"
    assert gunpowder.icon == "custom:icon"
    assert gunpowder.blurb == "Custom blurb."
    assert gunpowder.wiki_url == "https://minecraft.wiki/w/Gunpowder"
    assert gunpowder.source_tiers["name"] is SourceTier.C
    assert gunpowder.source_tiers["icon"] is SourceTier.C
    assert gunpowder.source_tiers["blurb"] is SourceTier.C
    assert gunpowder.source_tiers["wikiUrl"] is SourceTier.C


def test_a_curated_kind_override_changes_the_built_entity_kind() -> None:
    mystery_thing = run_merge().by_id["minecraft:mystery_thing"]
    assert mystery_thing.kind is EntityKind.BLOCK


def test_a_curated_override_of_an_unknown_id_is_reported() -> None:
    report = run_merge().report
    assert "minecraft:does_not_exist" in report.unknown_curated_overrides


def test_a_curated_alias_is_recorded_at_tier_c() -> None:
    gunpowder = run_merge().by_id["minecraft:gunpowder"]
    assert "gp" in gunpowder.aliases
    assert gunpowder.source_tiers["aliases"] is SourceTier.C


def test_stale_curated_documents_are_carried_into_the_report_unchanged() -> None:
    report = run_merge().report
    assert report.stale_curated_documents == CURATED.stale


# --- Advancement reconciliation and counts --------------------------------------


def test_the_advancement_reconciliation_is_carried_in_the_report() -> None:
    report = run_merge().report
    reconciliation = report.advancement_reconciliation
    assert "story/root" in reconciliation.matched
    assert "story/mine_stone" in reconciliation.matched
    assert "adventure/nothing_here" in reconciliation.missing_from_wiki


def test_counts_are_reported_per_registry_and_in_total() -> None:
    result = run_merge()
    assert result.report.counts["item"] == len(REGISTRIES["item"])
    assert result.report.counts["advancement"] == len(ADVANCEMENT_IDS)
    assert result.report.counts["entities"] == len(result.entities)


def test_the_result_is_indexed_consistently() -> None:
    result = run_merge()
    assert dict(result.by_id) == {entity.id: entity for entity in result.entities}


# --- Shape faults ------------------------------------------------------------------


def test_an_empty_registries_mapping_is_refused() -> None:
    with pytest.raises(NormalizeError, match="no mcmeta registries"):
        merge_entities(
            registries={},
            advancement_ids=ADVANCEMENT_IDS,
            join_table=JOIN_TABLE,
            sprite_index=SPRITE_INDEX,
            infobox_report=INFOBOX_REPORT,
            spawn_index=SPAWN_INDEX,
            drop_index=DROP_INDEX,
            trade_index=TRADE_INDEX,
            advancement_tree=ADVANCEMENT_TREE,
            extract_report=EXTRACT_REPORT,
            curated=CURATED,
            entity_classification=ENTITY_CLASSIFICATION,
        )


def test_an_empty_join_table_is_refused() -> None:
    empty_join_table = parse_resource_locations([])
    with pytest.raises(NormalizeError, match="no entries"):
        merge_entities(
            registries=REGISTRIES,
            advancement_ids=ADVANCEMENT_IDS,
            join_table=empty_join_table,
            sprite_index=SPRITE_INDEX,
            infobox_report=INFOBOX_REPORT,
            spawn_index=SPAWN_INDEX,
            drop_index=DROP_INDEX,
            trade_index=TRADE_INDEX,
            advancement_tree=ADVANCEMENT_TREE,
            extract_report=EXTRACT_REPORT,
            curated=CURATED,
            entity_classification=ENTITY_CLASSIFICATION,
        )


def test_an_empty_sprite_index_is_refused() -> None:
    empty_sprite_index = SpriteIndex.build(entries=(), skipped=())
    with pytest.raises(NormalizeError, match="no entries"):
        merge_entities(
            registries=REGISTRIES,
            advancement_ids=ADVANCEMENT_IDS,
            join_table=JOIN_TABLE,
            sprite_index=empty_sprite_index,
            infobox_report=INFOBOX_REPORT,
            spawn_index=SPAWN_INDEX,
            drop_index=DROP_INDEX,
            trade_index=TRADE_INDEX,
            advancement_tree=ADVANCEMENT_TREE,
            extract_report=EXTRACT_REPORT,
            curated=CURATED,
            entity_classification=ENTITY_CLASSIFICATION,
        )


def test_an_empty_entity_classification_is_refused() -> None:
    empty_classification = EntityClassification(by_path={})
    with pytest.raises(NormalizeError, match="no paths"):
        merge_entities(
            registries=REGISTRIES,
            advancement_ids=ADVANCEMENT_IDS,
            join_table=JOIN_TABLE,
            sprite_index=SPRITE_INDEX,
            infobox_report=INFOBOX_REPORT,
            spawn_index=SPAWN_INDEX,
            drop_index=DROP_INDEX,
            trade_index=TRADE_INDEX,
            advancement_tree=ADVANCEMENT_TREE,
            extract_report=EXTRACT_REPORT,
            curated=CURATED,
            entity_classification=empty_classification,
        )


def test_a_precedence_registry_missing_from_the_mcmeta_payload_is_a_shape_fault() -> None:
    registries = dict(REGISTRIES)
    del registries["item"]
    with pytest.raises(NormalizeError, match="item"):
        merge_entities(
            registries=registries,
            advancement_ids=ADVANCEMENT_IDS,
            join_table=JOIN_TABLE,
            sprite_index=SPRITE_INDEX,
            infobox_report=INFOBOX_REPORT,
            spawn_index=SPAWN_INDEX,
            drop_index=DROP_INDEX,
            trade_index=TRADE_INDEX,
            advancement_tree=ADVANCEMENT_TREE,
            extract_report=EXTRACT_REPORT,
            curated=CURATED,
            entity_classification=ENTITY_CLASSIFICATION,
        )


def test_an_entity_type_id_missing_from_the_classification_is_a_shape_fault() -> None:
    """`_registries_of_id` must refuse to guess when the classifier and the registries disagree.

    A classification built from a different registries payload than the one
    this call was given is a caller bug, per `merge_entities`'s own
    docstring -- not a fact about the game that should silently fall back to
    some default classification for the ID nobody named.
    """
    partial = EntityClassification(
        by_path={
            path: cls for path, cls in ENTITY_CLASSIFICATION.by_path.items() if path != "creeper"
        }
    )
    with pytest.raises(NormalizeError, match="creeper"):
        merge_entities(
            registries=REGISTRIES,
            advancement_ids=ADVANCEMENT_IDS,
            join_table=JOIN_TABLE,
            sprite_index=SPRITE_INDEX,
            infobox_report=INFOBOX_REPORT,
            spawn_index=SPAWN_INDEX,
            drop_index=DROP_INDEX,
            trade_index=TRADE_INDEX,
            advancement_tree=ADVANCEMENT_TREE,
            extract_report=EXTRACT_REPORT,
            curated=CURATED,
            entity_classification=partial,
        )


# --- `write_report` ----------------------------------------------------------------


def test_write_report_creates_parent_directories_and_writes_deterministic_json(
    tmp_path: Path,
) -> None:
    report = run_merge().report
    path = tmp_path / "nested" / "merge-report.json"
    write_report(report, path)

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["counts"]["entities"] == report.counts["entities"]
    assert path.read_text(encoding="utf-8").endswith("\n")


# --- Regression: the join that broke the first live merge ---------------------


def test_a_multi_registry_id_resolves_through_a_lower_precedence_registrys_row() -> None:
    """An ID in two registries must find its wiki row in *either* of them.

    `minecraft:acacia_boat` is an `entity_type` and an `item`, and the wiki
    documents only the item, on the shared `Boat` page. Kind precedence puts
    `entity_type` first, so a lookup that consulted only the chosen registry
    narrowed to the wiki kind `entity`, found nothing, and gave up -- losing
    the name, the page, the blurb and the `wikiUrl` of an entity that has all
    four.

    The first live merge did not merely lose that data, it could not build.
    The icon still resolved through the id route, which reads the hyphenated
    registry path out of `EntitySprite` and needs no wiki row, so the entity
    ended up with a Tier B provenance entry and no attribution link, and
    decision D1 refuses exactly that. Measured against the 26.2 registries on
    2026-08-31, 209 IDs share this shape: the boats, the chest boats, the
    minecarts, the spawn eggs.
    """
    result = run_merge()
    boat = result.by_id["minecraft:acacia_boat"]

    # `item` also wins the kind here, because the wiki's `Acacia Boat` row
    # names the ID exactly and `_registry_the_wiki_names_the_id_under` takes
    # that as the answer to "what is this ID primarily". A boat is an item,
    # so this is the right renderer as well as the right name.
    assert boat.kind is EntityKind.ITEM
    # The name, page and attribution come from the `item` row, the only one
    # the wiki wrote.
    assert boat.name == "Acacia Boat"
    assert boat.wiki_url == "https://minecraft.wiki/w/Acacia_Boat"
    assert boat.source_tiers["name"] is SourceTier.B
    assert boat.source_tiers["wikiUrl"] is SourceTier.B


def test_narrowing_by_kind_still_holds_when_several_registries_are_tried() -> None:
    """Trying more registries must not reopen the ambiguity that narrowing closes."""
    result = run_merge()
    mob = result.by_id["minecraft:entity_type/chicken"]
    assert mob.kind is EntityKind.MOB
    assert mob.name == "Chicken"
    assert mob.name != "Raw Chicken"

    item = result.by_id["minecraft:chicken"]
    assert item.kind is EntityKind.ITEM
    assert item.name == "Raw Chicken"
    assert item.name != "Chicken"


def test_the_registry_whose_wiki_row_names_the_id_wins_over_precedence() -> None:
    """`minecraft:ender_pearl` is an item, whatever the registry precedence says.

    It sits in `entity_type` and in `item`, and the wiki writes two rows:
    `Ender Pearl` for the thing in your hotbar and `Thrown Ender Pearl` for
    the projectile in flight. Straight precedence picked `entity_type`, so the
    live merge named the entity `Thrown Ender Pearl` -- a player typing "ender
    pearl" got no exact match at all, and the page they wanted ranked below
    whatever did match. That is the search-quality failure this task was asked
    to close, arriving through the merge rather than through alias generation.

    Comparing each candidate row's display name against the registry path
    settles it with no hand-written list of exceptions: `ender_pearl` matches
    `Ender Pearl`, so `item` wins the kind and the name.
    """
    result = run_merge()
    pearl = result.by_id["minecraft:ender_pearl"]
    assert pearl.kind is EntityKind.ITEM
    assert pearl.name == "Ender Pearl"


def test_both_meanings_of_a_clashing_id_are_given_separate_entities() -> None:
    """Disjoint display names mean separate entities for the item and the mob.

    `minecraft:chicken` is an item and an entity_type, and the wiki writes
    `Chicken` for the mob and `Raw Chicken` for the food. Rather than tossing
    one meaning away, the merge gives the bare ID to the item and qualifies
    the entity_type as `minecraft:entity_type/chicken`.
    """
    result = run_merge()
    item = result.by_id["minecraft:chicken"]
    assert item.kind is EntityKind.ITEM
    assert item.name == "Raw Chicken"

    mob = result.by_id["minecraft:entity_type/chicken"]
    assert mob.kind is EntityKind.MOB
    assert mob.name == "Chicken"


def test_a_section_is_never_attached_to_an_entity_with_no_attribution_link() -> None:
    """Wiki-authored content without a `wikiUrl` must be dropped and reported, not built.

    Forward resolution and `_own_row` answer two different questions, and they
    can disagree. A trade row names one display name, which may identify a
    registry ID unambiguously; the entity for that ID may still have no page
    of its own, because the wiki gave the ID several names and none of the
    tie-breaks in `_own_row` settles which is the real one.
    `minecraft:jigsaw` is that shape live: the wiki writes both `Jigsaw Block`
    and `Jigsaw structure Jigsaw`.

    Attaching the section anyway would publish a table the wiki compiled with
    no credit, which decision D1 refuses -- and it refuses it inside
    `Entity.__init__`, so the whole build would die at the end of the merge
    naming one ID and nothing about which table caused it. The guard turns
    that into a dropped section and a report entry, which is the same trade
    this module makes everywhere else: a visible gap over a wrong answer.
    """
    result = run_merge()

    jigsaw = result.by_id["minecraft:jigsaw"]
    assert jigsaw.wiki_url is None, "the fixture must keep this entity page-less"
    assert jigsaw.sections == ()

    reported = [row for row in result.report.unplaced if "Jigsaw" in row.subject]
    assert reported, "a dropped section must be reported, never silently lost"
    assert "attribution" in reported[0].reason


# --- Potions: enumerated outside the six-registry union ------------------------


def test_a_potion_entity_gets_the_namespaced_potion_slash_path_id() -> None:
    """Required, not cosmetic: fifteen potion paths collide with a `mob_effect` path."""
    result = run_merge()
    assert "minecraft:potion/awkward" in result.by_id
    assert result.by_id["minecraft:potion/awkward"].kind is EntityKind.ITEM


def test_a_potion_with_a_wiki_page_gets_its_wiki_url() -> None:
    result = run_merge()
    awkward = result.by_id["minecraft:potion/awkward"]
    assert awkward.wiki_url == "https://minecraft.wiki/w/Awkward_Potion"
    assert awkward.name == "Awkward Potion"


def test_a_long_or_strong_potion_variant_has_no_wiki_page_and_still_validates() -> None:
    """No `long_weakness` page exists on the live wiki; D1 must not need one here.

    This fixture attaches no Tier B section to a potion at all, so the real
    proof D1 is satisfied is that this entity builds at all: `Entity.build()`
    would raise if any Tier B section landed on it with no `wikiUrl`.
    """
    result = run_merge()
    long_weakness = result.by_id["minecraft:potion/long_weakness"]
    assert long_weakness.wiki_url is None
    assert long_weakness.name == "Potion of Weakness (Long)"


def test_a_potion_gets_its_own_potion_of_alias() -> None:
    result = run_merge()
    awkward = result.by_id["minecraft:potion/awkward"]
    assert "potion of awkward" in awkward.aliases


def test_a_derived_potion_name_still_gets_the_full_pair_of_aliases() -> None:
    """`awkward`'s own name IS `"Awkward Potion"`, so that alias is dropped as redundant.

    `long_weakness` has no wiki page, so its name is derived
    (`"Potion of Weakness (Long)"`) rather than read off one, and neither
    generated alias collides with it, so both survive.
    """
    result = run_merge()
    long_weakness = result.by_id["minecraft:potion/long_weakness"]
    assert "potion of long weakness" in long_weakness.aliases
    assert "long weakness potion" in long_weakness.aliases


def test_no_potion_registry_key_means_no_potion_entities() -> None:
    """Backward compatible: `registries.get("potion", ())` never raises on a missing key."""
    result = merge_entities(
        registries={k: v for k, v in REGISTRIES.items() if k != "potion"},
        advancement_ids=ADVANCEMENT_IDS,
        join_table=JOIN_TABLE,
        sprite_index=SPRITE_INDEX,
        infobox_report=INFOBOX_REPORT,
        spawn_index=SPAWN_INDEX,
        drop_index=DROP_INDEX,
        trade_index=TRADE_INDEX,
        advancement_tree=ADVANCEMENT_TREE,
        extract_report=EXTRACT_REPORT,
        curated=CURATED,
        entity_classification=ENTITY_CLASSIFICATION,
    )
    assert not any(entity.id.startswith("minecraft:potion/") for entity in result.entities)


# --- Enchanted trade items --------------------------------------------------------


def _merge_enchanted_trades() -> MergeResult:
    """Merge a small fixture whose trades give enchanted items.

    Built private rather than added to the shared fixture, because it needs its
    own registry and its own join table and would otherwise change the counts
    every other test in this file reads.
    """
    join_table = parse_resource_locations(
        [
            rl_row("Diamond Chestplate", "diamond_chestplate", "item"),
            # Both of these are real registry items whose own display name
            # starts with "Enchanted", which is what the exact-name-first rule
            # has to protect.
            rl_row("Enchanted Book", "enchanted_book", "item"),
            rl_row("Book", "book", "item"),
        ]
    )

    def trade(given: str) -> WikiTrade:
        return WikiTrade(
            profession="Armorer",
            page="Armorer",
            wiki_url="https://minecraft.wiki/w/Armorer",
            level="Master",
            wanted=(TradeItem(item="Emerald", quantity=WikiIntegerRange(minimum=8, maximum=8)),),
            given=TradeItem(item=given, quantity=WikiIntegerRange(minimum=1, maximum=1)),
            java_probability=None,
            max_trades=None,
            villager_xp=None,
            price_multiplier=None,
        )

    return merge_entities(
        # Every registry the merge precedence names has to be present, so the
        # others are carried through empty rather than dropped.
        registries={
            key: (["diamond_chestplate", "enchanted_book", "book"] if key == "item" else [])
            for key in REGISTRIES
        },
        advancement_ids=(),
        join_table=join_table,
        sprite_index=SPRITE_INDEX,
        infobox_report=INFOBOX_REPORT,
        spawn_index=SPAWN_INDEX,
        drop_index=DROP_INDEX,
        trade_index=TradeIndex.build(
            [
                trade("Diamond Chestplate"),
                trade("Enchanted Diamond Chestplate"),
                trade("Enchanted Book"),
            ]
        ),
        advancement_tree=ADVANCEMENT_TREE,
        extract_report=EXTRACT_REPORT,
        curated=CURATED,
        entity_classification=ENTITY_CLASSIFICATION,
    )


def test_an_enchanted_item_trade_attaches_to_the_item_it_enchants() -> None:
    """An enchantment is data on a stack, so `Enchanted Diamond Chestplate` is no registry entry.

    Without the fallback the row resolved to nothing and fell out as unplaced,
    which is why Diamond Chestplate, Diamond Pickaxe, Diamond Sword and Fishing
    Rod each carried no trades at all on the 26.2 build.
    """
    result = _merge_enchanted_trades()

    chestplate = result.by_id["minecraft:diamond_chestplate"]
    table = next(section for section in chestplate.sections if section.type == "TradeTable")

    given = next(
        trade.given
        for trade in table.trades
        if trade.given.name == "Enchanted Diamond Chestplate"
    )
    # The name keeps the qualifier, because an Armorer sells an enchanted one
    # and a page that called it a plain diamond chestplate would be wrong.
    assert given.name == "Enchanted Diamond Chestplate"
    assert given.ref is not None
    assert given.ref.id == "minecraft:diamond_chestplate"

    assert not any(row.table == "trade" for row in result.report.unplaced)


def test_a_real_item_named_enchanted_resolves_to_itself_not_to_its_base() -> None:
    """`Enchanted Book` is its own registry item, so stripping the prefix would be wrong.

    This is the guard on the rule above: the exact name is tried first, and the
    fallback only ever runs when it finds nothing.
    """
    result = _merge_enchanted_trades()

    book = result.by_id["minecraft:enchanted_book"]
    table = next(section for section in book.sections if section.type == "TradeTable")
    assert table.trades[0].given.ref is not None
    assert table.trades[0].given.ref.id == "minecraft:enchanted_book"

    # The plain book must not have picked up the enchanted book's trade.
    plain = result.by_id["minecraft:book"]
    assert not any(section.type == "TradeTable" for section in plain.sections)


def test_two_display_names_for_one_item_keep_both_trades() -> None:
    """A Fletcher sells a `Bow` and an `Enchanted Bow`, and both are `minecraft:bow`.

    `EntityDraft.add_section` is keyed by section type, so attaching a second
    table for the same item replaces the first rather than extending it. The
    merge groups by resolved target before it attaches, or the plain trade
    disappears the moment the enchanted one resolves to the same place.
    """
    result = _merge_enchanted_trades()

    chestplate = result.by_id["minecraft:diamond_chestplate"]
    table = next(section for section in chestplate.sections if section.type == "TradeTable")

    assert [trade.given.name for trade in table.trades] == [
        "Diamond Chestplate",
        "Enchanted Diamond Chestplate",
    ]


def test_wolf_breeding_and_taming_items_never_conflated() -> None:
    """Wolf is bred with meat and tamed with bones: those must never share a field."""
    wolf_registries = {
        "entity_type": ["wolf"],
        "block": [],
        "item": ["bone", "porkchop"],
        "mob_effect": [],
        "worldgen/biome": [],
        "enchantment": [],
    }
    wolf_join_table = parse_resource_locations(
        [
            rl_row("Wolf", "wolf", kind="entity"),
            rl_row("Bone", "bone", kind="item"),
            rl_row("Porkchop", "porkchop", kind="item"),
        ]
    )
    wolf_classification = EntityClassification(
        by_path={"wolf": EntityClass.SPAWN_EGG}
    )
    breeding_index = enrich_breeding.BreedingIndex(
        by_mob={
            "Wolf": enrich_breeding.MobBreeding(
                mob="Wolf",
                items=("Porkchop",),
                requires_taming=True,
            )
        }
    )
    curated = CuratedData(
        aliases={},
        overrides={},
        taming={"minecraft:wolf": ("Bone",)},
    )
    result = merge_entities(
        registries=wolf_registries,
        advancement_ids=(),
        join_table=wolf_join_table,
        sprite_index=SPRITE_INDEX,
        infobox_report=INFOBOX_REPORT,
        spawn_index=SPAWN_INDEX,
        drop_index=DROP_INDEX,
        trade_index=TRADE_INDEX,
        advancement_tree=ADVANCEMENT_TREE,
        extract_report=EXTRACT_REPORT,
        curated=curated,
        entity_classification=wolf_classification,
        breeding_index=breeding_index,
    )

    wolf = result.by_id["minecraft:wolf"]
    breeding_info = next(s for s in wolf.sections if isinstance(s, BreedingInfo))
    assert breeding_info.requires_taming is True
    assert [item.name for item in breeding_info.items] == ["Porkchop"]
    assert breeding_info.items[0].ref is not None
    assert breeding_info.items[0].ref.id == "minecraft:porkchop"
    assert "Bone" not in [item.name for item in breeding_info.items]
    assert [item.name for item in breeding_info.taming_items] == ["Bone"]
    assert breeding_info.taming_items[0].ref is not None
    assert breeding_info.taming_items[0].ref.id == "minecraft:bone"


def test_harvest_info_attached_to_block() -> None:
    test_registries = {
        "entity_type": ["creeper"],
        "block": ["obsidian", "oak_log", "stone"],
        "item": [],
        "mob_effect": [],
        "worldgen/biome": [],
        "enchantment": [],
    }
    test_join_table = parse_resource_locations(
        [
            rl_row("Creeper", "creeper", "entity"),
            rl_row("Obsidian", "obsidian", "block"),
            rl_row("Oak Log", "oak_log", "block"),
            rl_row("Stone", "stone", "block"),
        ]
    )
    harvest_index = {
        "minecraft:obsidian": BlockHarvest(
            block="minecraft:obsidian",
            tools=(HarvestTool.PICKAXE,),
            tier=HarvestTier.DIAMOND,
        ),
        "minecraft:oak_log": BlockHarvest(
            block="minecraft:oak_log",
            tools=(HarvestTool.AXE,),
            tier=HarvestTier.WOODEN,
        ),
        "minecraft:stone": BlockHarvest(
            block="minecraft:stone",
            tools=(HarvestTool.PICKAXE,),
            tier=HarvestTier.WOODEN,
        ),
    }
    result = merge_entities(
        registries=test_registries,
        advancement_ids=(),
        join_table=test_join_table,
        sprite_index=SPRITE_INDEX,
        infobox_report=INFOBOX_REPORT,
        spawn_index=SPAWN_INDEX,
        drop_index=DROP_INDEX,
        trade_index=TRADE_INDEX,
        advancement_tree=ADVANCEMENT_TREE,
        extract_report=EXTRACT_REPORT,
        curated=CURATED,
        entity_classification=ENTITY_CLASSIFICATION,
        harvest_index=harvest_index,
    )
    obsidian = result.by_id["minecraft:obsidian"]
    h_obsidian = next(s for s in obsidian.sections if isinstance(s, HarvestInfo))
    assert obsidian.sections[0] == h_obsidian
    assert h_obsidian.tools == (HarvestTool.PICKAXE,)
    assert h_obsidian.tier == HarvestTier.DIAMOND
    assert h_obsidian.drops_without_tool is False

    oak_log = result.by_id["minecraft:oak_log"]
    h_oak = next(s for s in oak_log.sections if isinstance(s, HarvestInfo))
    assert oak_log.sections[0] == h_oak
    assert h_oak.tools == (HarvestTool.AXE,)
    assert h_oak.tier == HarvestTier.WOODEN
    assert h_oak.drops_without_tool is True

    stone = result.by_id["minecraft:stone"]
    h_stone = next(s for s in stone.sections if isinstance(s, HarvestInfo))
    assert stone.sections[0] == h_stone
    assert h_stone.tools == (HarvestTool.PICKAXE,)
    assert h_stone.tier == HarvestTier.WOODEN
    assert h_stone.drops_without_tool is False


def test_harvest_info_unplaced_row_recorded() -> None:
    test_registries = {
        "entity_type": ["creeper"],
        "block": [],
        "item": [],
        "mob_effect": [],
        "worldgen/biome": [],
        "enchantment": [],
    }
    test_join_table = parse_resource_locations([rl_row("Creeper", "creeper", "entity")])
    harvest_index = {
        "minecraft:ghost_block": BlockHarvest(
            block="minecraft:ghost_block",
            tools=(HarvestTool.PICKAXE,),
            tier=HarvestTier.STONE,
        ),
    }
    result = merge_entities(
        registries=test_registries,
        advancement_ids=(),
        join_table=test_join_table,
        sprite_index=SPRITE_INDEX,
        infobox_report=INFOBOX_REPORT,
        spawn_index=SPAWN_INDEX,
        drop_index=DROP_INDEX,
        trade_index=TRADE_INDEX,
        advancement_tree=ADVANCEMENT_TREE,
        extract_report=EXTRACT_REPORT,
        curated=CURATED,
        entity_classification=ENTITY_CLASSIFICATION,
        harvest_index=harvest_index,
    )
    unplaced = [r for r in result.report.unplaced if r.table == "harvest"]
    assert len(unplaced) == 1
    assert unplaced[0].subject == "minecraft:ghost_block"

