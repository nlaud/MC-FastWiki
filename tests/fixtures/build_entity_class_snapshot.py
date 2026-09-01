"""Rebuild the entity_type classification snapshot of one Minecraft version.

A person runs this module by hand. It is not a test, and pytest does not collect
it, because the name does not start with `test_`. `tests/fixtures/build_block_
tag_snapshot.py` is the precedent this module follows, down to the shape of its
docstring and its numbered "how to move this to a new version" steps.

`tests/test_extract_entity_class_snapshot.py` reads the file that this module
writes. That file pins `pipeline.extract.entity_class.classify_entity_types`
against the real upstream data: the `entity_type` and `item` registries of the
`summary` branch, and the `loot_table/entities/**` file paths of the `data`
branch. Every test of `tests/test_extract_entity_class.py` builds its own
registries and file paths in memory, so none of them proves the classifier gives
the right per-clause counts for a real Minecraft version -- only this snapshot
does that.

Run it from the repository root:

    python -m tests.fixtures.build_entity_class_snapshot

The module opens the network. `fetch_summary_payload` and `fetch_data_files`
both cache their payload by content hash, so a rebuild against an
already-cached version reads no network for the payload itself -- but
`resolve_mcmeta_tag` caches nothing, so every run still sends two GETs to the
GitHub reference endpoint, one per branch, to turn each tag into a commit SHA.
A rerun with no network fails there even when both payloads are already on
disk, and a run behind the unauthenticated GitHub rate limit of 60 requests an
hour fails there too. Neither failure means the snapshot is wrong.

Read the module docstring of `pipeline.fetch.mcmeta` before you change the
version below. A snapshot tag must never become the pinned fixture of a release
build.

To move the snapshot to a new Minecraft version, do these steps in order. The
first one renames the file, because the name carries the version.

1. Set `SNAPSHOT_VERSION_ID` below to the new release ID.
2. Run the module. It writes a new file next to the old one.
3. Delete the fixture file of the old version. Nothing reads it.
4. Set `FIXTURE_VERSION_ID`, `REGISTRIES_TAG`, `REGISTRIES_SHA`, `DATA_TAG`,
   and `DATA_SHA` of `tests/test_extract_entity_class_snapshot.py` to the five
   values that the module printed. All five, not a subset: the header check
   compares each one, and a half-finished edit fails with the field that was
   missed.
5. Read the measured counts the module prints against the game, or against
   `pipeline.extract.entity_class`'s own module docstring if the counts have
   not changed.
6. Run `pytest tests/test_extract_entity_class_snapshot.py`.
"""

import json
from pathlib import Path

from pipeline.extract.entity_class import (
    ENTITY_TYPE_REGISTRY,
    ITEM_REGISTRY,
    LOOT_TABLE_ENTITY_DIRECTORY,
)
from pipeline.fetch.mcmeta import (
    MCMETA_ARCHIVE_URL,
    MCMETA_REPOSITORY,
    SUMMARY_PAYLOADS,
    McmetaTag,
    fetch_data_files,
    fetch_summary_payload,
    resolve_mcmeta_tag,
)

# The Minecraft version that the snapshot holds. The fixture pins one version on
# purpose, so a later release does not break the test. Raise this number when
# you want the snapshot to follow the game.
SNAPSHOT_VERSION_ID = "26.2"

# The one group of the `data` branch this snapshot needs. `fetch_data_files`
# reads only this group, so the archive walk skips the advancements, the
# recipes, and the tags.
LOOT_TABLE_GROUP = "loot_table"

FIXTURE_DIRECTORY = Path(__file__).resolve().parent

# The version, in the form that a file name takes. A dot reads as a suffix
# separator to half the tools that walk a directory, so `26.2` becomes `26_2`.
FIXTURE_SLUG = SNAPSHOT_VERSION_ID.replace(".", "_")

# Derived, not typed, for the same reason `tests/fixtures/build_block_tag_
# snapshot.py`'s own `TAG_FIXTURE` is: a hand-typed name survives a version
# bump unchanged, and a rebuild for a new version should write a new file
# rather than silently relabel stale content as current.
FIXTURE_PATH = FIXTURE_DIRECTORY / f"mcmeta_{FIXTURE_SLUG}_entity_class.json"


def _provenance(tag: McmetaTag, source_url: str) -> dict[str, str]:
    """Return the header one branch's read contributes to the fixture.

    Two branches feed this fixture -- `summary` for the registries, `data`
    for the loot table paths -- and mcmeta tags each branch separately, so
    each can (and typically does) point at a different commit. The fixture
    carries both headers rather than one, and the test checks both.
    """
    return {
        "version_id": tag.version_id,
        "tag": tag.tag,
        "commit_sha": tag.commit_sha,
        "source_url": source_url,
    }


def main() -> None:
    """Fetch the pinned registries and loot table paths, and write the fixture file."""
    registries_tag = resolve_mcmeta_tag(SNAPSHOT_VERSION_ID, "summary")
    registries_path = SUMMARY_PAYLOADS["registries"]
    registries_payload = fetch_summary_payload(registries_tag, "registries")
    registries: dict[str, list[str]] = json.loads(registries_payload)

    data_tag = resolve_mcmeta_tag(SNAPSHOT_VERSION_ID, "data")
    files = fetch_data_files(data_tag, groups=(LOOT_TABLE_GROUP,))
    loot_table_entity_paths = sorted(
        path for path in files if path.startswith(LOOT_TABLE_ENTITY_DIRECTORY)
    )

    document = {
        "registries_source": _provenance(registries_tag, registries_tag.raw_url(registries_path)),
        "data_source": _provenance(
            data_tag,
            MCMETA_ARCHIVE_URL.format(repository=MCMETA_REPOSITORY, commit_sha=data_tag.commit_sha),
        ),
        ENTITY_TYPE_REGISTRY: registries[ENTITY_TYPE_REGISTRY],
        ITEM_REGISTRY: registries[ITEM_REGISTRY],
        "loot_table_entity_paths": loot_table_entity_paths,
    }

    text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    FIXTURE_PATH.write_text(text, encoding="utf-8", newline="\n")

    # Print the header values under the names of the constants that step 4 of
    # the docstring asks for, so the person copying them does not have to work
    # out which value belongs to which constant.
    print(f"FIXTURE_VERSION_ID = {SNAPSHOT_VERSION_ID!r}")
    print(f"REGISTRIES_TAG = {registries_tag.tag!r}")
    print(f"REGISTRIES_SHA = {registries_tag.commit_sha!r}")
    print(f"DATA_TAG = {data_tag.tag!r}")
    print(f"DATA_SHA = {data_tag.commit_sha!r}")
    print(
        f"{FIXTURE_PATH.name}: {len(registries[ENTITY_TYPE_REGISTRY])} entity_type paths, "
        f"{len(loot_table_entity_paths)} loot table files"
    )


if __name__ == "__main__":
    main()
