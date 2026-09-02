"""Build the unified obtain tree: how a player gets one item.

`TODO.md`'s Phase 3 asks for one tree that answers "how do I get this," walking
crafting, smelting, brewing, and every kind of loot down to raw materials, with
"one set of rules, no special cases." This package is that tree, in three
layers:

`pipeline.obtain.producer` names the one node vocabulary every source reduces
to -- a `Producer` turns some `ProducerInput`s into one `ItemAmount`, whatever
made it. `pipeline.obtain.recipes`, `pipeline.obtain.loot`, and
`pipeline.obtain.brewing` are the adapters: each one reads a different upstream
shape (mcmeta's `recipe/*.json`, mcmeta's `loot_table/*.json` plus the two
Tier B indexes `pipeline.enrich.droptable` and `pipeline.enrich.trade` already
built, and `pipeline.enrich.brewing`'s wiki-sourced brewing tables) and returns
`Producer`s in the one shared shape. `pipeline.obtain.tree` is the walker: it
takes a `ProducerIndex` built from every adapter's output and expands one item
into a tree, and it is the *only* place the four structural rules of `TODO.md`
Phase 3 live -- cycle handling, memoization, the depth cap, and repeated-
subtree collapse. An adapter never has to know about any of the four; it only
ever emits flat producers.

Like `pipeline.extract`, most of what feeds this package is Tier A: mcmeta's
`recipe/` and `loot_table/` directories are exact, versioned game data, so a
shape this package claims to understand that turns out malformed is a fault
that stops the build, not a row to skip. The one named exception is
`crafting_special_*` (and its siblings with no declared ingredients, such as
`crafting_transmute`), which mcmeta ships with no ingredient list to read at
all -- those are skipped and counted in the report, exactly as `TODO.md` asks,
rather than raised on. Brewing sits at Tier B/C: it is sourced from the wiki's
own tables (`pipeline.enrich.brewing`), because -- unlike crafting and
smelting -- brewing has no data-pack representation to read from mcmeta at
all; it is hardcoded in the client, and the wiki is the only structured source
of it. See `pipeline/enrich/brewing.py`'s module docstring for the research
this claim rests on.

`ObtainError` is this package's own exception, mirroring `ExtractError` and
`EnrichError`: a fault in a shape this package claims to understand raises it,
naming the source (a recipe path, a loot table path, a brewing rule) and what
about the shape was unexpected.
"""

__all__ = ["ObtainError"]


class ObtainError(Exception):
    """One read of a source this package composes into the obtain tree failed.

    Raised for a shape this package claims to understand and could not parse:
    a recipe type it maps to a `Producer` but whose ingredients or result do
    not match that type's own documented shape, a loot table entry it cannot
    walk, or a brewing rule whose ingredient names it cannot resolve. It is
    never raised for a recipe type this package does not recognize at all --
    `pipeline.obtain.recipes` skips and reports those, the same way it skips
    `crafting_special_*`, because a recipe type add in a future Minecraft
    version is new data, not a broken read.
    """
