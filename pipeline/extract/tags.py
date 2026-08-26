"""Resolve one tag of the vanilla data pack to the flat set of IDs under it.

A tag file holds a `values` list. An entry of that list is an ID, such as
`minecraft:stone`, or a reference to another tag, such as `#minecraft:leaves`.
A tag therefore names a tree, and every stage that reads a tag wants the leaves
of that tree.

`TagIndex` walks that tree one time for each tag and remembers the answer. It
reads the files that `pipeline.fetch.mcmeta.fetch_data_files` returns, so it
takes bytes and returns IDs. It opens no socket.

One index covers one registry. A tag of the block registry lives at
`tags/block/<path>.json`, and a reference inside it names another block tag.
The item registry holds a separate tree of the same shape at `tags/item/`, and
the two trees hold tags of the same name. `minecraft:planks` is both. So the
registry is an argument of the index, not a guess of the resolver.
"""

import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ValidationError

from pipeline.extract import ExtractError
from pipeline.fetch import FetchError, decode_json

__all__ = [
    "BLOCK_REGISTRY",
    "DEFAULT_NAMESPACE",
    "TAG_DIRECTORY",
    "TAG_MARKER",
    "TagEntry",
    "TagFile",
    "TagIndex",
    "parse_tag_file",
    "tag_file_path",
]

# The directory of the tags inside `data/minecraft/`. `fetch_data_files` keys
# its answer from there, so the key of a block tag reads
# `tags/block/mineable/pickaxe.json`.
TAG_DIRECTORY = "tags"

# The registry of the tags that a harvest requirement reads. Minecraft 1.21
# renamed these directories to the singular form, so it is `tags/block/` and
# not `tags/blocks/`.
BLOCK_REGISTRY = "block"

# An ID with no namespace takes this one. The data pack format gives that rule,
# and vanilla files use the short form in places.
DEFAULT_NAMESPACE = "minecraft"

# The first character of a tag reference. `#minecraft:leaves` is a reference to
# a tag, and `minecraft:oak_leaves` is one block.
TAG_MARKER = "#"

# The namespace of a resource ID, and the path of one. The path accepts a
# slash, because a tag path holds one: `mineable/pickaxe`.
NAMESPACE_PATTERN = re.compile(r"[a-z0-9_.-]+")
RESOURCE_PATH_PATTERN = re.compile(r"[a-z0-9_./-]+")

# A segment of `.` or `..` reads as structure rather than as a name. The
# archive reader of the fetch stage refuses one for the same reason.
#
# The namespace is a segment too, and it is the one that decides a directory:
# an ID becomes `data/<namespace>/<registry>/<path>` in a data pack and a shard
# key downstream, so `..:foo` is the same walk upwards that `minecraft:../foo`
# is. Both patterns below accept a bare `.` and a bare `..`, so neither half of
# the check can be left to the pattern alone.
DOT_SEGMENTS = frozenset({".", ".."})


def _checked_resource_id(value: str, *, source: str) -> str:
    """Return `value` in the namespaced form, and refuse an ID that is not one.

    An ID that carries no namespace takes `minecraft`. An ID that carries any
    other namespace comes back unchanged. `TagIndex` refuses a foreign
    namespace where it reads a file, not here, because a foreign ID inside a
    `values` list is a name and not a file to open.
    """
    text = value.strip()
    namespace, separator, path = text.partition(":")
    if not separator:
        namespace, path = DEFAULT_NAMESPACE, text
    segments = [namespace, *path.split("/")]
    if (
        NAMESPACE_PATTERN.fullmatch(namespace) is None
        or RESOURCE_PATH_PATTERN.fullmatch(path) is None
        or any(segment in DOT_SEGMENTS or not segment for segment in segments)
    ):
        raise ExtractError(
            f"{source} names {value!r}, which is not a resource ID. An ID reads "
            f"`namespace:path`, of lowercase letters, digits, a dot, an underscore, a hyphen, "
            f"and a slash in the path, and neither the namespace nor a path segment is "
            f"{'.'!r} or {'..'!r}."
        )
    return f"{namespace}:{path}"


def tag_file_path(tag_id: str, *, registry: str) -> str:
    """Return the archive key of one tag of `registry`.

    `tag_id` is namespaced, such as `minecraft:mineable/pickaxe`. The answer is
    the key that `fetch_data_files` uses, such as
    `tags/block/mineable/pickaxe.json`.

    The pipeline reads `data/minecraft/` alone, so a tag of another namespace
    has no file in the archive and raises `ExtractError`.
    """
    namespace, _, path = tag_id.partition(":")
    if namespace != DEFAULT_NAMESPACE:
        raise ExtractError(
            f"the tag {tag_id!r} names the namespace {namespace!r}. This pipeline reads the "
            f"vanilla data pack alone, which holds the namespace {DEFAULT_NAMESPACE!r}."
        )
    return f"{TAG_DIRECTORY}/{registry}/{path}.json"


class TagEntry(BaseModel):
    """One entry of a `values` list, in the long form.

    The short form of an entry is a bare string. The long form is this object,
    and it adds `required`. A required entry that no file answers is a fault of
    the data pack. An entry with `required` set to false is a reference to
    something that another data pack can add, so this pipeline skips it.
    """

    id: str
    required: bool = True


class TagFile(BaseModel):
    """One tag file of the vanilla data pack.

    The format also holds `replace`, and this model drops it. `replace` tells
    the game to discard the entries that a data pack below this one added. This
    pipeline reads one layer, so nothing sits below and nothing can be
    replaced.
    """

    values: list[str | TagEntry]


def parse_tag_file(payload: bytes, *, source: str) -> TagFile:
    """Parse the bytes of one tag file. Name `source` so the error says which file.

    A payload that is not JSON, and a document that is not a tag file, both
    raise `ExtractError`. The fetch stage reports the same two faults as a
    `FetchError`, so this function translates that one error. A caller of the
    extract stage then handles one exception type.
    """
    try:
        document: Any = decode_json(payload, source=source)
    except FetchError as error:
        raise ExtractError(str(error)) from error
    try:
        return TagFile.model_validate(document)
    except ValidationError as error:
        raise ExtractError(f"{source} is not a tag file: {error}") from error


class TagIndex:
    """The tags of one registry, and the flat set of IDs under each one.

    Build the index from the files that `fetch_data_files` returns. The index
    keeps the bytes and parses a file the first time a caller asks for it.

    `registry` carries no default on purpose. The module docstring names the
    trap: `minecraft:planks` is a block tag and an item tag, and 76 tag names of
    the pinned `26.2-data` archive sit in both trees. Three of those 76 resolve
    to different sets -- `signs`, `banners`, and `piglin_repellents` -- and the
    block answer is the larger one, because it carries the wall variants that
    have no item form at all. A default registry turns "the caller forgot to
    say" into `minecraft:oak_wall_sign` on a list of ingredients, which is a
    wrong answer that reads like a right one.
    """

    def __init__(self, files: Mapping[str, bytes], *, registry: str) -> None:
        self._files = files
        self._registry = registry
        self._resolved: dict[str, frozenset[str]] = {}

    @property
    def registry(self) -> str:
        """The registry that this index reads, such as `block`."""
        return self._registry

    def holds(self, name: str) -> bool:
        """Say whether the archive holds the file of the tag `name`.

        A tag of another namespace answers `False` rather than raising. The
        archive holds `data/minecraft/` alone, so the file of a foreign tag is
        absent by construction, and "absent" is the answer this question asks
        for. `resolve` still raises on a *required* foreign reference, because
        there the missing file is a fault. That path reaches `tag_file_path`.
        """
        tag_id = self._tag_id(name)
        if tag_id.partition(":")[0] != DEFAULT_NAMESPACE:
            return False
        return tag_file_path(tag_id, registry=self._registry) in self._files

    def resolve(self, name: str) -> frozenset[str]:
        """Return every ID under the tag `name`, with the references resolved.

        `name` is a tag, with or without its namespace, and with or without the
        leading `#`. `mineable/pickaxe` and `#minecraft:mineable/pickaxe` name
        the same tag.

        The answer holds IDs alone. A reference to another tag is replaced by
        the IDs of that tag, at any depth.

        These faults raise `ExtractError`:

        - The archive holds no file for a required tag.
        - A tag refers to itself, at any depth. The error names the path.
        - An entry is not a resource ID.
        - A tag file is not JSON, or is not a tag file.

        A missing tag is a fault and not an empty answer. mcmeta could rename a
        directory in a future version. An empty answer would then travel down
        the pipeline as a Minecraft version where no block needs a tool.
        """
        return self._resolve(self._tag_id(name), ())

    def _tag_id(self, name: str) -> str:
        """Return the namespaced ID of the tag `name`, without the `#` marker."""
        text = name[1:] if name.startswith(TAG_MARKER) else name
        return _checked_resource_id(text, source=f"the tag {name!r}")

    def _resolve(self, tag_id: str, path: tuple[str, ...]) -> frozenset[str]:
        """Return every ID under `tag_id`. `path` holds the tags above it."""
        remembered = self._resolved.get(tag_id)
        if remembered is not None:
            return remembered
        if tag_id in path:
            cycle = " -> ".join([*path, tag_id])
            raise ExtractError(
                f"the tag {tag_id!r} refers to itself: {cycle}. A resolver without this check "
                f"reads the same files until the stack ends."
            )

        source = tag_file_path(tag_id, registry=self._registry)
        payload = self._files.get(source)
        if payload is None:
            raise ExtractError(
                f"the archive holds no file {source!r} for the tag {tag_id!r}. An absent tag is "
                f"a broken read, not a tag with no entries."
            )
        tag = parse_tag_file(payload, source=source)

        ids: set[str] = set()
        below = (*path, tag_id)
        for entry in tag.values:
            value = entry if isinstance(entry, str) else entry.id
            required = True if isinstance(entry, str) else entry.required
            if not value.startswith(TAG_MARKER):
                # A plain ID, which this stage does not check against a
                # registry. `required` says whether the game needs the ID to
                # exist, and the ID is a name here either way.
                ids.add(_checked_resource_id(value, source=source))
                continue
            reference = _checked_resource_id(value[1:], source=source)
            if not required and not self.holds(reference):
                # An optional reference to a tag that this data pack does not
                # hold. The game skips it, so this stage skips it too.
                continue
            ids |= self._resolve(reference, below)

        answer = frozenset(ids)
        self._resolved[tag_id] = answer
        return answer
