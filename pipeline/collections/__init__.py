"""Resolve manifest-driven collection pages into `Entity` objects.

This package sits at stage 7a of the build, between `merge_entities` (stage 7)
and the sprite atlas (stage 7b). A collection is an entity whose members are
other entities, so it can only be built after every other entity exists with
its final display name. Every input the stage needs -- the merged entity list,
the item_components payload, and the tag index -- is already in memory at that
point, so the build opens no new socket and an offline rebuild still works.

A new collection is added by writing one JSON manifest under
``pipeline/collections/manifests/``. No Python symbol is named there,
so adding a collection stays a data change.
"""

__all__ = ["CollectionError"]


class CollectionError(Exception):
    """A collection manifest resolved to something this build cannot ship.

    Two faults raise this rather than silently producing a broken page:

    1. **A member ID with no entity.** A tag naming a mob this version does not
       have would otherwise render as a missing row nobody sees. The error names
       the ID and the manifest, the same posture `TagIndex` takes on a missing
       tag file.

    2. **A rule that resolves to zero members.** A collection page with nothing
       on it is a broken read, not a version of Minecraft with no food. The
       error names the manifest and the rule.

    This mirrors `ExtractError` and `NormalizeError` in the other pipeline
    packages.
    """
