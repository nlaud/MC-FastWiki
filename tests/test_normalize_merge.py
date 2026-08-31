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
from pipeline.enrich.advancement import AdvancementTree, WikiAdvancement
from pipeline.enrich.droptable import DropIndex, LootingDrop, MobDrop
from pipeline.enrich.droptable import Ratio as DropRatio
from pipeline.enrich.infobox import EntityInfobox, HealthValue, InfoboxReport
from pipeline.enrich.infobox import Measure as InfoboxMeasure
from pipeline.enrich.resource_location import parse_resource_locations
from pipeline.enrich.spawn_table import SpawnEntry, SpawnIndex
from pipeline.enrich.sprite import SpriteIndex, parse_sprite_files
from pipeline.enrich.trade import Probability, TradeIndex, TradeItem, WikiTrade
from pipeline.fetch.extracts import ExtractReport, PageExtract
from pipeline.normalize import NormalizeError
from pipeline.normalize.curated import CuratedData, EntityOverride, StaleDocument
from pipeline.normalize.entity import EntityKind, SourceTier
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
    "entity_type": ["creeper", "chicken", "acacia_boat", "ender_pearl"],
    "block": [],
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
    ],
    "mob_effect": [],
    "worldgen/biome": ["jungle"],
    "enchantment": ["efficiency"],
}

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
        # Two names for one ID, neither of which normalises to `jigsaw` and
        # neither of which is shared with another ID. Every tie-break in
        # `_own_row` declines this on purpose, so the entity has no page.
        rl_row("Jigsaw Block", "jigsaw", "item"),
        rl_row("Jigsaw structure Jigsaw", "jigsaw", "item"),
        # poplar_boat and mystery_thing carry no row at all -- the D1 shape.
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
    )


# --- Enumeration and precedence ----------------------------------------------


def test_an_id_in_two_registries_becomes_one_entity_with_the_precedence_kind() -> None:
    result = run_merge()
    chicken = result.by_id["minecraft:chicken"]
    assert chicken.kind is EntityKind.MOB
    assert chicken.name == "Chicken"  # the entity-kind row, not the item row

    entry = next(m for m in result.report.multi_registry if m.id == "minecraft:chicken")
    assert entry.registries == ("entity_type", "item")
    assert entry.kind is EntityKind.MOB


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
    """Trying more registries must not reopen the ambiguity that narrowing closes.

    `IconRule.join_kinds` exists because `minecraft:chicken` is the raw
    chicken *item* and the chicken *mob*, and resolving one through the
    other's row is the wrong-answer failure this project ranks below a
    missing one. Walking `entity_type` and then `item` asks for each kind
    separately and takes the first hit, so the mob still wins its own row --
    but a future edit that dropped the narrowing to "just take any row" would
    pass the test above and fail this one.
    """
    result = run_merge()
    chicken = result.by_id["minecraft:chicken"]
    assert chicken.kind is EntityKind.MOB
    assert chicken.name == "Chicken"
    assert chicken.name != "Raw Chicken"


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


def test_a_name_match_never_displaces_a_registry_that_precedence_already_prefers() -> None:
    """The counterpart check, and the one that keeps the rule safe.

    `minecraft:chicken` is also an `entity_type` and an `item`, and the wiki
    writes `Chicken` for the mob and `Raw Chicken` for the food. Here the
    higher-precedence registry is the one whose row names the ID, so nothing
    moves and the mob keeps the page. A rule that preferred `item` in general
    would have renamed the chicken mob to `Raw Chicken`.
    """
    result = run_merge()
    chicken = result.by_id["minecraft:chicken"]
    assert chicken.kind is EntityKind.MOB
    assert chicken.name == "Chicken"


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
