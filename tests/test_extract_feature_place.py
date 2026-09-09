"""Tests for `pipeline.extract.feature_place`: places the game files as a feature."""

import json

import pytest

from pipeline.extract import ExtractError
from pipeline.extract.feature_place import extract_feature_places, load_feature_places


def _files(**overrides: object) -> dict[str, bytes]:
    """Return a minimal worldgen pack holding a two-pass overworld feature."""
    files: dict[str, bytes] = {
        "worldgen/configured_feature/monster_room.json": json.dumps(
            {"type": "minecraft:monster_room", "config": {}}
        ).encode(),
        "worldgen/placed_feature/monster_room.json": json.dumps(
            {
                "feature": "minecraft:monster_room",
                "placement": [
                    {"type": "minecraft:count", "count": 10},
                    {
                        "type": "minecraft:height_range",
                        "height": {
                            "type": "minecraft:uniform",
                            "min_inclusive": {"absolute": 0},
                            "max_inclusive": {"below_top": 0},
                        },
                    },
                ],
            }
        ).encode(),
        "worldgen/placed_feature/monster_room_deep.json": json.dumps(
            {
                "feature": "minecraft:monster_room",
                "placement": [
                    {"type": "minecraft:count", "count": 4},
                    {
                        "type": "minecraft:height_range",
                        "height": {
                            "type": "minecraft:uniform",
                            "min_inclusive": {"above_bottom": 6},
                            "max_inclusive": {"absolute": -1},
                        },
                    },
                ],
            }
        ).encode(),
        "worldgen/biome/plains.json": json.dumps(
            {"features": [[], ["minecraft:monster_room", "minecraft:monster_room_deep"]]}
        ).encode(),
        "tags/worldgen/biome/is_overworld.json": json.dumps(
            {"values": ["minecraft:plains"]}
        ).encode(),
        "tags/worldgen/biome/is_nether.json": json.dumps({"values": []}).encode(),
        "tags/worldgen/biome/is_end.json": json.dumps({"values": []}).encode(),
    }
    for path, value in overrides.items():
        files[path.replace("__", "/") + ".json"] = json.dumps(value).encode()
    return files


CURATED = {
    "minecraft:monster_room": {
        "name": "Monster Room",
        "page": "Monster Room",
        "placedFeatures": ["minecraft:monster_room", "minecraft:monster_room_deep"],
    }
}


def test_the_two_passes_are_summed_and_unioned_rather_than_taken_one_at_a_time() -> None:
    """A dungeon's rate is both passes, and its band spans both, not either alone."""
    place = extract_feature_places(_files(), CURATED)["minecraft:monster_room"]

    # 10 shallow attempts plus 4 deep ones. Showing either alone halves the rate.
    assert place.attempts_per_chunk == 14
    # The deep pass reaches `above_bottom 6`, which is Y -58 in a world whose
    # floor is -64, and the shallow one reaches the build ceiling. A band read
    # off one pass would stop at zero and hide half the world.
    assert place.min_y == -58
    assert place.max_y == 320


def test_the_dimension_is_derived_from_the_biomes_that_run_the_passes() -> None:
    place = extract_feature_places(_files(), CURATED)["minecraft:monster_room"]
    assert place.dimension.value == "overworld"
    assert place.biomes == ("minecraft:plains",)
    # One biome in the pack and one overworld biome, so it really is all of them.
    assert place.all_biomes_of_dimension is True


def test_the_biome_list_is_kept_even_when_it_covers_the_whole_dimension() -> None:
    """The flag is a rendering hint; the biome pages still need the ids to link back."""
    place = extract_feature_places(_files(), CURATED)["minecraft:monster_room"]
    assert place.all_biomes_of_dimension is True
    assert place.biomes != ()


def test_a_curated_id_the_pack_does_not_hold_is_an_error_not_an_empty_page() -> None:
    curated = {
        "minecraft:gone": {"name": "Gone", "page": "Gone", "placedFeatures": ["minecraft:gone"]}
    }
    with pytest.raises(ExtractError, match="no configured feature"):
        extract_feature_places(_files(), curated)


def test_a_curated_placed_feature_the_pack_does_not_hold_is_an_error() -> None:
    curated = {
        "minecraft:monster_room": {
            "name": "Monster Room",
            "page": "Monster Room",
            "placedFeatures": ["minecraft:monster_room", "minecraft:no_such_pass"],
        }
    }
    with pytest.raises(ExtractError, match="which this pack does not hold"):
        extract_feature_places(_files(), curated)


def test_the_committed_curated_document_names_the_dungeon_and_parses() -> None:
    """The real `feature-places.json` is loadable and still names the dungeon."""
    places = load_feature_places()
    assert "minecraft:monster_room" in places
    entry = places["minecraft:monster_room"]
    assert entry["page"] == "Monster Room"
    assert "minecraft:monster_room_deep" in entry["placedFeatures"]
