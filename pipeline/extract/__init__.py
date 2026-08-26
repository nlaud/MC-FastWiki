"""Parse the vanilla data pack into the shapes that later stages merge.

The fetch stage hands this stage bytes and nothing else. A module here takes a
mapping of file path to bytes, and it returns a model. It opens no socket, so
every test of this package builds its own files in memory.

This is Tier A of the three tiers that CLAUDE.md names. Tier A is the
completeness and correctness layer, so a fault here is never a warning. A stage
that reads no file, or that reads a file it does not understand, raises
`ExtractError` and stops the build.
"""

__all__ = ["ExtractError"]


class ExtractError(Exception):
    """One parse of the vanilla data pack failed.

    Every fault of an extract stage arrives as this class: a payload that is not
    JSON, a document whose shape the model rejects, a tag file that the archive
    does not hold, and a tag that refers to itself. A caller then stops the
    build on one exception type.

    This mirrors `FetchError` of the fetch stage, and it stays separate from it.
    The two names say which half of the pipeline failed. A `FetchError` points
    at the network or at the cache. An `ExtractError` points at the data, and it
    means the same read tomorrow gives the same answer.
    """
