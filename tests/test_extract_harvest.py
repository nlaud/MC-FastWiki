"""The block tag resolver, and the harvest requirement that it produces.

CLAUDE.md gives Tier A one job: be complete and be right. A harvest requirement
is a number that a player reads mid-match and then acts on, so a wrong tier
costs the match. Every rule of `pipeline.extract.tags` and
`pipeline.extract.harvest` is pinned here, one test for each.

No test in this module opens a socket. Both modules are pure functions from
bytes to models, and each test builds its own tag files in memory. The helper
below writes one file of the vanilla shape.
"""

import json
import re
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

import pytest
from pydantic import ValidationError

from pipeline.extract import ExtractError
from pipeline.extract.harvest import (
    MINEABLE_TAG_TEMPLATE,
    NEEDS_TOOL_TAG_TEMPLATE,
    BlockHarvest,
    HarvestTier,
    HarvestTool,
    extract_block_harvest,
)
from pipeline.extract.tags import (
    BLOCK_REGISTRY,
    TagIndex,
    parse_tag_file,
    tag_file_path,
)


def archive(tags: Mapping[str, Iterable[Any]]) -> dict[str, bytes]:
    """Return an archive of block tag files. The key of `tags` is the tag path."""
    return {
        f"tags/{BLOCK_REGISTRY}/{path}.json": json.dumps({"values": list(values)}).encode()
        for path, values in tags.items()
    }


class CountingFiles(Mapping[str, bytes]):
    """The files of an archive, with a log of every read.

    `reads` proves that the resolver reads one tag file one time. A `Mapping`
    and not a `dict` subclass, because the mixin routes `get` and `in` through
    `__getitem__`, so one counter covers every way the resolver asks.
    """

    def __init__(self, files: Mapping[str, bytes]) -> None:
        self._files = files
        self.reads: list[str] = []

    def __getitem__(self, key: str) -> bytes:
        self.reads.append(key)
        return self._files[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._files)

    def __len__(self) -> int:
        return len(self._files)


def block_index(files: Mapping[str, bytes]) -> TagIndex:
    """An index over the block registry.

    `TagIndex` takes `registry` with no default, so every construction in this
    module names one. The test below the resolver group pins that.
    """
    return TagIndex(files, registry=BLOCK_REGISTRY)


def mineable(tool: HarvestTool) -> str:
    """Return the tag path of one `mineable` tag."""
    return MINEABLE_TAG_TEMPLATE.format(tool=tool.value)


def needs(tier: HarvestTier) -> str:
    """Return the tag path of one `needs_<material>_tool` tag."""
    return NEEDS_TOOL_TAG_TEMPLATE.format(tier=tier.value)


# The seven tags that `extract_block_harvest` reads, with no entry. A test adds
# the entries of the tags it cares about.
EMPTY_TAGS: dict[str, list[Any]] = {
    **{mineable(tool): [] for tool in HarvestTool},
    **{needs(tier): [] for tier in HarvestTier if tier is not HarvestTier.WOODEN},
}


def harvest_of(tags: Mapping[str, Iterable[Any]]) -> dict[str, BlockHarvest]:
    """Run the stage over the seven tags, with `tags` filled in."""
    return extract_block_harvest(archive({**EMPTY_TAGS, **tags}))


# --- The tag resolver ---


def test_the_resolver_returns_the_ids_of_a_flat_tag() -> None:
    index = block_index(archive({"mineable/pickaxe": ["minecraft:stone", "minecraft:iron_ore"]}))
    assert index.resolve("mineable/pickaxe") == frozenset({"minecraft:stone", "minecraft:iron_ore"})


def test_the_resolver_replaces_a_reference_with_the_ids_of_that_tag() -> None:
    """A `#` entry is a tag, and the answer holds IDs alone.

    13 of the 417 entries of the live `mineable/pickaxe` are references, so a
    resolver that returned them unchanged would drop hundreds of blocks.
    """
    index = block_index(
        archive(
            {
                "mineable/pickaxe": ["minecraft:stone", "#minecraft:iron_ores"],
                "iron_ores": ["minecraft:iron_ore", "minecraft:deepslate_iron_ore"],
            }
        )
    )
    assert index.resolve("mineable/pickaxe") == frozenset(
        {"minecraft:stone", "minecraft:iron_ore", "minecraft:deepslate_iron_ore"}
    )


def test_the_resolver_follows_a_reference_of_any_depth() -> None:
    index = block_index(
        archive(
            {
                "mineable/axe": ["#minecraft:planks"],
                "planks": ["#minecraft:oak_planks"],
                "oak_planks": ["minecraft:oak_planks"],
            }
        )
    )
    assert index.resolve("mineable/axe") == frozenset({"minecraft:oak_planks"})


@pytest.mark.parametrize(
    "name",
    ["mineable/pickaxe", "minecraft:mineable/pickaxe", "#minecraft:mineable/pickaxe"],
)
def test_the_resolver_reads_the_three_forms_of_one_tag_name(name: str) -> None:
    index = block_index(archive({"mineable/pickaxe": ["minecraft:stone"]}))
    assert index.resolve(name) == frozenset({"minecraft:stone"})


def test_the_resolver_gives_an_unprefixed_entry_the_minecraft_namespace() -> None:
    """The data pack format allows the short form, and vanilla files use it.

    An answer that mixed `stone` and `minecraft:stone` would look like two
    blocks to every stage below, and one of the two would never join.
    """
    index = block_index(archive({"mineable/pickaxe": ["stone", "#iron_ores"], "iron_ores": []}))
    assert index.resolve("mineable/pickaxe") == frozenset({"minecraft:stone"})


def test_the_resolver_reads_the_long_form_of_an_entry() -> None:
    entry = {"id": "minecraft:stone", "required": True}
    index = block_index(archive({"mineable/pickaxe": [entry]}))
    assert index.resolve("mineable/pickaxe") == frozenset({"minecraft:stone"})


def test_the_resolver_skips_an_optional_reference_that_the_archive_does_not_hold() -> None:
    """`required: false` names a tag that another data pack can add.

    The game skips it, so the pipeline skips it. Raising here would fail a
    build on a tag that vanilla never holds.
    """
    index = block_index(
        archive(
            {
                "mineable/pickaxe": [
                    "minecraft:stone",
                    {"id": "#minecraft:absent", "required": False},
                ]
            }
        )
    )
    assert index.resolve("mineable/pickaxe") == frozenset({"minecraft:stone"})


def test_the_resolver_raises_on_a_required_reference_that_the_archive_does_not_hold() -> None:
    index = block_index(archive({"mineable/pickaxe": ["#minecraft:absent"]}))
    with pytest.raises(ExtractError, match=re.escape("tags/block/absent.json")):
        index.resolve("mineable/pickaxe")


def test_the_resolver_raises_on_a_tag_that_the_archive_does_not_hold() -> None:
    """A renamed directory must stop the build, not read as an empty tag."""
    index = block_index(archive({"mineable/pickaxe": []}))
    with pytest.raises(ExtractError, match="broken read"):
        index.resolve("mineable/shovel")


def test_the_resolver_raises_on_a_cycle_and_names_the_path() -> None:
    """Vanilla holds no cycle. A resolver with no guard reads until the stack ends."""
    index = block_index(
        archive({"mineable/pickaxe": ["#minecraft:ores"], "ores": ["#minecraft:mineable/pickaxe"]})
    )
    with pytest.raises(ExtractError) as raised:
        index.resolve("mineable/pickaxe")
    assert "minecraft:mineable/pickaxe -> minecraft:ores -> minecraft:mineable/pickaxe" in str(
        raised.value
    )


def test_the_resolver_reads_one_tag_file_one_time() -> None:
    """`#minecraft:leaves` is reached from more than one tag of the live archive."""
    files = archive(
        {
            "mineable/hoe": ["#minecraft:leaves"],
            "mineable/axe": ["#minecraft:leaves"],
            "leaves": ["minecraft:oak_leaves"],
        }
    )
    counted = CountingFiles(files)

    index = block_index(counted)
    assert index.resolve("mineable/hoe") == frozenset({"minecraft:oak_leaves"})
    assert index.resolve("mineable/axe") == frozenset({"minecraft:oak_leaves"})
    assert index.resolve("mineable/hoe") == frozenset({"minecraft:oak_leaves"})
    assert counted.reads.count("tags/block/leaves.json") == 1


def test_the_resolver_raises_on_a_tag_of_another_namespace() -> None:
    """The pipeline reads `data/minecraft/`, so no other namespace has a file."""
    index = block_index(archive({"mineable/pickaxe": ["#other:ores"]}))
    with pytest.raises(ExtractError, match="'other'"):
        index.resolve("mineable/pickaxe")


@pytest.mark.parametrize(
    "entry",
    [
        "minecraft:../recipe/stone",
        "MINECRAFT:Stone",
        "minecraft:sto ne",
        "#minecraft:",
        # The namespace is a segment too, and both dot forms match the
        # namespace pattern, so the pattern alone lets them through. An ID is a
        # directory name downstream -- `data/<namespace>/...` in a data pack,
        # and a shard key in `/data/dist` -- so `..` there is the same walk
        # upwards that `minecraft:../recipe/stone` above is.
        "..:stone",
        ".:stone",
        "#..:mineable/pickaxe",
    ],
)
def test_the_resolver_raises_on_an_entry_that_is_not_a_resource_id(entry: str) -> None:
    index = block_index(archive({"mineable/pickaxe": [entry]}))
    with pytest.raises(ExtractError, match="not a resource ID"):
        index.resolve("mineable/pickaxe")


def test_the_resolver_skips_an_optional_reference_of_another_namespace() -> None:
    """`required: false` on a foreign tag is the case the archive can never hold.

    mcmeta publishes `data/minecraft/` alone, so no file of another namespace
    is ever in the archive. That is exactly what `required: false` describes:
    a tag another data pack may add. The game skips it, so this stage skips it.
    Raising here would stop a whole build on an entry vanilla is free to add.
    """
    index = block_index(
        archive(
            {
                "mineable/pickaxe": [
                    "minecraft:stone",
                    {"id": "#c:ores", "required": False},
                ]
            }
        )
    )
    assert index.resolve("mineable/pickaxe") == frozenset({"minecraft:stone"})


def test_the_index_says_it_does_not_hold_a_tag_of_another_namespace() -> None:
    """`holds` answers a question. It must not raise instead of answering.

    A required foreign reference still raises through `resolve`, which is the
    test two above this one.
    """
    index = block_index(archive({"mineable/pickaxe": []}))
    assert index.holds("#c:ores") is False


@pytest.mark.parametrize(
    ("name", "expected"),
    [("mineable/pickaxe", True), ("#minecraft:mineable/pickaxe", True), ("mineable/hoe", False)],
)
def test_the_index_says_whether_the_archive_holds_a_tag(name: str, expected: bool) -> None:
    index = block_index(archive({"mineable/pickaxe": []}))
    assert index.holds(name) is expected


def test_the_parser_raises_on_a_payload_that_is_not_json() -> None:
    """The fetch stage reports this as a `FetchError`. The extract stage owns it here."""
    with pytest.raises(ExtractError, match="did not return JSON"):
        parse_tag_file(b"<html>404</html>", source="tags/block/mineable/pickaxe.json")


@pytest.mark.parametrize(
    "document",
    [{"replace": False}, {"values": "minecraft:stone"}, {"values": [1]}, ["minecraft:stone"]],
)
def test_the_parser_raises_on_a_document_that_is_not_a_tag_file(document: Any) -> None:
    with pytest.raises(ExtractError, match="is not a tag file"):
        parse_tag_file(json.dumps(document).encode(), source="tags/block/x.json")


def test_the_parser_ignores_the_replace_field() -> None:
    """One data pack layer, so nothing sits below it to replace."""
    tag = parse_tag_file(
        json.dumps({"replace": True, "values": ["minecraft:stone"]}).encode(),
        source="tags/block/x.json",
    )
    assert tag.values == ["minecraft:stone"]


def test_the_tag_path_reads_the_registry_of_the_index() -> None:
    """`minecraft:planks` is a block tag and an item tag, and they differ."""
    assert tag_file_path("minecraft:planks", registry="block") == "tags/block/planks.json"
    assert tag_file_path("minecraft:planks", registry="item") == "tags/item/planks.json"


def test_the_index_reads_the_registry_it_is_given() -> None:
    """One archive, one tag name, two registries, two answers.

    `signs` is one of the 76 tag names that the pinned `26.2-data` archive
    holds under both `tags/block/` and `tags/item/`, and one of the three whose
    two answers differ. The block tag carries the wall variants, which have no
    item form: `minecraft:oak_wall_sign` on a list of ingredients is a link to
    a page that no item can reach.
    """
    files = {
        "tags/block/signs.json": json.dumps(
            {"values": ["minecraft:oak_sign", "minecraft:oak_wall_sign"]}
        ).encode(),
        "tags/item/signs.json": json.dumps({"values": ["minecraft:oak_sign"]}).encode(),
    }
    assert TagIndex(files, registry="block").resolve("signs") == frozenset(
        {"minecraft:oak_sign", "minecraft:oak_wall_sign"}
    )
    assert TagIndex(files, registry="item").resolve("signs") == frozenset({"minecraft:oak_sign"})


def test_the_index_takes_no_default_registry() -> None:
    """A caller must name the registry, because a guess is a wrong answer.

    The test above shows what the guess costs. mypy catches this too, but only
    for the code it reads. This pins the runtime signature, so a default added
    back for convenience fails here and not in the block join months later.
    """
    with pytest.raises(TypeError, match="registry"):
        TagIndex({})  # type: ignore[call-arg]


# --- The harvest requirement ---


def test_the_stage_names_the_tool_of_a_block() -> None:
    harvest = harvest_of({mineable(HarvestTool.PICKAXE): ["minecraft:stone"]})
    assert harvest["minecraft:stone"].tools == (HarvestTool.PICKAXE,)


def test_the_stage_holds_every_tool_of_a_block_in_a_stable_order() -> None:
    """A block can sit in two `mineable` tags, so the field is a tuple."""
    harvest = harvest_of(
        {
            mineable(HarvestTool.HOE): ["minecraft:sculk"],
            mineable(HarvestTool.PICKAXE): ["minecraft:sculk"],
        }
    )
    assert harvest["minecraft:sculk"].tools == (HarvestTool.PICKAXE, HarvestTool.HOE)


def test_a_block_that_no_needs_tag_names_takes_the_wooden_tier() -> None:
    """`wooden` is the floor of the ladder. Every material of the tool drops the block."""
    harvest = harvest_of({mineable(HarvestTool.AXE): ["minecraft:oak_planks"]})
    assert harvest["minecraft:oak_planks"].tier is HarvestTier.WOODEN


@pytest.mark.parametrize(
    ("block", "tier"),
    [
        ("minecraft:oak_planks", HarvestTier.WOODEN),
        ("minecraft:iron_ore", HarvestTier.STONE),
        ("minecraft:gold_ore", HarvestTier.IRON),
        ("minecraft:ancient_debris", HarvestTier.DIAMOND),
    ],
)
def test_the_stage_reads_one_block_of_each_tier(block: str, tier: HarvestTier) -> None:
    """The four tiers, with the live vanilla block of each one.

    A wrong tier here is the fault that costs a match: the player takes the
    wrong pickaxe into the Nether and the ancient debris burns.
    """
    harvest = harvest_of(
        {
            mineable(HarvestTool.AXE): ["minecraft:oak_planks"],
            mineable(HarvestTool.PICKAXE): [
                "minecraft:iron_ore",
                "minecraft:gold_ore",
                "minecraft:ancient_debris",
            ],
            needs(HarvestTier.STONE): ["minecraft:iron_ore"],
            needs(HarvestTier.IRON): ["minecraft:gold_ore"],
            needs(HarvestTier.DIAMOND): ["minecraft:ancient_debris"],
        }
    )
    assert harvest[block].tier is tier


def test_a_block_of_two_needs_tags_takes_the_higher_tier() -> None:
    """Vanilla holds no such block today. A lower answer would be a wrong answer."""
    harvest = harvest_of(
        {
            mineable(HarvestTool.PICKAXE): ["minecraft:obsidian"],
            needs(HarvestTier.STONE): ["minecraft:obsidian"],
            needs(HarvestTier.DIAMOND): ["minecraft:obsidian"],
        }
    )
    assert harvest["minecraft:obsidian"].tier is HarvestTier.DIAMOND


def test_a_block_of_a_needs_tag_alone_keeps_an_empty_tool_tuple() -> None:
    """Reporting it beats dropping it. A future version could add such a block."""
    harvest = harvest_of({needs(HarvestTier.IRON): ["minecraft:mystery_block"]})
    assert harvest["minecraft:mystery_block"].tools == ()
    assert harvest["minecraft:mystery_block"].tier is HarvestTier.IRON


def test_a_block_that_no_tag_names_is_absent_from_the_map() -> None:
    """The map holds requirements. The registry list of Tier A holds every block."""
    harvest = harvest_of({mineable(HarvestTool.PICKAXE): ["minecraft:stone"]})
    assert "minecraft:dirt" not in harvest


def test_the_map_reads_in_id_order() -> None:
    """A stable order keeps the diff of a rebuild readable."""
    harvest = harvest_of({mineable(HarvestTool.PICKAXE): ["minecraft:stone", "minecraft:andesite"]})
    assert list(harvest) == ["minecraft:andesite", "minecraft:stone"]


def test_the_stage_raises_when_a_tag_file_is_absent() -> None:
    """mcmeta could rename a directory. That must fail the build."""
    files = archive({key: values for key, values in EMPTY_TAGS.items() if key != "mineable/hoe"})
    files["tags/block/mineable/pickaxe.json"] = json.dumps({"values": ["minecraft:stone"]}).encode()
    with pytest.raises(ExtractError, match=re.escape("tags/block/mineable/hoe.json")):
        extract_block_harvest(files)


def test_the_stage_raises_when_the_seven_tags_name_no_block() -> None:
    """CLAUDE.md: an empty read is a broken scrape, not a Minecraft with no data."""
    with pytest.raises(ExtractError, match="broken scrape"):
        harvest_of({})


def test_a_record_cannot_be_changed_after_it_is_built() -> None:
    """A later stage merges three tiers. A shared record that one stage edits is a bug."""
    harvest = harvest_of({mineable(HarvestTool.PICKAXE): ["minecraft:stone"]})
    with pytest.raises(ValidationError):
        harvest["minecraft:stone"].tier = HarvestTier.DIAMOND  # type: ignore[misc]


def test_the_tier_ladder_reads_from_the_lowest_to_the_highest() -> None:
    """The member order is the ladder, and `TIER_RANK` reads it."""
    assert list(HarvestTier) == [
        HarvestTier.WOODEN,
        HarvestTier.STONE,
        HarvestTier.IRON,
        HarvestTier.DIAMOND,
    ]


def test_the_tool_order_is_the_order_of_a_block_page() -> None:
    assert list(HarvestTool) == [
        HarvestTool.PICKAXE,
        HarvestTool.AXE,
        HarvestTool.SHOVEL,
        HarvestTool.HOE,
    ]


def test_the_record_carries_the_block_id_it_describes() -> None:
    harvest = harvest_of({mineable(HarvestTool.PICKAXE): ["minecraft:stone"]})
    assert harvest["minecraft:stone"] == BlockHarvest(
        block="minecraft:stone", tools=(HarvestTool.PICKAXE,), tier=HarvestTier.WOODEN
    )
