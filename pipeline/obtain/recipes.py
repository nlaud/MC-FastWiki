"""Turn mcmeta `recipe/*.json` into `Producer`s. The one Tier A adapter of this package.

Six recipe types cover every producer this module emits, in the 1.21.2+
ingredient shape verified live against the pinned `26.2-data` archive on
2026-09-01 -- a plain namespaced string (`"minecraft:oak_planks"`), a
`#`-prefixed tag (`"#minecraft:planks"`), or a JSON list of either, never the
pre-1.21.2 `{"item": ...}` object form:

- `minecraft:crafting_shaped`: `key` (symbol -> ingredient value), `pattern`
  (rows of symbols), `result` (`{"id": ..., "count"?: N}`).
- `minecraft:crafting_shapeless`: `ingredients` (a list of ingredient values).
- `minecraft:smelting` / `blasting` / `smoking` / `campfire_cooking`:
  `ingredient` (singular, not a list), `result`. Distinguished only by
  `Producer.station` (`"furnace"`, `"blast_furnace"`, `"smoker"`,
  `"campfire"`); `ObtainMethod.SMELTING` covers all four, because a player
  reads "smelt this" the same way regardless of which of the four stations
  they used, and the station name alone carries the distinction that matters.
- `minecraft:stonecutting`: `ingredient`, `result`. `ObtainMethod.CRAFTING`
  with `station="stonecutter"` -- see `ObtainMethod`'s own docstring for why
  there is no separate enum member for it.
- `minecraft:smithing_transform`: `base`, `template`, `addition`, `result`.
  `ObtainMethod.CRAFTING` with `station="smithing_table"`.

Every other recipe `type` is skipped and counted in the report rather than
raised on, split into two reasons. `minecraft:crafting_special_*` (book
cloning, banner duplication, firework stars, tipped arrows, armor dyeing, map
cloning and extending, repairing, and the rest of the family mcmeta ships with
no ingredient list at all) and `minecraft:crafting_transmute` (dyeing a
bundle, in-place; no distinct "ingredient becomes item" shape a `Producer`
can represent without guessing which of `input`/`material` is the thing being
transformed) are named outright, matching `TODO.md`'s own instruction to
count `crafting_special_*` rather than raise. Any *other* unrecognized `type`
-- one a future Minecraft version adds -- is skipped under the same "unhandled
recipe type" reason rather than raised on: a new recipe type is new data, not
a broken read, and `TODO.md`'s own Decision 6 argues at length for reading
mcmeta *because* it is exact, versioned data that this pipeline does not have
to guess about -- guessing how to parse a shape this module has never seen is
exactly the guess Decision 6 exists to avoid. `ObtainError` is reserved for a
malformed instance of a type this module *does* claim to handle in full: a
`crafting_shaped` recipe whose `pattern` references a symbol `key` never
defines, a `result` with no `id`, and so on. That split is what
`tests/test_obtain_recipes.py` pins down.

## Tag ingredients stay collapsed, not fanned out

Every `#tag` ingredient is resolved through `pipeline.extract.tags.TagIndex`
against the `item` registry (never a fresh reader of its own -- that module's
docstring already gives the reason a foreign namespace, a self-reference, and
a missing tag file must all raise rather than resolve to an empty set) and
kept as *one* `ProducerInput`, per `TODO.md` Decision 9 and `ProducerInput`'s
own docstring. `#minecraft:planks` produces one input labelled by the tag,
with `members` holding the thirteen wood planks it resolved to, never
thirteen separate inputs or thirteen separate producers.

## The untagged-alternatives list

`minecraft:crafting_shapeless`'s `fire_charge` recipe (verified live) writes
its third ingredient as `["minecraft:coal", "minecraft:charcoal"]` -- a bare
JSON list with no `#tag` id joining the two. There is no tag to label this
input by, so it takes `ProducerInput`'s third shape: `item` is the
alphabetically-first alternative and `members` carries the full sorted list.
This is a narrower reading of "list ingredient" than `TODO.md` anticipated in
detail, and it is called out in this task's own report rather than silently
folded into the tag case, because it is the one place this module's
`ProducerInput` shape bends slightly to cover a real upstream shape that has
no tag id to hang off of.
"""

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from pipeline.extract.tags import TagIndex
from pipeline.obtain import ObtainError
from pipeline.obtain.producer import ObtainMethod, Producer, ProducerInput, ProducerOutput

__all__ = [
    "COOKING_STATIONS",
    "NAMESPACE",
    "RECIPE_DIRECTORY",
    "SMITHING_TRANSFORM_TYPE",
    "STONECUTTING_TYPE",
    "RecipeExtractionResult",
    "SkippedRecipe",
    "extract_recipes",
]

RECIPE_DIRECTORY = "recipe"
NAMESPACE = "minecraft"

_CRAFTING_SHAPED = "minecraft:crafting_shaped"
_CRAFTING_SHAPELESS = "minecraft:crafting_shapeless"
STONECUTTING_TYPE = "minecraft:stonecutting"
SMITHING_TRANSFORM_TYPE = "minecraft:smithing_transform"

# The four cooking recipe types, mapped to the station name a `Producer`
# carries. `ObtainMethod.SMELTING` is the method for all four; the station is
# what tells a furnace recipe from a campfire one.
COOKING_STATIONS: Mapping[str, str] = {
    "minecraft:smelting": "furnace",
    "minecraft:blasting": "blast_furnace",
    "minecraft:smoking": "smoker",
    "minecraft:campfire_cooking": "campfire",
}

# Recipe types this module knows by name and skips outright, never raising on
# them. See the module docstring for what each one is and why guessing its
# shape would be worse than reporting it.
_SPECIAL_CRAFTING_PREFIX = "minecraft:crafting_special_"
_NAMED_SKIPS = frozenset({"minecraft:crafting_transmute"})

# A JSON pattern row's empty cell.
_EMPTY_CELL = " "


class SkippedRecipe(BaseModel, frozen=True):
    """One recipe file this module read and did not turn into a producer, and why."""

    recipe_id: str
    recipe_type: str
    reason: str


class RecipeExtractionResult(BaseModel, frozen=True):
    """Every producer `extract_recipes` built, and the recipes it skipped."""

    producers: tuple[Producer, ...]
    skipped: tuple[SkippedRecipe, ...]


def _namespaced(value: str) -> str:
    """Return `value` with the default namespace, when it carries none."""
    return value if ":" in value else f"{NAMESPACE}:{value}"


def _resolve_ingredient(
    value: Any, *, tags: TagIndex, source: str, is_dye: bool = False
) -> ProducerInput:
    """Return `value` as a `ProducerInput`, or raise `ObtainError`.

    `value` is one of the three shapes the module docstring names: a plain
    id, a `#tag`, or a list of either. A list that mixes a `#tag` reference
    with plain items is not a shape this module has ever observed live, and
    it raises rather than guessing which of the two rules should apply.

    When `is_dye` is true, an untagged list of colored variants resolves
    only to the white variant as a single non-cycling input, rather than
    cycling through all colored alternatives.
    """
    if isinstance(value, str):
        if value.startswith("#"):
            tag_id = value[1:]
            members = tuple(sorted(tags.resolve(tag_id)))
            return ProducerInput(tag=_namespaced(tag_id), members=members)
        return ProducerInput(item=_namespaced(value))
    if isinstance(value, list) and value and all(isinstance(entry, str) for entry in value):
        if any(entry.startswith("#") for entry in value):
            raise ObtainError(
                f"{source} names an ingredient list that mixes a #tag with plain items: "
                f"{value!r}. This module has not observed that shape live and will not guess "
                f"how to resolve it."
            )
        namespaced = sorted({_namespaced(entry) for entry in value})
        if is_dye:
            white_item = next(
                (entry for entry in namespaced if entry.split(":")[-1].startswith("white_")),
                None,
            )
            if white_item is not None:
                return ProducerInput(item=white_item)
        return ProducerInput(item=namespaced[0], members=tuple(namespaced))
    raise ObtainError(
        f"{source} names an ingredient of {value!r}, which is not a resolvable shape."
    )


def _result(document: Mapping[str, Any], *, source: str) -> ProducerOutput:
    """Return the `result` of one recipe as a `ProducerOutput`, or raise `ObtainError`."""
    result = document.get("result")
    if not isinstance(result, Mapping):
        raise ObtainError(f"{source} carries a result of {result!r}, not an object.")
    item = result.get("id")
    if not isinstance(item, str) or not item:
        raise ObtainError(f"{source} carries a result with no 'id': {dict(result)!r}.")
    count = result.get("count", 1)
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise ObtainError(f"{source} carries a result count of {count!r}, not a positive integer.")
    return ProducerOutput(item=_namespaced(item), count=count)


def _crafting_shaped(
    document: Mapping[str, Any], *, recipe_id: str, tags: TagIndex, source: str
) -> Producer:
    key = document.get("key")
    pattern = document.get("pattern")
    if not isinstance(key, Mapping) or not key:
        raise ObtainError(f"{source} carries a key of {key!r}, not a non-empty object.")
    if not isinstance(pattern, list) or not pattern or not all(isinstance(r, str) for r in pattern):
        raise ObtainError(f"{source} carries a pattern of {pattern!r}, not a list of rows.")

    counts: dict[str, int] = {}
    for row in pattern:
        for symbol in row:
            if symbol == _EMPTY_CELL:
                continue
            if symbol not in key:
                raise ObtainError(
                    f"{source} carries the pattern symbol {symbol!r}, which its key does not "
                    f"define."
                )
            counts[symbol] = counts.get(symbol, 0) + 1

    sorted_symbols = sorted(counts)
    symbol_to_input_idx = {sym: idx for idx, sym in enumerate(sorted_symbols)}

    inputs = tuple(
        _resolve_ingredient(key[symbol], tags=tags, source=source).model_copy(
            update={"count": counts[symbol]}
        )
        for symbol in sorted_symbols
    )

    grid_height = len(pattern)
    grid_width = max(len(row) for row in pattern) if pattern else 0
    grid_cells: list[int | None] = []
    for row in pattern:
        for col_idx in range(grid_width):
            symbol = row[col_idx] if col_idx < len(row) else _EMPTY_CELL
            if symbol == _EMPTY_CELL:
                grid_cells.append(None)
            else:
                grid_cells.append(symbol_to_input_idx[symbol])

    return Producer(
        method=ObtainMethod.CRAFTING,
        output=_result(document, source=source),
        inputs=inputs,
        source_id=recipe_id,
        grid=tuple(grid_cells),
        grid_width=grid_width,
        grid_height=grid_height,
    )


def _crafting_shapeless(
    document: Mapping[str, Any], *, recipe_id: str, tags: TagIndex, source: str
) -> Producer:
    ingredients = document.get("ingredients")
    if not isinstance(ingredients, list) or not ingredients:
        raise ObtainError(f"{source} carries ingredients of {ingredients!r}, not a non-empty list.")

    is_dye = recipe_id.startswith("minecraft:dye_") or recipe_id.startswith("dye_")
    resolved = [
        _resolve_ingredient(entry, tags=tags, source=source, is_dye=is_dye)
        for entry in ingredients
    ]
    aggregated: dict[tuple[str | None, str | None], ProducerInput] = {}
    order: list[tuple[str | None, str | None]] = []
    for entry in resolved:
        key = (entry.item, entry.tag)
        if key in aggregated:
            aggregated[key] = aggregated[key].model_copy(
                update={"count": aggregated[key].count + entry.count}
            )
        else:
            aggregated[key] = entry
            order.append(key)

    return Producer(
        method=ObtainMethod.CRAFTING,
        output=_result(document, source=source),
        inputs=tuple(aggregated[key] for key in order),
        source_id=recipe_id,
    )


def _single_ingredient(
    document: Mapping[str, Any],
    *,
    method: ObtainMethod,
    station: str,
    recipe_id: str,
    tags: TagIndex,
    source: str,
) -> Producer:
    ingredient = document.get("ingredient")
    if ingredient is None:
        raise ObtainError(f"{source} carries no 'ingredient'.")
    return Producer(
        method=method,
        output=_result(document, source=source),
        inputs=(_resolve_ingredient(ingredient, tags=tags, source=source),),
        source_id=recipe_id,
        station=station,
    )


def _smithing_transform(
    document: Mapping[str, Any], *, recipe_id: str, tags: TagIndex, source: str
) -> Producer:
    inputs: list[ProducerInput] = []
    for field in ("template", "base", "addition"):
        value = document.get(field)
        if value is None:
            raise ObtainError(f"{source} carries no {field!r}.")
        inputs.append(_resolve_ingredient(value, tags=tags, source=source))
    return Producer(
        method=ObtainMethod.CRAFTING,
        output=_result(document, source=source),
        inputs=tuple(inputs),
        source_id=recipe_id,
        station="smithing_table",
    )


def extract_recipes(files: Mapping[str, bytes], *, tags: TagIndex) -> RecipeExtractionResult:
    """Return every `Producer` that `files`'s `recipe/*.json` entries describe.

    `files` is the answer of `pipeline.fetch.mcmeta.fetch_data_files`, keyed
    by the path under `data/minecraft/`. Only entries under `recipe/` are
    read; everything else is ignored, exactly as `pipeline.extract.harvest`
    ignores every file outside the seven tags it reads. `tags` resolves a
    `#tag` ingredient against the `item` registry -- build it with
    `TagIndex(files, registry="item")`.

    Raises `ObtainError` when a recipe file this module recognizes by `type`
    is malformed for that type. Raises `ObtainError` when no `recipe/` file
    is found at all, matching every other Tier A stage's rule that an empty
    read is a broken scrape, not a version of Minecraft with no recipes.
    """
    entries = {
        key: payload for key, payload in files.items() if key.startswith(f"{RECIPE_DIRECTORY}/")
    }
    if not entries:
        raise ObtainError(
            f"no file under {RECIPE_DIRECTORY!r} was found. An empty read is a broken scrape, "
            f"not a version of Minecraft with no recipes."
        )

    producers: list[Producer] = []
    skipped: list[SkippedRecipe] = []
    for key in sorted(entries):
        payload = entries[key]
        recipe_path = key[len(RECIPE_DIRECTORY) + 1 : -len(".json")]
        recipe_id = _namespaced(recipe_path)
        source = f"recipe {key!r}"

        try:
            document: Any = json.loads(payload)
        except (ValueError, TypeError) as error:
            raise ObtainError(f"{source} is not JSON: {error}") from error
        if not isinstance(document, Mapping):
            raise ObtainError(f"{source} is not a JSON object.")

        recipe_type = document.get("type")
        if not isinstance(recipe_type, str):
            raise ObtainError(f"{source} carries no 'type'.")

        if recipe_path.startswith("dye_white_") or recipe_id.startswith("minecraft:dye_white_"):
            skipped.append(
                SkippedRecipe(
                    recipe_id=recipe_id,
                    recipe_type=recipe_type,
                    reason=(
                        "white dyeing recipes bleach colored items; white items are crafted from "
                        "base materials"
                    ),
                )
            )
            continue

        if recipe_type.startswith(_SPECIAL_CRAFTING_PREFIX):
            skipped.append(
                SkippedRecipe(
                    recipe_id=recipe_id,
                    recipe_type=recipe_type,
                    reason="a crafting_special_* recipe declares no ingredient list",
                )
            )
            continue
        if recipe_type in _NAMED_SKIPS:
            skipped.append(
                SkippedRecipe(
                    recipe_id=recipe_id,
                    recipe_type=recipe_type,
                    reason="this recipe type carries no representable ingredient-to-item shape",
                )
            )
            continue

        if recipe_type == _CRAFTING_SHAPED:
            producers.append(
                _crafting_shaped(document, recipe_id=recipe_id, tags=tags, source=source)
            )
        elif recipe_type == _CRAFTING_SHAPELESS:
            producers.append(
                _crafting_shapeless(document, recipe_id=recipe_id, tags=tags, source=source)
            )
        elif recipe_type in COOKING_STATIONS:
            producers.append(
                _single_ingredient(
                    document,
                    method=ObtainMethod.SMELTING,
                    station=COOKING_STATIONS[recipe_type],
                    recipe_id=recipe_id,
                    tags=tags,
                    source=source,
                )
            )
        elif recipe_type == STONECUTTING_TYPE:
            producers.append(
                _single_ingredient(
                    document,
                    method=ObtainMethod.CRAFTING,
                    station="stonecutter",
                    recipe_id=recipe_id,
                    tags=tags,
                    source=source,
                )
            )
        elif recipe_type == SMITHING_TRANSFORM_TYPE:
            producers.append(
                _smithing_transform(document, recipe_id=recipe_id, tags=tags, source=source)
            )
        else:
            skipped.append(
                SkippedRecipe(
                    recipe_id=recipe_id,
                    recipe_type=recipe_type,
                    reason="unhandled recipe type",
                )
            )

    return RecipeExtractionResult(producers=tuple(producers), skipped=tuple(skipped))
