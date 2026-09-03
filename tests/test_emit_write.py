"""`emit_build`: the writer, and the four rules its module docstring names.

Every test here writes into `tmp_path`, never into the real `data/dist` --
`emit_build`'s default `dist` argument is never exercised by this file, only
its override.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pipeline.emit import EmitError
from pipeline.emit.atlas import Atlas, DecodedSprite, pack_atlas
from pipeline.emit.manifest import BuildInfo
from pipeline.emit.write import emit_build
from pipeline.enrich.advancement import Reconciliation
from pipeline.normalize.entity import Entity, EntityKind
from pipeline.normalize.merge import MergeReport, MergeResult
from pipeline.validate import ValidationError
from pipeline.validate.conformance import GateDocuments

BUILD = BuildInfo(
    minecraft_version="26.2", mcmeta_ref="26.2-data", built_at=datetime(2026, 8, 31, tzinfo=UTC)
)


def _entity(entity_id: str, kind: EntityKind = EntityKind.ITEM) -> Entity:
    return Entity(
        id=entity_id,
        kind=kind,
        name=entity_id.split(":", 1)[-1],
        aliases=(),
        source_tiers={},
        sections=(),
    )


def _atlas() -> Atlas:
    """Return a small, real `Atlas` built through `pack_atlas`, not a hand-assembled stand-in."""
    sprite = DecodedSprite(width=2, height=2, rgba=bytes((1, 2, 3, 4)) * 4)
    return pack_atlas({"File:Apple.png": sprite}, {"InvSprite:Apple": "File:Apple.png"})


def _merge_result(entities: tuple[Entity, ...]) -> MergeResult:
    return MergeResult(
        entities=entities,
        by_id={entity.id: entity for entity in entities},
        report=MergeReport(
            advancement_reconciliation=Reconciliation(
                matched=(), missing_from_wiki=(), missing_from_tier_a=()
            )
        ),
    )


def test_rebuilding_unchanged_input_produces_byte_identical_shards_and_index(
    tmp_path: Path,
) -> None:
    result = _merge_result((_entity("minecraft:apple"), _entity("minecraft:zombie")))

    first = tmp_path / "first"
    second = tmp_path / "second"
    emit_build(result, BUILD, dist=first)
    emit_build(result, BUILD, dist=second)

    for name in ("index.json", "entities/item-0.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_manifest_json_differs_only_by_the_clock_reading(tmp_path: Path) -> None:
    """The one file decision D1 excepts from byte-for-byte determinism."""
    result = _merge_result((_entity("minecraft:apple"),))

    first = tmp_path / "first"
    second = tmp_path / "second"
    emit_build(result, BUILD, dist=first)
    later_build = BuildInfo(
        minecraft_version="26.2",
        mcmeta_ref="26.2-data",
        built_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    emit_build(result, later_build, dist=second)

    assert (first / "manifest.json").read_bytes() != (second / "manifest.json").read_bytes()
    assert (first / "index.json").read_bytes() == (second / "index.json").read_bytes()


def test_every_written_file_ends_with_exactly_one_lf_newline_and_no_cr(tmp_path: Path) -> None:
    result = _merge_result((_entity("minecraft:apple"),))
    emit_build(result, BUILD, dist=tmp_path)

    for name in ("index.json", "manifest.json", "entities/item-0.json"):
        data = (tmp_path / name).read_bytes()
        assert b"\r" not in data
        assert data.endswith(b"\n")
        assert not data.endswith(b"\n\n")


def test_a_shrinking_build_sweeps_the_shards_the_new_build_no_longer_writes(
    tmp_path: Path,
) -> None:
    big = _merge_result(
        (
            _entity("minecraft:apple", EntityKind.ITEM),
            _entity("minecraft:creeper", EntityKind.MOB),
            _entity("minecraft:mud", EntityKind.BLOCK),
        )
    )
    emit_build(big, BUILD, dist=tmp_path)
    assert (tmp_path / "entities" / "item-0.json").exists()
    assert (tmp_path / "entities" / "mob-0.json").exists()
    assert (tmp_path / "entities" / "block-0.json").exists()

    # A file outside `entities/` that this build never wrote or knows about.
    # The sweep must never reach it -- it is not even a `.json` shard, it is
    # proof the sweep is scoped to one directory rather than to "everything
    # under dist that this build did not write".
    sentinel = tmp_path / "sprites.png"
    sentinel.write_bytes(b"not a shard")

    small = _merge_result((_entity("minecraft:apple", EntityKind.ITEM),))
    report = emit_build(small, BUILD, dist=tmp_path)

    assert not (tmp_path / "entities" / "mob-0.json").exists()
    assert not (tmp_path / "entities" / "block-0.json").exists()
    assert (tmp_path / "entities" / "item-0.json").exists()
    assert sentinel.exists()
    assert set(report.removed) == {"entities/mob-0.json", "entities/block-0.json"}


def test_an_empty_merge_result_is_refused(tmp_path: Path) -> None:
    empty = _merge_result(())
    with pytest.raises(EmitError, match="no entities"):
        emit_build(empty, BUILD, dist=tmp_path / "dist")
    assert not (tmp_path / "dist").exists()


def test_a_dist_path_that_is_a_plain_file_is_refused(tmp_path: Path) -> None:
    result = _merge_result((_entity("minecraft:apple"),))
    not_a_directory = tmp_path / "dist"
    not_a_directory.write_text("not a directory", encoding="utf-8")

    with pytest.raises(EmitError, match="not a directory"):
        emit_build(result, BUILD, dist=not_a_directory)
    # Refused before any write; the file this call could not use is untouched.
    assert not_a_directory.read_text(encoding="utf-8") == "not a directory"


def test_nothing_is_written_when_the_build_is_refused(tmp_path: Path) -> None:
    """All-or-nothing: a shape fault must leave no partial `dist` behind."""
    empty = _merge_result(())
    dist = tmp_path / "dist"
    with pytest.raises(EmitError):
        emit_build(empty, BUILD, dist=dist)
    assert not dist.exists()


def test_the_report_names_every_shard_and_the_index_sizes(tmp_path: Path) -> None:
    result = _merge_result(
        (_entity("minecraft:apple"), _entity("minecraft:creeper", EntityKind.MOB))
    )
    report = emit_build(result, BUILD, dist=tmp_path)

    assert report.entity_count == 2
    assert {summary.name for summary in report.shards} == {"item-0", "mob-0"}
    assert report.index_bytes > 0
    assert 0 < report.index_gzipped_bytes <= report.index_bytes
    assert report.removed == ()


def test_a_shard_size_below_one_is_refused_before_anything_is_written(tmp_path: Path) -> None:
    """`emit_build` must surface `assign_shards`'s guard, not write an empty payload.

    A negative `shard_size` makes `range` empty rather than raising, so
    without the guard in `pipeline.emit.shard` this call would assign no
    shards, write an `index.json` naming nothing, and sweep every shard of the
    previous build away as stale -- reporting success the whole way. Asserting
    the refusal here, and not only in `tests/test_emit_shard.py`, is what ties
    that guard to the all-or-nothing rule: `dist` must not exist afterwards.
    """
    result = _merge_result((_entity("minecraft:apple"),))
    dist = tmp_path / "dist"
    with pytest.raises(EmitError, match="at least one"):
        emit_build(result, BUILD, dist=dist, shard_size=-1)
    assert not dist.exists()


# --- The `gate` keyword: pipeline.validate's hook point, per Option A ------------------


def test_a_none_gate_is_the_default_and_changes_nothing(tmp_path: Path) -> None:
    result = _merge_result((_entity("minecraft:apple"),))
    report = emit_build(result, BUILD, dist=tmp_path)
    assert report.entity_count == 1


def test_the_gate_sees_the_documents_this_build_is_about_to_write(tmp_path: Path) -> None:
    result = _merge_result(
        (_entity("minecraft:apple"), _entity("minecraft:creeper", EntityKind.MOB))
    )
    seen: list[GateDocuments] = []

    def gate(documents: GateDocuments) -> None:
        seen.append(documents)

    emit_build(result, BUILD, dist=tmp_path, gate=gate)

    assert len(seen) == 1
    documents = seen[0]
    assert set(documents.shards) == {"item-0", "mob-0"}
    item_ids = {entity["id"] for entity in documents.shards["item-0"]["entities"]}
    assert item_ids == {"minecraft:apple"}
    assert documents.index["schemaVersion"] == 1
    assert documents.manifest["minecraftVersion"] == "26.2"
    assert documents.obtain == {"schemaVersion": 1, "producers": {}}


def test_the_gate_runs_before_anything_is_written(tmp_path: Path) -> None:
    result = _merge_result((_entity("minecraft:apple"),))
    written_before_gate_ran = []

    def gate(documents: GateDocuments) -> None:
        written_before_gate_ran.append((tmp_path / "index.json").exists())

    emit_build(result, BUILD, dist=tmp_path, gate=gate)

    assert written_before_gate_ran == [False]
    assert (tmp_path / "index.json").exists()


def test_a_build_whose_gate_fails_writes_nothing(tmp_path: Path) -> None:
    """All-or-nothing extends to the gate: a refusal must leave no trace on disk at all."""
    result = _merge_result((_entity("minecraft:apple"),))
    dist = tmp_path / "dist"

    def refusing_gate(documents: GateDocuments) -> None:
        raise ValidationError("no thank you")

    with pytest.raises(ValidationError, match="no thank you"):
        emit_build(result, BUILD, dist=dist, gate=refusing_gate)

    assert not dist.exists()


def test_a_build_whose_gate_fails_after_a_previous_build_leaves_that_build_untouched(
    tmp_path: Path,
) -> None:
    """A refused *second* build must not disturb what an earlier, accepted build already wrote."""
    first = _merge_result((_entity("minecraft:apple"),))
    emit_build(first, BUILD, dist=tmp_path)
    before = (tmp_path / "index.json").read_bytes()

    second = _merge_result(
        (_entity("minecraft:apple"), _entity("minecraft:zombie", EntityKind.MOB))
    )

    def refusing_gate(documents: GateDocuments) -> None:
        raise ValidationError("refused")

    with pytest.raises(ValidationError):
        emit_build(second, BUILD, dist=tmp_path, gate=refusing_gate)

    assert (tmp_path / "index.json").read_bytes() == before
    assert not (tmp_path / "entities" / "mob-0.json").exists()


def test_the_gate_receiving_the_same_dicts_that_get_encoded_keeps_writes_deterministic(
    tmp_path: Path,
) -> None:
    """The gate must see the identical payload objects `_encode` serialises, not a second,
    independently rebuilt copy that could drift from what is actually written.
    """
    result = _merge_result((_entity("minecraft:apple"),))
    seen: list[GateDocuments] = []

    def gate(documents: GateDocuments) -> None:
        seen.append(documents)

    emit_build(result, BUILD, dist=tmp_path, gate=gate)

    on_disk = json.loads((tmp_path / "entities" / "item-0.json").read_text(encoding="utf-8"))
    assert seen[0].shards["item-0"] == on_disk


# --- The `atlas` keyword ---------------------------------------------------------------


def test_atlas_none_is_the_default_and_writes_neither_sprite_file(tmp_path: Path) -> None:
    result = _merge_result((_entity("minecraft:apple"),))
    report = emit_build(result, BUILD, dist=tmp_path)

    assert not (tmp_path / "sprites.png").exists()
    assert not (tmp_path / "sprites.json").exists()
    assert report.atlas_frame_count == 0
    assert report.atlas_png_bytes == 0
    assert report.atlas_map_bytes == 0
    assert report.atlas_map_gzipped_bytes == 0


def test_a_real_atlas_writes_both_sprite_files(tmp_path: Path) -> None:
    result = _merge_result((_entity("minecraft:apple"),))
    atlas = _atlas()

    report = emit_build(result, BUILD, dist=tmp_path, atlas=atlas)

    assert (tmp_path / "sprites.png").read_bytes() == atlas.png
    written_map = json.loads((tmp_path / "sprites.json").read_text(encoding="utf-8"))
    assert written_map == atlas.coordinates.model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    assert report.atlas_frame_count == 1
    assert report.atlas_png_bytes == len(atlas.png)
    assert report.atlas_map_bytes > 0
    assert 0 < report.atlas_map_gzipped_bytes <= report.atlas_map_bytes


def test_sprites_json_ends_with_exactly_one_lf_newline_and_no_cr(tmp_path: Path) -> None:
    result = _merge_result((_entity("minecraft:apple"),))
    emit_build(result, BUILD, dist=tmp_path, atlas=_atlas())

    data = (tmp_path / "sprites.json").read_bytes()
    assert b"\r" not in data
    assert data.endswith(b"\n")
    assert not data.endswith(b"\n\n")


def test_the_gate_sees_the_atlas_map_document_when_one_is_given(tmp_path: Path) -> None:
    result = _merge_result((_entity("minecraft:apple"),))
    atlas = _atlas()
    seen: list[GateDocuments] = []

    def gate(documents: GateDocuments) -> None:
        seen.append(documents)

    emit_build(result, BUILD, dist=tmp_path, gate=gate, atlas=atlas)

    assert seen[0].atlas == atlas.coordinates.model_dump(
        mode="json", by_alias=True, exclude_none=True
    )


def test_the_gate_sees_no_atlas_document_when_none_is_given(tmp_path: Path) -> None:
    result = _merge_result((_entity("minecraft:apple"),))
    seen: list[GateDocuments] = []

    def gate(documents: GateDocuments) -> None:
        seen.append(documents)

    emit_build(result, BUILD, dist=tmp_path, gate=gate)

    assert seen[0].atlas is None


def test_a_build_whose_gate_fails_writes_neither_sprite_file(tmp_path: Path) -> None:
    """All-or-nothing extends to the atlas exactly as it does to every other document."""
    result = _merge_result((_entity("minecraft:apple"),))
    dist = tmp_path / "dist"

    def refusing_gate(documents: GateDocuments) -> None:
        raise ValidationError("no thank you")

    with pytest.raises(ValidationError, match="no thank you"):
        emit_build(result, BUILD, dist=dist, gate=refusing_gate, atlas=_atlas())

    assert not dist.exists()


def test_an_atlas_less_rebuild_leaves_a_previous_builds_sprite_files_alone(tmp_path: Path) -> None:
    """Rule 2's stale-file sweep is scoped to `data/dist/entities/`, on purpose: an `atlas=None`
    build must not delete sprite files an earlier, atlas-writing build left behind.
    """
    result = _merge_result((_entity("minecraft:apple"),))
    emit_build(result, BUILD, dist=tmp_path, atlas=_atlas())
    png_before = (tmp_path / "sprites.png").read_bytes()
    map_before = (tmp_path / "sprites.json").read_bytes()

    emit_build(result, BUILD, dist=tmp_path)

    assert (tmp_path / "sprites.png").read_bytes() == png_before
    assert (tmp_path / "sprites.json").read_bytes() == map_before
