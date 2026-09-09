"""`validate_conformance`: every document `pipeline.emit.write.emit_build` is about to write,
checked against its schema.

The most important test in this file is `test_the_real_committed_dist_passes_conformance`: the
false-positive test. A gate that refused this repository's own committed, already-shipped
`data/dist` would be useless on day one -- every other test here builds a small, synthetic
`GateDocuments` and checks one failure mode at a time, but only this one proves the validator
agrees with 2120 real entities across 15 real shards that this pipeline itself produced.
"""

import json
from pathlib import Path

from pipeline.validate.conformance import (
    DEFAULT_MAX_FAILURES,
    GateDocuments,
    validate_conformance,
)

DIST = Path("data") / "dist"

_MANIFEST = {
    "schemaVersion": 1,
    "minecraftVersion": "26.2",
    "mcmetaRef": "26.2-data",
    "pipelineVersion": "0.1.0",
    "builtAt": "2026-09-02T00:00:00Z",
}
_INDEX = {
    "schemaVersion": 1,
    "entities": [{"id": "minecraft:apple", "n": "Apple", "k": "item", "a": [], "s": "item-0"}],
}
_OBTAIN: dict[str, object] = {"schemaVersion": 1, "producers": {}}
_ATLAS: dict[str, object] = {
    "schemaVersion": 1,
    "image": "sprites.png",
    "width": 4,
    "height": 2,
    "sprites": {"InvSprite:Apple": {"x": 0, "y": 0, "w": 4, "h": 2}},
}


def _apple(**overrides: object) -> dict[str, object]:
    entity: dict[str, object] = {
        "id": "minecraft:apple",
        "kind": "item",
        "name": "Apple",
        "aliases": [],
        "sourceTiers": {},
        "sections": [],
    }
    entity.update(overrides)
    return entity


def _shard(*entities: dict[str, object]) -> dict[str, object]:
    return {"schemaVersion": 1, "entities": list(entities)}


def _load_real_dist_documents() -> GateDocuments:
    """Read this repository's own committed `data/dist` into a `GateDocuments`.

    A test-only helper, not production code: `pipeline.validate.snapshot.BuildSnapshot.from_dist`
    reads the same tree for a different purpose (counts, not full documents) and deliberately does
    not return the full parsed payloads, so this function is not a duplicate of anything the
    pipeline itself needs at build time.
    """
    shards = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((DIST / "entities").glob("*.json"))
    }
    index = json.loads((DIST / "index.json").read_text(encoding="utf-8"))
    obtain = json.loads((DIST / "obtain.json").read_text(encoding="utf-8"))
    manifest = json.loads((DIST / "manifest.json").read_text(encoding="utf-8"))
    return GateDocuments(shards=shards, index=index, obtain=obtain, manifest=manifest)


def test_the_real_committed_dist_passes_conformance() -> None:
    documents = _load_real_dist_documents()
    report = validate_conformance(documents)

    assert report.failures == ()
    assert report.truncated_count == 0
    assert report.checked["entity"] == 2175
    assert report.checked["shard"] == 17
    assert report.checked["index"] == 1
    assert report.checked["obtain"] == 1
    assert report.checked["manifest"] == 1


def test_a_well_formed_minimal_build_passes() -> None:
    documents = GateDocuments(
        shards={"item-0": _shard(_apple())}, index=_INDEX, obtain=_OBTAIN, manifest=_MANIFEST
    )
    report = validate_conformance(documents)
    assert report.failures == ()
    assert report.checked == {"entity": 1, "shard": 1, "index": 1, "obtain": 1, "manifest": 1}


def test_a_none_atlas_is_not_checked_and_is_not_a_failure() -> None:
    """`GateDocuments.atlas` defaults to `None`, matching `emit_build`'s own default -- a build
    with no sprite atlas must not fail conformance, and `checked` must not claim to have
    validated an atlas document it never saw.
    """
    documents = GateDocuments(
        shards={"item-0": _shard(_apple())}, index=_INDEX, obtain=_OBTAIN, manifest=_MANIFEST
    )
    report = validate_conformance(documents)
    assert report.failures == ()
    assert "atlas" not in report.checked


def test_a_well_formed_atlas_is_validated_and_counted() -> None:
    documents = GateDocuments(
        shards={"item-0": _shard(_apple())},
        index=_INDEX,
        obtain=_OBTAIN,
        manifest=_MANIFEST,
        atlas=_ATLAS,
    )
    report = validate_conformance(documents)
    assert report.failures == ()
    assert report.checked["atlas"] == 1


def test_a_malformed_atlas_fails_naming_the_atlas_document() -> None:
    broken_atlas = dict(_ATLAS)
    del broken_atlas["width"]
    documents = GateDocuments(
        shards={"item-0": _shard(_apple())},
        index=_INDEX,
        obtain=_OBTAIN,
        manifest=_MANIFEST,
        atlas=broken_atlas,
    )
    report = validate_conformance(documents)
    atlas_failures = [failure for failure in report.failures if failure.document == "atlas"]
    assert atlas_failures
    assert any("width" in failure.message for failure in atlas_failures)


def test_an_entity_with_sections_stripped_fails_naming_the_id_and_a_pointer() -> None:
    """`sections` is required by `entity.schema.json`; an entity dict missing it must fail,
    naming the entity's own id and a JSON pointer into the malformed document.
    """
    broken = _apple()
    del broken["sections"]
    documents = GateDocuments(
        shards={"item-0": _shard(broken)}, index=_INDEX, obtain=_OBTAIN, manifest=_MANIFEST
    )

    report = validate_conformance(documents)

    entity_failures = [failure for failure in report.failures if failure.document == "entity"]
    assert entity_failures
    assert all(failure.entity_id == "minecraft:apple" for failure in entity_failures)
    assert any("sections" in failure.message for failure in entity_failures)


def test_a_malformed_wiki_url_fails_with_a_pointer_into_the_field() -> None:
    broken = _apple(wikiUrl="https://minecraft.fandom.com/wiki/Apple")
    documents = GateDocuments(
        shards={"item-0": _shard(broken)}, index=_INDEX, obtain=_OBTAIN, manifest=_MANIFEST
    )

    report = validate_conformance(documents)

    assert report.failures
    failure = report.failures[0]
    assert failure.document == "entity"
    assert failure.entity_id == "minecraft:apple"
    assert failure.pointer == "/wikiUrl"


def test_a_malformed_shard_fails_naming_the_shard_document() -> None:
    documents = GateDocuments(
        shards={"item-0": {"schemaVersion": 1}},  # missing required "entities"
        index=_INDEX,
        obtain=_OBTAIN,
        manifest=_MANIFEST,
    )

    report = validate_conformance(documents)

    assert any(failure.document == "shard:item-0" for failure in report.failures)


def test_a_malformed_index_obtain_and_manifest_each_fail_naming_their_own_document() -> None:
    documents = GateDocuments(
        shards={"item-0": _shard(_apple())},
        index={"schemaVersion": 1},  # missing required "entities"
        obtain={"producers": {}},  # missing required "schemaVersion"
        manifest={"schemaVersion": "not-an-int"},
        # ^ manifest is also missing every other required field
    )

    report = validate_conformance(documents)

    documents_with_failures = {failure.document for failure in report.failures}
    assert documents_with_failures == {"index", "obtain", "manifest"}


def test_failures_are_capped_with_a_truncated_count() -> None:
    broken_entities = [_apple(id=f"minecraft:apple-{i}") for i in range(DEFAULT_MAX_FAILURES + 5)]
    for entity in broken_entities:
        del entity["sections"]
    documents = GateDocuments(
        shards={"item-0": _shard(*broken_entities)},
        index=_INDEX,
        obtain=_OBTAIN,
        manifest=_MANIFEST,
    )

    report = validate_conformance(documents, max_failures=DEFAULT_MAX_FAILURES)

    assert len(report.failures) == DEFAULT_MAX_FAILURES
    assert report.truncated_count == 5


def test_max_failures_is_configurable() -> None:
    broken_entities = [_apple(id=f"minecraft:apple-{i}") for i in range(10)]
    for entity in broken_entities:
        del entity["sections"]
    documents = GateDocuments(
        shards={"item-0": _shard(*broken_entities)},
        index=_INDEX,
        obtain=_OBTAIN,
        manifest=_MANIFEST,
    )

    report = validate_conformance(documents, max_failures=3)

    assert len(report.failures) == 3
    assert report.truncated_count == 7
