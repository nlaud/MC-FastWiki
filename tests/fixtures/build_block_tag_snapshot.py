"""Rebuild the block tag snapshot and the harvest snapshot of one Minecraft version.

A person runs this module by hand. It is not a test, and pytest does not collect
it, because the name does not start with `test_`. `tests/typing/` holds the other
helper module of this suite, and this module follows that precedent.

`tests/test_extract_snapshot.py` reads the two files that this module writes.
Those files pin `pipeline.extract.tags` and `pipeline.extract.harvest` against
the real upstream data. Every other test of the extract stage builds its own tag
files in memory, so a parser that gives a wrong answer for the vanilla archive
still passes them.

Run it from the repository root:

    python -m tests.fixtures.build_block_tag_snapshot

The module opens the network. It reads one mcmeta tag and one archive through
the fetch stage of this repository, so it takes the same path that a build takes
and it writes the same content cache.

A second run still opens a socket. `fetch_data_files` caches the 2.7 MB archive
by content hash, so the download happens one time, but `resolve_mcmeta_tag`
caches nothing: every run sends one GET to the GitHub reference endpoint to turn
the tag into a commit SHA. So a rerun with no network fails there even when the
archive is already on disk, and a run behind the unauthenticated GitHub rate
limit of 60 requests an hour fails there too. Neither failure means the snapshot
is wrong.

Read the module docstring of `pipeline.fetch.mcmeta` before you change the
version below. A snapshot tag must never become the pinned fixture of a release
build.

To move the snapshot to a new Minecraft version, do these steps in order. The
first one renames both files, because the names carry the version.

1. Set `SNAPSHOT_VERSION_ID` below to the new release ID.
2. Run the module. It writes two new files next to the old pair.
3. Delete the fixture files of the old version. Nothing reads them.
4. Set `FIXTURE_VERSION_ID`, `FIXTURE_TAG`, and `FIXTURE_SHA` of
   `tests/test_extract_snapshot.py` to the three values that the module printed.
   All three, not the SHA alone: the header check compares each one, and a
   half-finished edit fails with the field that was missed.
5. Read the five spot checks of that module against the game.
6. Run `pytest tests/test_extract_snapshot.py`.
"""

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from pipeline.extract import ExtractError
from pipeline.extract.harvest import (
    MINEABLE_TAG_TEMPLATE,
    NEEDS_TOOL_TAG_TEMPLATE,
    TAGGED_TIERS,
    BlockHarvest,
    HarvestTool,
    extract_block_harvest,
)
from pipeline.extract.tags import (
    BLOCK_REGISTRY,
    DEFAULT_NAMESPACE,
    TAG_MARKER,
    TagIndex,
    parse_tag_file,
    tag_file_path,
)
from pipeline.fetch.mcmeta import (
    MCMETA_ARCHIVE_URL,
    MCMETA_REPOSITORY,
    McmetaTag,
    fetch_data_files,
    resolve_mcmeta_tag,
)

# The Minecraft version that the snapshot holds. The fixture pins one version on
# purpose, so a later release does not break the test. Raise this number when
# you want the snapshot to follow the game.
SNAPSHOT_VERSION_ID = "26.2"

# The branch that carries the vanilla data pack, and the group of it that the
# block tags sit in. `fetch_data_files` reads one group, so the archive walk
# skips the recipes, the loot tables, and the advancements.
DATA_BRANCH = "data"
TAG_GROUP = "tags"

FIXTURE_DIRECTORY = Path(__file__).resolve().parent

# The version, in the form that a file name takes. A dot reads as a suffix
# separator to half the tools that walk a directory, so `26.2` becomes `26_2`.
FIXTURE_SLUG = SNAPSHOT_VERSION_ID.replace(".", "_")

# Both names are derived, not typed. A hand-typed name survives a version bump
# unchanged, so `mcmeta_26_2_block_tags.json` would end up holding 26.3 data and
# every reader of the directory would believe the name. Deriving it means the
# rebuild writes a new pair and leaves the old pair alone, which is also what
# makes step 3 of the docstring a deletion rather than a merge.
#
# `.prettierignore` and `.gitattributes` both match these names with a glob that
# carries a `*` where the version sits, so a new version needs no edit to either
# file. Two gates prove it against a 26.3 name that no file answers:
# `format-scope.test.ts` for the first and `tests/test_repo_invariants.py` for
# the second.
TAG_FIXTURE = FIXTURE_DIRECTORY / f"mcmeta_{FIXTURE_SLUG}_block_tags.json"
HARVEST_FIXTURE = FIXTURE_DIRECTORY / f"mcmeta_{FIXTURE_SLUG}_block_harvest.json"


def harvest_root_tags() -> tuple[str, ...]:
    """Return the seven tags that `extract_block_harvest` reads.

    The names come from the templates and the enumerations of
    `pipeline.extract.harvest`, so this module holds no second list of them. A
    later version of that stage that reads an eighth tag moves the closure with
    it.
    """
    mineable = tuple(MINEABLE_TAG_TEMPLATE.format(tool=tool.value) for tool in HarvestTool)
    needs = tuple(NEEDS_TOOL_TAG_TEMPLATE.format(tier=tier.value) for tier in TAGGED_TIERS)
    return mineable + needs


def tag_id_of(name: str) -> str:
    """Return the namespaced ID of the tag `name`, without the `#` marker.

    `mineable/pickaxe` and `#minecraft:mineable/pickaxe` name the same tag.
    `TagIndex` applies the same two rules, and it keeps its version private.
    """
    text = name.removeprefix(TAG_MARKER)
    if ":" not in text:
        return f"{DEFAULT_NAMESPACE}:{text}"
    return text


def collect_closure(files: Mapping[str, bytes], roots: Iterable[str]) -> dict[str, bytes]:
    """Return every tag file that `roots` reaches, keyed by its archive path.

    The walk follows a `#` reference to its file, at any depth. It skips an
    optional reference that the archive does not answer, because the game skips
    that one too and `TagIndex.resolve` skips it as well.

    A required tag with no file raises `ExtractError`. That fault stops the
    rebuild, so a short closure never reaches the fixture.
    """
    index = TagIndex(files, registry=BLOCK_REGISTRY)
    closure: dict[str, bytes] = {}
    pending = [tag_id_of(root) for root in roots]
    while pending:
        tag_id = pending.pop()
        path = tag_file_path(tag_id, registry=BLOCK_REGISTRY)
        if path in closure:
            continue
        payload = files.get(path)
        if payload is None:
            raise ExtractError(
                f"the archive holds no file {path!r} for the tag {tag_id!r}. The snapshot needs "
                f"every file of the closure."
            )
        closure[path] = payload
        for entry in parse_tag_file(payload, source=path).values:
            value = entry if isinstance(entry, str) else entry.id
            required = True if isinstance(entry, str) else entry.required
            if not value.startswith(TAG_MARKER):
                continue
            reference = tag_id_of(value[1:])
            if not required and not index.holds(reference):
                continue
            pending.append(reference)
    return closure


def provenance(tag: McmetaTag) -> dict[str, str]:
    """Return the header that both fixtures carry.

    The header names the tag, the commit, and the URL that the bytes came from.
    A reader of the fixture then knows which version of the game it holds, and
    the test refuses a fixture of an unknown commit.
    """
    return {
        "version_id": tag.version_id,
        "tag": tag.tag,
        "commit_sha": tag.commit_sha,
        "source_url": MCMETA_ARCHIVE_URL.format(
            repository=MCMETA_REPOSITORY, commit_sha=tag.commit_sha
        ),
    }


def tag_snapshot(tag: McmetaTag, closure: Mapping[str, bytes]) -> dict[str, object]:
    """Return the document of the tag fixture.

    `files` holds the parsed JSON document of each tag file, not its bytes. A
    tag file is JSON, so the document keeps every value and every structure of
    the upstream file. Only the whitespace goes, and no parser reads whitespace.
    """
    return {
        **provenance(tag),
        "files": {path: json.loads(payload) for path, payload in sorted(closure.items())},
    }


def harvest_snapshot(tag: McmetaTag, blocks: Mapping[str, BlockHarvest]) -> dict[str, object]:
    """Return the document of the harvest fixture.

    A `BlockHarvest` carries the block ID twice, once as the key of the mapping
    and once in the record. The fixture writes it one time, and the test
    rebuilds the record from the key.
    """
    return {
        **provenance(tag),
        "blocks": {
            block: {"tools": [tool.value for tool in record.tools], "tier": record.tier.value}
            for block, record in blocks.items()
        },
    }


def write_fixture(path: Path, document: Mapping[str, object]) -> None:
    """Write one fixture file, indented, and with a final newline.

    `.gitattributes` gives every tracked file the ending LF, so this writes LF
    on every platform.
    """
    text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    """Fetch the pinned archive and write both fixture files."""
    tag = resolve_mcmeta_tag(SNAPSHOT_VERSION_ID, DATA_BRANCH)
    files = fetch_data_files(tag, groups=(TAG_GROUP,))
    closure = collect_closure(files, harvest_root_tags())

    blocks = extract_block_harvest(closure)

    write_fixture(TAG_FIXTURE, tag_snapshot(tag, closure))
    write_fixture(HARVEST_FIXTURE, harvest_snapshot(tag, blocks))

    # Print the three header values under the names of the constants that step
    # 4 of the docstring asks for, so the person copying them does not have to
    # work out which value belongs to which constant.
    print(f"FIXTURE_VERSION_ID = {tag.version_id!r}")
    print(f"FIXTURE_TAG = {tag.tag!r}")
    print(f"FIXTURE_SHA = {tag.commit_sha!r}")
    print(f"{TAG_FIXTURE.name}: {len(closure)} tag files")
    print(f"{HARVEST_FIXTURE.name}: {len(blocks)} blocks")


if __name__ == "__main__":
    main()
