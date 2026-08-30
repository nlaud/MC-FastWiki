"""The infobox parser against wikitext the wiki actually sent.

Every other test of this stage builds its infobox text in memory, one trap
per test. That proves the parsers do what their authors intended and proves
nothing about whether the intention matches a real page. This module reads
`tests/fixtures/wiki_infobox_pages.json`, which
`tests/fixtures/build_infobox_snapshot.py` captured from the live wiki, and
checks facts a person can verify against the game and against the wiki page.

It opens no socket. The pages are on disk.

**A failure here is a question, not a verdict.** The wiki has no version to
pin to -- it is edited continuously -- so an assertion that goes red means
either the parser changed or the wiki did, and the two are told apart by
reading the page named in the failing test. When it is the wiki, rebuild the
fixture, read the diff, and update the assertion. When it is the parser, the
fixture is doing its job.
"""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from pipeline.enrich.infobox import EntityInfobox, parse_infobox

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "wiki_infobox_pages.json"


@pytest.fixture(scope="module")
def snapshot() -> dict[str, Any]:
    """Return the whole snapshot document."""
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


@pytest.fixture(scope="module")
def entities(snapshot: dict[str, Any]) -> dict[str, EntityInfobox]:
    """Return every page of the snapshot, parsed once and shared across tests."""
    result: dict[str, EntityInfobox] = {}
    for title, page_text in snapshot["pages"].items():
        entity, _, _ = parse_infobox(title, page_text)
        result[title] = entity
    return result


def test_the_snapshot_records_where_and_when_it_came_from(snapshot: dict[str, Any]) -> None:
    """There is no Minecraft version to pin here, so the date tells a reader how old a
    disagreement with the live wiki might be.
    """
    assert snapshot["captured"]
    assert "CC BY-NC-SA" in snapshot["note"]
    assert snapshot["misses"] == []


def test_every_chosen_title_is_in_the_snapshot(snapshot: dict[str, Any]) -> None:
    assert set(snapshot["titles"]) == set(snapshot["pages"])


# --- The correctness-critical assertion: Creeper's height and damage --------


def test_creeper_is_java_height_not_bedrock_height(entities: dict[str, EntityInfobox]) -> None:
    """Creeper is 1.7 blocks tall in Java and 1.8 in Bedrock.

    1.8 reaching this model is exactly the correctness bug non-negotiable 1
    exists to prevent.
    """
    creeper = entities["Creeper"]
    assert creeper.size[0].height == Decimal("1.7")
    assert Decimal("1.8") not in {value.height for value in creeper.size}


def test_creepers_bedrock_explosion_damage_does_not_leak_through_regular(
    entities: dict[str, EntityInfobox],
) -> None:
    """The Bedrock region must not leak through its subordinate `'''Regular:'''` heading.

    This is the pair Decision 1 turns on, together with the Zombie test below:
    a region must survive a subordinate variant heading, and a block must not.
    """
    creeper = entities["Creeper"]
    values = {value.value.minimum for value in creeper.damage}
    values |= {value.value.maximum for value in creeper.damage}
    assert Decimal("14.75") not in values
    assert Decimal("22.5") in values


# --- The correctness-critical assertion: Zombie's unmarked Baby heading -----


def test_zombie_baby_height_is_kept_by_the_unmarked_heading_reset(
    entities: dict[str, EntityInfobox],
) -> None:
    """The unmarked `'''Baby:'''` heading must still clear an embedded marker.

    Zombie's `size` opens `'''Adult {{IN|Bedrock}}:'''`, an embedded block,
    right before `'''Baby:'''`. If the block were read as a region -- the
    mistake Decision 1 was refined to avoid -- `Baby` would inherit Bedrock
    and this value would either be dropped or wrong.
    """
    zombie = entities["Zombie"]
    baby = next(value for value in zombie.size if "Baby" in value.labels)
    assert baby.height == Decimal("0.98")
    assert baby.width == Decimal("0.49")


def test_zombies_adult_bedrock_height_is_never_kept(entities: dict[str, EntityInfobox]) -> None:
    zombie = entities["Zombie"]
    assert Decimal("1.9") not in {value.height for value in zombie.size}


# --- The correctness-critical assertion: Sheep's Bedrock-only dyes ---------


def test_sheeps_bedrock_only_dyes_do_not_appear(entities: dict[str, EntityInfobox]) -> None:
    """Sheep's four `{{only|be|ee}}` dyes must not appear."""
    sheep = entities["Sheep"]
    names = {item.name for item in sheep.usable_items}
    assert "Bone Meal" not in names
    assert "Ink Sac" not in names
    assert "Lapis Lazuli" not in names
    assert "Cocoa Beans" not in names
    assert "Wheat" in names


# --- The region list: 12 page-fields that must not leak Bedrock -------------


def test_cows_bedrock_size_does_not_leak_through_the_region(
    entities: dict[str, EntityInfobox],
) -> None:
    """`'''In {{JE}}:'''` reduces to a region once the connecting word `in` is dropped."""
    cow = entities["Cow"]
    assert Decimal("1.3") not in {value.height for value in cow.size}
    assert Decimal("1.4") in {value.height for value in cow.size}


def test_magma_cubes_bedrock_size_does_not_leak(entities: dict[str, EntityInfobox]) -> None:
    magma_cube = entities["Magma Cube"]
    widths = {value.width for value in magma_cube.size}
    # 2.0808 is Java's large width; 2.08 flat is Bedrock's.
    assert Decimal("2.0808") in widths


def test_skeletons_bedrock_damage_placeholder_never_becomes_a_value(
    entities: dict[str, EntityInfobox],
) -> None:
    """`'''{{IN|Bedrock}}:''' {{Needs testing}}` must contribute no number, Bedrock or otherwise."""
    skeleton = entities["Skeleton"]
    assert skeleton.damage
    assert all(value.value.minimum >= 0 for value in skeleton.damage)


def test_boggeds_plain_text_bedrock_heading_is_filtered_with_no_template_at_all(
    entities: dict[str, EntityInfobox], snapshot: dict[str, Any]
) -> None:
    """The Bogged page: `'''Bedrock:'''` carries no template, the one marker form that is not
    one.
    """
    assert "'''Bedrock:'''" in snapshot["pages"]["Bogged"]
    bogged = entities["Bogged"]
    assert bogged.size[0].height == Decimal("1.99")
    assert Decimal("1.9") not in {value.height for value in bogged.size}


# --- The block list: unmarked variant headings must clear an embedded marker


def test_chickens_baby_height_survives_the_connecting_word_block_form(
    entities: dict[str, EntityInfobox],
) -> None:
    """`'''Adult in {{JE}}:'''` is a block, and the unmarked `Baby` heading must clear it."""
    chicken = entities["Chicken"]
    baby = next(value for value in chicken.size if "Baby" in value.labels)
    assert baby.height == Decimal("0.4")


def test_goats_while_jumping_block_does_not_swallow_the_next_adult_heading(
    entities: dict[str, EntityInfobox],
) -> None:
    """`'''While jumping:'''{{only|java|short=1}}` -- a glued marker -- must still let the
    following `'''Adult:'''` reset cleanly to its own height, not the jumping one.
    """
    goat = entities["Goat"]
    heights = {value.height for value in goat.size if "Adult" in value.labels}
    assert Decimal("1.3") in heights
    assert Decimal("0.91") in heights


def test_wardens_embedded_marker_before_the_colon_is_still_a_block(
    entities: dict[str, EntityInfobox],
) -> None:
    """`'''While digging/emerging{{only|JE|short=1}}:'''` -- the marker sits before the colon."""
    warden = entities["Warden"]
    digging = next(v for v in warden.size if "While digging/emerging" in v.labels)
    assert digging.height == Decimal("1")


# --- The long tail: shapes section 3 of the brief records -------------------


def test_iron_golems_damage_is_an_en_dash_range(entities: dict[str, EntityInfobox]) -> None:
    iron_golem = entities["Iron Golem"]
    easy = next(value for value in iron_golem.damage if value.value.minimum == Decimal("4.75"))
    assert easy.value.maximum == Decimal("11.75")


def test_wolfs_same_line_bold_labels_are_read(entities: dict[str, EntityInfobox]) -> None:
    """`'''Wild:''' {{hp|8}}<br>'''Tamed:''' {{hp|40}}` -- labels and values on one line."""
    wolf = entities["Wolf"]
    by_label = {value.labels: value.value.minimum for value in wolf.health}
    assert by_label[("Wild",)] == Decimal("8")
    assert by_label[("Tamed",)] == Decimal("40")


def test_ocelots_mixed_itemlink_template_produces_no_usable_item(
    entities: dict[str, EntityInfobox],
) -> None:
    """`{{ItemLink|Raw Salmon}}` sits beside `{{drop|...}}` calls and must not become one."""
    ocelot = entities["Ocelot"]
    names = [item.name for item in ocelot.usable_items]
    assert "Raw Salmon" not in names
    assert "Raw Cod" in names


def test_frogs_damage_has_no_number_and_is_reported_unparsed(
    entities: dict[str, EntityInfobox], snapshot: dict[str, Any]
) -> None:
    """Instant kill, ignores health -- no `{{hp}}` template at all."""
    frog = entities["Frog"]
    assert frog.damage == ()
    _, unparsed, _ = parse_infobox("Frog", snapshot["pages"]["Frog"])
    assert any(entry.field == "damage" for entry in unparsed)


def test_happy_ghasts_combined_height_and_width_is_read(
    entities: dict[str, EntityInfobox],
) -> None:
    """`Height and width: 4.0 blocks` -- one value stands for both dimensions."""
    happy_ghast = entities["Happy Ghast"]
    ghast = next(value for value in happy_ghast.size if "Happy Ghast" in value.labels)
    assert ghast.height == ghast.width == Decimal("4.0")


def test_shulkers_second_infobox_on_the_page_is_not_read(
    entities: dict[str, EntityInfobox], snapshot: dict[str, Any]
) -> None:
    """Shulker's own page documents `Shulker Bullet` as a second `{{Infobox entity}}`.

    `parse_infobox` reads the first -- Shulker's own -- and leaves the second.
    """
    assert snapshot["pages"]["Shulker"].count("{{Infobox entity") == 2
    shulker = entities["Shulker"]
    labels = {value.labels for value in shulker.size}
    assert labels == {("Closed",), ("Peeking",), ("Open",)}


def test_cats_two_edition_regions_split_by_hr_with_no_br_beside_it(
    entities: dict[str, EntityInfobox], snapshot: dict[str, Any]
) -> None:
    """`'''{{JE}}:'''<br>{{hp|10}}<hr>'''{{BE}}:'''<br>...` -- `<hr>` glued directly on."""
    assert "<hr>" in snapshot["pages"]["Cat"]
    cat = entities["Cat"]
    assert cat.health
    assert cat.health[0].value.minimum == Decimal("10")
