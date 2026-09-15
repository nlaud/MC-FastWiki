"""`BuildSnapshot`'s two constructors: from a fresh `MergeResult`, and from a committed `data/dist`.

The `from_merge_result` tests below build their own small fixtures, so they assert exact numbers
and always will: three entities in, three entities out.

`test_from_dist_reads_the_real_committed_baseline` is the one that reads this repository's real
`data/dist`, and it asserts no counts at all. It used to. An earlier version of this docstring
cited "2120 entities, 15 shards, the 4002-producer obtain graph, the 1901-key sprite atlas" as
measured on 2026-09-02, and went on to say the assertions existed to catch `from_dist` reading the
tree wrong, "not to pin `data/dist` itself in place". Both halves aged badly: not one of those four
figures was still true, and the test pinned the tree anyway with roughly thirty-eight constants.
The weekly wiki refresh settled it by moving a count with no commit behind it. That test now checks
what this paragraph always claimed it checked. See its own docstring for the full reasoning.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Any

from pipeline.enrich.advancement import Reconciliation
from pipeline.normalize.entity import (
    DropTable,
    Entity,
    EntityKind,
    Section,
    SpawnInfo,
    StatBlock,
)
from pipeline.normalize.merge import MergeReport, MergeResult
from pipeline.obtain.producer import ObtainMethod, Producer, ProducerIndex, ProducerOutput
from pipeline.validate.snapshot import OPTIONAL_ENTITY_FIELDS, REQUIRED_ENTITY_FIELDS, BuildSnapshot

DIST = Path("data") / "dist"


def _reconciliation() -> Reconciliation:
    return Reconciliation(matched=(), missing_from_wiki=(), missing_from_tier_a=())


def _entity(
    entity_id: str,
    kind: EntityKind = EntityKind.ITEM,
    *,
    wiki_url: str | None = None,
    blurb: str | None = None,
    icon: str | None = None,
    sections: tuple[Section, ...] = (),
) -> Entity:
    return Entity(
        id=entity_id,
        kind=kind,
        name=entity_id.split(":", 1)[-1],
        aliases=(),
        wiki_url=wiki_url,
        blurb=blurb,
        icon=icon,
        source_tiers={},
        sections=sections,
    )


def _merge_result(entities: tuple[Entity, ...]) -> MergeResult:
    return MergeResult(
        entities=entities,
        by_id={entity.id: entity for entity in entities},
        report=MergeReport(advancement_reconciliation=_reconciliation()),
    )


def test_from_merge_result_counts_kinds_fields_and_sections() -> None:
    entities = (
        _entity(
            "minecraft:creeper",
            EntityKind.MOB,
            wiki_url="https://minecraft.wiki/w/Creeper",
            blurb="A hissing creature.",
            sections=(
                StatBlock(),
                SpawnInfo(),
            ),
        ),
        _entity("minecraft:zombie", EntityKind.MOB, sections=(DropTable(),)),
        _entity("minecraft:apple", EntityKind.ITEM, icon="ItemSprite:apple"),
    )
    result = _merge_result(entities)
    producer_index = ProducerIndex.from_producers(
        [
            Producer(
                method=ObtainMethod.CRAFTING,
                output=ProducerOutput(item="minecraft:apple"),
                inputs=(),
                source_id="apple",
            )
        ]
    )

    snapshot = BuildSnapshot.from_merge_result(result, producer_index)

    assert snapshot.total == 3
    assert snapshot.by_kind == {"mob": 2, "item": 1}
    assert snapshot.required_field_coverage == dict.fromkeys(REQUIRED_ENTITY_FIELDS, 3)
    assert snapshot.optional_field_coverage == {"wikiUrl": 1, "blurb": 1, "icon": 1}
    assert snapshot.section_type_counts == {"StatBlock": 1, "SpawnInfo": 1, "DropTable": 1}
    assert snapshot.obtain_producer_count == 1


def test_from_merge_result_defaults_to_an_empty_producer_index() -> None:
    result = _merge_result((_entity("minecraft:apple"),))
    snapshot = BuildSnapshot.from_merge_result(result)
    assert snapshot.obtain_producer_count == 0


def test_from_dist_reads_the_real_committed_baseline() -> None:
    """The false-positive test for the *snapshot* half: `from_dist` must read this repository's
    own `data/dist` back correctly.

    Every assertion below is a cross-check or an invariant. None of them pins a count.

    That is a deliberate reversal, and the reason is worth keeping. This test used to assert
    roughly thirty-eight exact figures -- the total, an eleven-entry per-kind dict, three optional
    coverage figures, twenty section-type counts, the producer count and the atlas count -- each
    trailed by a comment explaining which commit had last moved it. That worked while the only
    thing that moved these numbers was a change in this repository. The weekly wiki refresh broke
    the arrangement: it rebuilds from the wiki's own tables on a schedule, so a count can now move
    with no commit behind it at all. The first refresh to run added three Wandering Trader trades
    and reddened `main`, and a release bump would move most of the thirty-eight at once.

    The module docstring of this file already named the right intent -- these assertions exist to
    catch `from_dist` reading the tree wrong, "not to pin `data/dist` itself in place" -- so the
    fix is to assert that, and nothing else. Guarding against data that shrinks when it should not
    is a real job, but it belongs to `pipeline.validate.regression`, which does it with percentage
    rules against the committed baseline rather than with constants a person has to retype.

    The retired figures and the changelog comments that explained each move are in this file's git
    history. They are not maintained here any more, because a number nobody can update without
    rerunning a build is a number that goes stale silently -- this file's own module docstring
    still cites 2120 entities and a 4002-producer graph, and neither has been true for many
    commits.
    """
    snapshot = BuildSnapshot.from_dist(DIST)
    assert snapshot is not None

    # The strongest check available: `index.json` is written by
    # `pipeline.emit.search_index` while the shards are written by
    # `pipeline.emit.shard`, and the two spell the same field differently
    # (`k` against `kind`). So agreement between them is a genuine
    # cross-check of two independently produced files rather than this test
    # restating `from_dist`'s own arithmetic back to itself.
    index_payload: Any = json.loads((DIST / "index.json").read_text(encoding="utf-8"))
    index_entries = index_payload["entities"]
    assert snapshot.total == len(index_entries)
    assert snapshot.by_kind == dict(Counter(entry["k"] for entry in index_entries))

    # Internal consistency: every entity carries a kind, so the per-kind
    # breakdown has to add back up to the total.
    assert snapshot.total == sum(snapshot.by_kind.values())

    # A required field is required. This is the one coverage figure that is a
    # contract rather than a measurement, so it is still asserted exactly --
    # against the total this build actually has, not against a constant.
    assert snapshot.required_field_coverage == dict.fromkeys(REQUIRED_ENTITY_FIELDS, snapshot.total)

    # An optional field is optional, so the only thing true of every build is
    # that each one is carried by at least one entity and by no more than all
    # of them. A field that reached zero would mean the emitter stopped
    # writing it, which is the fault worth catching here.
    assert set(snapshot.optional_field_coverage) == set(OPTIONAL_ENTITY_FIELDS)
    for field, count in snapshot.optional_field_coverage.items():
        assert 0 < count <= snapshot.total, f"optional field {field!r} has coverage {count}"

    # Section counts, recounted from the shards by a flat `Counter` over a
    # generator rather than by `from_dist`'s nested increments. A shard the
    # glob misses, a double count, or a read of the wrong key all show up as
    # a disagreement.
    scanned: Counter[str] = Counter(
        section["type"]
        for shard_path in sorted((DIST / "entities").glob("*.json"))
        for entity in json.loads(shard_path.read_text(encoding="utf-8"))["entities"]
        for section in entity.get("sections", ())
        if isinstance(section, dict) and isinstance(section.get("type"), str)
    )
    assert snapshot.section_type_counts == dict(scanned)

    # The other two payloads, each checked against the file it is read from.
    obtain_payload: Any = json.loads((DIST / "obtain.json").read_text(encoding="utf-8"))
    assert snapshot.obtain_producer_count == sum(
        len(group) for group in obtain_payload["producers"].values()
    )

    atlas_payload: Any = json.loads((DIST / "sprites.json").read_text(encoding="utf-8"))
    assert snapshot.atlas_icon_count == len(atlas_payload["sprites"])

    # A floor, not a pin. Every assertion above compares one committed file
    # against another, so all of them would hold if `data/dist` were replaced
    # by a handful of entities. This is the one line that says the baseline is
    # a real build. It is deliberately far below any plausible real total, so
    # that content changes never reach it.
    assert snapshot.total > 1000
    assert snapshot.obtain_producer_count > 1000
    assert snapshot.atlas_icon_count > 1000



def test_from_dist_counts_a_required_field_that_a_shard_omits(tmp_path: Path) -> None:
    """Coverage of a required field must fall when an entity does not carry it.

    The real-baseline test above cannot prove this. Every entity in the committed `data/dist`
    carries every required field, so `from_dist` counting the field properly and `from_dist` not
    checking at all produce the identical answer there -- a mutation that deletes the `if field in
    entity` guard passes that test untouched. It only shows up against a shard that actually omits
    one, which is what this fixture is.
    """
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    (entities_dir / "item-0.json").write_text(
        '{"schemaVersion":1,"entities":['
        '{"id":"minecraft:apple","kind":"item","name":"Apple","aliases":[],'
        '"sourceTiers":{},"sections":[]},'
        '{"id":"minecraft:stick","kind":"item","name":"Stick","aliases":[],'
        '"sourceTiers":{}}'
        "]}",
        encoding="utf-8",
    )

    snapshot = BuildSnapshot.from_dist(tmp_path)

    assert snapshot is not None
    assert snapshot.total == 2
    # Only the apple carries `sections`; every other required field is on both.
    assert snapshot.required_field_coverage["sections"] == 1
    assert snapshot.required_field_coverage["id"] == 2


def test_from_dist_is_none_for_an_absent_directory(tmp_path: Path) -> None:
    assert BuildSnapshot.from_dist(tmp_path / "does-not-exist") is None


def test_from_dist_is_none_for_an_entities_directory_with_no_shards(tmp_path: Path) -> None:
    (tmp_path / "entities").mkdir()
    assert BuildSnapshot.from_dist(tmp_path) is None


def test_from_dist_is_none_when_every_shard_holds_no_entities(tmp_path: Path) -> None:
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    (entities_dir / "item-0.json").write_text(
        '{"schemaVersion":1,"entities":[]}', encoding="utf-8"
    )
    assert BuildSnapshot.from_dist(tmp_path) is None


def test_from_dist_ignores_a_missing_obtain_json(tmp_path: Path) -> None:
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    (entities_dir / "item-0.json").write_text(
        '{"schemaVersion":1,"entities":[{"id":"minecraft:apple","kind":"item","name":"Apple",'
        '"aliases":[],"sourceTiers":{},"sections":[]}]}',
        encoding="utf-8",
    )
    snapshot = BuildSnapshot.from_dist(tmp_path)
    assert snapshot is not None
    assert snapshot.total == 1
    assert snapshot.obtain_producer_count == 0


def test_from_dist_reads_zero_atlas_icons_when_sprites_json_is_absent(tmp_path: Path) -> None:
    """A `data/dist` with entity shards but no `sprites.json` at all -- a build that predates the
    atlas -- must read back as zero rather than raising, the same tolerant path `obtain.json`'s own
    absence already takes.
    """
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    (entities_dir / "item-0.json").write_text(
        '{"schemaVersion":1,"entities":[{"id":"minecraft:apple","kind":"item","name":"Apple",'
        '"aliases":[],"sourceTiers":{},"sections":[]}]}',
        encoding="utf-8",
    )
    snapshot = BuildSnapshot.from_dist(tmp_path)
    assert snapshot is not None
    assert snapshot.atlas_icon_count == 0


def test_from_dist_reads_zero_atlas_icons_when_sprites_is_not_a_dict(tmp_path: Path) -> None:
    """A `sprites.json` whose `sprites` value is not a dict is an unexpected shape, not a baseline
    to raise over -- matches `from_dist`'s own tolerant reads of `obtain.json`'s `producers`.
    """
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    (entities_dir / "item-0.json").write_text(
        '{"schemaVersion":1,"entities":[{"id":"minecraft:apple","kind":"item","name":"Apple",'
        '"aliases":[],"sourceTiers":{},"sections":[]}]}',
        encoding="utf-8",
    )
    (tmp_path / "sprites.json").write_text(
        '{"schemaVersion":1,"image":"sprites.png","width":512,"height":16,"sprites":[]}',
        encoding="utf-8",
    )
    snapshot = BuildSnapshot.from_dist(tmp_path)
    assert snapshot is not None
    assert snapshot.atlas_icon_count == 0


def test_from_merge_result_defaults_atlas_icon_count_to_zero() -> None:
    result = _merge_result((_entity("minecraft:apple"),))
    snapshot = BuildSnapshot.from_merge_result(result)
    assert snapshot.atlas_icon_count == 0


def test_from_merge_result_carries_the_given_atlas_icon_count() -> None:
    result = _merge_result((_entity("minecraft:apple"),))
    snapshot = BuildSnapshot.from_merge_result(result, atlas_icon_count=1901)
    assert snapshot.atlas_icon_count == 1901


def test_optional_and_required_field_constants_are_disjoint() -> None:
    assert set(REQUIRED_ENTITY_FIELDS).isdisjoint(OPTIONAL_ENTITY_FIELDS)
