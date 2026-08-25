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

This module keeps no disk cache. The next stage of Phase 1 adds the content-hash
cache that CLAUDE.md asks for, and it caches the large payloads that the SHA
below addresses.
"""

import re
from typing import Any

from pydantic import BaseModel, ValidationError, field_validator

from pipeline.fetch import FetchError, Transport, decode_json, get_bytes

__all__ = [
    "COMMIT_OBJECT_TYPE",
    "GITHUB_REF_URL",
    "MCMETA_BRANCHES",
    "MCMETA_RAW_URL",
    "MCMETA_REPOSITORY",
    "GitRef",
    "GitRefObject",
    "McmetaTag",
    "mcmeta_tag_name",
    "parse_git_ref",
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

# The branches that CLAUDE.md records, and the only names that this project
# asks for. A typo then fails with this list, not with a 404 that reads like an
# outage at GitHub.
MCMETA_BRANCHES = frozenset({"assets", "atlas", "data", "diff", "registries", "summary"})

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
    transport: Transport = get_bytes,
) -> McmetaTag:
    """Return the pinned mcmeta tag of one branch at one Minecraft version.

    `version_id` is a Minecraft Java Edition release ID, such as `26.2`.
    `pipeline.fetch.version_manifest.fetch_latest_release_id` returns that
    string. `branch` is one name of `MCMETA_BRANCHES`.

    Set `allow_prerelease` to read a snapshot tag. A release build leaves it
    off. Pass `transport` to read the bytes from somewhere else. A test passes a
    callable of its own, so no test of this module opens a socket.

    Any failure raises `FetchError` and stops the build.
    """
    if not allow_prerelease:
        _reject_a_prerelease(version_id)
    tag = mcmeta_tag_name(version_id, branch)
    url = GITHUB_REF_URL.format(repository=MCMETA_REPOSITORY, tag=tag)
    reference = parse_git_ref(transport(url), expected_tag=tag, source=url)
    return McmetaTag(
        version_id=version_id,
        branch=branch,
        tag=tag,
        commit_sha=reference.object.sha,
    )
