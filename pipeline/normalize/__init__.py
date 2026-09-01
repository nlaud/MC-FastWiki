"""Merge Tier A and Tier B into the canonical `Entity` model, resolve IDs, dedupe.

CLAUDE.md names this package's job: take the vanilla registry data of Tier A
(`pipeline.extract`) and the wiki-sourced facts of Tier B (`pipeline.enrich`)
and produce the one `Entity` per registry ID that `pipeline.emit` writes into
the site's search index and shards.

**`reconcile.py` stops one step short of the merge, and `entity.py`/`merge.py`
are the step after it.** Phase 2 -- the phase `reconcile.py` was added in --
only proves that Tier A and Tier B *can* be joined, by building the join
tables and the icon chain, and reports where that join succeeds and where it
does not. `entity.py` now defines the `Entity` model itself, and `merge.py`'s
`merge_entities` is what actually applies the reconciled join, field by field,
to build one `Entity` per registry ID rather than one reconciliation count per
registry.

Two consequences follow from that scope, and both are deliberate rather than
temporary shortcuts.

`reconcile` never fails a build. `pipeline.enrich`'s own package docstring
draws the line CLAUDE.md draws between the tiers: Tier A raises and stops the
build, because a missing recipe is a wrong answer, while Tier B drops a row it
cannot read and says why, because a wiki page mid-edit is not a build-stopping
fault. A reconciliation report sits above both tiers and names where they
disagree -- an item with no wiki row, a registry ID no sprite family answers to
-- and CLAUDE.md's own reasoning applies here a second time: a threshold for
how much disagreement is acceptable is a decision Phase 3's validation gate
should make once the fields it gates on actually exist, not a number this
report guesses at today.

`NormalizeError` is this package's shape-level fault, matching
`pipeline.enrich.EnrichError` and `pipeline.fetch.FetchError`: it means a
reconciliation was asked to run over an empty registry list or an empty sprite
index, which is not a Minecraft version with nothing to check but a scrape that
produced nothing -- the same distinction CLAUDE.md draws for every other empty
result this pipeline can produce.
"""

__all__ = ["NormalizeError"]


class NormalizeError(Exception):
    """A tier-merge stage was asked to work from data it cannot trust.

    Reserved for a shape fault: an empty registry mapping, an empty sprite
    index, a registry an icon rule names that the mcmeta payload no longer
    carries. It is not raised for one entity that cannot be reconciled --
    `reconcile`'s report carries those -- the same distinction
    `pipeline.enrich.EnrichError` draws between a row this pipeline cannot read
    and a table it no longer understands.
    """
