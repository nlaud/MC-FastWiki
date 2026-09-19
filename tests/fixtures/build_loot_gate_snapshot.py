"""Rebuild the pool-level and entry-level tool gate snapshot of one Minecraft version.

A person runs this module by hand. It is not a test, and pytest does not collect
it, because the name does not start with `test_`.
`tests/fixtures/build_block_tag_snapshot.py` is the precedent this module follows,
and its docstring holds the longer argument for why a snapshot is rebuilt by hand
rather than fetched inside a test.

`tests/test_obtain_loot.py` reads the file that this module writes. That file pins
`pipeline.obtain.loot`'s tool gate reading against the real upstream data. Every
other loot test in that suite builds its own tables in memory, so a walk that stops
reading a pool's own `conditions` still passes them -- which is exactly the fault
that shipped: 76 block tables gate their drop on silk touch at the pool level, and
the walk seeded `gate=None` for every pool.

Run it from the repository root:

    python -m tests.fixtures.build_loot_gate_snapshot

The module opens the network. It reads one mcmeta tag and one archive through the
fetch stage of this repository, so it takes the same path that a build takes. A
rerun with no network fails in `resolve_mcmeta_tag`, which caches nothing, even
when the archive is already on disk. That failure does not mean the snapshot is
wrong.

## What the snapshot holds, and why it holds the input as well as the answer

`tables` carries the parsed document of every `loot_table/blocks/*.json` that
names a tool gate at any depth, plus two controls that must never gain one. The
test replays `extract_loot` over those documents, so it exercises the real walk
rather than comparing two numbers this module wrote.

`answer` carries what the walk must produce: the two pool-level counts, and the
note of every `(source, item)` pair the gated tables yield. `blockTablesScanned`
records how many block tables the whole archive held when the snapshot was taken,
so a later reader can tell a shrinking archive from a shrinking gate list.

Storing only the gated tables means the test cannot notice a *new* table upstream
gaining a pool gate. Rerunning this module is what notices that, on the hand run,
rather than mid-build after a Minecraft release. That is the same division of
labour `build_block_tag_snapshot.py` documents.

To move the snapshot to a new Minecraft version:

1. Set `SNAPSHOT_VERSION_ID` below to the new release ID.
2. Run the module. It writes a new file next to the old one, because the name
   carries the version.
3. Delete the fixture file of the old version. Nothing reads it.
4. Set `GATE_FIXTURE` in `tests/test_obtain_loot.py` to the new name.
5. Run `pytest tests/test_obtain_loot.py`.
"""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pipeline.fetch.cache import ContentCache
from pipeline.fetch.mcmeta import MCMETA_REPOSITORY, fetch_data_files, resolve_mcmeta_tag
from pipeline.obtain.loot import BLOCK_LOOT_DIRECTORY, PREDICATE_DIRECTORY, extract_loot
from pipeline.obtain.loot import _condition_gate as condition_gate
from pipeline.obtain.loot import _predicate_index as predicate_index

# The release this snapshot pins. Read `pipeline.fetch.mcmeta`'s module docstring
# before changing it: a snapshot tag must never become the pinned fixture of a
# release build.
Predicates = Mapping[str, Mapping[str, Any]]

SNAPSHOT_VERSION_ID = "26.3"
BRANCH = "data"

# Two tables that carry no tool gate at all and must never grow one. They travel
# in the snapshot so the test can prove the walk stays silent where the archive is
# silent, rather than only proving it speaks where the archive speaks.
CONTROL_TABLES = (
    f"{BLOCK_LOOT_DIRECTORY}/stone.json",
    f"{BLOCK_LOOT_DIRECTORY}/dirt.json",
)

# One table whose gate sits on the *entry*, inside a `minecraft:alternatives`
# wrapper, paired with an ungated sibling. It is the shape the reader already
# handled before this change, and it must keep working.
ENTRY_GATED_CONTROL = f"{BLOCK_LOOT_DIRECTORY}/diamond_ore.json"


def _table_names_a_gate(document: object, predicates: Predicates) -> bool:
    """Return whether `document` names a tool gate on any pool or any entry."""
    if not isinstance(document, dict):
        return False
    pools = document.get("pools")
    if not isinstance(pools, list):
        return False
    for pool in pools:
        if not isinstance(pool, dict):
            continue
        if condition_gate(pool.get("condition"), predicates) is not None:
            return True
        if _entries_name_a_gate(pool.get("entries"), predicates):
            return True
    return False


def _entries_name_a_gate(entries: object, predicates: Predicates) -> bool:
    """Return whether any entry reachable from `entries` names a tool gate."""
    if not isinstance(entries, list):
        return False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if condition_gate(entry.get("condition"), predicates) is not None:
            return True
        if _entries_name_a_gate(entry.get("children"), predicates):
            return True
    return False


def main() -> None:
    """Write the gate snapshot of `SNAPSHOT_VERSION_ID` and print its header."""
    cache = ContentCache(Path("data") / ".cache")
    tag = resolve_mcmeta_tag(SNAPSHOT_VERSION_ID, BRANCH, cache=cache)
    # `predicate` travels with the tables from 26.3 on: a table names
    # `minecraft:tool/can_silk_touch` rather than spelling the condition out, so
    # the gate is unreadable without the registry that holds it.
    files = fetch_data_files(tag, groups=("loot_table", "predicate"), cache=cache)
    predicates = predicate_index(files)
    predicate_files = {
        path: payload
        for path, payload in files.items()
        if path.startswith(PREDICATE_DIRECTORY)
    }

    block_tables = {
        path: json.loads(payload)
        for path, payload in files.items()
        if path.startswith(f"{BLOCK_LOOT_DIRECTORY}/")
    }

    keep = {
        path: document
        for path, document in sorted(block_tables.items())
        if _table_names_a_gate(document, predicates)
    }
    for path in (*CONTROL_TABLES, ENTRY_GATED_CONTROL):
        if path in block_tables:
            keep[path] = block_tables[path]

    pool_silk = 0
    pool_shears = 0
    for document in block_tables.values():
        gates = {
            condition_gate(pool.get("condition"), predicates)
            for pool in document.get("pools", [])
            if isinstance(pool, dict)
        }
        if "requires silk touch" in gates:
            pool_silk += 1
        elif "requires shears" in gates:
            pool_shears += 1

    replay = extract_loot(
        {path: json.dumps(document).encode() for path, document in sorted(keep.items())}
        | predicate_files
    )
    notes = {
        f"{producer.source_id}|{producer.output.item}": producer.note
        for producer in replay.producers
    }

    document = {
        "version_id": tag.version_id,
        "tag": tag.tag,
        "commit_sha": tag.commit_sha,
        "source_url": f"https://github.com/{MCMETA_REPOSITORY}/tree/{tag.commit_sha}",
        "blockTablesScanned": len(block_tables),
        "predicates": {
            path: json.loads(payload) for path, payload in sorted(predicate_files.items())
        },
        "answer": {
            "poolSilkTouchTables": pool_silk,
            "poolShearsTables": pool_shears,
            "notes": dict(sorted(notes.items())),
        },
        "tables": dict(sorted(keep.items())),
    }

    slug = SNAPSHOT_VERSION_ID.replace(".", "_")
    out = Path("tests") / "fixtures" / f"mcmeta_{slug}_loot_gates.json"
    out.write_text(json.dumps(document, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    print(f"wrote {out}")
    print(f"  version_id  {tag.version_id}")
    print(f"  tag         {tag.tag}")
    print(f"  commit_sha  {tag.commit_sha}")
    print(f"  block tables scanned      {len(block_tables)}")
    print(f"  tables kept in the fixture {len(keep)}")
    print(f"  pool-level silk touch      {pool_silk}")
    print(f"  pool-level shears          {pool_shears}")


if __name__ == "__main__":
    main()
