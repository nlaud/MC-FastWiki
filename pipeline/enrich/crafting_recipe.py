"""Wiki crafting recipes, parsed into a grid that Tier A recipes can be compared with.

**This is a cross-check, not a source.** Decision 6 of TODO.md says why: the wiki
collapses variants, so one row covers all thirteen wood types as `Matching
Wooden Stairs`, and expanding that back into exact per-item recipes is guesswork.
mcmeta gives exact per-item recipes for free. So the recipes a page renders come
from Tier A, and these exist to catch a Tier A read that went wrong -- a recipe
mcmeta has and the wiki does not, or a shape the two disagree on.

That is also why this module does not try as hard as the others to be complete.
It reports what it cannot read and moves on, because a row it fails on costs a
comparison, not an answer.

Four things about the row format, all of them checked against the live bucket on
2026-08-27.

**The slot key is column then row, and the row digit counts downward.** `A1` is
top-left and `C3` is bottom-right. This is not guessable and getting it backwards
would silently transpose every asymmetric recipe, so it was pinned against two
recipes whose shape is known: the wooden pickaxe has planks in `A1`, `B1`, `C1`
and sticks in `B2`, `B3`, which is planks across the top and sticks down the
middle; the torch has coal in `B2` and a stick in `B3`, which is coal above
stick. Letters are columns left to right, digits are rows top to bottom.

**One row can hold several recipes, packed positionally with semicolons.** The
map-cloning row holds eight: `Output` is `Map, 2; Map BE, 3; ...` and each slot
holds eight `;`-separated values in the same order, with an empty part where
that variant leaves the slot empty. A value with exactly one part applies to
every variant -- the torch's `Output` is one value against two coal variants. A
value with some other number of parts is a row this module cannot align, so it
is reported rather than guessed at: nine of 640 rows are in that state, and
guessing would attach the wrong ingredient to a real recipe. 568 rows hold a
single recipe and never take this path at all.

**An output is a name, an optional count after a comma, and an optional
bracketed annotation.** `Torch, 4`, `Matching Wooden Fence,3` with no space, and
`Written Book,2[&7by Steve/Copy of a copy]`.

**Bedrock recipes are in here and are marked only in prose.** There is no
edition column and no edition field. The wiki renders `{{IN|BE}}` into a
`title="This statement only applies to Bedrock Edition"` span inside
`description`, and 39 rows carry it -- glow sticks, balloons, and the rest of
the Bedrock and Education content. Those rows are dropped and reported. A second
mark catches what the first misses: where one row packs a Java variant and a
Bedrock one together, the wiki distinguishes the outputs by name, as `Map` and
`Map BE`. Any variant whose output ends in ` BE` goes the same way.

Both are text matches, so both are heuristics, and they are only tolerable
because of what this data is for: nothing here is rendered, so a Bedrock row that
slipped through would produce a spurious cross-check mismatch rather than a wrong
number on the screen. Tier A remains the authority on what recipes Java has.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, model_validator

from pipeline.enrich import (
    EnrichError,
    SkippedRow,
    clean_text,
    group_by,
    main_namespace,
    optional_text,
    row_json,
    row_page_name,
    wiki_url,
)
from pipeline.fetch import Transport
from pipeline.fetch.bucket import fetch_bucket_rows
from pipeline.fetch.cache import ContentCache

__all__ = [
    "ANY_PREFIX",
    "BEDROCK_ONLY",
    "BEDROCK_OUTPUT_SUFFIX",
    "BUCKET",
    "COLUMNS",
    "GRID_COLUMNS",
    "GRID_ROWS",
    "MATCHING_PREFIX",
    "SLOT_KEYS",
    "VARIANT_SEPARATOR",
    "CraftingOutput",
    "RecipeIndex",
    "WikiCraftingRecipe",
    "fetch_crafting_recipes",
    "parse_crafting_recipes",
    "parse_output",
]

BUCKET = "crafting_recipe"

COLUMNS = ("page_name", "type", "json")

# The grid, in the wiki's own key order: a column letter then a row digit.
GRID_COLUMNS = ("A", "B", "C")
GRID_ROWS = ("1", "2", "3")

# Every slot key, in reading order: A1 B1 C1 / A2 B2 C2 / A3 B3 C3.
SLOT_KEYS = tuple(f"{column}{row}" for row in GRID_ROWS for column in GRID_COLUMNS)

# The key that holds the crafted item, and what separates packed variants.
OUTPUT_KEY = "Output"
VARIANT_SEPARATOR = ";"

# The two prefixes the wiki uses for a collapsed variant group. `Matching Planks`
# means "the plank that matches the output", `Any Shulker Box` means any of them.
# A recipe carrying either cannot be compared one-to-one with a Tier A recipe,
# which is what `is_collapsed` is for.
MATCHING_PREFIX = "Matching "
ANY_PREFIX = "Any "

# How the wiki's `{{IN|BE}}` template renders once expanded. The module docstring
# holds the caveat about matching on prose.
BEDROCK_ONLY = re.compile(
    r"only applies to \[*Bedrock Edition|applies only to \[*Bedrock", re.IGNORECASE
)

# How the wiki names a Bedrock output inside a row it shares with Java: `Map BE`
# beside `Map`. The row itself carries no Bedrock mark, so this is the only
# thing separating the two variants.
BEDROCK_OUTPUT_SUFFIX = " BE"

# An output: a name, an optional `, count`, and an optional `[annotation]`.
OUTPUT = re.compile(
    r"(?P<item>.+?)"
    r"(?:\s*,\s*(?P<count>\d+))?"
    r"(?:\s*\[(?P<annotation>[^\]]*)\])?"
    r"\Z"
)


class CraftingOutput(BaseModel, frozen=True):
    """What one recipe produces."""

    item: str
    count: int = 1
    # The bracketed aside the wiki attaches to a few outputs, such as the
    # authorship note on a copied written book. Kept rather than discarded
    # because it is the only thing separating two otherwise identical rows.
    annotation: str | None = None


class WikiCraftingRecipe(BaseModel, frozen=True):
    """One crafting recipe as the wiki records it, on a three-by-three grid."""

    page: str
    wiki_url: str
    # The wiki's label for the recipe when a page holds several, as wikitext:
    # `[[Map]]<br>(cloned)`. Absent on most rows.
    name: str | None
    # The wiki's own category: `Building block`, `Redstone`, `Miscellaneous`.
    category: str | None
    description: str | None
    shapeless: bool
    # Which of the row's packed recipes this is, and how many it held. Both are
    # kept so a cross-check can say "variant 3 of 8 of the Map row" rather than
    # naming a row that holds eight different things.
    variant: int
    variants: int
    output: CraftingOutput
    # Three rows of three cells, top to bottom and left to right. `None` is an
    # empty slot.
    grid: tuple[
        tuple[str | None, str | None, str | None],
        tuple[str | None, str | None, str | None],
        tuple[str | None, str | None, str | None],
    ]

    @property
    def ingredients(self) -> tuple[str, ...]:
        """Return the distinct occupied cells, sorted.

        The comparable form for a shapeless recipe, where position carries no
        meaning, and the first thing to compare for a shaped one.
        """
        return tuple(sorted({cell for row in self.grid for cell in row if cell is not None}))

    @property
    def trimmed_grid(self) -> tuple[tuple[str | None, ...], ...]:
        """Return the grid cropped to the smallest box that holds every cell.

        Tier A stores a recipe's pattern at its natural size -- a torch is two
        rows of one column -- while the wiki always writes into the same
        three-by-three frame, so the two only line up after the empty border is
        removed. An empty recipe trims to an empty tuple.
        """
        occupied = [
            (row_index, column_index)
            for row_index, row in enumerate(self.grid)
            for column_index, cell in enumerate(row)
            if cell is not None
        ]
        if not occupied:
            return ()
        first_row = min(row for row, _ in occupied)
        last_row = max(row for row, _ in occupied)
        first_column = min(column for _, column in occupied)
        last_column = max(column for _, column in occupied)
        return tuple(
            tuple(row[first_column : last_column + 1])
            for row in self.grid[first_row : last_row + 1]
        )

    @property
    def is_collapsed(self) -> bool:
        """Return whether this recipe stands for a family rather than one item.

        True when any cell or the output starts with `Matching ` or `Any `. Such
        a recipe has no single Tier A counterpart -- `Matching Wooden Fence`
        covers thirteen of them -- so a cross-check must group rather than
        compare.
        """
        names = [cell for row in self.grid for cell in row if cell is not None]
        names.append(self.output.item)
        return any(
            name.startswith(MATCHING_PREFIX) or name.startswith(ANY_PREFIX) for name in names
        )


class RecipeIndex(BaseModel, frozen=True):
    """Every wiki crafting recipe that parsed, indexed by output item."""

    recipes: tuple[WikiCraftingRecipe, ...]
    by_output: Mapping[str, tuple[WikiCraftingRecipe, ...]]
    skipped: tuple[SkippedRow, ...] = ()

    @classmethod
    def build(
        cls, recipes: Sequence[WikiCraftingRecipe], skipped: Sequence[SkippedRow] = ()
    ) -> "RecipeIndex":
        """Return an index over `recipes`, with the output lookup computed."""
        return cls(
            recipes=tuple(recipes),
            by_output=group_by(recipes, lambda recipe: recipe.output.item),
            skipped=tuple(skipped),
        )

    @model_validator(mode="after")
    def _index_must_match_the_recipes(self) -> "RecipeIndex":
        """Refuse an index that does not index its own recipes."""
        if dict(self.by_output) != group_by(self.recipes, lambda recipe: recipe.output.item):
            raise EnrichError("the output index does not match the recipes of this table.")
        return self


def parse_output(text: str, *, source: str) -> CraftingOutput:
    """Return the item, count, and annotation that `text` describes.

    `Torch, 4` and `Matching Wooden Fence,3` both give a count; a bare name
    gives one. `Written Book,2[&7by Steve/Copy of a copy]` gives all three.
    """
    match = OUTPUT.fullmatch(text.strip())
    if match is None or not match["item"].strip():
        raise EnrichError(f"{source} answered an output of {text!r}.")
    annotation = match["annotation"]
    return CraftingOutput(
        item=clean_text(match["item"]),
        count=int(match["count"]) if match["count"] is not None else 1,
        annotation=clean_text(annotation) if annotation else None,
    )


def _split_variants(value: str) -> list[str]:
    """Return the semicolon-separated parts of one packed field, edges trimmed."""
    return [clean_text(part) for part in value.split(VARIANT_SEPARATOR)]


def _variant_count(fields: Mapping[str, list[str]], *, page: str) -> int:
    """Return how many recipes the row packs, or raise `EnrichError`.

    The count is the longest field. Every other field must hold either that many
    parts or exactly one, which applies to all of them. Anything between is a
    row whose columns do not line up, and the caller turns that into a skip.
    """
    count = max(len(parts) for parts in fields.values())
    ragged = {key: len(parts) for key, parts in fields.items() if len(parts) not in {1, count}}
    if ragged:
        listed = ", ".join(f"{key}={length}" for key, length in sorted(ragged.items()))
        raise EnrichError(
            f"{page} packs {count} recipes but {listed}, so its variants do not line up."
        )
    return count


def _cell(fields: Mapping[str, list[str]], slot: str, variant: int) -> str | None:
    """Return the value of `slot` for one variant, or `None` when it is empty.

    A field the row does not carry is an empty slot. A field with a single part
    holds that part for every variant; see the module docstring.
    """
    parts = fields.get(slot)
    if parts is None:
        return None
    value = parts[0] if len(parts) == 1 else parts[variant]
    return value or None


def _grid_row(
    fields: Mapping[str, list[str]], row: str, variant: int
) -> tuple[str | None, str | None, str | None]:
    """Return one row of the grid, left to right.

    Written out rather than built by comprehension so the three-cell shape is
    the declared type of the result and not a runtime hope.
    """
    return (
        _cell(fields, f"A{row}", variant),
        _cell(fields, f"B{row}", variant),
        _cell(fields, f"C{row}", variant),
    )


def parse_crafting_recipes(
    rows: Sequence[Mapping[str, Any]], *, source: str = BUCKET
) -> RecipeIndex:
    """Return the wiki's crafting recipes, and a report of what was dropped.

    Pure. A row is dropped, with a reason, when it is outside the main
    namespace, when its description marks it Bedrock- or Education-only, when it
    names no output, and when its packed variants do not line up. None of those
    raises: this table is a cross-check, so losing a row costs a comparison and
    the report says which one.
    """
    kept, skipped = main_namespace(rows, source=source)
    recipes: list[WikiCraftingRecipe] = []
    for row in kept:
        page = row_page_name(row, source=source)
        document = row_json(row, source=source)
        description = optional_text(document, "description")
        if description is not None and BEDROCK_ONLY.search(description):
            skipped.append(
                SkippedRow(
                    page=page,
                    subject=optional_text(document, OUTPUT_KEY),
                    reason="the description marks this recipe Bedrock Edition only",
                )
            )
            continue
        raw_output = optional_text(document, OUTPUT_KEY)
        if raw_output is None:
            skipped.append(SkippedRow(page=page, subject=None, reason="the row names no output"))
            continue

        fields = {OUTPUT_KEY: _split_variants(raw_output)}
        for key in SLOT_KEYS:
            value = document.get(key)
            if isinstance(value, str):
                fields[key] = _split_variants(value)
        try:
            count = _variant_count(fields, page=page)
        except EnrichError as error:
            skipped.append(SkippedRow(page=page, subject=raw_output, reason=str(error)))
            continue

        name = optional_text(document, "name")
        category = optional_text(document, "type")
        # `shapeless` arrives as the integer 1, the string "1", and the string
        # "true" across the live table. Its presence is the signal; only an
        # explicit falsehood turns it off.
        raw_shapeless = document.get("shapeless")
        shapeless = raw_shapeless is not None and str(raw_shapeless).lower() not in {
            "0",
            "false",
            "",
        }

        for variant in range(count):
            output_parts = fields[OUTPUT_KEY]
            output_text = output_parts[0] if len(output_parts) == 1 else output_parts[variant]
            if not output_text:
                skipped.append(
                    SkippedRow(
                        page=page,
                        subject=raw_output,
                        reason=f"variant {variant + 1} of {count} names no output",
                    )
                )
                continue
            output = parse_output(output_text, source=f"{source} row {page}")
            if output.item.endswith(BEDROCK_OUTPUT_SUFFIX):
                skipped.append(
                    SkippedRow(
                        page=page,
                        subject=output.item,
                        reason="the output is named as the Bedrock Edition variant",
                    )
                )
                continue
            recipes.append(
                WikiCraftingRecipe(
                    page=page,
                    wiki_url=wiki_url(page),
                    name=name,
                    category=category,
                    description=description,
                    shapeless=shapeless,
                    variant=variant,
                    variants=count,
                    output=output,
                    grid=(
                        _grid_row(fields, "1", variant),
                        _grid_row(fields, "2", variant),
                        _grid_row(fields, "3", variant),
                    ),
                )
            )
    return RecipeIndex.build(recipes, skipped)


def fetch_crafting_recipes(
    *,
    revision: str,
    cache: ContentCache | None = None,
    transport: Transport | None = None,
) -> RecipeIndex:
    """Fetch the `crafting_recipe` bucket and return its recipes.

    No `where` clause: the bucket has no edition column, so the Bedrock rows can
    only be found once the descriptions are in hand.
    """
    rows = fetch_bucket_rows(
        BUCKET,
        COLUMNS,
        revision=revision,
        cache=cache,
        transport=transport,
    )
    return parse_crafting_recipes(rows)
