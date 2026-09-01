"""The entity_type classifier against the real vanilla registries and loot tables of one version.

`tests/test_extract_entity_class.py` pins the rules of `pipeline.extract.
entity_class.classify_entity_types`. Every test there builds its own
registries and loot table paths in memory, so none of them proves the
classifier gives the right per-clause counts for a real Minecraft version.

A fault passes that suite: a change of the classifier can alter the answer for
the real `entity_type` registry and still pass, because no test there reads the
real one.

So this module reads a committed snapshot of the pinned `26.2` mcmeta payloads,
`fixtures/mcmeta_26_2_entity_class.json`. It carries the `entity_type` and
`item` registries and every `loot_table/entities/**` file path of that
version. `fixtures/build_entity_class_snapshot.py` rebuilds it; a person runs
that module by hand, and its docstring holds the steps.

The measured counts asserted below were verified against this exact snapshot
on 2026-08-31, and `pipeline.extract.entity_class`'s own module docstring
cites the same numbers: 158 `entity_type` paths, 88 `SPAWN_EGG`, 5
`LOOT_TABLE_ONLY`, and 65 `NEITHER`.

No test in this module opens a socket. The classifier is a pure function from
a registries mapping and a set of file paths to a mapping, and the autouse
fixture below fails any test that tries to reach the network anyway.
"""

import json
import socket
from pathlib import Path
from typing import Any

import pytest

from pipeline.extract.entity_class import EntityClass, classify_entity_types
from pipeline.fetch.mcmeta import MCMETA_ARCHIVE_URL, MCMETA_REPOSITORY, SUMMARY_PAYLOADS
from tests.fixtures.build_entity_class_snapshot import FIXTURE_PATH

# The version, the tags, and the commits both branches of the fixture record.
# A fixture of an unknown version fails here, rather than passing quietly with
# numbers from another release of the game.
FIXTURE_VERSION_ID = "26.2"
REGISTRIES_TAG = "26.2-summary"
REGISTRIES_SHA = "711a353b47d84e6cb592a1b72f682e5f44759284"
DATA_TAG = "26.2-data"
DATA_SHA = "4d12c0553e21e461085d08dcb2c5d412398c494e"

# The exact 5 IDs of clause 2, per `pipeline.extract.entity_class`'s own
# module docstring: a loot table but no spawn egg.
CLAUSE_2_IDS = frozenset({"armor_stand", "giant", "illusioner", "mannequin", "player"})

# The exact 23 IDs that end up in no other precedence registry at all, so a
# real merge would give every one of them `EntityKind.ENTITY`.
CLAUSE_3_NO_OTHER_REGISTRY_IDS = frozenset(
    {
        "area_effect_cloud",
        "block_display",
        "breeze_wind_charge",
        "dragon_fireball",
        "evoker_fangs",
        "experience_orb",
        "eye_of_ender",
        "falling_block",
        "fireball",
        "fishing_bobber",
        "interaction",
        "item",
        "item_display",
        "leash_knot",
        "lightning_bolt",
        "llama_spit",
        "marker",
        "ominous_item_spawner",
        "shulker_bullet",
        "small_fireball",
        "spawner_minecart",
        "text_display",
        "wither_skull",
    }
)


@pytest.fixture(autouse=True)
def refuse_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test of this module that opens a socket.

    This is the fixture of `tests/test_mcmeta.py` and `tests/
    test_extract_snapshot.py`, and those modules hold the reason: a snapshot
    test that reaches upstream is not a snapshot test, and it fails on the
    day that GitHub is slow.
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise RuntimeError("this test tried to reach the network")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "gethostbyname", refuse)


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    """The parsed document of the entity_class fixture."""
    parsed: Any = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict), f"{FIXTURE_PATH.name} must hold one JSON object"
    return parsed


@pytest.fixture
def files(document: dict[str, Any]) -> dict[str, bytes]:
    """The fixture's loot table paths, back in the shape `fetch_data_files` returns.

    The classifier reads only paths, never bytes -- see `pipeline.extract.
    entity_class`'s own module docstring -- so every value here is empty.
    """
    return dict.fromkeys(document["loot_table_entity_paths"], b"")


@pytest.fixture
def registries(document: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    """The fixture's `entity_type` and `item` registries, as tuples."""
    return {
        "entity_type": tuple(document["entity_type"]),
        "item": tuple(document["item"]),
    }


def test_the_fixture_names_the_pinned_commit_of_both_branches(document: dict[str, Any]) -> None:
    """Both branches' headers must carry the version, the tag, and the commit this module pins.

    The registries and the loot table paths are rebuilt together, and a test
    that trusted one header alone could not tell whether the other half of
    the fixture holds the version it claims.
    """
    registries_source = document["registries_source"]
    assert registries_source["version_id"] == FIXTURE_VERSION_ID
    assert registries_source["tag"] == REGISTRIES_TAG
    assert registries_source["commit_sha"] == REGISTRIES_SHA
    assert registries_source["source_url"] == (
        f"https://raw.githubusercontent.com/{MCMETA_REPOSITORY}/{REGISTRIES_SHA}/"
        f"{SUMMARY_PAYLOADS['registries']}"
    )

    data_source = document["data_source"]
    assert data_source["version_id"] == FIXTURE_VERSION_ID
    assert data_source["tag"] == DATA_TAG
    assert data_source["commit_sha"] == DATA_SHA
    assert data_source["source_url"] == MCMETA_ARCHIVE_URL.format(
        repository=MCMETA_REPOSITORY, commit_sha=DATA_SHA
    )


def test_the_fixture_file_name_carries_the_pinned_version() -> None:
    assert FIXTURE_VERSION_ID.replace(".", "_") in FIXTURE_PATH.name
    assert FIXTURE_PATH.is_file(), "the fixture of the pinned version must exist"


def test_the_registry_holds_158_entity_type_paths(registries: dict[str, tuple[str, ...]]) -> None:
    """The measured count `pipeline.extract.entity_class`'s module docstring cites."""
    assert len(registries["entity_type"]) == 158


def test_the_classifier_reproduces_the_measured_per_clause_counts(
    files: dict[str, bytes], registries: dict[str, tuple[str, ...]]
) -> None:
    """The regression gate: the exact counts this task's brief measured on 2026-08-31.

    A change to `classify_entity_types` that alters the answer for the real
    `entity_type` registry fails here, even though every in-memory test of
    `tests/test_extract_entity_class.py` still passes.
    """
    result = classify_entity_types(files, registries)

    counts: dict[EntityClass, int] = {}
    for entity_class in result.by_path.values():
        counts[entity_class] = counts.get(entity_class, 0) + 1

    assert counts[EntityClass.SPAWN_EGG] == 88
    assert counts[EntityClass.LOOT_TABLE_ONLY] == 5
    assert counts[EntityClass.NEITHER] == 65
    assert len(result.by_path) == 158


def test_the_spawn_egg_set_is_a_strict_subset_of_the_loot_table_set(
    files: dict[str, bytes], registries: dict[str, tuple[str, ...]]
) -> None:
    """The property that makes clause 2 exactly 5 IDs rather than a fuzzy boundary.

    Every `SPAWN_EGG` path must also answer to a loot table, so clause 2
    (`LOOT_TABLE_ONLY`) is precisely "has a loot table, does not have a spawn
    egg" with nothing left ambiguous.
    """
    result = classify_entity_types(files, registries)
    spawn_egg = {path for path, cls in result.by_path.items() if cls is EntityClass.SPAWN_EGG}
    loot_table = {
        path
        for path, cls in result.by_path.items()
        if cls in (EntityClass.SPAWN_EGG, EntityClass.LOOT_TABLE_ONLY)
    }
    assert spawn_egg < loot_table
    assert len(loot_table) == 93


def test_clause_two_is_exactly_the_five_named_ids(
    files: dict[str, bytes], registries: dict[str, tuple[str, ...]]
) -> None:
    result = classify_entity_types(files, registries)
    undecided = {path for path, cls in result.by_path.items() if cls is EntityClass.LOOT_TABLE_ONLY}
    assert undecided == CLAUSE_2_IDS


def test_clause_three_with_no_other_registry_membership_is_exactly_the_23_named_ids(
    files: dict[str, bytes], registries: dict[str, tuple[str, ...]]
) -> None:
    """The IDs that would become `EntityKind.ENTITY` in a real merge.

    `classify_entity_types` does not itself know about `block` or `item`
    membership -- see its own module docstring's closing section -- so this
    test does the cross-reference `pipeline.normalize.merge` would do, using
    the same fixture's `item` registry to find the demoted IDs with no other
    home.
    """
    result = classify_entity_types(files, registries)
    neither = {path for path, cls in result.by_path.items() if cls is EntityClass.NEITHER}
    item_ids = set(registries["item"])
    no_other_registry = {path for path in neither if path not in item_ids and path != "tnt"}
    assert no_other_registry == CLAUSE_3_NO_OTHER_REGISTRY_IDS


def test_tnt_classifies_as_neither_and_is_also_a_block(
    files: dict[str, bytes], registries: dict[str, tuple[str, ...]]
) -> None:
    """`tnt` is the one clause-3 ID a real merge would demote into `block` rather than `item`.

    It sits in both `block` and `item`, and `_REGISTRY_PRECEDENCE` in
    `pipeline.normalize.merge` puts `block` ahead of `item`, so `block` wins
    once `entity_type` is demoted out of the way.
    """
    result = classify_entity_types(files, registries)
    assert result.by_path["tnt"] is EntityClass.NEITHER
    assert "tnt" in registries["item"]


def test_the_builder_reads_only_names_that_the_pipeline_exports() -> None:
    """Every pipeline name the builder imports must sit in that module's `__all__`.

    Mirrors `tests/test_extract_snapshot.py`'s own check of `build_block_tag_
    snapshot`, for the same reason: nothing in CI runs `build_entity_class_
    snapshot`, so a renamed export would only surface as an `ImportError` the
    day someone reaches for it to follow a Minecraft release.
    """
    import ast
    import importlib

    from tests.fixtures import build_entity_class_snapshot

    source = Path(build_entity_class_snapshot.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source, filename="build_entity_class_snapshot.py")
    outside: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module or ""
        if module != "pipeline" and not module.startswith("pipeline."):
            continue
        exported = getattr(importlib.import_module(module), "__all__", None)
        if exported is None:
            pytest.fail(f"{module} carries no `__all__`, so it states no contract to check")
        for alias in node.names:
            if alias.name not in set(exported):
                outside.setdefault(module, []).append(alias.name)
    assert outside == {}
