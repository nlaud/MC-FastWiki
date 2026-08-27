"""The extract stage against the real vanilla block tags of one Minecraft version.

`tests/test_extract_harvest.py` pins the rules of `pipeline.extract.tags` and
`pipeline.extract.harvest`. Every test there builds its own tag files in memory,
so none of them reads the shape that mcmeta publishes.

A fault passes that suite: a change of the parser can alter the answer for the
real archive and still pass, because no test there reads the real archive.

So this module reads two committed snapshots of the pinned `26.2-data` archive:

- `fixtures/mcmeta_26_2_block_tags.json` holds the input. It carries the parsed
  document of every tag file that the seven harvest tags reach.
- `fixtures/mcmeta_26_2_block_harvest.json` holds the answer. It carries the
  harvest requirement of every block that those tags name.

`fixtures/build_block_tag_snapshot.py` rebuilds both files. A person runs that
module by hand, and its docstring holds the steps.

What this module does not do is report a change of the upstream shape. A
committed snapshot is a copy of one archive, so it can only ever prove the
parser against the shape mcmeta published on that day. The rebuild is what
reads the new shape: it runs `parse_tag_file` over the fresh files, and a
`values` list that changed form fails there, on the hand run, rather than
mid-build after a Minecraft release.

No test in this module opens a socket. The extract stage is a pure function from
bytes to models, and the autouse fixture below fails any test that tries to reach
the network anyway.
"""

import ast
import importlib
import json
import socket
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from pipeline.extract.harvest import (
    BlockHarvest,
    HarvestTier,
    HarvestTool,
    extract_block_harvest,
)
from pipeline.extract.tags import BLOCK_REGISTRY, TAG_MARKER, tag_file_path
from pipeline.fetch.mcmeta import MCMETA_ARCHIVE_URL, MCMETA_REPOSITORY
from tests.fixtures import build_block_tag_snapshot
from tests.fixtures.build_block_tag_snapshot import (
    HARVEST_FIXTURE,
    TAG_FIXTURE,
    harvest_root_tags,
    tag_id_of,
)

# The file of the builder, for the import check at the end of this module.
BUILDER_SOURCE = Path(build_block_tag_snapshot.__file__)

# The version, the tag, and the commit that both fixtures record. The test reads
# the header of each file and compares it with these three values. A fixture of
# an unknown version then fails here, rather than passing quietly with numbers
# from another release of the game.
FIXTURE_VERSION_ID = "26.2"
FIXTURE_TAG = "26.2-data"
FIXTURE_SHA = "4d12c0553e21e461085d08dcb2c5d412398c494e"

# The floor of the block count. The pinned archive names 861 blocks, and a
# rebuild that lost most of its content falls far below this number. The floor
# sits well under the real count on purpose, because a Minecraft version adds
# and removes blocks and this test states a broken read, not a block list.
MINIMUM_BLOCK_COUNT = 400

# Five blocks, and what the game gives each one. A person read these against
# Minecraft. They catch a rebuild that changed the answer, which a snapshot
# compared only with itself cannot do.
SPOT_CHECKS = (
    ("minecraft:obsidian", (HarvestTool.PICKAXE,), HarvestTier.DIAMOND),
    ("minecraft:stone", (HarvestTool.PICKAXE,), HarvestTier.WOODEN),
    ("minecraft:dirt", (HarvestTool.SHOVEL,), HarvestTier.WOODEN),
    ("minecraft:oak_log", (HarvestTool.AXE,), HarvestTier.WOODEN),
    ("minecraft:hay_block", (HarvestTool.HOE,), HarvestTier.WOODEN),
)


@pytest.fixture(autouse=True)
def refuse_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test of this module that opens a socket.

    This is the fixture of `tests/test_mcmeta.py`, and that module holds the
    reason. The short form: a snapshot test that reaches upstream is not a
    snapshot test, and it fails on the day that GitHub is slow.
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise RuntimeError("this test tried to reach the network")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "gethostbyname", refuse)


def _document(path: Path) -> dict[str, Any]:
    """Return the parsed document of one fixture file."""
    document: Any = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict), f"{path.name} must hold one JSON object"
    return document


@pytest.fixture(scope="module")
def tag_document() -> dict[str, Any]:
    """The document of the tag fixture."""
    return _document(TAG_FIXTURE)


@pytest.fixture(scope="module")
def harvest_document() -> dict[str, Any]:
    """The document of the harvest fixture."""
    return _document(HARVEST_FIXTURE)


@pytest.fixture
def archive(tag_document: dict[str, Any]) -> dict[str, bytes]:
    """The tag fixture, back in the shape that `fetch_data_files` returns.

    The extract stage takes bytes, so each document goes back through
    `json.dumps`. Only the whitespace of the upstream file differs, and no
    parser reads whitespace.
    """
    return {path: json.dumps(value).encode() for path, value in tag_document["files"].items()}


@pytest.fixture
def snapshot(harvest_document: dict[str, Any]) -> dict[str, BlockHarvest]:
    """The harvest fixture, as the mapping that `extract_block_harvest` returns.

    The fixture writes the block ID one time, as the key. The record takes it
    back here, so a key and a record can never disagree in the file.
    """
    return {
        block: BlockHarvest(
            block=block,
            tools=tuple(HarvestTool(tool) for tool in record["tools"]),
            tier=HarvestTier(record["tier"]),
        )
        for block, record in harvest_document["blocks"].items()
    }


@pytest.mark.parametrize("fixture_name", ["tag_document", "harvest_document"])
def test_each_fixture_names_the_pinned_commit(
    fixture_name: str, request: pytest.FixtureRequest
) -> None:
    """Both fixtures must carry the version, the tag, and the commit of this module.

    The two files are rebuilt together, and a test that compares one with the
    other alone cannot tell whether either holds the version it claims. So each
    header is compared with a constant here. A half-finished rebuild, or a
    fixture copied from another version, then fails with the version named.
    """
    document: dict[str, Any] = request.getfixturevalue(fixture_name)

    assert document["version_id"] == FIXTURE_VERSION_ID
    assert document["tag"] == FIXTURE_TAG
    assert document["commit_sha"] == FIXTURE_SHA
    assert document["source_url"] == MCMETA_ARCHIVE_URL.format(
        repository=MCMETA_REPOSITORY, commit_sha=FIXTURE_SHA
    )


@pytest.mark.parametrize("fixture_path", [TAG_FIXTURE, HARVEST_FIXTURE])
def test_each_fixture_file_name_carries_the_pinned_version(fixture_path: Path) -> None:
    """The name of each fixture file must carry the version that its header names.

    `build_block_tag_snapshot` derives both names from `SNAPSHOT_VERSION_ID`, so
    a rebuild for a new version writes a new pair rather than overwriting the
    old one. That only helps while the name and the header agree.

    The failure this catches is the one that the derived name exists to prevent,
    arriving by the other route: a person edits `FIXTURE_VERSION_ID` here and
    forgets `SNAPSHOT_VERSION_ID` there, so `mcmeta_26_2_block_tags.json` is
    read as the 26.3 snapshot. Both globs that keep these files out of Prettier
    and out of a review diff match on the version segment too, so a name that
    drifts also drops the file out of both rules.
    """
    assert FIXTURE_VERSION_ID.replace(".", "_") in fixture_path.name
    assert fixture_path.is_file(), "the fixture of the pinned version must exist"


def test_the_tag_fixture_holds_every_root_of_the_harvest_stage(
    tag_document: dict[str, Any],
) -> None:
    """The fixture must hold the file of each of the seven tags that the stage reads.

    `extract_block_harvest` resolves four `mineable` tags and three `needs` tags.
    A missing root raises inside the stage, and the error there names one tag of
    an archive that the test built. This check names it as a fault of the
    fixture, which is what it is.
    """
    roots = {
        tag_file_path(tag_id_of(name), registry=BLOCK_REGISTRY) for name in harvest_root_tags()
    }
    assert roots <= set(tag_document["files"])


def test_the_tag_fixture_holds_the_whole_closure(tag_document: dict[str, Any]) -> None:
    """Every tag that the fixture refers to must have a file in the fixture.

    The snapshot is the transitive closure of the seven roots. A builder that
    stopped early would leave a reference with no file, and the stage would then
    fail with an error that reads like a broken upstream archive. This check
    states the real fault, and it states it before any other test runs the stage.
    """
    files: Mapping[str, Any] = tag_document["files"]
    missing: dict[str, list[str]] = {}
    for path, document in files.items():
        for entry in document["values"]:
            value = entry if isinstance(entry, str) else entry["id"]
            required = True if isinstance(entry, str) else entry.get("required", True)
            if not required or not value.startswith(TAG_MARKER):
                continue
            reference = tag_file_path(tag_id_of(value[1:]), registry=BLOCK_REGISTRY)
            if reference not in files:
                missing.setdefault(path, []).append(reference)
    assert missing == {}


def test_the_tag_fixture_holds_no_optional_reference(tag_document: dict[str, Any]) -> None:
    """No entry of the fixture may be an optional reference to another tag.

    The check above skips an optional reference, and it has to. An optional
    reference with no file in the fixture has two readings that the fixture
    cannot tell apart: the upstream archive did not answer it either, which is
    correct and is what the game does, or the builder dropped it, which is a
    short closure. The fixture records the closure alone, not what the archive
    held, so nothing in it decides between the two.

    The pinned `26.2-data` archive settles it for now: all 1,011 entries of the
    53 files are plain strings, so not one of them is optional and the ambiguity
    has no instance. This test pins that fact. When mcmeta first writes
    `{"id": "#minecraft:...", "required": false}` into one of these tags, a
    rebuild fails here rather than writing a snapshot whose completeness no test
    can check, and the person who sees it extends the fixture to record which
    optional references the archive answered.
    """
    optional: dict[str, list[str]] = {}
    for path, document in tag_document["files"].items():
        for entry in document["values"]:
            if isinstance(entry, str) or entry.get("required", True):
                continue
            optional.setdefault(path, []).append(entry["id"])
    assert optional == {}


def test_the_extract_stage_reproduces_the_harvest_snapshot(
    archive: dict[str, bytes], snapshot: dict[str, BlockHarvest]
) -> None:
    """The stage over the tag fixture must give the harvest fixture, record for record.

    This is the regression gate. A change of `pipeline.extract.tags` or of
    `pipeline.extract.harvest` that alters the answer for the real archive fails
    here, and the failure names the blocks that moved.
    """
    answer = extract_block_harvest(archive)

    assert set(answer) - set(snapshot) == set(), "the stage names a block that the snapshot lacks"
    assert set(snapshot) - set(answer) == set(), "the snapshot names a block that the stage lacks"
    changed = {
        block: {"stage": answer[block], "snapshot": snapshot[block]}
        for block in snapshot
        if answer[block] != snapshot[block]
    }
    assert changed == {}
    # The stage promises ID order, and a later stage shards its output. Two
    # builds of one version must write the same bytes.
    assert list(answer) == list(snapshot)


@pytest.mark.parametrize(("block", "tools", "tier"), SPOT_CHECKS)
def test_a_hand_checked_block_holds_its_requirement(
    block: str,
    tools: tuple[HarvestTool, ...],
    tier: HarvestTier,
    snapshot: dict[str, BlockHarvest],
) -> None:
    """Five blocks must hold the tool and the tier that the game gives them.

    The test above compares the snapshot with the stage, and both move together
    when a person rebuilds the fixture. These five values came from the game
    instead, so a rebuild that silently changed the answer fails here.
    """
    assert snapshot[block] == BlockHarvest(block=block, tools=tools, tier=tier)


def test_the_snapshot_holds_most_of_the_block_registry(
    snapshot: dict[str, BlockHarvest],
) -> None:
    """The snapshot must name several hundred blocks.

    CLAUDE.md gives the rule: a build that produces fewer entities than the last
    one is almost always a broken scrape. A fixture that lost most of its
    content is the same fault, one step earlier.
    """
    assert len(snapshot) >= MINIMUM_BLOCK_COUNT


def test_the_builder_reads_only_names_that_the_pipeline_exports() -> None:
    """Every pipeline name that the builder imports must sit in that module's `__all__`.

    Nothing in CI runs `build_block_tag_snapshot`. It opens the network, so it
    stays a hand run, and a name it imports that a pipeline module has since
    renamed produces an `ImportError` at the worst moment: the day someone
    reaches for it to follow a Minecraft release.

    `__all__` is what this repository writes the contract in -- every module of
    `pipeline` carries one, and the constants of a stage sit in it next to the
    functions. So the check is that the builder stays inside the contract, and
    the fix for a failure is one of two things, both cheap: export the name, or
    stop reading it.

    The source is read rather than the imported module. An import list is a fact
    of the file, and `ast` states it without the test having to guess which of
    the module's globals arrived by import.
    """
    tree = ast.parse(BUILDER_SOURCE.read_text(encoding="utf-8"), filename=BUILDER_SOURCE.name)
    outside: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module or ""
        # The dot matters. `startswith("pipeline")` would also take a package
        # named `pipelinex`, and this test must not decide anything about one.
        if module != "pipeline" and not module.startswith("pipeline."):
            continue
        exported = getattr(importlib.import_module(module), "__all__", None)
        if exported is None:
            pytest.fail(f"{module} carries no `__all__`, so it states no contract to check")
        for alias in node.names:
            if alias.name not in set(exported):
                outside.setdefault(module, []).append(alias.name)
    assert outside == {}
