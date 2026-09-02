"""Turn a `BrewingIndex` plus the potion registry into `BREWING` producers.

`pipeline.enrich.brewing` reports wiki *facts* -- which ingredient makes
which named effect, and which effect corrupts into which other one. This
module is where those facts meet the one list that can prove any of them
real: `registries["potion"]`, 46 entries in the pinned `26.2-summary`
verified live on 2026-09-01. Every producer this module builds is checked
against that list before it is emitted; a rule that produces an ID the
registry does not hold is dropped and counted, never guessed into existence.
`long_healing` is the case named outright in this task's own brief -- an
instant-effect potion takes no duration extension, so the registry holds no
such entry, and inventing one would be exactly the guess `CLAUDE.md`'s Tier
rules forbid.

## Ids as real, expandable inputs

Every producer this module builds names its *precursor potion* as a real
input, not an implicit detail: an effect recipe's second input is
`minecraft:potion/awkward`, a base recipe's second input is `minecraft:
potion/water`, and a modifier's second input is the unmodified potion. This
is what lets `pipeline.obtain.tree` walk a potion's whole brewing chain the
way `TODO.md`'s Decision 12 describes it -- "a potion node expands into its
brewing step; every ingredient of that step keeps expanding" -- rather than
this module hand-flattening the chain itself. `minecraft:potion/water` is
the bottom of every one of those chains, and it gets a producer of its own
here -- an `ObtainMethod.FILLING` one, from a glass bottle. It is the single
edge in this module that is not brewing, and it earns its place by being
load-bearing for all 44 brewable potions at once: without it every potion
tree stops at "water bottle" and the glass bottle, glass, and sand beneath
it are unreachable from any potion in the game.

## The effect-name to potion-id gap

The wiki names *effects* (`"Speed"`); the registry names *potions*
(`"swiftness"`). Five of them differ in wording, not in meaning, and
`_EFFECT_NAME_EXCEPTIONS` is that exact five-entry table, verified against
the live registry list:

| Wiki name | Potion registry id |
|---|---|
| Speed | `swiftness` |
| Jump Boost | `leaping` |
| Instant Health | `healing` |
| Instant Damage | `harming` |
| Slowness + Resistance | `turtle_master` |

Every other effect name resolves by casefolding and joining on `_`: `Poison`
gives `poison`, `Fire Resistance` gives `fire_resistance`, and so on. An
effect name that resolves to neither the exception table nor a live registry
entry is reported in `UnresolvedEffect`, never silently dropped -- this is
what lets this module survive a new potion added in a future version rather
than quietly ignoring it.

## Long/strong modifiers and corruption, generated mechanically

Neither needs its own wikitext parse. A `long_`/`strong_` variant is
mechanical: for every non-prefixed registry path, try `long_<path>` and
`strong_<path>` and keep whichever the registry actually holds -- the
registry membership check alone reproduces exactly the set the `Brewing`
page's "Extended"/"Enhanced" table columns would otherwise have to be parsed
to discover (verified: `strong_invisibility` is absent from both the
registry and that page's Enhanced column for Potion of Invisibility, which
shows as the wiki's own `�` "not applicable" marker). Corruption runs the
same way, once per prefix (`""`, `"long_"`, `"strong_"`), against `pipeline.
enrich.brewing.BrewingIndex.corruption_map`: `long_swiftness` corrupts into
`long_slowness` because both IDs exist and the un-prefixed pair already
does, exactly matching the in-game rule that a `long_`/`strong_` prefix
carries through corruption.

## Container steps: real vanilla items, not new entities

`TODO.md`'s review settled on 46 drinkable-only potion pages, with no
separate splash or lingering entity. `minecraft:splash_potion` and
`minecraft:lingering_potion` are themselves ordinary Tier A items already,
so gunpowder and dragon's breath become `BREWING` producers of *those* two
existing items rather than of anything invented: `minecraft:splash_potion`
gets one producer per drinkable potion (`gunpowder` + that potion), and
`minecraft:lingering_potion` gets one producer from `minecraft:splash_potion`
itself (`dragon's breath` + a splash potion), matching the in-game order --
dragon's breath converts a splash potion, never a drinkable one, into a
lingering one.
"""

from collections.abc import Mapping, Sequence

from pydantic import BaseModel

from pipeline.enrich.brewing import WIKI_NAME_TO_ITEM_ID, BrewingIndex
from pipeline.obtain.producer import ObtainMethod, Producer, ProducerInput, ProducerOutput

__all__ = [
    "BREWING_STAND",
    "GLASS_BOTTLE_ITEM",
    "LINGERING_POTION_ITEM",
    "POTION_ID_TEMPLATE",
    "SPLASH_POTION_ITEM",
    "BrewingExtractionResult",
    "UnresolvedEffect",
    "build_brewing_producers",
]

# The scheme every potion entity's ID follows, per this task's own decision:
# fifteen potion paths collide with `mob_effect` paths, so the potion
# registry alone is not enough namespacing.
POTION_ID_TEMPLATE = "minecraft:potion/{path}"

BREWING_STAND = "brewing_stand"

# Real vanilla items, not invented for this task -- see the module
# docstring's container-steps section for why no splash/lingering *potion*
# entity exists to target instead.
SPLASH_POTION_ITEM = "minecraft:splash_potion"
LINGERING_POTION_ITEM = "minecraft:lingering_potion"

# The water bottle, and the item it is filled from. `water` is a real entry
# of the 46-strong potion registry, so the water bottle is `minecraft:potion/
# water` like every other potion rather than an item of its own -- which is
# also why it needs no special case anywhere in the tree walker.
_WATER_POTION_PATH = "water"
GLASS_BOTTLE_ITEM = "minecraft:glass_bottle"

# The five wiki effect names that spell differently from their registry
# potion id. See the module docstring's table for the live-verified pairing.
_EFFECT_NAME_EXCEPTIONS: Mapping[str, str] = {
    "Speed": "swiftness",
    "Jump Boost": "leaping",
    "Instant Health": "healing",
    "Instant Damage": "harming",
    "Slowness + Resistance": "turtle_master",
}

_LONG_PREFIX = "long_"
_STRONG_PREFIX = "strong_"
_PREFIXES = ("", _LONG_PREFIX, _STRONG_PREFIX)


class UnresolvedEffect(BaseModel, frozen=True):
    """One wiki effect name whose resolved potion id the registry does not hold."""

    effect_name: str
    resolved_path: str
    reason: str


class BrewingExtractionResult(BaseModel, frozen=True):
    """Every `BREWING` producer this module built, and what it could not place.

    `uncovered_potions` lists every registry potion path with zero producers
    once every rule has run -- the coverage assertion `tests/test_obtain_
    brewing.py` checks against the 46-entry registry. Expected to hold
    exactly `luck` on the live 26.2 data, the one potion the wiki's own
    Un-brewable section names for Java. `water` is absent from this list
    despite having no brewing recipe, because it does have a producer: the
    `FILLING` one this module emits for the water bottle.
    """

    producers: tuple[Producer, ...]
    unresolved_effects: tuple[UnresolvedEffect, ...]
    uncovered_potions: tuple[str, ...]


def _potion_path(effect_name: str) -> str:
    """Return the registry potion path `effect_name` names, resolved by name then by rule."""
    exception = _EFFECT_NAME_EXCEPTIONS.get(effect_name)
    if exception is not None:
        return exception
    return effect_name.casefold().replace(" ", "_")


def _potion_id(path: str) -> str:
    return POTION_ID_TEMPLATE.format(path=path)


def build_brewing_producers(
    brewing: BrewingIndex, potion_paths: Sequence[str]
) -> BrewingExtractionResult:
    """Return every `BREWING` producer `brewing` and `potion_paths` together prove real.

    `potion_paths` is `registries["potion"]` -- the unprefixed paths of the
    46 live potion registry entries, `"awkward"`, `"swiftness"`, and so on,
    with no namespace and no `potion/` prefix.
    """
    registry = frozenset(potion_paths)
    fermented_spider_eye = brewing.weakness_recipe.ingredient_item
    redstone = WIKI_NAME_TO_ITEM_ID["Redstone Dust"]
    glowstone_dust = WIKI_NAME_TO_ITEM_ID["Glowstone Dust"]

    producers: list[Producer] = []
    unresolved: list[UnresolvedEffect] = []

    def emit(*, output_path: str, inputs: tuple[ProducerInput, ...], source_id: str) -> None:
        producers.append(
            Producer(
                method=ObtainMethod.BREWING,
                output=ProducerOutput(item=_potion_id(output_path)),
                inputs=inputs,
                source_id=source_id,
                station=BREWING_STAND,
            )
        )

    # --- The water bottle: where every brewing chain actually bottoms out ---
    #
    # `minecraft:potion/water` is an input of all 44 brewable potions and is
    # the output of nothing else in this pipeline: it is not brewed, crafted,
    # smelted, dropped, or traded. Without this one producer every potion
    # tree in the game stops at "water bottle" and the glass bottle under it
    # -- and the glass, and the sand under that -- is unreachable from any
    # potion at all, which is the gap review caught on the first live build.
    #
    # The edge itself is the wiki's own, from the Brewing page's Brewing
    # equipment table: a water bottle is "made by filling a glass bottle from
    # a cauldron or a water source block." It is stated in that table's prose
    # column rather than in a structured cell, so `pipeline.enrich.brewing`
    # deliberately does not try to parse the relationship out of a sentence;
    # this is one structural edge, fixed by the shape of the game rather than
    # by any version's potion list, and it is written here where a reader can
    # check it against that quote. Nothing about it changes when a new potion
    # or a new effect ingredient is added -- those still arrive entirely from
    # the parsed tables, which is the property this module was asked to keep.
    if _WATER_POTION_PATH in registry:
        producers.append(
            Producer(
                method=ObtainMethod.FILLING,
                output=ProducerOutput(item=_potion_id(_WATER_POTION_PATH)),
                inputs=(ProducerInput(item=GLASS_BOTTLE_ITEM),),
                source_id="brewing/equipment/water_bottle",
                note="filled from a water source block or a cauldron",
            )
        )

    # --- Base recipes: water bottle + ingredient -> awkward/thick/mundane ---
    for base in brewing.base_recipes:
        if base.result_path not in registry:
            unresolved.append(
                UnresolvedEffect(
                    effect_name=base.result_path,
                    resolved_path=base.result_path,
                    reason="a base recipe's own result path is not a registry potion",
                )
            )
            continue
        emit(
            output_path=base.result_path,
            inputs=(
                ProducerInput(item=base.ingredient_item),
                ProducerInput(item=_potion_id("water")),
            ),
            source_id=f"brewing/base/{base.result_path}",
        )

    # --- Weakness: water bottle + fermented spider eye -> weakness ---------
    weakness = brewing.weakness_recipe
    if weakness.result_path in registry:
        emit(
            output_path=weakness.result_path,
            inputs=(
                ProducerInput(item=weakness.ingredient_item),
                ProducerInput(item=_potion_id("water")),
            ),
            source_id="brewing/base/weakness",
        )
    else:
        unresolved.append(
            UnresolvedEffect(
                effect_name="Weakness",
                resolved_path=weakness.result_path,
                reason="the weakness base recipe's result path is not a registry potion",
            )
        )

    # --- Effect recipes: awkward potion + ingredient -> effect -------------
    for effect in brewing.effect_recipes:
        path = _potion_path(effect.effect_name)
        if path not in registry:
            unresolved.append(
                UnresolvedEffect(
                    effect_name=effect.effect_name,
                    resolved_path=path,
                    reason="resolved to a potion id the registry does not hold",
                )
            )
            continue
        emit(
            output_path=path,
            inputs=(
                ProducerInput(item=effect.ingredient_item),
                ProducerInput(item=_potion_id("awkward")),
            ),
            source_id=f"brewing/effect/{path}",
        )

    # --- Corruption: fermented spider eye + source -> corrupted, per prefix -
    for prefix in _PREFIXES:
        for source_name, corrupted_name in brewing.corruption_map.items():
            source_path = prefix + _potion_path(source_name)
            corrupted_path = prefix + _potion_path(corrupted_name)
            if source_path not in registry or corrupted_path not in registry:
                continue
            emit(
                output_path=corrupted_path,
                inputs=(
                    ProducerInput(item=fermented_spider_eye),
                    ProducerInput(item=_potion_id(source_path)),
                ),
                source_id=f"brewing/corruption/{corrupted_path}/{source_path}",
            )

    # --- Long/strong modifiers, mechanical against the registry -------------
    for path in sorted(registry):
        if path.startswith(_LONG_PREFIX) or path.startswith(_STRONG_PREFIX):
            continue
        long_path = _LONG_PREFIX + path
        if long_path in registry:
            emit(
                output_path=long_path,
                inputs=(ProducerInput(item=redstone), ProducerInput(item=_potion_id(path))),
                source_id=f"brewing/modifier/long/{path}",
            )
        strong_path = _STRONG_PREFIX + path
        if strong_path in registry:
            emit(
                output_path=strong_path,
                inputs=(ProducerInput(item=glowstone_dust), ProducerInput(item=_potion_id(path))),
                source_id=f"brewing/modifier/strong/{path}",
            )

    # --- Container steps: real items, not new entities ----------------------
    for path in sorted(registry):
        producers.append(
            Producer(
                method=ObtainMethod.BREWING,
                output=ProducerOutput(item=SPLASH_POTION_ITEM),
                inputs=(
                    ProducerInput(item=brewing.gunpowder_item),
                    ProducerInput(item=_potion_id(path)),
                ),
                source_id=f"brewing/container/splash/{path}",
                station=BREWING_STAND,
            )
        )
    producers.append(
        Producer(
            method=ObtainMethod.BREWING,
            output=ProducerOutput(item=LINGERING_POTION_ITEM),
            inputs=(
                ProducerInput(item=brewing.dragon_breath_item),
                ProducerInput(item=SPLASH_POTION_ITEM),
            ),
            source_id="brewing/container/lingering",
            station=BREWING_STAND,
        )
    )

    covered = {
        producer.output.item.removeprefix("minecraft:potion/")
        for producer in producers
        if producer.output.item.startswith("minecraft:potion/")
    }
    uncovered = tuple(sorted(registry - covered))

    return BrewingExtractionResult(
        producers=tuple(producers),
        unresolved_effects=tuple(unresolved),
        uncovered_potions=uncovered,
    )
