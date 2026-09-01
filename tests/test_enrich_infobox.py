"""The nine infobox field parsers, one trap per test.

Every shape here is quoted from section 3 of the implementation brief, which
verified each one against the live wiki on 2026-08-30. Each test builds a
minimal `{{Infobox entity}}` in memory and reads it through `parse_infobox`,
the public entry point -- no test reaches into the private field parsers
directly, so a change to how a field is walked internally cannot silently
break what a caller actually sees.
"""

from decimal import Decimal

import pytest

from pipeline.enrich import EnrichError
from pipeline.enrich.infobox import (
    Difficulty,
    EntityInfobox,
    FilteredLine,
    UnparsedField,
    parse_infobox,
    select_infobox_pages,
)


def infobox(**fields: str) -> str:
    """Return the wikitext of a page whose `{{Infobox entity}}` carries `fields`."""
    body = "\n".join(f"| {name} = {value}" for name, value in fields.items())
    return f"{{{{Infobox entity\n{body}\n}}}}"


PAGE = "TestMob"


def parse(
    **fields: str,
) -> tuple[EntityInfobox, tuple[UnparsedField, ...], tuple[FilteredLine, ...]]:
    return parse_infobox(PAGE, infobox(**fields))


# --- No infobox at all: a shape fault, not an unparsed field ----------------


def test_a_page_with_no_infobox_template_raises() -> None:
    with pytest.raises(EnrichError, match="Infobox entity"):
        parse_infobox(PAGE, "Just some prose, no template here.")


# --- health -------------------------------------------------------------------


def test_health_plain() -> None:
    entity, unparsed, _ = parse(health="{{hp|20}}")
    assert len(entity.health) == 1
    assert entity.health[0].labels == ()
    assert entity.health[0].value.minimum == Decimal("20")
    assert entity.health[0].value.is_fixed
    assert unparsed == ()


def test_health_extra_named_argument_is_ignored_for_the_value() -> None:
    """`{{hp|10|mob=1}}` -- Pig's health."""
    entity, _, _ = parse(health="{{hp|10|mob=1}}")
    assert entity.health[0].value.minimum == Decimal("10")


def test_health_second_template_name() -> None:
    """`{{health|10}}` -- Dolphin, Hoglin."""
    entity, _, _ = parse(health="{{health|10}}")
    assert entity.health[0].value.minimum == Decimal("10")


def test_health_labelled_variants_large_medium() -> None:
    """`'''Large:''' {{hp|16}}<br>'''Medium:''' {{hp|4}}` -- Magma Cube, Slime."""
    entity, _, _ = parse(health="'''Large:''' {{hp|16}}<br>'''Medium:''' {{hp|4}}")
    by_label = {value.labels: value.value.minimum for value in entity.health}
    assert by_label[("Large",)] == Decimal("16")
    assert by_label[("Medium",)] == Decimal("4")


def test_health_labelled_variants_wild_tamed() -> None:
    """`'''Wild:''' {{hp|8}}<br>'''Tamed:''' {{hp|40}}` -- Wolf."""
    entity, _, _ = parse(health="'''Wild:''' {{hp|8}}<br>'''Tamed:''' {{hp|40}}")
    by_label = {value.labels: value.value.minimum for value in entity.health}
    assert by_label[("Wild",)] == Decimal("8")
    assert by_label[("Tamed",)] == Decimal("40")


def test_health_inline_labels_not_bold() -> None:
    """`Uncracked: {{hp|100}}<br>Low cracked: {{hp|75}}` -- Iron Golem."""
    entity, _, _ = parse(health="Uncracked: {{hp|100}}<br>Low cracked: {{hp|75}}")
    by_label = {value.labels: value.value.minimum for value in entity.health}
    assert by_label[("Uncracked",)] == Decimal("100")
    assert by_label[("Low cracked",)] == Decimal("75")


def test_health_range_plus_inline_marker() -> None:
    """`{{hp|20}} <br> {{hp|40}} to {{hp|100}} (leaders){{only|JE|short=1}}` -- Zombie."""
    entity, _, _ = parse(
        health="{{hp|20}} <br> {{hp|40}} to {{hp|100}} (leaders){{only|JE|short=1}}"
    )
    plain = next(value for value in entity.health if value.labels == ())
    assert plain.value == plain.value.__class__(minimum=Decimal("20"), maximum=Decimal("20"))
    leaders = next(value for value in entity.health if "leaders" in value.labels)
    assert leaders.value.minimum == Decimal("40")
    assert leaders.value.maximum == Decimal("100")


def test_health_edition_regions_cat() -> None:
    """`'''{{JE}}:'''<br>{{hp|10}}<hr>'''{{BE}}:'''<br>Wild: {{hp|10}}` -- Cat.

    Only the Java figure survives; the whole Bedrock region is dropped.
    """
    entity, _, filtered = parse(
        health="'''{{JE}}:'''<br>{{hp|10}}<hr>'''{{BE}}:'''<br>Wild: {{hp|10}}"
    )
    assert len(entity.health) == 1
    assert entity.health[0].value.minimum == Decimal("10")
    assert any(entry.field == "health" for entry in filtered)


def test_health_value_with_a_long_prose_qualifier_keeps_the_value() -> None:
    """`{{hp|1}} (immune to damage when spawned using a [[creaking heart]])` -- Creaking.

    The qualifier is too long to read as a label (`_trailing_label` refuses
    anything over 19 characters), so it is dropped and the value is kept.
    """
    entity, _, _ = parse(
        health="{{hp|1}} (immune to damage when spawned using a [[creaking heart]])"
    )
    assert len(entity.health) == 1
    assert entity.health[0].value.minimum == Decimal("1")
    assert entity.health[0].labels == ()


# --- damage ---------------------------------------------------------------------


def test_damage_difficulty_tiers() -> None:
    entity, _, _ = parse(
        damage="Easy: {{hp|2.5}}<br />Normal: {{hp|3}}<br>Hard: {{hp|4.5}}"
    )
    by_difficulty = {value.difficulties: value.value.minimum for value in entity.damage}
    assert by_difficulty[(Difficulty.EASY,)] == Decimal("2.5")
    assert by_difficulty[(Difficulty.NORMAL,)] == Decimal("3")
    assert by_difficulty[(Difficulty.HARD,)] == Decimal("4.5")


def test_damage_combined_tiers() -> None:
    entity, _, _ = parse(damage="Easy and Normal: {{hp|2}}<br>Hard: {{hp|3}}")
    combined = next(value for value in entity.damage if len(value.difficulties) == 2)
    assert combined.difficulties == (Difficulty.EASY, Difficulty.NORMAL)
    assert combined.value.minimum == Decimal("2")


def test_damage_en_dash_range() -> None:
    """`Easy: {{hp|4.75}} – {{hp|11.75}}` -- Iron Golem."""
    entity, _, _ = parse(damage="Easy: {{hp|4.75}} – {{hp|11.75}}")
    assert entity.damage[0].value.minimum == Decimal("4.75")
    assert entity.damage[0].value.maximum == Decimal("11.75")


def test_damage_hyphen_range() -> None:
    """`Easy: {{hp|2}} - {{hp|4}}` -- Stray."""
    entity, _, _ = parse(damage="Easy: {{hp|2}} - {{hp|4}}")
    assert entity.damage[0].value.minimum == Decimal("2")
    assert entity.damage[0].value.maximum == Decimal("4")


def test_damage_word_to_range() -> None:
    """`Easy and Normal: {{hp|2}} to {{hp|5}}` -- Piglin."""
    entity, _, _ = parse(damage="Easy and Normal: {{hp|2}} to {{hp|5}}")
    assert entity.damage[0].value.minimum == Decimal("2")
    assert entity.damage[0].value.maximum == Decimal("5")


def test_damage_attack_modes_separated_by_hr() -> None:
    """`'''Melee:''' ... <hr> '''Roar:''' ...` -- Ravager."""
    entity, _, _ = parse(
        damage="'''Melee:'''<br>Easy: {{hp|5}}<hr>'''Roar:'''<br>Easy: {{hp|10}}"
    )
    by_label = {value.labels: value.value.minimum for value in entity.damage}
    assert by_label[("Melee",)] == Decimal("5")
    assert by_label[("Roar",)] == Decimal("10")


def test_damage_scalar_plus_prose() -> None:
    """`{{hp|3}} against rabbits and baby turtles only` -- Cat."""
    entity, _, _ = parse(damage="{{hp|3}} against rabbits and baby turtles only")
    assert entity.damage[0].value.minimum == Decimal("3")
    assert entity.damage[0].difficulties == ()


def test_damage_no_number_is_unparsed() -> None:
    """`Instant kill, ignores health (Used only on small slimes...)` -- Frog. No `{{hp}}` at all."""
    entity, unparsed, _ = parse(
        damage="Instant kill, ignores health (Used only on small slimes and magma cubes)"
    )
    assert entity.damage == ()
    assert len(unparsed) == 1
    assert unparsed[0].field == "damage"
    assert "Instant kill" in unparsed[0].text


def test_damage_needs_testing_placeholder_is_not_a_value() -> None:
    """`'''{{IN|Bedrock}}:''' {{Needs testing}}` -- Skeleton, Stray, Bogged, Piglin.

    The placeholder is folded into the heading itself (see
    `pipeline.enrich.markup._heading_core`), so it never becomes a content row
    at all -- it produces no value and no `FilteredLine`. The field still
    needs a real Java value elsewhere to avoid going unparsed, and that value
    must be exactly what the Java region held, nothing from the placeholder.
    """
    entity, unparsed, _ = parse(
        damage=(
            "'''{{IN|Java}}:'''<br>Easy: {{hp|2}}<br>"
            "'''{{IN|Bedrock}}:''' {{Needs testing}}"
        )
    )
    assert [value.value.minimum for value in entity.damage] == [Decimal("2")]
    assert not any(u.field == "damage" for u in unparsed)


def test_damage_extra_named_arguments_do_not_affect_the_value() -> None:
    """`{{hp|5|withered=1}}, {{hp|7|poisoned=1}}, {{hp|4|notag=1}}`."""
    entity, _, _ = parse(
        damage="Easy: {{hp|5|withered=1}}<br>Normal: {{hp|7|poisoned=1}}<br>Hard: {{hp|4|notag=1}}"
    )
    values = {value.difficulties: value.value.minimum for value in entity.damage}
    assert values[(Difficulty.EASY,)] == Decimal("5")
    assert values[(Difficulty.NORMAL,)] == Decimal("7")
    assert values[(Difficulty.HARD,)] == Decimal("4")


def test_damage_hoglin_lone_difficulty_label_pairs_with_the_next_line() -> None:
    """Hoglin's split shape: `Easy:` alone, then the value on the next line."""
    entity, _, _ = parse(
        damage="'''Adult in {{JE}}:'''<br>Easy:<br> {{hp|2.5}} to {{hp|5}}"
    )
    assert entity.damage[0].difficulties == (Difficulty.EASY,)
    assert entity.damage[0].value.minimum == Decimal("2.5")
    assert entity.damage[0].value.maximum == Decimal("5")


def test_damage_bedrock_region_does_not_leak_through_a_subordinate_heading() -> None:
    """The Creeper shape in miniature: a standalone region survives a nested variant heading."""
    entity, _, filtered = parse(
        damage=(
            "'''{{IN|JE}}:'''<br>'''Regular:'''<br>Easy: {{hp|22.5}}<hr>"
            "'''{{IN|BE}}:'''<br>'''Regular:'''<br>Easy: {{hp|14.75}}"
        )
    )
    values = [value.value.minimum for value in entity.damage]
    assert Decimal("22.5") in values
    assert Decimal("14.75") not in values
    assert any(entry.line == "Easy: {{hp|14.75}}" for entry in filtered)


# --- size -------------------------------------------------------------------


def test_size_plain() -> None:
    entity, _, _ = parse(size="Height: 0.9 blocks<br>Width: 1.4 blocks")
    assert entity.size[0].height == Decimal("0.9")
    assert entity.size[0].width == Decimal("1.4")


def test_size_capitalised_blocks() -> None:
    """`Height: 1.8 Blocks<br>Width: 0.6 Blocks` -- Blaze, Ravager, Stray."""
    entity, _, _ = parse(size="Height: 1.8 Blocks<br>Width: 0.6 Blocks")
    assert entity.size[0].height == Decimal("1.8")


def test_size_singular_block() -> None:
    """`Height: 1 block<br>Width: 1 block` -- Shulker."""
    entity, _, _ = parse(size="Height: 1 block<br>Width: 1 block")
    assert entity.size[0].height == Decimal("1")
    assert entity.size[0].width == Decimal("1")


def test_size_bolded_labels() -> None:
    """`'''Height:''' 0.5 Blocks <br> '''Width:''' 0.9 Blocks` -- Phantom."""
    entity, _, _ = parse(size="'''Height:''' 0.5 Blocks <br> '''Width:''' 0.9 Blocks")
    assert entity.size[0].height == Decimal("0.5")
    assert entity.size[0].width == Decimal("0.9")


def test_size_height_and_width_combined() -> None:
    """`Height and width: 4.0 blocks` -- Happy Ghast."""
    entity, _, _ = parse(size="Height and width: 4.0 blocks")
    assert entity.size[0].height == Decimal("4.0")
    assert entity.size[0].width == Decimal("4.0")


def test_size_labelled_variants() -> None:
    entity, _, _ = parse(
        size="'''Adult:'''<br>Height: 1.4 blocks<br>Width: 0.9 blocks<br>"
        "'''Baby:'''<br>Height: 0.7 blocks<br>Width: 0.45 blocks"
    )
    by_label = {value.labels: (value.height, value.width) for value in entity.size}
    assert by_label[("Adult",)] == (Decimal("1.4"), Decimal("0.9"))
    assert by_label[("Baby",)] == (Decimal("0.7"), Decimal("0.45"))


def test_size_variant_labels_closed_peeking_open() -> None:
    """Shulker's three variant labels."""
    entity, _, _ = parse(
        size=(
            "'''Closed:'''<br>Height: 1 block<br>Width: 1 block<br>"
            "'''Peeking:'''<br>Height: 1.2 blocks<br>Width: 1 block<br>"
            "'''Open:'''<br>Height: 2 blocks<br>Width: 1 block"
        )
    )
    labels = {value.labels for value in entity.size}
    assert labels == {("Closed",), ("Peeking",), ("Open",)}


# --- usableitems --------------------------------------------------------------


def test_usable_items_canonical() -> None:
    entity, _, _ = parse(usableitems="{{drop|Item|Flint and Steel}}")
    assert entity.usable_items[0].name == "Flint and Steel"
    assert entity.usable_items[0].kind == "Item"


def test_usable_items_lowercase_kind() -> None:
    entity, _, _ = parse(usableitems="{{drop|item|Name Tag}}")
    assert entity.usable_items[0].kind == "item"


def test_usable_items_capitalised_template_name() -> None:
    """`{{Drop|Item|Lead}}` -- Zoglin, Allay, Copper Golem."""
    entity, _, _ = parse(usableitems="{{Drop|Item|Lead}}")
    assert entity.usable_items[0].name == "Lead"


def test_usable_items_block_kind() -> None:
    entity, _, _ = parse(usableitems="{{drop|block|Golden Dandelion}}")
    assert entity.usable_items[0].kind == "block"


def test_usable_items_id_override_with_display_text_after() -> None:
    """`{{drop|Item|id=Raw Beef|Meat}}` -- Wolf. The display text wins over the id."""
    entity, _, _ = parse(usableitems="{{drop|Item|id=Raw Beef|Meat}}")
    assert entity.usable_items[0].name == "Meat"


def test_usable_items_env_kind_with_text_argument() -> None:
    """`{{Drop|Env|Item|text=Any item}}` -- Allay."""
    entity, _, _ = parse(usableitems="{{Drop|Env|Item|text=Any item}}")
    assert entity.usable_items[0].name == "Any item"
    assert entity.usable_items[0].kind == "Env"


def test_usable_items_a_different_template_mixed_in_is_ignored() -> None:
    """`{{ItemLink|Raw Salmon}}` -- Ocelot. Not a `{{drop}}` call, so it produces no item."""
    entity, _, _ = parse(usableitems="{{drop|Item|Raw Cod}}<br>{{ItemLink|Raw Salmon}}")
    assert [item.name for item in entity.usable_items] == ["Raw Cod"]


def test_usable_items_trailing_note() -> None:
    """`{{drop|Item|Shears}}<small>(when equipped with a saddle)</small>`."""
    entity, _, _ = parse(
        usableitems="{{drop|Item|Shears}}<small>(when equipped with a saddle)</small>"
    )
    assert entity.usable_items[0].note == "when equipped with a saddle"


def test_usable_items_bedrock_only_is_dropped_and_must_be_dropped() -> None:
    """`{{drop|item|Bone Meal}}{{only|be|ee|short=1}}` -- Sheep's four Bedrock-only dyes."""
    entity, _, filtered = parse(
        usableitems=(
            "{{drop|Item|Wheat}}\n"
            "{{drop|item|Bone Meal}}{{only|be|ee|short=1}}"
        )
    )
    names = [item.name for item in entity.usable_items]
    assert "Bone Meal" not in names
    assert "Wheat" in names
    assert any(entry.field == "usableitems" for entry in filtered)


def test_usable_items_list_marker_separated() -> None:
    """`* {{Drop|Item|Axe}}` -- Copper Golem."""
    entity, _, _ = parse(usableitems="* {{Drop|Item|Axe}}\n* {{Drop|Item|Lead}}")
    assert [item.name for item in entity.usable_items] == ["Axe", "Lead"]


# --- armor --------------------------------------------------------------------


def test_armor_plain() -> None:
    entity, _, _ = parse(armor="{{armor|2}}")
    assert entity.armor[0].value.minimum == Decimal("2")


def test_armor_labelled_variants() -> None:
    entity, _, _ = parse(
        armor="'''Large:''' {{armor|12}}<br>'''Medium:''' {{armor|6}}<br>'''Small:''' {{armor|3}}"
    )
    by_label = {value.labels: value.value.minimum for value in entity.armor}
    assert by_label[("Large",)] == Decimal("12")
    assert by_label[("Small",)] == Decimal("3")


def test_armor_closed_opened() -> None:
    """`Closed: {{armor|20}} <br> Opened: {{armor|0}}` -- Shulker. Zero is a real value."""
    entity, _, _ = parse(armor="Closed: {{armor|20}} <br> Opened: {{armor|0}}")
    by_label = {value.labels: value.value.minimum for value in entity.armor}
    assert by_label[("Closed",)] == Decimal("20")
    assert by_label[("Opened",)] == Decimal("0")


# --- behavior -----------------------------------------------------------------


def test_behavior_hostile() -> None:
    entity, _, _ = parse(behavior="Hostile")
    assert entity.behavior[0].text == "Hostile"


def test_behavior_two_conditions_by_br() -> None:
    entity, _, _ = parse(
        behavior="Neutral (naturally spawned)<br>Passive (player-built)"
    )
    assert [value.text for value in entity.behavior] == [
        "Neutral (naturally spawned)",
        "Passive (player-built)",
    ]


def test_behavior_html_comment_is_stripped() -> None:
    entity, _, _ = parse(behavior="Passive <!-- Only include behavior with players -->")
    assert entity.behavior[0].text == "Passive"


def test_behavior_ref_tag_is_stripped() -> None:
    entity, _, _ = parse(
        behavior='Passive<ref group="note" name="passive">Can unintentionally hurt.</ref>'
    )
    assert entity.behavior[0].text == "Passive"


# --- mobtype --------------------------------------------------------------------


def test_mob_type_single() -> None:
    entity, _, _ = parse(mobtype="{{EntityLink|Monster}}")
    assert entity.mob_type == ("Monster",)


def test_mob_type_two_by_br() -> None:
    entity, _, _ = parse(mobtype="{{EntityLink|Undead}}<br>{{EntityLink|Monster}}")
    assert entity.mob_type == ("Undead", "Monster")


def test_mob_type_two_by_comma() -> None:
    """`{{EntityLink|Golem}}, {{EntityLink|Monster}}` -- Shulker."""
    entity, _, _ = parse(mobtype="{{EntityLink|Golem}}, {{EntityLink|Monster}}")
    assert entity.mob_type == ("Golem", "Monster")


# --- speed --------------------------------------------------------------------


def test_speed_plain() -> None:
    entity, _, _ = parse(speed="0.23")
    assert entity.speed[0].text == "0.23"
    assert entity.speed[0].labels == ()


def test_speed_labelled_baby() -> None:
    entity, _, _ = parse(speed="0.23<br>0.35 (baby)")
    labelled = next(value for value in entity.speed if value.labels)
    assert labelled.labels == ("baby",)
    assert labelled.text == "0.35"


def test_speed_html_comment_is_stripped() -> None:
    entity, _, _ = parse(speed="0.3<!--Walking: 0.24<br>Sprinting: 0.399-->")
    assert entity.speed[0].text == "0.3"


def test_speed_prose_is_unparsed() -> None:
    """`0.25 when idle and 0.3125 when attacking` -- Wither Skeleton.

    Two numbers, no clean label to hang either one on.
    """
    entity, unparsed, _ = parse(speed="0.25 when idle and 0.3125 when attacking")
    assert entity.speed == ()
    assert any(u.field == "speed" for u in unparsed)


# --- knockbackresistance -------------------------------------------------------


def test_knockback_resistance_percent() -> None:
    entity, _, _ = parse(knockbackresistance="100%")
    assert entity.knockback_resistance[0].text == "100%"


def test_knockback_resistance_en_dash_range() -> None:
    entity, _, _ = parse(knockbackresistance="0%–5%")
    assert entity.knockback_resistance[0].text == "0%–5%"


def test_knockback_resistance_edition_marked_drops_bedrock_keeps_java() -> None:
    """`70%{{only|java|short=1}}<br>75%{{only|bedrock|short=1}}`."""
    entity, _, filtered = parse(
        knockbackresistance="70%{{only|java|short=1}}<br>75%{{only|bedrock|short=1}}"
    )
    assert [value.text for value in entity.knockback_resistance] == ["70%"]
    assert any(entry.field == "knockbackresistance" for entry in filtered)


# --- select_infobox_pages ------------------------------------------------------


def test_select_infobox_pages_keeps_a_page_with_the_template() -> None:
    pages = {"Creeper": infobox(health="{{hp|20}}")}
    with_template, without_template = select_infobox_pages(pages)
    assert with_template == pages
    assert without_template == ()


def test_select_infobox_pages_reports_a_page_with_no_template() -> None:
    """Armor Stand is the measured live case: a mcmeta mob with no wiki infobox."""
    pages = {"Armor Stand": "Armor Stand is a decorative item, not documented with an infobox."}
    with_template, without_template = select_infobox_pages(pages)
    assert with_template == {}
    assert without_template == ("Armor Stand",)


def test_select_infobox_pages_splits_a_mix_and_sorts_the_misses() -> None:
    pages = {
        "Zombie": infobox(health="{{hp|20}}"),
        "Player": "No infobox entity template on this page.",
        "Creeper": infobox(health="{{hp|20}}"),
        "Armor Stand": "No infobox entity template on this page either.",
    }
    with_template, without_template = select_infobox_pages(pages)
    assert set(with_template) == {"Zombie", "Creeper"}
    assert with_template["Zombie"] == pages["Zombie"]
    assert with_template["Creeper"] == pages["Creeper"]
    # Sorted, not insertion order -- `pages` names Player before Armor Stand.
    assert without_template == ("Armor Stand", "Player")


def test_select_infobox_pages_of_an_empty_mapping_is_empty() -> None:
    with_template, without_template = select_infobox_pages({})
    assert with_template == {}
    assert without_template == ()
