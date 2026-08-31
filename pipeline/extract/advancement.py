"""Tier A advancement IDs, from the data-pack paths the vanilla archive holds.

`pipeline.enrich.advancement.AdvancementTree.reconcile(tier_a_ids)` has always
expected a Tier A list of advancement internal IDs to join against -- the
module docstring of `pipeline.enrich.advancement` calls the wiki table "keyed
on `internal_id`" and states the join is "a dictionary lookup rather than a
name match" -- but nothing in `pipeline.extract` has produced that list until
now. This module is the missing half: it reads the file paths that
`pipeline.fetch.mcmeta.fetch_data_files` already returns under the
`advancement` group and turns them into the same internal-ID shape the wiki
table uses.

`fetch_data_files` keys its answer by the path under `data/minecraft/`, so an
advancement file arrives as `advancement/story/mine_stone.json`. The internal
ID strips the `advancement/` directory and the `.json` extension, giving
`story/mine_stone` -- exactly what `pipeline.enrich.advancement.INTERNAL_ID`
matches and exactly the key `AdvancementTree.by_id` uses.

**`recipes/**` is excluded, on purpose.** The vanilla data pack carries one
advancement file per unlockable recipe under `advancement/recipes/<tab>/
<recipe>.json` -- `recipes/misc/iron_pickaxe_from_planks_and_sticks.json` and
several hundred siblings. These are not advancements a player ever sees in the
in-game advancement screen; they exist purely so the game can gate a recipe
behind "you have picked up the ingredient once," and the community and the
wiki alike do not treat them as advancements at all. The Minecraft Wiki's
`Advancement` page -- the one page `pipeline.enrich.advancement` reads, per
its own module docstring -- documents only the roughly 126 player-facing
advancements and none of the recipe-unlock bookkeeping. Counting `recipes/**`
here would not create a join gap so much as manufacture one: several hundred
Tier A IDs with a `reconcile()` `missing_from_wiki` entry that will never
close, because there is nothing on the wiki to close it with, and several
hundred `kind="advancement"` search entries a player has no reason to type.
So this extractor drops the `recipes/**` subtree the same way
`pipeline.fetch.mcmeta.DATA_GROUPS` already drops `datapacks/` -- a
deliberate, documented exclusion rather than an oversight -- and the count on
each side of that decision is recorded in the merge report so the choice stays
auditable rather than silently baked in.

An archive with no advancement file at all is a broken read, not a version of
the game with none: every release since 1.12 has shipped advancements, so an
empty answer means the fetch stage handed this module the wrong group, or
`fetch_data_files` was called for `advancement` and returned nothing. Per the
Tier A rule CLAUDE.md states and `pipeline.extract`'s own package docstring
repeats, that raises `ExtractError` rather than returning an empty tuple.
"""

from collections.abc import Mapping

from pipeline.extract import ExtractError

__all__ = [
    "ADVANCEMENT_DIRECTORY",
    "ADVANCEMENT_FILE_SUFFIX",
    "RECIPE_ADVANCEMENT_DIRECTORY",
    "extract_advancement_ids",
]

# The directory of an advancement file inside `data/minecraft/`, as
# `fetch_data_files` keys it: `advancement/story/mine_stone.json`.
ADVANCEMENT_DIRECTORY = "advancement/"

ADVANCEMENT_FILE_SUFFIX = ".json"

# The subtree of `advancement/` that holds recipe-unlock bookkeeping rather
# than player-facing advancements. See the module docstring for why these are
# excluded rather than counted as a wiki join gap.
RECIPE_ADVANCEMENT_DIRECTORY = "advancement/recipes/"


def extract_advancement_ids(files: Mapping[str, bytes]) -> tuple[str, ...]:
    """Return the sorted internal IDs of every player-facing advancement.

    `files` is the answer of `pipeline.fetch.mcmeta.fetch_data_files` for the
    `advancement` group (or a superset of groups that includes it): a mapping
    of path under `data/minecraft/` to the file's bytes. Only the path is read
    here -- the bytes of an advancement file describe its criteria and reward,
    which is not this module's concern, so a caller may pass a mapping whose
    values are empty and still get a correct answer.

    A path under `advancement/recipes/` is dropped; see the module docstring
    for the reason. Every other path under `advancement/` becomes one ID, by
    stripping the directory and the `.json` extension:
    `advancement/story/mine_stone.json` becomes `story/mine_stone`.

    Raises `ExtractError` when `files` holds no advancement file at all. An
    empty read is a failed fetch, not a Minecraft version with no
    advancements -- the same rule `pipeline.extract.harvest.extract_block_
    harvest` applies to an archive with no block tag.
    """
    ids = sorted(
        path[len(ADVANCEMENT_DIRECTORY) : -len(ADVANCEMENT_FILE_SUFFIX)]
        for path in files
        if path.startswith(ADVANCEMENT_DIRECTORY)
        and path.endswith(ADVANCEMENT_FILE_SUFFIX)
        and not path.startswith(RECIPE_ADVANCEMENT_DIRECTORY)
    )
    if not ids:
        raise ExtractError(
            "the archive holds no advancement file outside advancement/recipes/. An empty read "
            "is a broken fetch, not a version of Minecraft with no advancements."
        )
    return tuple(ids)
