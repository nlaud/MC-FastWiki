"""Pin one `misode/mcmeta` version tag, and turn it into a commit SHA.

Tier A of this project comes from `misode/mcmeta`. That repository publishes the
output of Mojang's data generator as JSON. It keeps one orphan branch for each
kind of data, and it tags every branch for every Minecraft version. The tag name
is `<version>-<branch>`, such as `26.2-summary`.

CLAUDE.md gives the rule that this module holds: pin to a version tag, never to
a bare branch head. A branch head moves. Two builds of the same Minecraft
version then read different data, and neither build is reproducible. A branch
head also carries snapshot data within hours of a snapshot release, so a release
build can read snapshot numbers. A wrong Minecraft number looks exactly like a
right one on the screen.

The module turns a version ID into a `McmetaTag`. Later stages take their raw
URLs from that object, so they read one immutable commit for the whole build.

Three guards keep a snapshot out of a release build:

1. `parse_git_ref` requires the `ref` of the answer to name the exact tag that
   the caller asked for. A prefix match is then a failure, not a silent
   substitution.
2. `resolve_mcmeta_tag` refuses a version ID that carries a pre-release marker.
   The caller passes `allow_prerelease=True` to read a snapshot on purpose.
3. `pipeline.fetch.version_manifest.VersionManifest` already proves that
   `latest.release` names an entry of the type `release`. Guard 2 is the second
   layer. It covers a version ID that arrives from a hand-written argument
   instead of from the manifest.

A fourth guard keeps the read *on* the pinned commit once the pin is made. The
SHA sits in one segment of the raw URL, and everything after that segment is the
`path` argument of `McmetaTag.raw_url`. A `..` segment there walks back over the
SHA: every RFC 3986 reader between this module and the file resolves dot
segments, so `../summary/item_components/data.json` becomes the URL of the
*branch head*, which is the one read this module exists to prevent. So
`raw_url` checks its path the way `mcmeta_tag_name` checks its version ID, and
`McmetaTag.commit_sha` carries the same 40-character rule as the SHA it is
built from, because a `McmetaTag` can also be rebuilt from a cache file rather
than from an answer that `parse_git_ref` already checked.

Two readers sit on top of the pin, and they read the two branches differently
because the branches are shaped differently.

`fetch_summary_payload` reads the `summary` branch over `raw_url`. That branch
holds each group of Tier A as one file: `registries/data.json`,
`blocks/data.json`, and `item_components/data.json`. Three reads cover three of
the payload groups of Phase 1.

`fetch_data_files` reads the `data` branch as one gzip archive. That branch
holds 5,422 files across the four groups that Phase 1 wants, and 5,422 requests
against a volunteer-facing CDN is not a thing to do once, let alone on every
build. GitHub serves the whole branch at `codeload.github.com` for 2.7 MB in
under a second, and the archive of one commit is byte-for-byte the same on every
download, so it caches by content hash like any other payload.

Both readers take a `ContentCache`, so a second build of one Minecraft version
reads no network at all. Both read a payload before they store it, so a body
that is not the payload costs one fetch rather than every build after it.
`_fetch_and_read` holds the reason.
"""

import io
import re
import tarfile
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel, ValidationError, field_validator

from pipeline.fetch import FetchError, Transport, decode_json, get_bytes
from pipeline.fetch.cache import ContentCache, fetch_and_read

__all__ = [
    "ARCHIVE_NAMESPACE_ROOT",
    "COMMIT_OBJECT_TYPE",
    "DATA_GROUPS",
    "GITHUB_REF_URL",
    "MAX_ARCHIVE_BYTES",
    "MCMETA_ARCHIVE_URL",
    "MCMETA_BRANCHES",
    "MCMETA_RAW_URL",
    "MCMETA_REPOSITORY",
    "SUMMARY_PAYLOADS",
    "TAR_HEADER_BYTES",
    "GitRef",
    "GitRefObject",
    "McmetaTag",
    "fetch_data_files",
    "fetch_summary_payload",
    "mcmeta_tag_name",
    "parse_git_ref",
    "read_data_archive",
    "resolve_mcmeta_tag",
]

MCMETA_REPOSITORY = "misode/mcmeta"

# The GitHub single-reference endpoint. It matches one exact name.
#
# Two other endpoints answer the same question, and both are wrong here:
#
# * `/repos/{repository}/tags` pages the whole tag list. mcmeta needs 42 pages
#   of 100 rows, against an unauthenticated limit of 60 requests per hour. One
#   resolve would spend most of the hour.
# * `/git/matching-refs/tags/{prefix}` matches a prefix. The prefix `26.2-`
#   returns 153 rows, and the rows hold `26.2-pre-1-data`, `26.2-rc-1-data`, and
#   `26.2-snapshot-8-data`. A prefix match is the trap that this module exists
#   to close.
#
# A tag that does not exist answers 404, and `get_bytes` names the URL in the
# `FetchError` that it raises. That is the failure to expect when mcmeta has not
# yet tagged a new Minecraft release.
GITHUB_REF_URL = "https://api.github.com/repos/{repository}/git/ref/tags/{tag}"

# Where a later stage reads a file of the pinned commit. The SHA goes in the
# path, so the read cannot move under the build.
MCMETA_RAW_URL = "https://raw.githubusercontent.com/{repository}/{commit_sha}/{path}"

# Where GitHub serves one whole commit as a gzip archive. The SHA goes in the
# path here too, so the archive cannot move under the build.
#
# `api.github.com/repos/{repository}/tarball/{sha}` answers the same question
# and is the wrong endpoint for it. It redirects to `legacy.tar.gz`, whose
# member paths start with a directory named after the nearest tag, such as
# `misode-mcmeta-26.2-data-0-g4d12c05`. That name depends on the tag history of
# the repository rather than on the commit. The URL below names the commit in
# the member paths instead, as `mcmeta-<commit_sha>`, and it costs no redirect.
MCMETA_ARCHIVE_URL = "https://codeload.github.com/{repository}/tar.gz/{commit_sha}"

# The branches that CLAUDE.md records, and the only names that this project
# asks for. A typo then fails with this list, not with a 404 that reads like an
# outage at GitHub.
MCMETA_BRANCHES = frozenset({"assets", "atlas", "data", "diff", "registries", "summary"})

# The files of the `summary` branch that Phase 1 reads, by the name that this
# project calls each one.
#
# `registries` comes from here rather than from the `registries` branch. Both
# hold the same lists. The branch spreads them over 182 files, one for each
# registry, and this is one file of 966 kB that holds all 182. Reading the
# branch would mean 182 requests for data that arrives here in one.
#
# CLAUDE.md gives the trap of `item_components`: its keys are unprefixed, so a
# lookup of `minecraft:apple` returns nothing and says nothing. The key is
# `apple`.
SUMMARY_PAYLOADS: Mapping[str, str] = {
    "blocks": "blocks/data.json",
    "item_components": "item_components/data.json",
    "registries": "registries/data.json",
}

# The directory of the `data` branch that holds the vanilla data pack. mcmeta
# publishes one namespace, `minecraft`, and 8,528 of the 8,531 files of the
# branch sit under this prefix.
ARCHIVE_NAMESPACE_ROOT = "data/minecraft"

# The groups of the `data` branch that this pipeline reads. `datapacks/` also holds
# recipes and tags, and it is left out on purpose: it holds the experimental
# trade rebalance pack, which is not the vanilla game. The prefix test below
# excludes it, because its path is `data/minecraft/datapacks/...` rather than
# `data/minecraft/tags/...`.
DATA_GROUPS = (
    "advancement",
    "enchantment",
    "loot_table",
    "recipe",
    "tags",
    "worldgen/biome",
    "worldgen/configured_feature",
    "worldgen/placed_feature",
)

# How many bytes of archive this module reads before it stops.
#
# The whole `data` branch is 9.1 MB of files in 9,030 members today, which is
# 9.6 MB of archive once each member's header block is counted, and the groups
# above are roughly 3 MB of that. 256 MB leaves room for many years of growth
# and still fails a gzip bomb long before it fills the memory of a CI runner.
# The reader adds up every member as it walks the headers in order, so it stops
# part-way through a bomb rather than after it.
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024

# The size of one tar header block, which is what a member costs before its
# content is counted at all.
#
# Counting it is what makes the limit above a limit. A member that declares no
# content still costs this much of the decompressed stream, and `tarfile` holds
# one `TarInfo` for each member it has walked, so an archive of a few hundred
# thousand empty members exhausts memory while a content-only total stays at
# zero. Measured: 200,000 empty members compress to 940 kB and expand to 102 MB
# of headers, which a content-only total reads as an empty archive.
TAR_HEADER_BYTES = 512

# mcmeta uses lightweight tags. A lightweight tag points straight at the commit,
# so `object.sha` is the commit SHA and `object.type` is `commit`. An annotated
# tag points at a tag object instead, and the SHA of that object is not a commit
# SHA. A raw URL built from it would 404. So this module refuses any other type
# rather than return a SHA that names the wrong object.
COMMIT_OBJECT_TYPE = "commit"

# A full Git object name: 40 lowercase hexadecimal characters.
COMMIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")

# What a version ID may hold. The ID goes into a URL path, so a character
# outside this set could add a path segment or a query to the request. Every
# Minecraft release ID of the manifest fits the set.
SAFE_VERSION_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]+")

# What one segment of a path inside the pinned commit may hold. The same set as
# a version ID, and for the same reason: the segment goes into a URL path, so a
# `?`, a `#`, a `%`, a space, or a control character would end the path early or
# make it unsendable. Every path that mcmeta serves fits the set --
# `item_components/data.json`, `loot_table/blocks/oak_log.json`.
SAFE_PATH_SEGMENT_PATTERN = re.compile(r"[A-Za-z0-9._-]+")

# The two segments that a path must not hold. Both match the pattern above, so
# they need naming on their own.
DOT_SEGMENTS = frozenset({".", ".."})

# A weekly snapshot ID, such as `26w01a`. It carries no other marker, so the
# shape of the ID is the whole signal.
#
# The tail is not letters alone. Mojang has shipped `20w14infinite`,
# `22w13oneblockatatime`, and `23w13a_or_b`, and the underscores of the last one
# are what a letters-only tail misses: `23w13a_or_b` carries no `snapshot`,
# `pre`, or `rc` marker either, so it would read as a release here and pin the
# tag of a Minecraft version that was a joke. No release ID has this shape, so a
# wider tail costs nothing.
WEEKLY_SNAPSHOT_PATTERN = re.compile(r"\d{2}w\d{2}[a-z][a-z0-9_]*", re.IGNORECASE)

# The pre-release markers of a Mojang version ID. Mojang separates the marker
# with a hyphen, a space, or an underscore, and the case varies over the years:
# `26.3-snapshot-10`, `1.20-pre1`, `1.20-rc1`, `1.14.2 Pre-Release 4`. The
# lookahead stops a false match inside a longer word.
PRERELEASE_MARKER_PATTERN = re.compile(r"[-\s_](?:snapshot|pre|rc)(?![a-z])", re.IGNORECASE)


def _checked_object_name(value: str, noun: str) -> str:
    """Return `value` when it is a full Git object name, and raise when it is not.

    The name goes straight into a raw URL, and every later stage of the build
    reads that URL. A short name, a branch name, or an empty string would fail
    there, one stage later and one URL away from the answer that produced it --
    and `main` would not fail at all. It would read the branch head.
    """
    if COMMIT_SHA_PATTERN.fullmatch(value) is None:
        raise ValueError(f"the {noun} {value!r} is not a full 40-character Git object name")
    return value


def _checked_repository_path(path: str) -> str:
    """Return `path` when it names one file inside a pinned commit.

    The pin is the point of this module, and it lives in one segment of the raw
    URL. Everything after that segment is this string, so this string can undo
    the pin. `../summary/item_components/data.json` resolves to
    `raw.githubusercontent.com/misode/mcmeta/summary/item_components/data.json`
    under RFC 3986 dot-segment removal, which is what `urllib.parse.urljoin`, a
    proxy, and the CDN in front of raw.githubusercontent.com all apply. That URL
    is the branch head: it moves under the build, and it carries snapshot data
    within hours of a snapshot release.

    A later stage builds this string from upstream data -- a registry ID, a loot
    table name -- and CLAUDE.md says the manifest is not the only thing that can
    supply a value, so the rule here matches `mcmeta_tag_name`: check it, do not
    trust it.
    """
    segments = path.split("/")
    unsafe = [
        segment
        for segment in segments
        if segment in DOT_SEGMENTS or SAFE_PATH_SEGMENT_PATTERN.fullmatch(segment) is None
    ]
    if unsafe:
        raise FetchError(
            f"the repository path {path!r} does not name one file inside a pinned commit. "
            f"A path holds segments of letters, digits, a dot, an underscore, or a hyphen, "
            f"joined by one slash each, and no segment is {'.'!r} or {'..'!r}."
        )
    return path


class GitRefObject(BaseModel):
    """The `object` of a Git reference: what the reference points at."""

    sha: str
    type: str

    @field_validator("sha")
    @classmethod
    def _sha_must_be_a_full_object_name(cls, value: str) -> str:
        """Refuse a SHA that is not 40 hexadecimal characters."""
        return _checked_object_name(value, "object sha")


class GitRef(BaseModel):
    """One answer of the GitHub single-reference endpoint.

    The answer also carries `node_id` and two `url` fields. This project builds
    its own URLs from the SHA, so the model drops them.
    """

    ref: str
    object: GitRefObject


class McmetaTag(BaseModel):
    """One pinned mcmeta branch, and the commit that the tag named.

    Later stages read `commit_sha`, not `tag`. A tag can move, and a maintainer
    can delete a tag and write it again. A commit SHA cannot change. So one
    resolve at the start of a build fixes the data for the whole build.
    """

    version_id: str
    branch: str
    tag: str
    commit_sha: str

    @field_validator("commit_sha")
    @classmethod
    def _commit_sha_must_be_a_full_object_name(cls, value: str) -> str:
        """Refuse a commit SHA that is not 40 hexadecimal characters.

        `resolve_mcmeta_tag` builds this model from a SHA that `parse_git_ref`
        already checked, so this rule never fires on that path. It fires on the
        other one: the content-hash cache of the next stage writes this model to
        disk and reads it back, and a `McmetaTag` rebuilt from an edited or
        truncated cache file goes straight into `raw_url`. A `commit_sha` of
        `main` there reads the branch head and reports nothing.
        """
        return _checked_object_name(value, "commit sha")

    def raw_url(self, path: str) -> str:
        """Return the URL of one file of this commit.

        `path` is the path inside the branch, such as `item_components/data.json`.
        A path that could read anything other than one file of this commit
        raises `FetchError`. `_checked_repository_path` holds the reason.
        """
        return MCMETA_RAW_URL.format(
            repository=MCMETA_REPOSITORY,
            commit_sha=self.commit_sha,
            path=_checked_repository_path(path),
        )


def mcmeta_tag_name(version_id: str, branch: str) -> str:
    """Return the mcmeta tag of one branch at one Minecraft version.

    The function checks both parts before it joins them. A bad branch name fails
    with the accepted list. A version ID with a character that a URL path reads
    as structure fails here, before the request goes out.
    """
    if branch not in MCMETA_BRANCHES:
        accepted = ", ".join(sorted(MCMETA_BRANCHES))
        raise FetchError(f"{branch!r} is not an mcmeta branch. This project reads: {accepted}.")
    if SAFE_VERSION_ID_PATTERN.fullmatch(version_id) is None:
        raise FetchError(
            f"the version id {version_id!r} holds a character that this module does not put "
            f"in a URL path. A Minecraft version id holds letters, digits, a dot, an "
            f"underscore, or a hyphen."
        )
    return f"{version_id}-{branch}"


def _reject_a_prerelease(version_id: str) -> None:
    """Stop a snapshot, a pre-release, or a release candidate at the door.

    Non-negotiable 1 of CLAUDE.md asks for correct Java Edition data. A build of
    the wrong version of the game breaks that rule in the way that is hardest to
    see: every number on the screen still looks like a Minecraft number.
    """
    weekly = WEEKLY_SNAPSHOT_PATTERN.fullmatch(version_id) is not None
    if weekly or PRERELEASE_MARKER_PATTERN.search(version_id) is not None:
        raise FetchError(
            f"the version id {version_id!r} names a pre-release of Minecraft, and this build "
            f"takes releases only. Pass allow_prerelease=True to read a snapshot on purpose."
        )


def parse_git_ref(payload: bytes, *, expected_tag: str, source: str) -> GitRef:
    """Read one reference answer, and prove that it names `expected_tag`.

    The function is pure. It reads bytes and returns a model, so every rule here
    is covered by a test that opens no socket.

    The equality check is the first guard of this module. The endpoint matches
    an exact name today. This check keeps that fact a fact: an endpoint that
    started to answer a near match would fail the build instead of pinning the
    wrong tag.
    """
    document: Any = decode_json(payload, source=source)
    if not isinstance(document, dict):
        raise FetchError(
            f"{source} returned {type(document).__name__} at the top level, not a JSON object"
        )
    try:
        reference = GitRef.model_validate(document)
    except ValidationError as error:
        raise FetchError(f"{source} is not a usable Git reference: {error}") from error

    wanted = f"refs/tags/{expected_tag}"
    if reference.ref != wanted:
        raise FetchError(
            f"{source} answered with the reference {reference.ref!r}, and this build asked for "
            f"{wanted!r}. A near match must not pin a tag."
        )
    if reference.object.type != COMMIT_OBJECT_TYPE:
        raise FetchError(
            f"the tag {expected_tag!r} points at a Git object of the type "
            f"{reference.object.type!r}, not {COMMIT_OBJECT_TYPE!r}. mcmeta writes lightweight "
            f"tags, so this build reads the commit sha straight off the tag."
        )
    return reference


def resolve_mcmeta_tag(
    version_id: str,
    branch: str,
    *,
    allow_prerelease: bool = False,
    cache: ContentCache | None = None,
    transport: Transport = get_bytes,
) -> McmetaTag:
    """Return the pinned mcmeta tag of one branch at one Minecraft version.

    `version_id` is a Minecraft Java Edition release ID, such as `26.2`.
    `pipeline.fetch.version_manifest.fetch_latest_release_id` returns that
    string. `branch` is one name of `MCMETA_BRANCHES`.

    Set `allow_prerelease` to read a snapshot tag. A release build leaves it
    off. Pass `transport` to read the bytes from somewhere else. A test passes a
    callable of its own, so no test of this module opens a socket.

    Pass `cache` to store the answer, keyed by the URL alone and with no caller
    revision. That is safe here in a way it is not for
    `pipeline.fetch.version_manifest.fetch_version_manifest`, and the
    difference is worth being precise about, because the two reads look alike
    and only one of them names an immutable thing. The URL this function reads
    is `.../git/ref/tags/26.2-data`: the version is *in the URL*, so the entry
    can never answer a question about a different version. A published mcmeta
    version tag also points at one commit and stays there -- the repository
    cuts a new tag per Minecraft version rather than moving an old one. The
    manifest URL names no version at all, which is exactly why that function
    demands a revision and this one does not.

    Without a cache this function opens the network on every call, which is
    what it has always done and what a fresh build wants. With one, two
    lookups of an already-built version cost nothing, and `python -m pipeline
    build --offline` can pin its tags with no network at all.

    Any failure raises `FetchError` and stops the build.
    """
    if not allow_prerelease:
        _reject_a_prerelease(version_id)
    tag = mcmeta_tag_name(version_id, branch)
    url = GITHUB_REF_URL.format(repository=MCMETA_REPOSITORY, tag=tag)

    def read(payload: bytes) -> GitRef:
        return parse_git_ref(payload, expected_tag=tag, source=url)

    # `fetch_and_read` rather than the `_fetch_and_read` alias below: this
    # function sits above that binding in the file, and naming the import
    # directly keeps the read order-independent instead of relying on a
    # module-level name that is bound two hundred lines further down.
    reference = (
        read(transport(url))
        if cache is None
        else fetch_and_read(cache, url, transport=transport, read=read)
    )
    return McmetaTag(
        version_id=version_id,
        branch=branch,
        tag=tag,
        commit_sha=reference.object.sha,
    )


def _checked_archive_segments(name: str, source: str) -> list[str]:
    """Split one archive member name into segments, and refuse a name that lies.

    This reader keeps every file in memory and writes none, so a member named
    `../../etc/passwd` overwrites nothing. The rule is still here, because the
    names that leave this module do not stop at this module. Each one becomes a
    dictionary key, then a cache key, then part of an entity ID, and a later
    stage will join one to a path on disk. A name that carries a dot segment or
    a leading slash is wrong at the moment it arrives, and that is the cheapest
    moment to say so.

    The rule is the rule of `_checked_repository_path`, with two additions that
    only an archive needs. A backslash is refused because Windows reads it as a
    separator and POSIX reads it as an ordinary character, so a member named
    `a\\..\\b` means two different things on two machines. A drive letter is
    refused for the same reason: `C:file` is a path relative to another drive.

    Every one of the 9,030 member names of the live `data` branch passes.
    """
    if not name:
        raise FetchError(f"{source} holds a member with an empty name.")
    if "\\" in name or name.startswith("/") or re.fullmatch(r"[A-Za-z]:.*", name) is not None:
        raise FetchError(
            f"{source} holds the member {name!r}, which is not a relative path of one archive."
        )
    segments = name.split("/")
    unsafe = [
        segment
        for segment in segments
        if segment in DOT_SEGMENTS or SAFE_PATH_SEGMENT_PATTERN.fullmatch(segment) is None
    ]
    if unsafe:
        raise FetchError(
            f"{source} holds the member {name!r}. A member path holds segments of letters, "
            f"digits, a dot, an underscore, or a hyphen, joined by one slash each, and no "
            f"segment is {'.'!r} or {'..'!r}."
        )
    return segments


def read_data_archive(
    payload: bytes,
    *,
    groups: Iterable[str] = DATA_GROUPS,
    source: str,
) -> dict[str, bytes]:
    """Read one mcmeta `data` archive, and return the files of `groups`.

    The key of the answer is the path under `data/minecraft/`, such as
    `recipe/oak_stairs.json` or `tags/item/planks.json`. The value is the bytes
    of that file. A caller decodes the JSON itself, because this function stays
    a reader and the extract stage owns the parsing.

    The function is pure. It takes bytes and returns a dictionary, so a test
    builds its own archive in memory and opens no socket. Name `source` so the
    error of a bad archive says which read produced it.

    Every fault raises `FetchError`: a body that is not a gzip archive, a member
    that is not a regular file, a member name that could leave the archive, two
    members of one name, an archive that goes past `MAX_ARCHIVE_BYTES`, and an
    archive that holds no wanted file at all. The last one matters as much as
    the rest. mcmeta could rename a directory in a future version, and an empty
    answer would then travel down the pipeline as "Minecraft has no recipes"
    rather than as a broken read.
    """
    prefixes = tuple(f"{ARCHIVE_NAMESPACE_ROOT}/{group}/" for group in groups)
    if not prefixes:
        raise FetchError(f"{source} was read with no group to look for.")

    files: dict[str, bytes] = {}
    root: str | None = None
    archive_bytes = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            for member in archive:
                # The header declares the size, so this runs before the content
                # of the member is decompressed and it stops a bomb part-way
                # through. The header block itself counts too, because a member
                # that declares no content still costs one, and `tarfile` holds
                # a `TarInfo` for every member it has walked.
                archive_bytes += TAR_HEADER_BYTES + max(member.size, 0)
                if archive_bytes > MAX_ARCHIVE_BYTES:
                    raise FetchError(
                        f"{source} holds more than {MAX_ARCHIVE_BYTES} bytes of archive. "
                        f"The mcmeta data branch is under 10 MB, so this is not that archive."
                    )
                if member.isdir():
                    continue
                if not member.isfile():
                    raise FetchError(
                        f"{source} holds the member {member.name!r}, which is not a regular file "
                        f"or a directory. mcmeta publishes neither a link nor a device node, so "
                        f"this archive is not the one this build asked for."
                    )

                segments = _checked_archive_segments(member.name, source)
                if len(segments) < 2:
                    # A file at the top level of the archive. GitHub wraps every
                    # commit in one directory, so a file here means the layout
                    # changed and the strip below would remove a real segment.
                    raise FetchError(
                        f"{source} holds the file {member.name!r} outside the root directory of "
                        f"the archive."
                    )
                if root is None:
                    root = segments[0]
                elif segments[0] != root:
                    raise FetchError(
                        f"{source} holds two root directories, {root!r} and {segments[0]!r}. "
                        f"One commit archive holds one."
                    )

                relative = "/".join(segments[1:])
                if not relative.startswith(prefixes):
                    continue
                handle = archive.extractfile(member)
                if handle is None:
                    raise FetchError(f"{source} could not open the member {member.name!r}.")
                content = handle.read()
                if len(content) != member.size:
                    raise FetchError(
                        f"{source} declared {member.size} bytes for {member.name!r} and gave "
                        f"{len(content)}. The archive is truncated."
                    )

                key = relative[len(ARCHIVE_NAMESPACE_ROOT) + 1 :]
                if key in files:
                    raise FetchError(
                        f"{source} holds two members named {member.name!r}. A later member would "
                        f"silently replace an earlier one."
                    )
                files[key] = content
    except (tarfile.TarError, EOFError, OSError) as error:
        raise FetchError(f"{source} is not a readable gzip archive: {error}") from error

    if not files:
        wanted = ", ".join(prefixes)
        raise FetchError(
            f"{source} holds no file under any of: {wanted}. An empty read is a broken scrape, "
            f"not a version of Minecraft with no data."
        )
    return files


# `fetch_and_read` moved to `pipeline.fetch.cache` when the Bucket client of
# Tier B needed the same rule: read a payload before you store it, so an error
# page from a proxy never enters the store. The name stays bound here because
# this module's docstring and two of its functions name it, and because a reader
# who finds the old private name in the history lands on the current one.
_fetch_and_read = fetch_and_read


def fetch_summary_payload(
    tag: McmetaTag,
    name: str,
    *,
    cache: ContentCache | None = None,
    transport: Transport = get_bytes,
) -> bytes:
    """Return one file of the pinned `summary` branch, as bytes.

    `name` is a key of `SUMMARY_PAYLOADS`. `tag` comes from `resolve_mcmeta_tag`
    with the branch `summary`.

    The answer is cached by content hash, so a second build of one Minecraft
    version reads no network. Pass `cache` to name the store, which every test
    does. Pass `transport` to read the bytes from somewhere else.

    The bytes come back undecoded, because the extract stage owns the parsing.
    They are still decoded once here, and thrown away, so that a body which is
    not JSON never enters the store. `_fetch_and_read` holds the reason.
    """
    if tag.branch != "summary":
        raise FetchError(
            f"the tag {tag.tag!r} pins the branch {tag.branch!r}, and a summary payload lives on "
            f"the branch 'summary'."
        )
    path = SUMMARY_PAYLOADS.get(name)
    if path is None:
        accepted = ", ".join(sorted(SUMMARY_PAYLOADS))
        raise FetchError(f"{name!r} is not a summary payload. This project reads: {accepted}.")
    store = ContentCache() if cache is None else cache
    url = tag.raw_url(path)

    def read(payload: bytes) -> bytes:
        decode_json(payload, source=url)
        return payload

    return _fetch_and_read(store, url, transport=transport, read=read)


def fetch_data_files(
    tag: McmetaTag,
    *,
    groups: Iterable[str] = DATA_GROUPS,
    cache: ContentCache | None = None,
    transport: Transport = get_bytes,
) -> dict[str, bytes]:
    """Return the vanilla data pack files of `groups`, from the pinned `data` branch.

    The key of the answer is the path under `data/minecraft/`, such as
    `loot_table/entities/creeper.json`. `tag` comes from `resolve_mcmeta_tag`
    with the branch `data`.

    One archive covers every group, so this is one request for the 5,422 files
    that Phase 1 reads. The archive is cached by content hash, and its URL
    carries the pinned commit SHA, so the cached copy never goes stale.

    The archive is read before it is stored, so a body that is not an archive
    costs one fetch rather than every future build. `_fetch_and_read` holds the
    reason.
    """
    if tag.branch != "data":
        raise FetchError(
            f"the tag {tag.tag!r} pins the branch {tag.branch!r}, and the vanilla data pack lives "
            f"on the branch 'data'."
        )
    # Read the argument one time. `Iterable` accepts a generator, and a
    # generator that is walked twice is empty on the second walk.
    wanted = tuple(groups)
    unknown = sorted(set(wanted) - set(DATA_GROUPS))
    if unknown:
        accepted = ", ".join(DATA_GROUPS)
        raise FetchError(
            f"{', '.join(repr(group) for group in unknown)} is not a data group of this project. "
            f"This project reads: {accepted}."
        )
    # `read_data_archive` refuses this too. Refusing it there alone would mean
    # the 2.7 MB archive is already downloaded by the time anyone says so.
    if not wanted:
        accepted = ", ".join(DATA_GROUPS)
        raise FetchError(f"a data read names at least one group. This project reads: {accepted}.")
    url = MCMETA_ARCHIVE_URL.format(repository=MCMETA_REPOSITORY, commit_sha=tag.commit_sha)
    store = ContentCache() if cache is None else cache

    def read(payload: bytes) -> dict[str, bytes]:
        return read_data_archive(payload, groups=wanted, source=url)

    return _fetch_and_read(store, url, transport=transport, read=read)
