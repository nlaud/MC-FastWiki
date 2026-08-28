"""Crafting recipes: the grid orientation, the packed variants, and what is dropped.

`pipeline.enrich.crafting_recipe` is a cross-check against Tier A rather than a
source, so its failures cost a comparison and not an answer. That is why almost
everything here is skipped-and-reported rather than raised.

The grid orientation is the exception. Getting it backwards would transpose
every asymmetric recipe silently, so the two tests that pin it use recipes whose
shape is known from the game.

`parse_crafting_recipes` is pure, so nothing here opens a socket.
"""

import json
from typing import Any

import pytest

from pipeline.enrich import EnrichError
from pipeline.enrich.crafting_recipe import (
    RecipeIndex,
    parse_crafting_recipes,
    parse_output,
)

SOURCE = "test"


def row(page: str, output: str, slots: dict[str, str], **extra: Any) -> dict[str, Any]:
    """Return one `crafting_recipe` row, shaped the way the live API sends it."""
    document: dict[str, Any] = {"Output": output, "description": "", **slots, **extra}
    return {"page_name": page, "type": document.get("type"), "json": json.dumps(document)}


def test_the_grid_is_column_letter_then_row_digit() -> None:
    """A wooden pickaxe is planks across the top and sticks down the middle.

    This is the test that pins the orientation. `A1`, `B1`, `C1` hold the planks
    and `B2`, `B3` hold the sticks, so letters are columns left to right and
    digits are rows top to bottom. Read the other way the recipe would come out
    transposed, and every asymmetric recipe with it.
    """
    index = parse_crafting_recipes(
        [
            row(
                "Wooden Pickaxe",
                "Wooden Pickaxe",
                {
                    "A1": "Any Planks",
                    "B1": "Any Planks",
                    "C1": "Any Planks",
                    "B2": "Stick",
                    "B3": "Stick",
                },
            )
        ]
    )

    assert index.recipes[0].grid == (
        ("Any Planks", "Any Planks", "Any Planks"),
        (None, "Stick", None),
        (None, "Stick", None),
    )


def test_the_row_digit_counts_downward() -> None:
    """A torch is coal above a stick, and the coal is in `B2`, not `B3`."""
    index = parse_crafting_recipes(
        [row("Torch", "Torch, 4", {"B2": "Coal", "B3": "Stick"})]
    )

    assert index.recipes[0].trimmed_grid == (("Coal",), ("Stick",))


def test_the_grid_trims_to_the_size_tier_a_stores() -> None:
    """Tier A stores a torch as two rows of one column; the wiki always writes 3x3."""
    index = parse_crafting_recipes(
        [row("Bread", "Bread", {"A2": "Wheat", "B2": "Wheat", "C2": "Wheat"})]
    )

    assert index.recipes[0].trimmed_grid == (("Wheat", "Wheat", "Wheat"),)


def test_one_row_can_pack_several_recipes() -> None:
    """The torch row holds coal and charcoal in the same slot, separated by a semicolon.

    The output is a single value against two variants, which means it applies to
    both. 72 of the 640 live rows pack more than one recipe this way.
    """
    index = parse_crafting_recipes(
        [row("Torch", "Torch, 4", {"B2": "Coal; Charcoal", "B3": "Stick"})]
    )

    assert [recipe.grid[1][1] for recipe in index.recipes] == ["Coal", "Charcoal"]
    assert [recipe.variant for recipe in index.recipes] == [0, 1]
    assert {recipe.variants for recipe in index.recipes} == {2}
    assert {recipe.output.count for recipe in index.recipes} == {4}


def test_an_empty_part_of_a_packed_slot_is_an_empty_slot() -> None:
    """Positional packing means a missing ingredient is written as nothing at all."""
    index = parse_crafting_recipes(
        [row("Map", "Map; Locator Map", {"B2": "Empty Map", "C3": ";Compass"})]
    )

    assert index.recipes[0].grid[2][2] is None
    assert index.recipes[1].grid[2][2] == "Compass"


def test_a_row_whose_variants_do_not_line_up_is_skipped_and_reported() -> None:
    """Nine live rows are in this state, and guessing would attach a wrong ingredient.

    A field holds either one value for all variants or exactly as many as there
    are. Four against eight is neither.
    """
    index = parse_crafting_recipes(
        [row("Map", "a; b; c; d", {"A2": "one; two", "B2": "x"})]
    )

    assert index.recipes == ()
    assert "do not line up" in index.skipped[0].reason


def test_a_bedrock_only_recipe_is_skipped_and_reported() -> None:
    """The bucket has no edition column; the wiki marks it in rendered prose only.

    This is a text match and so a heuristic, which is tolerable only because
    nothing from this module is rendered. A row that slipped through would cause
    a spurious cross-check mismatch, not a wrong number on the screen.
    """
    index = parse_crafting_recipes(
        [
            row(
                "Glow Stick",
                "White Glow Stick",
                {"B3": "Luminol"},
                description=(
                    '<span title="This statement only applies to Bedrock Edition and '
                    'Minecraft Education">Bedrock Edition only</span>'
                ),
            )
        ]
    )

    assert index.recipes == ()
    assert "Bedrock Edition only" in index.skipped[0].reason


def test_a_bedrock_variant_inside_a_shared_row_is_skipped_by_its_output_name() -> None:
    """The map row packs Java and Bedrock together and marks neither in prose.

    The only thing separating them is the output name: `Map` against `Map BE`.
    Without this the Bedrock variant reaches the cross-check as a Java recipe
    the vanilla data does not have.
    """
    index = parse_crafting_recipes(
        [row("Map", "Map; Map BE; Locator Map", {"B2": "Empty Map"})]
    )

    assert [recipe.output.item for recipe in index.recipes] == ["Map", "Locator Map"]
    assert index.skipped[0].reason == "the output is named as the Bedrock Edition variant"


def test_a_collapsed_variant_group_is_flagged_rather_than_expanded() -> None:
    """`Matching Planks` covers thirteen woods, so it has no single Tier A counterpart.

    Decision 9 of TODO.md keeps the display collapsed on purpose. The
    cross-check has to know it cannot compare such a row one to one.
    """
    index = parse_crafting_recipes(
        [
            row(
                "Wooden Fence",
                "Matching Wooden Fence,3",
                {"A2": "Matching Planks", "B2": "Stick", "C2": "Matching Planks"},
            )
        ]
    )

    recipe = index.recipes[0]
    assert recipe.is_collapsed
    assert recipe.output.item == "Matching Wooden Fence"
    assert recipe.output.count == 3


def test_a_plain_recipe_is_not_flagged_as_collapsed() -> None:
    """Only `Matching ` and `Any ` mark a family."""
    index = parse_crafting_recipes([row("Bread", "Bread", {"A2": "Wheat"})])

    assert not index.recipes[0].is_collapsed


@pytest.mark.parametrize(
    ("text", "item", "count", "annotation"),
    [
        ("Torch, 4", "Torch", 4, None),
        ("Matching Wooden Fence,3", "Matching Wooden Fence", 3, None),
        ("Block of Gold", "Block of Gold", 1, None),
        ("Written Book,2[&7by Steve]", "Written Book", 2, "&7by Steve"),
    ],
)
def test_an_output_is_a_name_a_count_and_an_annotation(
    text: str, item: str, count: int, annotation: str | None
) -> None:
    """All four shapes appear in the live table, spacing included."""
    output = parse_output(text, source=SOURCE)

    assert (output.item, output.count, output.annotation) == (item, count, annotation)


def test_an_output_that_is_not_a_name_raises() -> None:
    """An output of nothing is not a recipe, and the caller turns it into a skip."""
    with pytest.raises(EnrichError):
        parse_output("  ", source=SOURCE)


@pytest.mark.parametrize("flag", [1, "1", "true"])
def test_every_spelling_of_shapeless_reads_as_shapeless(flag: object) -> None:
    """The live table carries all three, because wiki editors write it by hand."""
    index = parse_crafting_recipes([row("Sugar", "Sugar", {"B2": "Sugar Cane"}, shapeless=flag)])

    assert index.recipes[0].shapeless


def test_a_row_without_the_flag_is_shaped() -> None:
    """Absence is the common case: 529 of the 640 live rows."""
    index = parse_crafting_recipes([row("Bread", "Bread", {"A2": "Wheat"})])

    assert not index.recipes[0].shapeless


def test_the_ingredient_list_is_the_comparable_form() -> None:
    """Distinct and sorted, which is what a shapeless recipe can be compared on."""
    index = parse_crafting_recipes(
        [row("Bread", "Bread", {"A2": "Wheat", "B2": "Wheat", "C2": "Wheat"})]
    )

    assert index.recipes[0].ingredients == ("Wheat",)


def test_an_index_that_does_not_index_its_own_recipes_is_refused() -> None:
    """The lookup is a field on a frozen model, so it is checked, not trusted."""
    recipe = parse_crafting_recipes([row("Bread", "Bread", {"A2": "Wheat"})]).recipes[0]

    with pytest.raises(EnrichError, match="output index"):
        RecipeIndex(recipes=(recipe,), by_output={})
