"""Derive the harvest requirement of every block from the vanilla block tags.

A block page must answer one question in a match. Which tool breaks this block,
and how good must that tool be? The vanilla data pack holds the answer in two
families of block tags.

1. `tags/block/mineable/<tool>.json` names the tool that breaks the block. The
   four files are `pickaxe`, `axe`, `shovel`, and `hoe`.
2. `tags/block/needs_<material>_tool.json` names the material floor of that
   tool. The three files are `needs_stone_tool`, `needs_iron_tool`, and
   `needs_diamond_tool`.

A block that no `needs` tag names takes the tier `wooden`, which means every
material of the right tool drops the block.

One ladder stays out of this module. The six `incorrect_for_<material>_tool`
tags read the other way around: each one names the blocks that one tool material
cannot break. They add no requirement of their own -- every one of them is a
list of `#needs_*_tool` references -- so the three files above carry the whole
answer, and this module reads the source rather than the six views of it.

The two extra materials collapse onto the four tiers rather than extending them.
In the pinned `26.2-data` archive `incorrect_for_copper_tool` holds exactly what
`incorrect_for_stone_tool` holds, and `incorrect_for_gold_tool` holds exactly
what `incorrect_for_wooden_tool` holds. So copper harvests what stone harvests
and gold harvests what wood harvests, whatever their durability and speed say. A
later phase that shows every material still starts at those files, because the
equality is a fact of one version and not a rule of the game.

The stage is a pure function from the files of the archive to a mapping, so no
test of it opens a socket. Two suites read it from opposite ends.
`tests/test_extract_harvest.py` builds its own tag files in memory, one rule per
file, and `tests/test_extract_snapshot.py` runs the stage over a committed
snapshot of the real `26.2-data` tag files and compares the answer with a
committed snapshot of the answer.
"""

from collections.abc import Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from pipeline.extract import ExtractError
from pipeline.extract.tags import BLOCK_REGISTRY, TagIndex

__all__ = [
    "MINEABLE_TAG_TEMPLATE",
    "NEEDS_TOOL_TAG_TEMPLATE",
    "TAGGED_TIERS",
    "BlockHarvest",
    "HarvestTier",
    "HarvestTool",
    "extract_block_harvest",
]

# The tag of one tool, and the tag of one material floor. The `mineable` tags
# sit in their own directory. The `needs` tags sit at the top of the block tag
# directory.
MINEABLE_TAG_TEMPLATE = "mineable/{tool}"
NEEDS_TOOL_TAG_TEMPLATE = "needs_{tier}_tool"


class HarvestTool(StrEnum):
    """The tool that breaks a block, from the `mineable` tags.

    The order of the members is the order that a block page shows. A block can
    sit in two of these tags, so a record holds a tuple of them.
    """

    PICKAXE = "pickaxe"
    AXE = "axe"
    SHOVEL = "shovel"
    HOE = "hoe"


class HarvestTier(StrEnum):
    """The material floor of the tool, from the `needs_<material>_tool` tags.

    The order of the members is the ladder, from the lowest to the highest.
    `WOODEN` is the floor of a block that no `needs` tag names, and it means
    every material works. Gold and copper are not on this ladder, and the
    module docstring holds the reason.
    """

    WOODEN = "wooden"
    STONE = "stone"
    IRON = "iron"
    DIAMOND = "diamond"


# The tiers that a tag names. `WOODEN` is the default, and no tag carries it.
TAGGED_TIERS = (HarvestTier.STONE, HarvestTier.IRON, HarvestTier.DIAMOND)

# The ladder, as a rank for each tier. A block that two `needs` tags name takes
# the highest of them. Vanilla holds no such block today.
TIER_RANK = {tier: rank for rank, tier in enumerate(HarvestTier)}


class BlockHarvest(BaseModel):
    """What one block needs before it drops itself.

    `tools` holds the tools that break the block, in the order of `HarvestTool`.
    The tuple is empty when a `needs` tag names the block and no `mineable` tag
    does. Vanilla holds no such block today. A future version could add one,
    and an empty tuple reports it rather than hiding it.
    """

    model_config = ConfigDict(frozen=True)

    block: str
    tools: tuple[HarvestTool, ...]
    tier: HarvestTier


def extract_block_harvest(files: Mapping[str, bytes]) -> dict[str, BlockHarvest]:
    """Return the harvest requirement of every block that the seven tags name.

    `files` is the answer of `pipeline.fetch.mcmeta.fetch_data_files`, which
    keys each file by its path under `data/minecraft/`. The answer is keyed by
    the namespaced block ID, in ID order.

    A block that none of the seven tags names is absent from the answer. The
    map states the requirements that these tags carry. It is not a list of every
    block of the game, and the registry list of Tier A is where that comes from.

    Every fault raises `ExtractError`: a tag file that the archive does not
    hold, a file that is not a tag file, a tag that refers to itself, and an
    answer that holds no block at all.
    """
    index = TagIndex(files, registry=BLOCK_REGISTRY)

    tools: dict[str, list[HarvestTool]] = {}
    for tool in HarvestTool:
        for block in index.resolve(MINEABLE_TAG_TEMPLATE.format(tool=tool.value)):
            tools.setdefault(block, []).append(tool)

    tiers: dict[str, HarvestTier] = {}
    for tier in TAGGED_TIERS:
        for block in index.resolve(NEEDS_TOOL_TAG_TEMPLATE.format(tier=tier.value)):
            held = tiers.get(block)
            if held is None or TIER_RANK[tier] > TIER_RANK[held]:
                tiers[block] = tier

    harvest = {
        block: BlockHarvest(
            block=block,
            tools=tuple(tools.get(block, ())),
            tier=tiers.get(block, HarvestTier.WOODEN),
        )
        for block in sorted(tools.keys() | tiers.keys())
    }
    if not harvest:
        raise ExtractError(
            "the block tags name no block at all. An empty read is a broken scrape, not a "
            "version of Minecraft where every block breaks by hand."
        )
    return harvest
