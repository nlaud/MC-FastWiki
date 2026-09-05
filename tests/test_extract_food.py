"""`pipeline.extract.food`: what eating an item does, read from two components.

Every payload here is built in memory, one rule per test, the way
`tests/test_extract_harvest.py` builds its tag files. The stage opens no
socket, so nothing here needs a fixture of the real 956 kB file.

The values in the happy-path cases are the real 26.2 ones, copied from
`misode/mcmeta@26.2-summary/item_components/data.json`, so a test that passes
is a test that agrees with the game rather than with itself.
"""

import pytest

from pipeline.extract import ExtractError
from pipeline.extract.food import (
    SATURATION_DIGITS,
    ConsumeEffectKind,
    extract_food,
)


def _payload(**items: dict[str, object]) -> dict[str, dict[str, object]]:
    """Return an `item_components` payload holding exactly `items`."""
    return dict(items)


def test_reads_nutrition_and_saturation_of_a_plain_food() -> None:
    facts = extract_food(_payload(apple={"minecraft:food": {"nutrition": 4, "saturation": 2.4}}))

    assert set(facts) == {"minecraft:apple"}
    apple = facts["minecraft:apple"]
    assert apple.nutrition == 4
    assert apple.saturation == 2.4
    assert apple.can_always_eat is False
    assert apple.effects == ()


def test_the_answer_is_keyed_by_the_namespaced_id_not_the_unprefixed_path() -> None:
    """Fact 1 of the module docstring: the source keys are unprefixed.

    A caller holding a registry ID must be able to look the item up without
    knowing which half of the pipeline stripped the namespace.
    """
    facts = extract_food(_payload(apple={"minecraft:food": {"nutrition": 4, "saturation": 2.4}}))

    assert "minecraft:apple" in facts
    assert "apple" not in facts


def test_float32_noise_in_saturation_is_rounded_away() -> None:
    """Fact 2: `beef` really does read 1.8000001 upstream.

    Rounding at this boundary is what stops `7.2000003 saturation` reaching a
    page, and it happens once rather than in every later reader.
    """
    facts = extract_food(
        _payload(
            beef={"minecraft:food": {"nutrition": 3, "saturation": 1.8000001}},
            suspicious_stew={
                "minecraft:food": {
                    "nutrition": 6,
                    "saturation": 7.2000003,
                    "can_always_eat": True,
                }
            },
        )
    )

    assert facts["minecraft:beef"].saturation == 1.8
    assert facts["minecraft:suspicious_stew"].saturation == 7.2
    assert SATURATION_DIGITS == 2


def test_can_always_eat_is_carried_when_the_component_sets_it() -> None:
    facts = extract_food(
        _payload(
            golden_apple={
                "minecraft:food": {"nutrition": 4, "saturation": 9.6, "can_always_eat": True}
            }
        )
    )

    assert facts["minecraft:golden_apple"].can_always_eat is True


def test_an_apply_effects_group_carries_its_probability_onto_every_effect() -> None:
    """`probability` sits on the group, not on each effect inside it.

    Rotten flesh is the real case: one 80% group holding one effect.
    """
    facts = extract_food(
        _payload(
            rotten_flesh={
                "minecraft:food": {"nutrition": 4, "saturation": 0.8},
                "minecraft:consumable": {
                    "on_consume_effects": [
                        {
                            "type": "minecraft:apply_effects",
                            "effects": [{"id": "minecraft:hunger", "duration": 600}],
                            "probability": 0.8,
                        }
                    ]
                },
            }
        )
    )

    (entry,) = facts["minecraft:rotten_flesh"].effects
    assert entry.kind is ConsumeEffectKind.APPLY_EFFECTS
    (applied,) = entry.applied
    assert applied.effect == "minecraft:hunger"
    assert applied.duration_ticks == 600
    assert applied.amplifier == 0
    assert applied.probability == 0.8


def test_an_omitted_probability_means_certain() -> None:
    facts = extract_food(
        _payload(
            spider_eye={
                "minecraft:food": {"nutrition": 2, "saturation": 3.2},
                "minecraft:consumable": {
                    "on_consume_effects": [
                        {
                            "type": "minecraft:apply_effects",
                            "effects": [{"id": "minecraft:poison", "duration": 100}],
                        }
                    ]
                },
            }
        )
    )

    (entry,) = facts["minecraft:spider_eye"].effects
    (applied,) = entry.applied
    assert applied.probability == 1.0


def test_amplifier_stays_zero_based_here() -> None:
    """The 1-based level is a display decision, made in `pipeline.normalize.merge`.

    Golden apple's regeneration is amplifier 1 upstream and reads as level II
    on screen. This stage carries the source's own number.
    """
    facts = extract_food(
        _payload(
            golden_apple={
                "minecraft:food": {"nutrition": 4, "saturation": 9.6, "can_always_eat": True},
                "minecraft:consumable": {
                    "on_consume_effects": [
                        {
                            "type": "minecraft:apply_effects",
                            "effects": [
                                {
                                    "id": "minecraft:regeneration",
                                    "duration": 100,
                                    "amplifier": 1,
                                },
                                {"id": "minecraft:absorption", "duration": 2400},
                            ],
                        }
                    ]
                },
            }
        )
    )

    (entry,) = facts["minecraft:golden_apple"].effects
    regeneration, absorption = entry.applied
    assert regeneration.amplifier == 1
    assert absorption.amplifier == 0


def test_remove_effects_accepts_a_bare_string() -> None:
    """Fact 4: honey bottle spells its one cured effect as a string, not a list."""
    facts = extract_food(
        _payload(
            honey_bottle={
                "minecraft:food": {"nutrition": 6, "saturation": 1.2, "can_always_eat": True},
                "minecraft:consumable": {
                    "on_consume_effects": [
                        {"type": "minecraft:remove_effects", "effects": "minecraft:poison"}
                    ]
                },
            }
        )
    )

    (entry,) = facts["minecraft:honey_bottle"].effects
    assert entry.kind is ConsumeEffectKind.REMOVE_EFFECTS
    assert entry.removed == ("minecraft:poison",)


def test_remove_effects_also_accepts_a_list() -> None:
    """The vanilla codec allows it even though 26.2 ships no item that uses it."""
    facts = extract_food(
        _payload(
            test_item={
                "minecraft:consumable": {
                    "on_consume_effects": [
                        {
                            "type": "minecraft:remove_effects",
                            "effects": ["minecraft:poison", "minecraft:wither"],
                        }
                    ]
                }
            }
        )
    )

    (entry,) = facts["minecraft:test_item"].effects
    assert entry.removed == ("minecraft:poison", "minecraft:wither")


@pytest.mark.parametrize(
    ("kind", "payload_type"),
    [
        (ConsumeEffectKind.CLEAR_ALL_EFFECTS, "minecraft:clear_all_effects"),
        (ConsumeEffectKind.TELEPORT_RANDOMLY, "minecraft:teleport_randomly"),
        (ConsumeEffectKind.PLAY_SOUND, "minecraft:play_sound"),
    ],
)
def test_the_payload_free_kinds_are_read_rather_than_skipped(
    kind: ConsumeEffectKind, payload_type: str
) -> None:
    """Fact 3: modelling `apply_effects` alone would drop the milk bucket."""
    facts = extract_food(
        _payload(
            test_item={"minecraft:consumable": {"on_consume_effects": [{"type": payload_type}]}}
        )
    )

    (entry,) = facts["minecraft:test_item"].effects
    assert entry.kind is kind
    assert entry.applied == ()
    assert entry.removed == ()


def test_a_consumable_without_food_is_still_in_the_answer() -> None:
    """The milk bucket restores nothing and still answers a real question."""
    facts = extract_food(
        _payload(
            milk_bucket={
                "minecraft:consumable": {
                    "on_consume_effects": [{"type": "minecraft:clear_all_effects"}]
                }
            }
        )
    )

    milk = facts["minecraft:milk_bucket"]
    assert milk.nutrition is None
    assert milk.saturation is None
    assert milk.effects[0].kind is ConsumeEffectKind.CLEAR_ALL_EFFECTS


def test_an_item_that_says_nothing_about_eating_is_absent() -> None:
    facts = extract_food(
        _payload(
            apple={"minecraft:food": {"nutrition": 4, "saturation": 2.4}},
            stone={"minecraft:max_stack_size": 64},
            potion={"minecraft:consumable": {"animation": "drink"}},
        )
    )

    assert set(facts) == {"minecraft:apple"}


def test_an_unknown_consume_effect_type_raises_rather_than_being_skipped() -> None:
    """A sixth type is a thing eating an item now does, and wants reading."""
    with pytest.raises(ExtractError, match="minecraft:summon_dragon"):
        extract_food(
            _payload(
                test_item={
                    "minecraft:consumable": {
                        "on_consume_effects": [{"type": "minecraft:summon_dragon"}]
                    }
                }
            )
        )


def test_an_apply_effects_entry_with_no_effects_raises() -> None:
    with pytest.raises(ExtractError, match="no effects list"):
        extract_food(
            _payload(
                test_item={
                    "minecraft:consumable": {
                        "on_consume_effects": [{"type": "minecraft:apply_effects", "effects": []}]
                    }
                }
            )
        )


def test_an_effect_without_an_id_raises() -> None:
    with pytest.raises(ExtractError, match="has no id"):
        extract_food(
            _payload(
                test_item={
                    "minecraft:consumable": {
                        "on_consume_effects": [
                            {"type": "minecraft:apply_effects", "effects": [{"duration": 100}]}
                        ]
                    }
                }
            )
        )


@pytest.mark.parametrize("probability", [0, 1.5, -0.2])
def test_a_probability_outside_the_open_unit_interval_raises(probability: float) -> None:
    with pytest.raises(ExtractError, match="probability"):
        extract_food(
            _payload(
                test_item={
                    "minecraft:consumable": {
                        "on_consume_effects": [
                            {
                                "type": "minecraft:apply_effects",
                                "effects": [{"id": "minecraft:poison", "duration": 100}],
                                "probability": probability,
                            }
                        ]
                    }
                }
            )
        )


@pytest.mark.parametrize(
    "component",
    [
        {"nutrition": "four", "saturation": 2.4},
        {"nutrition": 4, "saturation": "lots"},
        {"nutrition": -1, "saturation": 2.4},
        {"saturation": 2.4},
    ],
)
def test_a_malformed_food_component_raises(component: dict[str, object]) -> None:
    with pytest.raises(ExtractError):
        extract_food(_payload(test_item={"minecraft:food": component}))


def test_a_non_boolean_can_always_eat_raises() -> None:
    with pytest.raises(ExtractError, match="can_always_eat"):
        extract_food(
            _payload(
                test_item={
                    "minecraft:food": {
                        "nutrition": 4,
                        "saturation": 2.4,
                        "can_always_eat": "yes",
                    }
                }
            )
        )


def test_a_payload_that_is_not_an_object_raises() -> None:
    with pytest.raises(ExtractError, match="not an object"):
        extract_food(["apple"])  # type: ignore[arg-type]


def test_an_empty_answer_raises_rather_than_returning_nothing() -> None:
    """CLAUDE.md's rule: an empty read is a broken fetch, not a real answer."""
    with pytest.raises(ExtractError, match="no food and no consume effect"):
        extract_food(_payload(stone={"minecraft:max_stack_size": 64}))
