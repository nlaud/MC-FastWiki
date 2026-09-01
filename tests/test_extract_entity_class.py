"""The `entity_type` classifier: the three clauses, the sheep collapse, and the empty-archive fault.

`classify_entity_types` is a pure function over a `fetch_data_files`-shaped
mapping of path to bytes plus the mcmeta `registries` payload, so every test
here builds both in memory and opens no socket. The bytes of a loot table
file are never read -- only the path -- so every fixture below uses an empty
payload, the same convention `tests/test_extract_advancement.py` uses for
`extract_advancement_ids`.
"""

import pytest

from pipeline.extract import ExtractError
from pipeline.extract.entity_class import EntityClass, classify_entity_types


def archive(*paths: str) -> dict[str, bytes]:
    """Return a `fetch_data_files`-shaped mapping over `paths`, with empty bytes."""
    return dict.fromkeys(paths, b"{}")


def registries(
    *, entity_type: tuple[str, ...], item: tuple[str, ...] = ()
) -> dict[str, tuple[str, ...]]:
    """Return a minimal registries payload naming only the two keys this module reads."""
    return {"entity_type": entity_type, "item": item}


# --- Clause 1: a spawn egg -------------------------------------------------------


def test_a_spawn_egg_classifies_as_spawn_egg_even_with_no_loot_table() -> None:
    """A spawn egg settles the question outright, with no loot table needed at all.

    Not realistic for the live game -- every mob with a spawn egg also has a
    loot table, per the module docstring's measured subset relationship --
    but the classifier itself must not depend on that fact holding, only on
    the spawn egg signal it is actually given.
    """
    result = classify_entity_types(
        archive("loot_table/entities/unrelated.json"),
        registries(entity_type=("creeper",), item=("creeper_spawn_egg",)),
    )
    assert result.by_path["creeper"] is EntityClass.SPAWN_EGG


def test_a_spawn_egg_wins_even_when_a_loot_table_also_exists() -> None:
    """Clause 1 is checked first, and a loot table alongside a spawn egg changes nothing."""
    result = classify_entity_types(
        archive("loot_table/entities/creeper.json"),
        registries(entity_type=("creeper",), item=("creeper_spawn_egg",)),
    )
    assert result.by_path["creeper"] is EntityClass.SPAWN_EGG


# --- Clause 2: a loot table but no spawn egg --------------------------------------


def test_a_loot_table_with_no_spawn_egg_is_undecided() -> None:
    result = classify_entity_types(
        archive("loot_table/entities/armor_stand.json"),
        registries(entity_type=("armor_stand",), item=("armor_stand",)),
    )
    assert result.by_path["armor_stand"] is EntityClass.LOOT_TABLE_ONLY


def test_the_wrong_spawn_egg_name_does_not_count() -> None:
    """`armor_stand` in the item registry is not `armor_stand_spawn_egg`.

    The signal is the exact suffixed name, not mere co-membership in `item`
    -- `armor_stand` genuinely has an item form (the item you place to spawn
    it), and that item form must not be mistaken for a spawn egg.
    """
    result = classify_entity_types(
        archive("loot_table/entities/armor_stand.json"),
        registries(entity_type=("armor_stand",), item=("armor_stand",)),
    )
    assert result.by_path["armor_stand"] is not EntityClass.SPAWN_EGG


# --- Clause 3: neither ------------------------------------------------------------


def test_neither_signal_classifies_as_neither() -> None:
    result = classify_entity_types(
        archive("loot_table/entities/creeper.json"),
        registries(entity_type=("arrow",), item=()),
    )
    assert result.by_path["arrow"] is EntityClass.NEITHER


def test_an_item_registry_membership_with_the_wrong_suffix_is_still_neither() -> None:
    """`arrow` sitting in `item` as plain `arrow` is not a spawn egg for it.

    Only the exact `<path>_spawn_egg` name counts -- see the module
    docstring's signal definition.
    """
    result = classify_entity_types(
        archive("loot_table/entities/creeper.json"),
        registries(entity_type=("arrow",), item=("arrow",)),
    )
    assert result.by_path["arrow"] is EntityClass.NEITHER


# --- The sheep variant collapse ----------------------------------------------------


def test_sheep_color_variants_collapse_onto_one_entity_type() -> None:
    """The seventeen files `sheep` owns must count as the one entity type `sheep`.

    Mirrors the shape the pinned `26.2` archive actually holds, which is the
    trap: `sheep` is not sixteen nested colour files, it is sixteen nested
    colour files *plus* a top-level `sheep.json` that is neither nested nor a
    colour. A reader that handles only one of the two shapes still collapses
    the other into a second, phantom entity type, so both appear here in the
    one test and the assertion is that the classifier knows of exactly one
    `sheep`.
    """
    colors = (
        "black",
        "blue",
        "brown",
        "cyan",
        "gray",
        "green",
        "light_blue",
        "light_gray",
        "lime",
        "magenta",
        "orange",
        "pink",
        "purple",
        "red",
        "white",
        "yellow",
    )
    assert len(colors) == 16
    files = archive(
        "loot_table/entities/sheep.json",
        *(f"loot_table/entities/sheep/{color}.json" for color in colors),
    )
    assert len(files) == 17
    result = classify_entity_types(files, registries(entity_type=("sheep",), item=()))
    assert result.by_path["sheep"] is EntityClass.LOOT_TABLE_ONLY
    assert set(result.by_path) == {"sheep"}


def test_a_top_level_file_and_a_nested_variant_are_read_the_same_way() -> None:
    """A plain `creeper.json` and a nested `sheep/black.json` both name their entity type.

    One trap this test closes: stripping `.json` only from the top-level
    shape and forgetting the nested shape has no suffix to strip would
    silently misclassify every variant-bearing entity type.
    """
    result = classify_entity_types(
        archive("loot_table/entities/creeper.json", "loot_table/entities/sheep/white.json"),
        registries(entity_type=("creeper", "sheep"), item=()),
    )
    assert result.by_path["creeper"] is EntityClass.LOOT_TABLE_ONLY
    assert result.by_path["sheep"] is EntityClass.LOOT_TABLE_ONLY


# --- The empty-archive fault --------------------------------------------------------


def test_an_archive_with_no_entity_loot_table_at_all_is_refused() -> None:
    with pytest.raises(ExtractError, match="broken fetch"):
        classify_entity_types(
            archive("loot_table/blocks/oak_log.json", "advancement/story/root.json"),
            registries(entity_type=("creeper",), item=()),
        )


def test_an_empty_mapping_is_refused() -> None:
    with pytest.raises(ExtractError, match="broken fetch"):
        classify_entity_types({}, registries(entity_type=("creeper",), item=()))


# --- Registries payload shape faults -------------------------------------------------


def test_a_missing_entity_type_registry_is_refused() -> None:
    with pytest.raises(ExtractError, match="entity_type"):
        classify_entity_types(
            archive("loot_table/entities/creeper.json"), {"item": ("creeper_spawn_egg",)}
        )


def test_a_missing_item_registry_is_refused() -> None:
    with pytest.raises(ExtractError, match="item"):
        classify_entity_types(
            archive("loot_table/entities/creeper.json"), {"entity_type": ("creeper",)}
        )


# --- Every entity_type path gets an answer ------------------------------------------


def test_every_entity_type_path_of_the_registry_gets_an_answer() -> None:
    """The answer must cover every path of `registries["entity_type"]`, not a subset."""
    result = classify_entity_types(
        archive("loot_table/entities/creeper.json"),
        registries(entity_type=("creeper", "arrow", "armor_stand"), item=("creeper_spawn_egg",)),
    )
    assert set(result.by_path) == {"creeper", "arrow", "armor_stand"}
