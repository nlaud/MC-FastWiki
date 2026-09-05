"""Read what eating an item does, from the `minecraft:food` and `minecraft:consumable` components.

An item page must answer one question in a match. If I eat this, what do I get
back and what does it do to me? The `item_components` summary of mcmeta holds
the whole answer in two components, so this stage is Tier A and opens no wiki
page.

1. `minecraft:food` carries `nutrition`, `saturation`, and `can_always_eat`.
   44 of the 1,537 items in `26.2-summary` have it.
2. `minecraft:consumable` carries `on_consume_effects`, a list of the things
   that happen when the item goes down. 43 items have the component and 11 of
   them have a non-empty list.

Neither component implies the other, and both directions of the mismatch are
real. `milk_bucket` clears every effect and restores no hunger at all, so it is
consumable and not food. `apple` restores hunger and does nothing else, so its
`minecraft:consumable` is an empty object.

## Four facts of the source, each of which fails quietly without a guard

1. **The keys are unprefixed.** The map is keyed `apple`, not `minecraft:apple`.
   CLAUDE.md names this trap and `pipeline.fetch.mcmeta` repeats it, because a
   lookup of the namespaced ID returns nothing and says nothing. This module
   takes the unprefixed key and hands back the namespaced ID, so no later stage
   has to remember which half of the pipeline it is standing in.

2. **`saturation` arrives with float32 noise.** `beef` reads `1.8000001` and
   `suspicious_stew` reads `7.2000003`, because the value is a 32-bit float
   widened to a 64-bit one. Printing it raw would put `7.2000003 saturation` on
   the screen. `SATURATION_DIGITS` rounds it once, here at the boundary, rather
   than leaving every later reader to decide how many digits it trusts.

3. **`on_consume_effects` has five entry types, not one.** `apply_effects` is
   the interesting one, and it is not the only one: `remove_effects`,
   `clear_all_effects`, `teleport_randomly`, and `play_sound` all appear in
   26.2. A module that modelled `apply_effects` alone would silently drop the
   milk bucket and the chorus fruit, which is why `ConsumeEffectKind` is a
   closed enum and an entry this module cannot name raises rather than skips.

4. **`remove_effects` carries a bare string, not a list.** `honey_bottle` reads
   `"effects": "minecraft:poison"` where `apply_effects` reads a list of
   objects under the same key name. Both spellings are accepted here.

`probability` sits on the wrapping entry rather than on each effect inside it,
so a `rotten_flesh` entry says "80% chance of this whole group". Three items
carry one at all: `rotten_flesh` 0.8, `poisonous_potato` 0.6, `chicken` 0.3.
Every other entry is certain, and this module fills in the 1.0 rather than
leaving `None` for a renderer to interpret.

The stage is a pure function from the decoded payload to a mapping, so no test
of it opens a socket. `tests/test_extract_food.py` builds its own payloads in
memory, one rule per case.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from pipeline.extract import ExtractError

__all__ = [
    "CONSUMABLE_COMPONENT",
    "FOOD_COMPONENT",
    "SATURATION_DIGITS",
    "AppliedEffect",
    "ConsumeEffect",
    "ConsumeEffectKind",
    "FoodFacts",
    "extract_food",
]

# The two components this stage reads. Every other key of an item's component
# map belongs to another phase.
FOOD_COMPONENT = "minecraft:food"
CONSUMABLE_COMPONENT = "minecraft:consumable"

# The namespace every unprefixed key of `item_components` belongs to. mcmeta
# publishes one namespace on this branch, so this is a constant rather than a
# guess: fact 1 of the module docstring.
VANILLA_NAMESPACE = "minecraft"

# How many digits of `saturation` survive. Two is enough for every value in
# 26.2 -- the widest real one is `12.8` -- and it is what turns the float32
# noise of fact 2 back into the number the game means.
SATURATION_DIGITS = 2

# What `probability` means when an `apply_effects` entry omits it: the group
# always lands.
CERTAIN = 1.0


class ConsumeEffectKind(StrEnum):
    """The five `on_consume_effects` entry types of 26.2.

    Closed on purpose. A sixth type in a later Minecraft version is a fact this
    project has to look at before it renders, not one to drop on the floor, so
    `extract_food` raises on a type this enum does not name.
    """

    APPLY_EFFECTS = "minecraft:apply_effects"
    REMOVE_EFFECTS = "minecraft:remove_effects"
    CLEAR_ALL_EFFECTS = "minecraft:clear_all_effects"
    TELEPORT_RANDOMLY = "minecraft:teleport_randomly"
    PLAY_SOUND = "minecraft:play_sound"


class AppliedEffect(BaseModel):
    """One status effect that eating the item applies.

    `duration_ticks` stays in ticks rather than becoming seconds here, because
    ticks are what the source says and the renderer is the one place that knows
    how a duration should read on screen. `amplifier` stays zero-based for the
    same reason: level I is amplifier 0, and turning that into a Roman numeral
    is a display decision.
    """

    model_config = ConfigDict(frozen=True)

    effect: str
    duration_ticks: int = Field(ge=0)
    amplifier: int = Field(ge=0)
    probability: float = Field(gt=0.0, le=1.0)


class ConsumeEffect(BaseModel):
    """One entry of `on_consume_effects`, whichever of the five types it is.

    `applied` is non-empty only for `APPLY_EFFECTS`, and `removed` only for
    `REMOVE_EFFECTS`. The other three types carry no payload at all -- their
    whole meaning is the kind itself.
    """

    model_config = ConfigDict(frozen=True)

    kind: ConsumeEffectKind
    applied: tuple[AppliedEffect, ...] = ()
    removed: tuple[str, ...] = ()


class FoodFacts(BaseModel):
    """What one item restores and what it does, keyed by its namespaced ID.

    `nutrition` and `saturation` are `None` together, for an item that is
    consumable without being food. No item in 26.2 carries one without the
    other, and the two fields move as a pair because the `minecraft:food`
    component either exists or does not.
    """

    model_config = ConfigDict(frozen=True)

    item: str
    nutrition: int | None = None
    saturation: float | None = None
    can_always_eat: bool = False
    effects: tuple[ConsumeEffect, ...] = ()


def _require_mapping(value: object, *, subject: str) -> Mapping[str, Any]:
    """Return `value` as a mapping, or raise naming what was read instead."""
    if not isinstance(value, Mapping):
        raise ExtractError(
            f"{subject} is {type(value).__name__}, not an object. `item_components` holds one "
            f"object per item, and each component inside it is an object too."
        )
    return value


def _parse_applied_effects(
    entry: Mapping[str, Any], *, subject: str
) -> tuple[AppliedEffect, ...]:
    """Return the effects of one `apply_effects` entry, with its group probability."""
    raw_probability = entry.get("probability", CERTAIN)
    if not isinstance(raw_probability, (int, float)) or isinstance(raw_probability, bool):
        raise ExtractError(
            f"{subject} has a probability of {raw_probability!r}, which is not a number."
        )
    probability = float(raw_probability)
    if not 0.0 < probability <= 1.0:
        raise ExtractError(
            f"{subject} has a probability of {probability}, which is outside (0, 1]. A group "
            f"that never lands would not be written down, and one above 1 is not a chance."
        )

    raw_effects = entry.get("effects")
    if not isinstance(raw_effects, list) or not raw_effects:
        raise ExtractError(
            f"{subject} is an apply_effects entry with no effects list. Such an entry applies "
            f"nothing, so it is a shape fault rather than an item that does nothing."
        )

    applied: list[AppliedEffect] = []
    for index, raw in enumerate(raw_effects):
        effect = _require_mapping(raw, subject=f"{subject} effect {index}")
        identifier = effect.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ExtractError(f"{subject} effect {index} has no id.")
        duration = effect.get("duration", 0)
        amplifier = effect.get("amplifier", 0)
        if not isinstance(duration, int) or isinstance(duration, bool):
            raise ExtractError(
                f"{subject} effect {index} has a duration of {duration!r}, which is not a whole "
                f"number of ticks."
            )
        if not isinstance(amplifier, int) or isinstance(amplifier, bool):
            raise ExtractError(
                f"{subject} effect {index} has an amplifier of {amplifier!r}, which is not a "
                f"whole number."
            )
        applied.append(
            AppliedEffect(
                effect=identifier,
                duration_ticks=duration,
                amplifier=amplifier,
                probability=probability,
            )
        )
    return tuple(applied)


def _parse_removed_effects(entry: Mapping[str, Any], *, subject: str) -> tuple[str, ...]:
    """Return the effect IDs of one `remove_effects` entry.

    Fact 4 of the module docstring: the key holds a bare string for the one item
    that uses it today, and the vanilla codec also accepts a list, so both are
    read here rather than only the spelling 26.2 happens to ship.
    """
    raw = entry.get("effects")
    if isinstance(raw, str) and raw:
        return (raw,)
    if isinstance(raw, list) and raw:
        removed: list[str] = []
        for index, value in enumerate(raw):
            if not isinstance(value, str) or not value:
                raise ExtractError(f"{subject} names {value!r} at {index}, which is not an ID.")
            removed.append(value)
        return tuple(removed)
    raise ExtractError(
        f"{subject} is a remove_effects entry naming no effect. It removes nothing, which is a "
        f"shape fault rather than a real item."
    )


def _parse_consume_effects(component: Mapping[str, Any], *, item: str) -> tuple[ConsumeEffect, ...]:
    """Return every `on_consume_effects` entry of one item's consumable component."""
    raw_entries = component.get("on_consume_effects")
    if raw_entries is None:
        return ()
    if not isinstance(raw_entries, list):
        raise ExtractError(
            f"{item} has an on_consume_effects of {type(raw_entries).__name__}, not a list."
        )

    effects: list[ConsumeEffect] = []
    for index, raw in enumerate(raw_entries):
        subject = f"{item} on_consume_effects[{index}]"
        entry = _require_mapping(raw, subject=subject)
        raw_kind = entry.get("type")
        if not isinstance(raw_kind, str):
            raise ExtractError(f"{subject} has no type.")
        try:
            kind = ConsumeEffectKind(raw_kind)
        except ValueError as error:
            known = ", ".join(sorted(member.value for member in ConsumeEffectKind))
            raise ExtractError(
                f"{subject} is of type {raw_kind!r}, which this pipeline does not know. The "
                f"types it knows are: {known}. A new type is a thing eating an item now does, "
                f"so it wants reading before the build ships a page that omits it."
            ) from error

        if kind is ConsumeEffectKind.APPLY_EFFECTS:
            effects.append(
                ConsumeEffect(kind=kind, applied=_parse_applied_effects(entry, subject=subject))
            )
        elif kind is ConsumeEffectKind.REMOVE_EFFECTS:
            effects.append(
                ConsumeEffect(kind=kind, removed=_parse_removed_effects(entry, subject=subject))
            )
        else:
            effects.append(ConsumeEffect(kind=kind))
    return tuple(effects)


def _parse_food(component: Mapping[str, Any], *, item: str) -> tuple[int, float, bool]:
    """Return `nutrition`, the rounded `saturation`, and `can_always_eat` of one item."""
    nutrition = component.get("nutrition")
    if not isinstance(nutrition, int) or isinstance(nutrition, bool) or nutrition < 0:
        raise ExtractError(
            f"{item} has a nutrition of {nutrition!r}. A food component states how many hunger "
            f"points the item restores, as a whole number that is not negative."
        )

    saturation = component.get("saturation")
    if not isinstance(saturation, (int, float)) or isinstance(saturation, bool) or saturation < 0:
        raise ExtractError(
            f"{item} has a saturation of {saturation!r}. A food component states saturation as a "
            f"number that is not negative."
        )

    can_always_eat = component.get("can_always_eat", False)
    if not isinstance(can_always_eat, bool):
        raise ExtractError(
            f"{item} has a can_always_eat of {can_always_eat!r}, which is not true or false."
        )

    return nutrition, round(float(saturation), SATURATION_DIGITS), can_always_eat


def extract_food(payload: Mapping[str, Any]) -> dict[str, FoodFacts]:
    """Return what eating does, for every item that says anything about it.

    `payload` is the decoded `item_components/data.json` of the pinned mcmeta
    `summary` branch, which `pipeline.fetch.mcmeta.fetch_summary_payload` reads
    under the name `item_components`. Its keys are unprefixed item paths, and
    the answer this function returns is keyed by the namespaced item ID, in ID
    order.

    An item is in the answer when it has a `minecraft:food` component, or when
    its `minecraft:consumable` component carries at least one entry of
    `on_consume_effects`. An item with neither is absent: `apple` is present
    because it feeds, and a plain `stone` is not present at all.

    Every fault raises `ExtractError`: a payload that is not an object, a
    component that is not an object, a nutrition or saturation that is not a
    number, an `on_consume_effects` entry of a type this pipeline does not
    know, and an answer that holds no item at all.
    """
    items = _require_mapping(payload, subject="the item_components payload")

    facts: dict[str, FoodFacts] = {}
    for path in sorted(items):
        components = _require_mapping(items[path], subject=f"the components of {path!r}")
        item = f"{VANILLA_NAMESPACE}:{path}"

        nutrition: int | None = None
        saturation: float | None = None
        can_always_eat = False
        if FOOD_COMPONENT in components:
            food = _require_mapping(
                components[FOOD_COMPONENT], subject=f"the food component of {path!r}"
            )
            nutrition, saturation, can_always_eat = _parse_food(food, item=item)

        effects: tuple[ConsumeEffect, ...] = ()
        if CONSUMABLE_COMPONENT in components:
            consumable = _require_mapping(
                components[CONSUMABLE_COMPONENT],
                subject=f"the consumable component of {path!r}",
            )
            effects = _parse_consume_effects(consumable, item=item)

        if nutrition is None and not effects:
            continue

        facts[item] = FoodFacts(
            item=item,
            nutrition=nutrition,
            saturation=saturation,
            can_always_eat=can_always_eat,
            effects=effects,
        )

    if not facts:
        raise ExtractError(
            "item_components names no food and no consume effect at all. An empty read is a "
            "broken fetch, not a version of Minecraft where nothing can be eaten."
        )
    return facts
