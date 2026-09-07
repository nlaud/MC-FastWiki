"""Tests for `pipeline.enrich.effect`.

Exercises status effect parsing: Infobox category, behaviour prose extraction,
causes table parsing with rowspans, column variants, Bedrock scoping, prose-only
causes, and verification cross-checking against Tier A data.
"""

import pytest

from pipeline.enrich import EnrichError
from pipeline.enrich.effect import (
    EFFECT_PAGE_TITLES,
    EffectIndex,
    EffectPageFacts,
    RawEffectSource,
    _drop_other_edition_sentences,
    _extract_behaviour,
    _link_display_text,
    _parse_infobox_category,
    fetch_effects,
    parse_effect_page,
    verify_effect_sources,
)
from pipeline.extract.food import AppliedEffect, ConsumeEffect, ConsumeEffectKind, FoodFacts
from pipeline.fetch.cache import ContentCache

_SAMPLE_SPEED_PAGE = """
{{Infobox effect
| title = Speed
| type = Positive
| id = speed
}}
Speed is a beneficial status effect that increases movement speed.

== Effects ==
Increases walking speed by 20% x level and expands FOV.

== Causes ==
{| class="wikitable"
! Cause
! Potency
! Length
! Notes
|-
| {{ItemLink|Potion of Swiftness}}
| I
| 3:00
| Brewed with Sugar.
|-
| {{ItemLink|Potion of Swiftness}} (extended)
| I
| 8:00
| Brewed with Redstone Dust.
|-
| {{BlockLink|Beacon}} set to Speed
| I or II
| 0:11 – 0:16
| Primary power.
|-
| {{IN|Bedrock}} {{ItemLink|Bedrock Exclusive}}
| I
| 1:00
| Bedrock only cause.
|}
"""

_SAMPLE_INSTANT_HEALTH_PAGE = """
{{Infobox effect
| title = Instant Health
| type = Positive
| id = instant_health
}}
Instant Health restores health immediately.

== Effect ==
Restores {{hp|4}} per level. Harms undead.

== Causes ==
{| class="wikitable"
! Cause
! Potency
! Length
! Heals
! Damage
! Notes
|-
| {{ItemLink|Potion of Healing}}
| I
| Instant
| {{hp|4}}
| {{hp|6}}
| rowspan="2" | Restores instantly.
|-
| {{ItemLink|Splash Potion of Healing}}
| I
| Instant
| {{hp|4}}
| {{hp|6}}
|}
"""

_SAMPLE_HERO_PAGE = """
{{Infobox effect
| title = Hero of the Village
| type = Positive
| id = hero_of_the_village
}}
Hero of the Village grants discounts on villager trades.

== Effect ==
Grants discounts on trades with villagers and gifts from villagers.

== Causes ==
{| class="wikitable"
! Cause
! Potency
! Length
! Notes
|-
| rowspan="2" | Defeating a raid
| {{IN|Bedrock}} I
| Permanent
| Bedrock raid win.
|-
| {{IN|Java}} I
| 40:00
| Java raid win.
|}
"""

_SAMPLE_WATER_BREATHING_PAGE = """
{{Infobox effect
| title = Water Breathing
| type = Positive
| id = water_breathing
}}
Water Breathing is a status effect that prevents drowning.
In Bedrock Edition it also increases visibility underwater.

== Causes ==
{| class="wikitable"
! Cause
! Potency
! Length
! Notes
|-
| {{ItemLink|Potion of Water Breathing}}
| I
| 3:00
| Brewed with Pufferfish.
|}
"""

_SAMPLE_HEALTH_BOOST_PAGE = """
{{Infobox effect
| title = Health Boost
| type = Positive
| id = health_boost
}}
Health Boost adds extra hearts to the health bar.

== Effect ==
Adds 4 extra health points per level.

== Cause ==
Health Boost is obtained only by executing the /effect command.
"""

_SAMPLE_BAD_LUCK_PAGE = """
{{Infobox effect
| title = Bad Luck
| type = Negative
| id = bad_luck
}}
Bad Luck decreases the chances of high-quality loot.

== Effect ==
Decreases luck attribute by 1 per level.

== Causes ==
Bad Luck cannot be obtained in normal gameplay. It can be obtained using /effect or /give.
"""


def test_parse_infobox_category() -> None:
    assert _parse_infobox_category("{{Infobox effect|type=Positive}}", title="Test") == "positive"
    assert _parse_infobox_category("{{Infobox effect|type=Negative}}", title="Test") == "negative"
    assert _parse_infobox_category("{{Infobox effect|type=Neutral}}", title="Test") == "neutral"

    with pytest.raises(EnrichError, match="unrecognized effect type"):
        _parse_infobox_category("{{Infobox effect|type=Unknown}}", title="Test")

    with pytest.raises(EnrichError, match=r"no '\{\{Infobox effect\}\}' found"):
        _parse_infobox_category("plain text without infobox", title="Test")


def test_extract_behaviour() -> None:
    page = """
== Effects ==
Increases walking speed by 20% x level and restores {{hp|4}} health.
{{only|bedrock}} Bedrock detail.

== Causes ==
Table here
"""
    behaviour = _extract_behaviour(page, title="Speed")
    assert behaviour is not None
    assert "Increases walking speed" in behaviour
    assert "4 health" in behaviour
    assert "Bedrock detail" not in behaviour


def test_extract_behaviour_water_breathing_lead() -> None:
    page = """
{{Infobox effect
| title = Water Breathing
}}
Water Breathing is a status effect that prevents drowning.

== Causes ==
Table
"""
    behaviour = _extract_behaviour(page, title="Water Breathing")
    assert behaviour == "Water Breathing is a status effect that prevents drowning."


def test_parse_speed_page() -> None:
    facts = parse_effect_page("Speed", _SAMPLE_SPEED_PAGE)
    assert facts.title == "Speed"
    assert facts.category == "positive"
    assert facts.behaviour is not None
    assert "Increases walking speed" in facts.behaviour
    # 3 Java causes, Bedrock exclusive dropped
    assert len(facts.sources) == 3
    assert facts.sources[0].name == "Potion of Swiftness"
    assert facts.sources[0].potency == "I"
    assert facts.sources[0].length == "3:00"
    assert facts.sources[0].qualifier is None

    assert facts.sources[1].name == "Potion of Swiftness"
    assert facts.sources[1].qualifier == "(extended)"

    assert facts.sources[2].name == "Beacon"
    assert facts.sources[2].qualifier == "set to Speed"
    assert facts.sources[2].potency == "I or II"


def test_behaviour_drops_an_unmarked_bedrock_sentence() -> None:
    """Prose that names Bedrock in words carries no `{{only}}` marker to scope.

    Two effects of the 26.2 build shipped Bedrock mechanics into this Java-only
    reference this way. The Haste one also read as a broken sentence, because
    the `<math>` formula it depended on is stripped: "In Bedrock Edition, Haste
    sets the mining speed to where is the level."
    """
    paragraph = (
        "In Java Edition, Haste increases mining speed by 20% per level. "
        "In Bedrock Edition, Haste sets the mining speed to where is the level."
    )
    kept = _drop_other_edition_sentences(paragraph)
    assert kept == "In Java Edition, Haste increases mining speed by 20% per level."


def test_behaviour_keeps_a_version_number_sentence_intact() -> None:
    """A decimal must not read as a sentence boundary and split a sentence in half."""
    paragraph = "Nausea warps vision. And in Bedrock Edition 26.40, it is affected by an option."
    assert _drop_other_edition_sentences(paragraph) == "Nausea warps vision."


def test_behaviour_leaves_java_only_prose_untouched() -> None:
    """The filter must not fire on prose that never mentions the other edition."""
    paragraph = "Speed increases movement speed by 20% per level. It also widens the FOV."
    assert _drop_other_edition_sentences(paragraph) == paragraph


def test_link_display_text_reads_a_named_display_argument() -> None:
    """`{{EntityLink|Witch|text=Witches}}` reads as "Witches", not "text=Witches".

    The wiki spells a display-text override two ways, and only the positional
    one was handled. The named one leaked its `text=` key into three notes of
    the 26.2 build, one of them mid-sentence: "Only applies to text=spiders on
    Hard difficulty."
    """
    assert _link_display_text("Witch", "text=Witches") == "Witches"
    assert _link_display_text("Spider", "name=spiders") == "spiders"


def test_link_display_text_falls_back_to_the_title() -> None:
    """A named argument that is not display text leaves the title on screen."""
    assert _link_display_text("Witch", None) == "Witch"
    assert _link_display_text("Witch", "Witches") == "Witches"
    assert _link_display_text("Spider", "link=Cave Spider") == "Spider"


def test_a_note_keeps_no_template_argument_key() -> None:
    """The whole point, checked through the parser rather than the helper."""
    page = _SAMPLE_SPEED_PAGE.replace(
        "| Brewed with Sugar.",
        "| {{EntityLink|Witch|text=Witches}} drink this when far away.",
    )
    assert "text=Witches" in page, "the fixture substitution must actually apply"
    facts = parse_effect_page("Speed", page)
    notes = [source.note for source in facts.sources if source.note]
    assert notes, "the sample page must carry at least one note for this to test anything"
    assert not any("text=" in note for note in notes)


def test_parse_instant_health_page_with_extra_columns() -> None:
    facts = parse_effect_page("Instant Health", _SAMPLE_INSTANT_HEALTH_PAGE)
    assert facts.category == "positive"
    assert len(facts.sources) == 2
    assert facts.sources[0].name == "Potion of Healing"
    assert facts.sources[0].note == "Heals: 4; Damage: 6. Restores instantly."
    # Rowspan on notes carried to row 2
    assert facts.sources[1].name == "Splash Potion of Healing"
    assert facts.sources[1].note == "Heals: 4; Damage: 6. Restores instantly."


def test_parse_hero_page_with_rowspan_and_edition_filter() -> None:
    facts = parse_effect_page("Hero of the Village", _SAMPLE_HERO_PAGE)
    assert len(facts.sources) == 1
    # Bedrock row dropped, Java row kept with cause name from rowspan
    assert facts.sources[0].name == "Defeating a raid"
    assert facts.sources[0].length == "40:00"
    assert facts.sources[0].note == "Java raid win."


def test_parse_prose_causes() -> None:
    health_boost = parse_effect_page("Health Boost", _SAMPLE_HEALTH_BOOST_PAGE)
    assert len(health_boost.sources) == 1
    assert health_boost.sources[0].name == "Commands"

    bad_luck = parse_effect_page("Bad Luck", _SAMPLE_BAD_LUCK_PAGE)
    assert len(bad_luck.sources) == 1
    assert bad_luck.sources[0].name == "Commands"


def test_verify_effect_sources_success() -> None:
    # Build a mock index covering expected effects
    by_title = {
        title: EffectPageFacts(
            title=title,
            category="positive",
            behaviour="Sample behaviour",
            sources=(RawEffectSource(name="Source"),),
        )
        for title in EFFECT_PAGE_TITLES
    }
    index = EffectIndex(by_title=by_title)

    food_facts = FoodFacts(
        item="minecraft:spider_eye",
        effects=(
            ConsumeEffect(
                kind=ConsumeEffectKind.APPLY_EFFECTS,
                applied=(
                    AppliedEffect(
                        effect="minecraft:poison",
                        amplifier=0,
                        duration_ticks=100,
                        probability=1.0,
                    ),
                ),
            ),
        ),
    )

    errors = verify_effect_sources(
        index,
        potion_paths=("swiftness", "healing", "poison"),
        food_index={"minecraft:spider_eye": food_facts},
    )
    assert errors == []


def test_verify_effect_sources_missing_or_empty() -> None:
    by_title = {
        "Speed": EffectPageFacts(
            title="Speed",
            category="positive",
            behaviour="Fast",
            sources=(),  # empty sources
        ),
    }
    index = EffectIndex(by_title=by_title)

    errors = verify_effect_sources(
        index,
        potion_paths=("swiftness", "healing"),  # Healing is missing entirely, Speed has empty
        food_index=None,
    )
    assert len(errors) == 2
    assert any("Instant Health" in e and "not parsed" in e for e in errors)
    assert any("Speed" in e and "zero parsed sources" in e for e in errors)


def test_live_cached_fetch_effects() -> None:
    cache = ContentCache()
    index = fetch_effects(revision="26.2", cache=cache)

    assert len(index.effects) == 39
    assert len(index.by_title) == 39

    for facts in index.effects:
        assert facts.category in ("positive", "negative", "neutral")
        assert facts.behaviour is not None
        assert len(facts.behaviour) > 10
        assert len(facts.sources) > 0, f"Effect {facts.title} has no sources"
