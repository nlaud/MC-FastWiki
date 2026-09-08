"""`BuildSnapshot`'s two constructors: from a fresh `MergeResult`, and from a committed `data/dist`.

The real baseline numbers asserted below (2120 entities, 15 shards, the per-kind breakdown, the
section-type counts, the 4002-producer obtain graph, the 1901-key sprite atlas) were measured
against the committed `data/dist` on 2026-09-02, the same measurement `pipeline.validate`'s own
module docstring and this task's brief both cite. A future build of a newer Minecraft version will
change these numbers, and that is expected -- these assertions exist to catch `BuildSnapshot.
from_dist` reading the tree wrong, not to pin `data/dist` itself in place.
"""

from pathlib import Path

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
    """The false-positive test for the *snapshot* half: this repository's own `data/dist` must
    read back with the exact numbers the module docstring and this task's brief both cite.
    """
    snapshot = BuildSnapshot.from_dist(DIST)

    assert snapshot is not None
    assert snapshot.total == 2141
    assert snapshot.by_kind == {
        "block": 1195,
        "item": 540,
        "advancement": 126,
        "mob": 91,
        "biome": 66,
        "enchantment": 43,
        "effect": 39,
        "entity": 28,
        "profession": 13,
    }
    assert snapshot.required_field_coverage == dict.fromkeys(REQUIRED_ENTITY_FIELDS, 2141)
    # 2035 before minecraft:nether/brew_potion (Local Brewery) received a curated icon override.
    # 2097 wikiUrl, 1971 blurb, 2036 icon before 13 villager professions were added.
    assert snapshot.optional_field_coverage == {"wikiUrl": 2110, "blurb": 1984, "icon": 2049}
    assert snapshot.section_type_counts == {
        "AdvancementInfo": 126,
        # 157 before `_wiki_rows` learned to fall back from `Enchanted <item>`
        # to `<item>`. 169 before Potato trade disambiguation resolved onto
        # minecraft:potato. 170 before 13 villager professions and Wandering
        # Trader mob trades attached.
        "TradeTable": 184,
        "StatBlock": 93,
        "DropTable": 65,
        "SpawnInfo": 53,
        "BreedingInfo": 26,
        # 44 items with a `minecraft:food` component, plus the milk bucket,
        # which clears every effect while restoring no hunger. `ominous_bottle`
        # is the third consumable-only item and is deliberately absent: its
        # whole consume behaviour is a sound, which a page cannot draw.
        "FoodInfo": 45,
        "HarvestInfo": 861,
        "EffectSources": 39,
        "GenerationInfo": 52,
        "EnchantInfo": 43,
        "ProfessionInfo": 13,
    }
    # 3998 before Arrow of * mob drops (Bogged, Parched, Stray) resolved to minecraft:tipped_arrow.
    # 4001 before 10 unread loot table families added 267 producers.
    # 4268 before 6 unhandled recipe types added 43 producers.
    # 4311 before curated one-off producers added 14 producers.
    # 4325 before 12 creeper-dropped music discs were expanded.
    assert snapshot.obtain_producer_count == 4337
    # 1914 before Local Brewery (InvSprite:Potion) and Ominous Banner (BlockSprite:ominous-banner)
    # joined the atlas. 1916 before 13 profession icons joined the atlas.
    assert snapshot.atlas_icon_count == 1929


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
