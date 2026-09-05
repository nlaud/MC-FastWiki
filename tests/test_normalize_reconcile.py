"""The Tier A / Tier B reconciliation report, and the two counts it must not conflate.

`pipeline.normalize.reconcile` answers two different questions about one
registry ID, and this module's own docstring names the trap in conflating
them: whether the wiki knows the ID at all (`missing_from_tier_b`) is not the
same question as whether an icon chain resolves for it (`missing_icons`),
because the id-based half of a chain needs no wiki row to succeed. Every test
below builds its join table and sprite index in memory, one trap per test, the
way `tests/test_enrich_resource_location.py` and `tests/test_enrich_sprite.py`
do for the tables this module joins.
"""

import json
from pathlib import Path

import pytest

from pipeline.enrich.resource_location import parse_resource_locations
from pipeline.enrich.sprite import SpriteIndex, parse_sprite_files
from pipeline.normalize import NormalizeError
from pipeline.normalize.reconcile import (
    ICON_RULES,
    AmbiguousIcon,
    IconRule,
    MissingEntity,
    MissingIcon,
    hyphenated_sprite_id,
    reconcile,
    resolve_display_name_icon,
    resolve_icon,
    write_report,
)


def rl_row(display_name: str, resource_location: str, kind: str = "item") -> dict[str, object]:
    """Return one `resource_location` row, shaped the way the live API sends it."""
    return {
        "page_name": display_name,
        "display_name": display_name,
        "resource_location": resource_location,
        "json": json.dumps({"Edition": "java", "Type": kind}),
    }


def sprite_row(family: str, sprite_id: str, file_title: str | None = None) -> dict[str, object]:
    """Return one `spritefile` row, shaped the way the live API sends it."""
    resolved = file_title if file_title is not None else f"File:{family} {sprite_id}.png"
    return {"page_name": resolved, "name": family, "id": sprite_id, "file": resolved}


# --- `hyphenated_sprite_id` ----------------------------------------------------


def test_an_underscore_becomes_a_hyphen() -> None:
    """`BlockSprite` writes `acacia-button` where the registry writes `acacia_button`."""
    assert hyphenated_sprite_id("acacia_button") == "acacia-button"


def test_a_namespaced_id_has_its_prefix_stripped_first() -> None:
    """A sprite id never carries a namespace, whichever form the caller passes in."""
    assert hyphenated_sprite_id("minecraft:acacia_button") == "acacia-button"
    assert hyphenated_sprite_id("acacia_button") == hyphenated_sprite_id("minecraft:acacia_button")


def test_an_id_with_no_underscore_is_unchanged() -> None:
    assert hyphenated_sprite_id("creeper") == "creeper"


# --- `resolve_icon`: the display-name route ------------------------------------


def test_the_display_name_route_resolves_through_invsprite() -> None:
    """`item`'s rule tries `InvSprite` first, keyed by the wiki's own display name."""
    join_table = parse_resource_locations([rl_row("Iron Sword", "iron_sword", "item")])
    sprite_index = parse_sprite_files(
        [sprite_row("InvSprite", "Iron Sword", "File:Invicon Iron Sword.png")]
    )
    resolution = resolve_icon(
        "minecraft:iron_sword", ICON_RULES["item"], join_table, sprite_index
    )

    assert resolution.sprite is not None
    assert resolution.sprite.file_title == "File:Invicon Iron Sword.png"
    assert resolution.matched_family == "InvSprite"
    assert resolution.matched_route == "display_name"


def test_the_id_route_resolves_with_no_wiki_row_at_all() -> None:
    """The id-based fallback needs no `resource_location` row, unlike the display-name route.

    This is why `missing_from_tier_b` and `missing_icons` are different counts:
    a registry ID absent from every wiki row can still have a working icon.
    """
    join_table = parse_resource_locations([rl_row("Something Else", "something_else")])
    sprite_index = parse_sprite_files(
        [sprite_row("BlockSprite", "acacia-button")]
    )
    resolution = resolve_icon(
        "minecraft:acacia_button", ICON_RULES["block"], join_table, sprite_index
    )

    assert resolution.sprite is not None
    assert resolution.matched_family == "BlockSprite"
    assert resolution.matched_route == "id"


def test_the_display_name_route_is_tried_before_the_id_route() -> None:
    """`item` prefers `InvSprite`; a caller must not fall to the id route when it need not."""
    join_table = parse_resource_locations([rl_row("Iron Sword", "iron_sword", "item")])
    sprite_index = parse_sprite_files(
        [
            sprite_row("InvSprite", "Iron Sword", "File:Correct.png"),
            sprite_row("ItemSprite", "iron-sword", "File:Wrong.png"),
        ]
    )
    resolution = resolve_icon(
        "minecraft:iron_sword", ICON_RULES["item"], join_table, sprite_index
    )
    assert resolution.sprite is not None
    assert resolution.sprite.file_title == "File:Correct.png"


def test_an_ambiguous_display_name_is_never_used_to_pick_an_icon() -> None:
    """The join table already refuses to choose; picking an icon through it would be the same
    wrong choice from the other direction.
    """
    join_table = parse_resource_locations(
        [
            rl_row("Air", "air", "block"),
            rl_row("Air", "air_block", "block"),
        ]
    )
    sprite_index = parse_sprite_files([sprite_row("InvSprite", "Air")])
    resolution = resolve_icon("minecraft:air", ICON_RULES["block"], join_table, sprite_index)

    assert resolution.sprite is None
    assert resolution.ambiguous_display_name == "Air"


def test_an_ambiguous_display_name_still_lets_the_id_route_resolve() -> None:
    """A working id-based icon means the ambiguity never surfaces as a report line at all."""
    join_table = parse_resource_locations(
        [
            rl_row("Air", "air", "block"),
            rl_row("Air", "air_block", "block"),
        ]
    )
    sprite_index = parse_sprite_files([sprite_row("BlockSprite", "air")])
    resolution = resolve_icon("minecraft:air", ICON_RULES["block"], join_table, sprite_index)

    assert resolution.sprite is not None
    assert resolution.matched_route == "id"
    assert resolution.ambiguous_display_name is None


def test_a_rule_with_no_display_name_family_skips_that_route_entirely() -> None:
    """`entity_type` has no `InvSprite`-style route; only the id-based chain runs."""
    join_table = parse_resource_locations([rl_row("Creeper", "creeper", "entity")])
    sprite_index = parse_sprite_files([sprite_row("EntitySprite", "creeper")])
    resolution = resolve_icon(
        "minecraft:creeper", ICON_RULES["entity_type"], join_table, sprite_index
    )
    assert resolution.sprite is not None
    assert resolution.matched_route == "id"


def test_every_route_tried_is_recorded_even_on_a_full_miss() -> None:
    join_table = parse_resource_locations([rl_row("Ghost Item", "ghost_item", "item")])
    sprite_index = parse_sprite_files([sprite_row("InvSprite", "Unrelated")])
    resolution = resolve_icon("minecraft:ghost_item", ICON_RULES["item"], join_table, sprite_index)

    assert resolution.sprite is None
    assert ("InvSprite", "Ghost Item") in resolution.routes_tried
    assert ("ItemSprite", "ghost-item") in resolution.routes_tried
    assert ("BlockSprite", "ghost-item") in resolution.routes_tried


def test_an_empty_sprite_index_cannot_be_built_for_this_test() -> None:
    """`parse_sprite_files` itself refuses an empty row list -- see `pipeline.enrich.sprite`."""
    with pytest.raises(Exception, match="no rows"):
        parse_sprite_files([])


# --- `reconcile` ---------------------------------------------------------------


def _registries(**overrides: list[str]) -> dict[str, list[str]]:
    """Return a full `ICON_RULES`-shaped registries mapping, empty unless overridden."""
    base: dict[str, list[str]] = {name: [] for name in ICON_RULES}
    base.update(overrides)
    return base


def test_a_tier_a_id_with_no_wiki_row_is_reported_missing_from_tier_b() -> None:
    join_table = parse_resource_locations([rl_row("Iron Sword", "iron_sword", "item")])
    sprite_index = parse_sprite_files([sprite_row("InvSprite", "Iron Sword")])
    registries = _registries(item=["iron_sword", "poplar_boat"])

    report = reconcile(registries=registries, join_table=join_table, sprite_index=sprite_index)

    assert report.missing_from_tier_b == (
        MissingEntity(registry="item", registry_id="minecraft:poplar_boat"),
    )


def test_an_id_route_icon_does_not_need_a_wiki_row() -> None:
    """The measured fact the module docstring gives: most `poplar_*` items still have icons."""
    join_table = parse_resource_locations([rl_row("Something", "something", "item")])
    sprite_index = parse_sprite_files([sprite_row("ItemSprite", "poplar-boat")])
    registries = _registries(item=["poplar_boat"])

    report = reconcile(registries=registries, join_table=join_table, sprite_index=sprite_index)

    assert report.missing_from_tier_b == (
        MissingEntity(registry="item", registry_id="minecraft:poplar_boat"),
    )
    assert report.missing_icons == ()
    assert report.counts["item"].iconed == 1


def test_a_registry_id_with_neither_a_wiki_row_nor_an_icon_is_reported_both_ways() -> None:
    join_table = parse_resource_locations([rl_row("Something", "something", "item")])
    sprite_index = parse_sprite_files([sprite_row("InvSprite", "Something")])
    registries = _registries(item=["sulfur_cube_bucket"])

    report = reconcile(registries=registries, join_table=join_table, sprite_index=sprite_index)

    assert report.missing_from_tier_b == (
        MissingEntity(registry="item", registry_id="minecraft:sulfur_cube_bucket"),
    )
    assert report.missing_icons == (
        MissingIcon(
            registry="item",
            registry_id="minecraft:sulfur_cube_bucket",
            routes_tried=(
                ("ItemSprite", "sulfur-cube-bucket"),
                ("BlockSprite", "sulfur-cube-bucket"),
            ),
        ),
    )


def test_a_wiki_id_matching_no_registry_at_all_is_missing_from_tier_a() -> None:
    """`blockBorder` is a real wiki row and a gamerule key, not a registry ID."""
    join_table = parse_resource_locations(
        [rl_row("Block Border", "blockBorder", "item"), rl_row("Iron Sword", "iron_sword", "item")]
    )
    sprite_index = parse_sprite_files([sprite_row("InvSprite", "Iron Sword")])
    registries = _registries(item=["iron_sword"])

    report = reconcile(registries=registries, join_table=join_table, sprite_index=sprite_index)

    assert report.missing_from_tier_a == ("minecraft:blockBorder",)


def test_membership_is_checked_against_every_registry_not_a_handful() -> None:
    """`ancient_city` lives in `worldgen/structure`, not `block` or `item` -- a false alarm averted
    only by checking every registry mcmeta publishes.
    """
    join_table = parse_resource_locations([rl_row("Ancient City", "ancient_city", "structure")])
    sprite_index = parse_sprite_files([sprite_row("InvSprite", "Placeholder")])
    registries = _registries()
    registries["worldgen/structure"] = ["ancient_city"]

    report = reconcile(registries=registries, join_table=join_table, sprite_index=sprite_index)

    assert report.missing_from_tier_a == ()


def test_an_ambiguous_display_name_is_reported_as_an_ambiguity_not_a_miss() -> None:
    join_table = parse_resource_locations(
        [rl_row("Air", "air", "block"), rl_row("Air", "air_block", "block")]
    )
    sprite_index = parse_sprite_files([sprite_row("InvSprite", "Air")])
    registries = _registries(block=["air"])

    report = reconcile(registries=registries, join_table=join_table, sprite_index=sprite_index)

    assert report.ambiguous_icons == (
        AmbiguousIcon(
            registry="block",
            registry_id="minecraft:air",
            display_name="Air",
            candidate_registry_ids=("minecraft:air", "minecraft:air_block"),
        ),
    )
    assert report.missing_icons == ()


def test_enchantment_is_exempt_and_never_produces_missing_icons() -> None:
    join_table = parse_resource_locations([rl_row("Efficiency", "efficiency", "item")])
    sprite_index = parse_sprite_files([sprite_row("InvSprite", "Placeholder")])
    registries = _registries(enchantment=["efficiency", "sharpness", "mending"])

    report = reconcile(registries=registries, join_table=join_table, sprite_index=sprite_index)

    assert report.missing_icons == ()
    assert report.exempt_registries[0].registry == "enchantment"
    assert "enchantment sprite family" in report.exempt_registries[0].reason
    assert report.counts["enchantment"].iconed == 0
    assert report.counts["enchantment"].missing == 0
    assert report.counts["enchantment"].total == 3


def test_counts_summarize_every_reconciled_registry() -> None:
    join_table = parse_resource_locations(
        [rl_row("Iron Sword", "iron_sword", "item"), rl_row("Ghost", "ghost_item", "item")]
    )
    sprite_index = parse_sprite_files([sprite_row("InvSprite", "Iron Sword")])
    registries = _registries(item=["iron_sword", "ghost_item"])

    report = reconcile(registries=registries, join_table=join_table, sprite_index=sprite_index)

    assert report.counts["item"].total == 2
    assert report.counts["item"].iconed == 1
    assert report.counts["item"].missing == 1


def test_an_empty_registries_mapping_is_refused() -> None:
    sprite_index = parse_sprite_files([sprite_row("InvSprite", "X")])
    with pytest.raises(NormalizeError, match="no mcmeta registries"):
        reconcile(registries={}, join_table=parse_resource_locations([rl_row("X", "x")]),
                  sprite_index=sprite_index)


def test_a_sprite_index_with_no_entries_is_refused() -> None:
    """An empty spritefile read is a failed scrape, not a wiki with no sprites.

    Built by hand rather than through `parse_sprite_files`, which already
    refuses an empty row list on its own -- this proves `reconcile` enforces
    the rule itself too, for a `SpriteIndex` that reaches it some other way.
    """
    join_table = parse_resource_locations([rl_row("X", "x")])
    empty_index = SpriteIndex.build(entries=(), skipped=())
    registries = _registries(item=["x"])
    with pytest.raises(NormalizeError, match="no entries"):
        reconcile(registries=registries, join_table=join_table, sprite_index=empty_index)


def test_an_icon_rule_registry_missing_from_the_mcmeta_payload_is_a_shape_fault() -> None:
    """A stale `ICON_RULES` registry against a renamed or removed registry is not zero misses."""
    join_table = parse_resource_locations([rl_row("X", "x")])
    sprite_index = parse_sprite_files([sprite_row("InvSprite", "X")])
    registries = _registries()
    del registries["item"]

    with pytest.raises(NormalizeError, match="item"):
        reconcile(registries=registries, join_table=join_table, sprite_index=sprite_index)


# --- `write_report` -------------------------------------------------------------


def test_write_report_creates_parent_directories_and_writes_deterministic_json(
    tmp_path: Path,
) -> None:
    join_table = parse_resource_locations([rl_row("Iron Sword", "iron_sword", "item")])
    sprite_index = parse_sprite_files([sprite_row("InvSprite", "Iron Sword")])
    registries = _registries(item=["iron_sword"])
    report = reconcile(registries=registries, join_table=join_table, sprite_index=sprite_index)
    path = tmp_path / "nested" / "tier-reconciliation.json"

    write_report(report, path)

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["counts"]["item"]["total"] == 1
    assert path.read_text(encoding="utf-8").endswith("\n")


# --- `IconRule` ------------------------------------------------------------------


def test_a_rule_with_no_families_and_has_icons_true_would_never_resolve() -> None:
    """Not a refused construction -- documented in `IconRule`'s own docstring as the reason
    `enchantment` instead sets `has_icons=False`.
    """
    rule = IconRule(registry="nothing")
    join_table = parse_resource_locations([rl_row("X", "x")])
    sprite_index = parse_sprite_files([sprite_row("InvSprite", "X")])
    resolution = resolve_icon("minecraft:x", rule, join_table, sprite_index)
    assert resolution.sprite is None
    assert resolution.routes_tried == ()


# --- `resolve_display_name_icon` and scoped ambiguity ---------------------------


def test_resolve_display_name_icon_strips_file_extension() -> None:
    """Extensions like .gif and .png in wiki image parameters are stripped."""
    join_table = parse_resource_locations([rl_row("Wheat", "wheat", "item")])
    sprite_index = parse_sprite_files([sprite_row("InvSprite", "Wheat")])

    res = resolve_display_name_icon("Wheat.gif", join_table, sprite_index)
    assert res.sprite is not None
    assert res.sprite.file_title == "File:InvSprite Wheat.png"


def test_resolve_display_name_icon_id_fallback() -> None:
    """When display_name route finds no sprite, candidate's id route is tried."""
    join_table = parse_resource_locations([rl_row("Wind Charge", "wind_charge", "item")])
    sprite_index = parse_sprite_files([sprite_row("ItemSprite", "wind-charge")])

    res = resolve_display_name_icon("Wind Charge", join_table, sprite_index)
    assert res.sprite is not None
    assert res.sprite.file_title == "File:ItemSprite wind-charge.png"
    assert res.matched_route == "id"


def test_resolve_icon_scopes_ambiguity_to_rule_join_kinds() -> None:
    """Item ender_eye resolves because entity eye_of_ender is outside item join kinds."""
    join_table = parse_resource_locations(
        [
            rl_row("Eye of Ender", "ender_eye", "item"),
            rl_row("Eye of Ender", "eye_of_ender", "entity"),
        ]
    )
    sprite_index = parse_sprite_files([sprite_row("InvSprite", "Eye of Ender")])

    res = resolve_icon("minecraft:ender_eye", ICON_RULES["item"], join_table, sprite_index)
    assert res.sprite is not None
    assert res.sprite.file_title == "File:InvSprite Eye of Ender.png"


def test_resolve_display_name_icon_scopes_ambiguity_to_item_block_first() -> None:
    """Display name with item and entity candidates prioritizes item/block without ambiguity."""
    join_table = parse_resource_locations(
        [
            rl_row("Eye of Ender", "ender_eye", "item"),
            rl_row("Eye of Ender", "eye_of_ender", "entity"),
        ]
    )
    sprite_index = parse_sprite_files([sprite_row("InvSprite", "Eye of Ender")])

    res = resolve_display_name_icon("Eye of Ender", join_table, sprite_index)
    assert res.sprite is not None
    assert res.sprite.file_title == "File:InvSprite Eye of Ender.png"


def test_resolve_display_name_icon_declines_when_ambiguous_within_join_kinds() -> None:
    """Two items sharing the same display name cannot be resolved unambiguously."""
    join_table = parse_resource_locations(
        [
            rl_row("Widget", "widget_a", "item"),
            rl_row("Widget", "widget_b", "item"),
        ]
    )
    sprite_index = parse_sprite_files([sprite_row("InvSprite", "Widget")])

    res = resolve_display_name_icon("Widget", join_table, sprite_index)
    assert res.sprite is None
    assert res.routes_tried == (("ambiguous", "Widget"),)
    assert res.ambiguous_display_name == "Widget"


def test_resolve_display_name_icon_missing_candidate_reports_routes_tried() -> None:
    """A display name with no candidate returns None with tried routes."""
    join_table = parse_resource_locations([])
    sprite_index = parse_sprite_files([sprite_row("InvSprite", "something")])

    res = resolve_display_name_icon("Uncraftable Potion", join_table, sprite_index)
    assert res.sprite is None
    assert res.routes_tried == (("display_name", "Uncraftable Potion"),)

