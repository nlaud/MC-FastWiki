"""End-to-end: one `MergeResult` spanning every kind, through `emit_build`, onto disk.

The unit tests of `test_emit_shard.py`, `test_emit_search_index.py`, and
`test_emit_write.py` each pin one module's own contract in isolation. This
file is the integration check none of them can be: it builds one realistic
`MergeResult`, writes it with `emit_build`, and then reads the actual files
back off disk to check the one property that only shows up once every module
runs together -- that `index.json`'s `s` field always names a shard file that
exists and genuinely holds the id it claims to.

`shard_size=5` is passed explicitly, rather than relying on the real
`DEFAULT_SHARD_SIZE` of 200. The chunking rule `pipeline.emit.shard` applies
does not change shape with the shard size -- `assign_shards`'s own tests
already pin the boundary arithmetic -- so a small size is what forces several
kinds into multiple shards each with a fixture of a realistic few dozen
entities, rather than requiring this file to construct 201 fake items just to
reach the same code path the real build already exercises at its own size.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline.emit.manifest import BuildInfo
from pipeline.emit.write import emit_build
from pipeline.enrich.advancement import Reconciliation
from pipeline.normalize.entity import Entity, EntityKind
from pipeline.normalize.merge import MergeReport, MergeResult

SHARD_SIZE = 5
ENTITIES_PER_KIND = 12

# 10 index-gzipped-bytes ceiling, generous against the measured figure this
# test prints -- see `test_the_snapshot_stays_under_a_generous_gzipped_ceiling`
# for why a loose bound is the right shape for this particular assertion.
GZIPPED_CEILING_BYTES = 8_000


def _entity(kind: EntityKind, index: int) -> Entity:
    entity_id = f"minecraft:{kind.value}_{index:04d}"
    # Every third entity carries an icon, so the fixture exercises both the
    # present and the omitted `i` shape of an `IndexEntry`.
    icon = f"InvSprite:{kind.value}-{index}" if index % 3 == 0 else None
    return Entity(
        id=entity_id,
        kind=kind,
        name=f"{kind.value.title()} {index}",
        aliases=(f"{kind.value}{index}-alias",),
        icon=icon,
        source_tiers={},
        sections=(),
    )


def _build_merge_result() -> MergeResult:
    entities = tuple(
        _entity(kind, index) for kind in EntityKind for index in range(ENTITIES_PER_KIND)
    )
    return MergeResult(
        entities=entities,
        by_id={entity.id: entity for entity in entities},
        report=MergeReport(
            advancement_reconciliation=Reconciliation(
                matched=(), missing_from_wiki=(), missing_from_tier_a=()
            )
        ),
    )


BUILD = BuildInfo.model_validate(
    {
        "minecraft_version": "26.2",
        "mcmeta_ref": "26.2-data",
        "built_at": "2026-08-31T00:00:00+00:00",
    }
)


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    """Write the full fixture into `tmp_path` once, and hand back the `dist` root."""
    dist = tmp_path / "dist"
    result = _build_merge_result()
    report = emit_build(result, BUILD, dist=dist, shard_size=SHARD_SIZE)
    dist.joinpath("_report.json").write_text(
        json.dumps(report.model_dump(mode="json")), encoding="utf-8"
    )
    return dist


def _report(dist: Path) -> dict[str, Any]:
    """Re-read the `EmitReport` this module's own fixture stashed alongside the build.

    Kept out of the payload the real build writes -- `_report.json` is not one
    of `emit_build`'s own files, it is this test file's way of handing the
    fixture's `EmitReport` from the `snapshot` fixture to the tests that need
    it without recomputing the build a second time.
    """
    document: dict[str, Any] = json.loads(dist.joinpath("_report.json").read_text(encoding="utf-8"))
    return document


def test_the_full_file_tree_matches_the_expected_shard_layout(snapshot: Path) -> None:
    expected_shard_count_per_kind = -(-ENTITIES_PER_KIND // SHARD_SIZE)  # ceil division
    expected_shards = {
        f"{kind.value}-{index}.json"
        for kind in EntityKind
        for index in range(expected_shard_count_per_kind)
    }

    actual_shards = {path.name for path in (snapshot / "entities").glob("*.json")}
    assert actual_shards == expected_shards

    assert (snapshot / "index.json").is_file()
    assert (snapshot / "manifest.json").is_file()


def test_every_index_entry_names_a_shard_that_exists_and_holds_that_id(snapshot: Path) -> None:
    index = json.loads((snapshot / "index.json").read_text(encoding="utf-8"))
    assert len(index["entities"]) == len(EntityKind) * ENTITIES_PER_KIND

    # Cache each shard file's own id set once, rather than re-reading and
    # re-parsing the same file for every one of its entries.
    shard_ids: dict[str, set[str]] = {}

    for entry in index["entities"]:
        shard_name = entry["s"]
        if shard_name not in shard_ids:
            shard_path = snapshot / "entities" / f"{shard_name}.json"
            assert shard_path.is_file(), f"index names shard {shard_name!r}, which does not exist"
            shard_document = json.loads(shard_path.read_text(encoding="utf-8"))
            shard_ids[shard_name] = {entity["id"] for entity in shard_document["entities"]}
        assert entry["id"] in shard_ids[shard_name]


def test_every_index_entry_omits_the_icon_key_exactly_when_the_entity_has_none(
    snapshot: Path,
) -> None:
    index = json.loads((snapshot / "index.json").read_text(encoding="utf-8"))
    for entry in index["entities"]:
        # `_entity` gives every third index an icon; the id ends in the
        # zero-padded index this fixture built it from.
        source_index = int(entry["id"].rsplit("_", 1)[-1])
        if source_index % 3 == 0:
            assert "i" in entry
        else:
            assert "i" not in entry


def test_the_shards_and_the_index_agree_with_the_returned_report(snapshot: Path) -> None:
    report = _report(snapshot)
    assert report["entity_count"] == len(EntityKind) * ENTITIES_PER_KIND
    assert len(report["shards"]) == len({p.name for p in (snapshot / "entities").glob("*.json")})

    index_bytes = (snapshot / "index.json").read_bytes()
    assert report["index_bytes"] == len(index_bytes)


def test_the_snapshot_stays_under_a_generous_gzipped_ceiling(snapshot: Path) -> None:
    """Print the real measured size, and pin only a loose ceiling against it.

    `TODO.md` Phase 4 gives the real budget this figure feeds: a keystroke has
    16 ms against the whole loaded index. That budget is a Phase 4 concern to
    assert precisely once the real ~5,000-entity index exists; this fixture is
    120 entities, so the meaningful thing this test can do today is print the
    true number for a human to sanity-check and assert it has not blown up by
    an order of magnitude, which is what would signal a real regression this
    early.
    """
    report = _report(snapshot)
    gzipped = report["index_gzipped_bytes"]
    total = len(EntityKind) * ENTITIES_PER_KIND
    print(f"\nmeasured index.json gzipped size for {total} entities: {gzipped} bytes")
    assert 0 < gzipped <= report["index_bytes"]
    assert gzipped < GZIPPED_CEILING_BYTES
