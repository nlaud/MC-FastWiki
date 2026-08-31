"""The Tier A advancement ID extractor: path parsing, and the `recipes/**` exclusion.

`extract_advancement_ids` is a pure function over the keys of the mapping that
`pipeline.fetch.mcmeta.fetch_data_files` returns, so every test here builds its
own file mapping in memory and opens no socket. The bytes are never read, so
every fixture below uses an empty payload.
"""

import pytest

from pipeline.extract import ExtractError
from pipeline.extract.advancement import extract_advancement_ids


def archive(*paths: str) -> dict[str, bytes]:
    """Return a `fetch_data_files`-shaped mapping over `paths`, with empty bytes."""
    return dict.fromkeys(paths, b"{}")


def test_a_story_advancement_becomes_its_tab_and_path() -> None:
    ids = extract_advancement_ids(archive("advancement/story/mine_stone.json"))
    assert ids == ("story/mine_stone",)


def test_every_tab_strips_the_directory_and_the_extension() -> None:
    ids = extract_advancement_ids(
        archive(
            "advancement/story/root.json",
            "advancement/nether/root.json",
            "advancement/end/root.json",
            "advancement/adventure/kill_a_mob.json",
            "advancement/husbandry/balanced_diet.json",
        )
    )
    assert ids == (
        "adventure/kill_a_mob",
        "end/root",
        "husbandry/balanced_diet",
        "nether/root",
        "story/root",
    )


def test_the_answer_is_sorted() -> None:
    ids = extract_advancement_ids(
        archive("advancement/story/root.json", "advancement/adventure/kill_a_mob.json")
    )
    assert ids == ("adventure/kill_a_mob", "story/root")


def test_a_recipe_unlock_advancement_is_excluded() -> None:
    """`advancement/recipes/**` is bookkeeping, not a player-facing advancement.

    The module docstring gives the reason: the wiki's `Advancement` page never
    documents these, so counting them would manufacture a wiki join gap that
    can never close rather than report a real one.
    """
    ids = extract_advancement_ids(
        archive(
            "advancement/story/mine_stone.json",
            "advancement/recipes/misc/iron_pickaxe_from_planks_and_sticks.json",
            "advancement/recipes/building_blocks/acacia_planks.json",
        )
    )
    assert ids == ("story/mine_stone",)


def test_a_file_outside_the_advancement_directory_is_ignored() -> None:
    """Only `advancement/` is this module's concern; `recipe/` and `tags/` are Tier A too,
    but they belong to other stages of the pipeline.
    """
    ids = extract_advancement_ids(
        archive(
            "advancement/story/root.json",
            "recipe/oak_stairs.json",
            "tags/block/mineable/pickaxe.json",
        )
    )
    assert ids == ("story/root",)


def test_a_file_with_no_json_extension_is_ignored() -> None:
    ids = extract_advancement_ids(
        archive("advancement/story/root.json", "advancement/story/root.json.bak")
    )
    assert ids == ("story/root",)


def test_an_empty_mapping_is_refused() -> None:
    with pytest.raises(ExtractError, match="broken fetch"):
        extract_advancement_ids({})


def test_a_mapping_of_only_recipe_advancements_is_refused() -> None:
    """Excluding `recipes/**` must not turn a fetch of only that subtree into a silent
    empty answer -- it is still reported as the broken read it is.
    """
    with pytest.raises(ExtractError, match="broken fetch"):
        extract_advancement_ids(
            archive("advancement/recipes/misc/iron_pickaxe_from_planks_and_sticks.json")
        )


def test_a_mapping_with_no_advancement_files_at_all_is_refused() -> None:
    with pytest.raises(ExtractError, match="broken fetch"):
        extract_advancement_ids(archive("recipe/oak_stairs.json", "tags/block/planks.json"))
