"""Repository invariants that CLAUDE.md and AGENTS.md name but no tool checks.

Both fail silently. A mirror that drifts still renders, and a working tree
checked out with CRLF still runs; the damage shows up later as a review diff
nobody wrote or as a format gate that reports every file in the repository.
pytest is the only gate that reads the whole tree, so they live here next to
the version check.
"""

import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from pipeline.fetch.mcmeta import DATA_GROUPS, SUMMARY_PAYLOADS

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
AGENTS_MD = REPO_ROOT / "AGENTS.md"

# The sync note sits above this line and names the other file, so it is the one
# part that differs on purpose.
HORIZONTAL_RULE = "---"


def _body_below_the_rule(path: Path) -> str:
    """Return everything after the first horizontal rule, bytes unchanged.

    `read_bytes` rather than `read_text`: text mode collapses CRLF to LF, which
    would hide exactly the drift the second test in this module looks for.
    """
    text = path.read_bytes().decode("utf-8")
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if line.rstrip("\r") == HORIZONTAL_RULE:
            return "\n".join(lines[index + 1 :])
    pytest.fail(f"{path.name} has no horizontal rule, so the mirror has no boundary")


def test_claude_md_and_agents_md_mirror_below_the_rule() -> None:
    """CLAUDE.md and AGENTS.md must stay byte-identical below the rule.

    Prettier and ruff both skip Markdown so neither rewrites the hand-wrapped
    text, which means nothing else compares the two files. An edit applied to
    one and forgotten on the other leaves whichever agent reads the stale copy
    working from rules that no longer hold.
    """
    assert _body_below_the_rule(CLAUDE_MD) == _body_below_the_rule(AGENTS_MD)


def test_tracked_files_check_out_with_lf() -> None:
    """No tracked file may land in the working tree with CRLF or mixed endings.

    `.gitattributes` sets `eol=lf` to guarantee this. Without it, `text=auto`
    alone defers to `core.autocrlf`, which the Git for Windows installer turns
    on by default, so a fresh clone rewrites every file to CRLF. Prettier's
    `endOfLine` defaults to `lf`, so `pnpm format:check` then reports every
    file it reads, and the mirror above breaks in the same stroke.
    """
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH, so the working-tree endings cannot be read")

    listing = subprocess.run(
        ["git", "ls-files", "--eol", "-z"],
        capture_output=True,
        check=True,
        cwd=REPO_ROOT,
        text=True,
    ).stdout

    offenders = [
        entry.split("\t", 1)[1]
        for entry in listing.split("\0")
        if entry and entry.split("\t", 1)[0].split()[1] in {"w/crlf", "w/mixed"}
    ]
    assert offenders == []


# `/data` does not exist yet. The emit stage of the pipeline writes `/data/dist`
# and the fetch stage writes `/data/.cache` beside it, and neither stage is
# built. Name the stage rather than a phase of TODO.md: that file deletes a
# phase once its checklist empties, so a reference to a phase number goes
# dangling on the commit that finishes it. `git check-ignore` reads path names
# only, so it answers for a path that has no file behind it.
# The trailing slash on the first entry is necessary. The rule ends with a
# slash, so it matches a directory only, and no directory exists here yet.
IGNORED_DATA_PATHS = (
    "data/.cache/",
    "data/.cache/mcmeta/26.2/registries.json",
    "data/.cache/sprites/a1b2c3.png",
)
# One shard, standing in for the whole of the Phase 1 output tree.
PHASE_ONE_SHARD = "data/dist/entities/mob-0.json"

TRACKED_DATA_PATHS = (
    "data/dist/index.json",
    "data/dist/entities/mob-0.json",
    "data/dist/sprites.png",
    "data/curated/mob-overrides.json",
)


def _ignored_paths(candidates: tuple[str, ...], repo_root: Path = REPO_ROOT) -> set[str]:
    """Return the candidates that the ignore rules of the repository match.

    `--no-index` is load-bearing, not a tidying flag. Without it `git
    check-ignore` consults the index first and reports every tracked path as
    unmatched, whatever the ignore rules say. That is the wrong question
    here: this module asks what the rules do, and it asks it about
    `/data/dist`, which Phase 1 commits. Index-aware, the answer flips to
    "not ignored" for those paths the moment they become tracked, so the
    gate below would go green against a repository whose `git add` had
    already started dropping regenerated shards on the floor.

    `git check-ignore` exits with code 1 when it matches no path, so this
    passes `check=False`. A non-zero exit is an answer here, not a failure.
    """
    result = subprocess.run(
        ["git", "check-ignore", "--stdin", "-z", "--no-index"],
        capture_output=True,
        check=False,
        cwd=repo_root,
        input="\0".join(candidates),
        text=True,
    )
    if result.returncode not in {0, 1}:
        pytest.fail(f"git check-ignore failed: {result.stderr.strip()}")
    return {path for path in result.stdout.split("\0") if path}


def test_data_cache_is_ignored_and_data_dist_is_tracked() -> None:
    """Git must ignore `/data/.cache` and must track `/data/dist`.

    CLAUDE.md names both halves. The cache holds the intermediate files of the
    pipeline, which no clone needs. `/data/dist` holds the payload that the web
    build reads, and the build reads nothing else, so a deployment stays static
    only while Git tracks that directory. A bare `dist/` rule added later would
    match both `web/dist` and `data/dist`, and the site would then build from a
    directory that a fresh clone does not have. This test is the gate.
    """
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH, so the ignore rules cannot be read")

    assert _ignored_paths(IGNORED_DATA_PATHS) == set(IGNORED_DATA_PATHS)
    assert _ignored_paths(TRACKED_DATA_PATHS) == set()


@pytest.fixture
def phase_one_repo(tmp_path: Path) -> Path:
    """A throwaway repository shaped the way Phase 1 leaves this one.

    `/data/dist` holds committed pipeline output, which is the state that makes
    the check above hard: the paths under test are tracked. Local configuration
    overrides the global and system files, so nothing on the developer machine
    can decide the outcome: `core.excludesFile` cannot add an ignore rule this
    fixture did not write, and neither a signing key nor a global hook can stall
    the commit. Git reads a `core.hooksPath` that does not exist as "no hooks".
    """
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH, so the ignore rules cannot be read")

    def git(*args: str) -> None:
        subprocess.run(["git", *args], capture_output=True, check=True, cwd=tmp_path, text=True)

    git("init", "-q", ".")
    git("config", "core.excludesFile", str(tmp_path / "no-such-excludes"))
    git("config", "core.hooksPath", str(tmp_path / "no-such-hooks"))
    git("config", "commit.gpgsign", "false")
    git("config", "user.email", "gate@example.invalid")
    git("config", "user.name", "gate")

    (tmp_path / ".gitignore").write_text("web/dist/\n/data/.cache/\n", encoding="utf-8")
    shard = tmp_path / PHASE_ONE_SHARD
    shard.parent.mkdir(parents=True)
    shard.write_text("{}\n", encoding="utf-8")

    git("add", "-A")
    git("commit", "-qm", "phase 1 output")
    return tmp_path


def test_the_ignore_gate_still_answers_for_a_tracked_path(phase_one_repo: Path) -> None:
    """A tracked path that an ignore rule matches must read as ignored.

    This pins the gate above rather than the rules. `git check-ignore` answers
    from the index unless told otherwise, and the index says "tracked, so not
    ignored" for every file Phase 1 commits under `/data/dist`. A gate built on
    that answer inverts precisely when it starts to matter: add a bare `dist/`
    rule, and `git add` quietly stops staging regenerated shards while the test
    reports green, which is the silent break the rule in `.gitignore` warns
    about. So the helper has to see the rule through the index, and this is the
    only test that can tell whether it does, because `/data/dist` does not
    exist in this repository yet.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", PHASE_ONE_SHARD],
        capture_output=True,
        check=True,
        cwd=phase_one_repo,
        text=True,
    ).stdout
    assert PHASE_ONE_SHARD in tracked.split("\0"), "the fixture must commit the shard"

    candidates = (PHASE_ONE_SHARD,)
    assert _ignored_paths(candidates, phase_one_repo) == set()

    gitignore = phase_one_repo / ".gitignore"
    gitignore.write_text(gitignore.read_text(encoding="utf-8") + "dist/\n", encoding="utf-8")

    assert _ignored_paths(candidates, phase_one_repo) == set(candidates)


# `/data/dist` holds the whole of the pipeline output, so every path below must
# read as generated. The three entries come from `TRACKED_DATA_PATHS` above.
GENERATED_PATHS = tuple(path for path in TRACKED_DATA_PATHS if path.startswith("data/dist/"))

# None of these may read as generated. `data/curated` holds the hand-written
# overrides, and a person reviews every line of them.
#
# `web/dist` catches a pattern widened at the front. Note which mutation that
# is: dropping the leading slash is not one. A pattern that holds a slash
# anywhere but its last character is already anchored to the directory of the
# `.gitattributes` file, so `data/dist/**` matches exactly what `/data/dist/**`
# matches, and no guard can tell the two apart. The mutation that does reach
# `web/dist` is a widened prefix -- `**/dist/**` or `*dist/**` -- which marks
# every `dist` directory at any depth.
#
# The two mirror documents catch a pattern that spread to the whole repository,
# which would collapse the one diff that always needs a reader.
PLAIN_PATHS = (
    "data/curated/mob-overrides.json",
    "web/dist/assets/app.js",
    "CLAUDE.md",
    "AGENTS.md",
    # The hand-written fixtures of `tests/fixtures`. They sit in the directory
    # that the snapshot rule below covers, so a rule widened to the directory
    # rather than to the file names would take these two with it.
    "tests/fixtures/version_manifest_v2.json",
    "tests/fixtures/mcmeta_ref_26_2_summary.json",
)

# The mcmeta snapshots that `tests/fixtures/build_block_tag_snapshot.py` writes.
# 6,405 lines of JSON that no person wrote, committed for the same reason
# `/data/dist` is committed, and needing the same mark for the same reason: a
# version bump rewrites both files, and the hand-written half of that pull
# request has to stay readable.
#
# The 26.3 rows are paths with no file behind them. `git check-attr` answers for
# a name, so they prove that the rule carries a `*` where the version sits. A
# rule naming 26.2 outright would pass on the first two rows and leave the next
# snapshot unmarked, which is a failure nobody sees until the release PR.
GENERATED_FIXTURE_PATHS = (
    "tests/fixtures/mcmeta_26_2_block_tags.json",
    "tests/fixtures/mcmeta_26_2_block_harvest.json",
    "tests/fixtures/mcmeta_26_3_block_tags.json",
    "tests/fixtures/mcmeta_26_3_block_harvest.json",
)

# `git check-attr` prints the value of the attribute, not the word "set". A
# rule written as `linguist-generated` gives `set`, and one written as
# `linguist-generated=true` gives `true`. Linguist reads both as enabled, so
# the gate below must accept both. Anything else means the mark is absent.
ENABLED_VALUES = frozenset({"set", "true"})

# `* text=auto eol=lf` at the top of `.gitattributes` decides these, and the
# generated-file rule under it must leave them alone.
LINE_ENDING_ATTRIBUTES = (("text", "auto"), ("eol", "lf"))


def _attribute_values(
    candidates: tuple[str, ...], attribute: str, repo_root: Path = REPO_ROOT
) -> dict[str, str]:
    """Return the value Git resolves for `attribute` on each candidate path.

    `git check-attr` reads path names alone. It answers for a path that has no
    file behind it, which is what this module needs, because `/data` does not
    exist yet. `-z` makes the tool read NUL-separated input and write fields
    that are each NUL-*terminated*, three per path: path, attribute, value.

    Every field is kept, including an empty one. A rule written as
    `linguist-generated=` resolves to the empty string, and discarding that
    field would shift every later record by one and pair a path with another
    path. A length check cannot see that corruption, because the shortened
    stream is still a whole number of records.

    The path column is compared against the candidates rather than trusted. A
    gate that asserts "none of these is marked" reads the same green whether
    Git answered "no" or did not answer at all.
    """
    result = subprocess.run(
        ["git", "check-attr", "--stdin", "-z", attribute],
        capture_output=True,
        check=True,
        cwd=repo_root,
        input="\0".join(candidates),
        text=True,
    )
    # Every field carries a terminator, so the split leaves one trailing empty
    # field and nothing else to drop.
    fields = result.stdout.split("\0")
    if fields and fields[-1] == "":
        fields = fields[:-1]
    if len(fields) != 3 * len(candidates):
        pytest.fail(
            f"git check-attr wrote {len(fields)} fields for {len(candidates)} paths, "
            f"so the output is not the three-field records this helper reads"
        )
    if fields[0::3] != list(candidates):
        pytest.fail(f"git check-attr answered for {fields[0::3]}, not for {list(candidates)}")
    return dict(zip(fields[0::3], fields[2::3], strict=True))


def _generated_paths(candidates: tuple[str, ...], repo_root: Path = REPO_ROOT) -> set[str]:
    """Return the candidates that `.gitattributes` marks as generated."""
    values = _attribute_values(candidates, "linguist-generated", repo_root)
    return {path for path, value in values.items() if value in ENABLED_VALUES}


@pytest.fixture
def empty_value_repo(tmp_path: Path) -> Path:
    """A throwaway repository whose rule resolves to the empty string.

    `linguist-generated=` is the one rule shape that makes `git check-attr`
    write an empty value field, which is what the record parsing above has to
    survive. No commit is needed: `check-attr` reads the working-tree
    `.gitattributes` and answers for paths that have no file behind them.

    `core.attributesFile` is pointed at nothing, the way `phase_one_repo`
    points `core.excludesFile` at nothing, so no rule from the developer
    machine reaches this fixture.
    """
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH, so the attributes cannot be read")

    def git(*args: str) -> None:
        subprocess.run(["git", *args], capture_output=True, check=True, cwd=tmp_path, text=True)

    git("init", "-q", ".")
    git("config", "core.attributesFile", str(tmp_path / "no-such-attributes"))

    attributes = tmp_path / ".gitattributes"
    attributes.write_text("/data/dist/** linguist-generated=\n", encoding="utf-8")
    return tmp_path


def test_the_attribute_gate_keeps_an_empty_value_field(empty_value_repo: Path) -> None:
    """An empty attribute value must not shift the records that follow it.

    This pins the helper rather than the rules. `git check-attr -z` terminates
    every field, so a rule written as `linguist-generated=` writes an empty
    value field, and discarding empty fields shifts each later record by one
    and pairs a path with another path. A count check cannot catch that: three
    paths lose three fields and the stream stays a whole number of records, so
    the helper returns a confident wrong answer instead of failing.

    The gate above then reports the mark as absent for a reason that has
    nothing to do with the mark, and a reader chasing that message edits a
    pattern that was never wrong.
    """
    candidates = GENERATED_PATHS
    assert len(candidates) == 3, "the shift needs more than one record to show"

    values = _attribute_values(candidates, "linguist-generated", empty_value_repo)

    # Every path keeps its own value, and that value is the empty string --
    # not the path that followed it.
    assert values == dict.fromkeys(candidates, "")
    # An empty value is not the mark. Linguist reads `set` and `true`.
    assert _generated_paths(candidates, empty_value_repo) == set()


def test_pipeline_output_is_marked_as_generated() -> None:
    """GitHub must collapse each file under `/data/dist` in a review.

    Every Minecraft release rewrites that tree, and no person writes a line of
    it. GitHub hides a file behind a "Load diff" control only when
    `.gitattributes` marks the file as generated. Without the mark, a release
    pull request buries the hand-written change under thousands of
    machine-written lines, and the reviewer reads neither.

    `.gitattributes` fails in silence. A wrong pattern reports no error and
    prints no warning, so the only way to see the failure is to read the
    attribute back through Git. This test does that.
    """
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH, so the attributes cannot be read")

    # `GENERATED_PATHS` is derived, so a rewrite of `TRACKED_DATA_PATHS` could
    # leave it empty, and `_generated_paths(()) == set(())` is `set() ==
    # set()`: green with nothing checked. Pin the count so that rewrite fails
    # here instead of quietly retiring the gate.
    assert len(GENERATED_PATHS) == 3, "the /data/dist paths of TRACKED_DATA_PATHS went missing"

    assert _generated_paths(GENERATED_PATHS) == set(GENERATED_PATHS)
    assert _generated_paths(PLAIN_PATHS) == set()


def test_the_mcmeta_test_fixtures_are_marked_as_generated() -> None:
    """GitHub must collapse the mcmeta snapshots of `tests/fixtures` too.

    They are not pipeline output, so the rule above does not reach them, and
    the reason for the mark is the same either way: 6,405 lines that a script
    wrote, rewritten whole every time the pinned Minecraft version moves.
    Unmarked, the pull request that raises that version shows the hand-written
    change and the machine-written change at the same size.

    The 26.3 rows carry the other half of the check. They name no file, and
    `git check-attr` answers for a name, so a rule that spelled 26.2 out passes
    on the pair that exists and leaves the next snapshot bare. That failure has
    no symptom until the release, which is the wrong moment to find it.
    """
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH, so the attributes cannot be read")

    assert _generated_paths(GENERATED_FIXTURE_PATHS) == set(GENERATED_FIXTURE_PATHS)
    # The hand-written fixtures share the directory, so the rule must name the
    # files and not the directory. `PLAIN_PATHS` holds both of them.
    assert _generated_paths(PLAIN_PATHS) == set()


def test_the_generated_mark_leaves_the_line_endings_alone() -> None:
    """Marking `/data/dist` generated must not disturb `text=auto eol=lf`.

    Nothing else can check this yet. `test_tracked_files_check_out_with_lf`
    reads `git ls-files --eol`, which reports only files that exist and are
    tracked, and `/data/dist` arrives with Phase 1. So a rule written today
    that unsets `text` would go unnoticed until the pipeline commits several
    thousand JSON shards, and every one of them would then check out with CRLF
    on Windows.

    The reachable mistake is `binary`, or a hand-written `-text`, added by
    someone trying to make the collapse stronger. `binary` is a macro for
    `-diff -merge -text`: it resolves `text` to `unset` and leaves `eol`
    unspecified, and `-diff` is the thing the file already warns against,
    because it makes `git diff` and `git log -p` print "Binary files differ"
    instead of the content.
    """
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH, so the attributes cannot be read")

    for attribute, expected in LINE_ENDING_ATTRIBUTES:
        values = _attribute_values(GENERATED_PATHS, attribute)
        assert values == dict.fromkeys(GENERATED_PATHS, expected)


# README.md repeats three versions that the manifests own. A repeated fact
# rots. Raise `requires-python` and the README still names the old floor, and
# the next contributor installs a toolchain the pipeline rejects. Neither
# prettier nor ruff reads Markdown, and no manifest reads prose, so nothing
# else in the repository compares the two.
README_MD = REPO_ROOT / "README.md"
PYPROJECT_TOML = REPO_ROOT / "pyproject.toml"
PACKAGE_JSON = REPO_ROOT / "package.json"

REQUIREMENTS_HEADING = "## Requirements"

# One row of the Requirements list: `- **Python 3.12 or later** — the pipeline.`
# The bold label is the whole claim, so the gate compares labels and ignores
# the prose after the dash. Matching the version alone would pass on `3.12`
# found inside `3.12.1`, inside a path, or inside another section.
REQUIREMENT_LINE = re.compile(r"^- \*\*(?P<label>[^*]+)\*\* — ")

# A bound this module cannot read is a bound it must not translate. `>=3.12`
# means "or later"; `>=3.12,<4` does not, and `~=3.12` does not either.
VERSION = re.compile(r"\d+(?:\.\d+)*")


def _floor_label(tool: str, constraint: str) -> str:
    """Return the README label that a `>=` bound requires."""
    if not constraint.startswith(">="):
        pytest.fail(f"{tool} constraint {constraint!r} is not a `>=` bound, so `or later` is wrong")
    version = constraint[2:].strip()
    if VERSION.fullmatch(version) is None:
        pytest.fail(f"{tool} constraint {constraint!r} holds more than one bound")
    return f"{tool} {version} or later"


def _pinned_label(package_manager: str) -> str:
    """Return the README label that the `packageManager` pin requires.

    The pin carries an optional integrity suffix. `corepack use pnpm@11.23.0`
    does not write `pnpm@11.23.0`; it writes `pnpm@11.23.0+sha512.<hash>`, and
    that is the normal shape of the field, not a corruption of it. The suffix
    pins the download, not the version a contributor installs, so it belongs
    nowhere near the README label and must not fail this gate: a bump made
    with corepack leaves a correct README and a hash the prose never mentions.
    """
    tool, _, pin = package_manager.partition("@")
    version, _, _ = pin.partition("+")
    if VERSION.fullmatch(version) is None:
        pytest.fail(f"packageManager {package_manager!r} names no plain version")
    return f"{tool} {version}"


def _readme_section(heading: str) -> list[str]:
    """Return the lines under a README `##` heading, up to the next one.

    A heading that is absent fails here rather than returning an empty list.
    Each gate below reads one section and compares what it holds against the
    repository, so an empty list compares nothing against nothing and reports
    green for a README that dropped the whole section.
    """
    lines = README_MD.read_text(encoding="utf-8").split("\n")
    if heading not in lines:
        pytest.fail(f"README.md has no `{heading}` heading, so the section it gates is gone")

    body: list[str] = []
    for line in lines[lines.index(heading) + 1 :]:
        if line.startswith("## "):
            break
        body.append(line)
    return body


def _readme_requirement_labels() -> list[str]:
    """Return the bold label of each row of the README Requirements list."""
    return [
        match.group("label")
        for line in _readme_section(REQUIREMENTS_HEADING)
        if (match := REQUIREMENT_LINE.match(line)) is not None
    ]


def test_readme_states_the_toolchain_versions_that_the_manifests_set() -> None:
    """The README must name the Python, Node, and pnpm versions of the manifests.

    The README is the first file a contributor reads, and its Requirements
    list is where it answers which Python and which Node. Those two answers
    live in `pyproject.toml` and `package.json`, so the README states them
    twice over. This test is what keeps the second copy true.

    Order matters here as well as content. The list reads as the install order
    of the two halves, and a row that goes missing has to fail rather than
    leave a shorter list that still matches on the rows it kept.
    """
    pyproject = tomllib.loads(PYPROJECT_TOML.read_text(encoding="utf-8"))
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))

    expected = [
        _floor_label("Python", pyproject["project"]["requires-python"]),
        _floor_label("Node", package["engines"]["node"]),
        _pinned_label(package["packageManager"]),
    ]
    assert _readme_requirement_labels() == expected



WHERE_TO_READ_HEADING = "## Where to read next"

# Each pointer row of that list names its files in backticks. The rows carry
# more than one name, so the gate reads every token of the row rather than the
# first one.
POINTER_ROW = re.compile(r"^- ")
BACKTICKED = re.compile(r"`(?P<name>[^`]+)`")


def test_the_readme_points_at_files_that_the_repository_holds() -> None:
    """Every file the README sends a reader to must exist.

    The list is the entry point of the repository, and a row of it is read
    under pressure: `docs/mcmeta-fallback.md` is the procedure someone opens
    when a release build has already failed. A row that names a file a fresh
    clone does not hold sends that reader looking for nothing, and the README
    says outright that a gate keeps that from happening.

    This gate reads the list rows alone, and it is the only one that can:
    the list is a section that has to be there and has to name something, and
    a gate that scans the whole file reads a deleted list as green. The prose
    of the README also points at files, and
    `test_the_documents_point_at_the_files_that_the_repository_holds` below
    covers those.
    """
    rows = [line for line in _readme_section(WHERE_TO_READ_HEADING) if POINTER_ROW.match(line)]
    assert rows, "the `Where to read next` list is empty, so the README points nowhere"

    named = [match.group("name") for row in rows for match in BACKTICKED.finditer(row)]
    assert named, "no row of the list names a file in backticks"

    missing = [name for name in named if not (REPO_ROOT / name.lstrip("/")).exists()]
    assert missing == []


# The repository map of CLAUDE.md names ten directories, and most of them
# arrive with a later phase, so nothing can gate the whole map yet. `/docs` is
# the one that is different: the `Where to read next` list of the README now
# sends a reader into it.
DOCS_DIR = REPO_ROOT / "docs"

# The map row, as CLAUDE.md writes it: the path, then whitespace, then the
# description. The description has to be there. A bare `/docs` line would match
# a mention in the prose, and the prose discusses that directory often.
REPO_MAP_DOCS_ROW = re.compile(r"^/docs +\S")


def test_the_docs_directory_of_the_repository_map_holds_a_document() -> None:
    """`/docs` must exist and must hold a document.

    The gate above proves that each file the README names is present. It
    cannot prove that `/docs` survives as a directory, because a README that
    drops its `docs/` row passes that gate with the directory deleted, and the
    repository map of CLAUDE.md then points at nothing.

    An empty directory reads the same way to a reader and is easier to reach:
    Git does not track a directory, so `/docs` disappears from a clone the
    moment its last file goes. This test asks for the file, not the directory.
    """
    map_rows = [
        line
        for line in CLAUDE_MD.read_text(encoding="utf-8").split("\n")
        if REPO_MAP_DOCS_ROW.match(line)
    ]
    assert len(map_rows) == 1, "the repository map of CLAUDE.md no longer names `/docs`"

    assert DOCS_DIR.is_dir(), "the repository map names `/docs`, and a fresh clone does not hold it"

    documents = sorted(path.name for path in DOCS_DIR.glob("*.md"))
    assert documents, "`/docs` holds no document, so Git drops the directory from a clone"


# The documents that send a reader to another file of this repository. The
# README does it in its prose as well as in its list -- the `No JDK, no jars`
# section names `docs/mcmeta-fallback.md` -- and the fallback document names
# the module whose failure sends a reader to it.
FALLBACK_DOC = DOCS_DIR / "mcmeta-fallback.md"
GUIDED_DOCUMENTS = (README_MD, FALLBACK_DOC)

# One pointer: a backticked token that ends in `.md` or `.py`. Both extensions
# name a file a reader opens next, and neither shape appears in these documents
# for any other reason. Every other backticked token is a command, a package, a
# symbol, a directory, or a path inside an upstream payload -- `pnpm dev`,
# `DATA_GROUPS`, `/data/dist`, `blocks/data.json` -- and none of those is a
# file of this repository to check.
DOCUMENT_POINTER = re.compile(r"[A-Za-z0-9._/-]+\.(?:md|py)")

# The fence line of a Markdown code block, opening or closing.
#
# The blocks have to come out before anything counts backticks, and the reason
# is not that a fence holds no pointer. It is that a fence holds three
# backticks. `BACKTICKED` pairs them in the order it meets them, so one fence
# shifts every pair after it by one: the text between two inline spans reads as
# a span, and the spans themselves read as the text between. A gate that scans
# a document with code blocks in it therefore stops seeing the names it exists
# to check, and it reports that as green.
CODE_FENCE = re.compile(r"^\s*```")


def _prose_lines(document: Path) -> list[str]:
    """Return the lines of `document` that sit outside a fenced code block."""
    lines: list[str] = []
    inside = False
    for line in _document_text(document).split("\n"):
        if CODE_FENCE.match(line):
            inside = not inside
            continue
        if not inside:
            lines.append(line)
    return lines


def _document_text(document: Path) -> str:
    """Return the text of one document, and fail by name when it is gone.

    Every gate below names its document as a constant, so a renamed or deleted
    document would otherwise end the run with a `FileNotFoundError` and an
    absolute path from a temporary checkout. The rename is the likely edit
    here, and the reader who made it needs the repository-relative name and the
    reason the file is read at all.
    """
    try:
        return document.read_text(encoding="utf-8")
    except FileNotFoundError:
        relative = document.relative_to(REPO_ROOT).as_posix()
        pytest.fail(f"{relative} is gone, and the gates of this module read it by name")


def _pointer_names(document: Path) -> list[str]:
    """Return every file of this repository that `document` names in backticks."""
    return sorted(
        {
            match.group("name")
            for line in _prose_lines(document)
            for match in BACKTICKED.finditer(line)
            if DOCUMENT_POINTER.fullmatch(match.group("name"))
        }
    )


def test_the_documents_point_at_the_files_that_the_repository_holds() -> None:
    """A file that a document names must exist, wherever the name sits.

    The gate on the `Where to read next` list reads that list alone, and the
    pointers of this repository outgrew it in the same commit that wrote the
    fallback document: the `No JDK, no jars` section of the README now names
    `docs/mcmeta-fallback.md` in a paragraph, and the fallback document names
    `pipeline/fetch/mcmeta.py`.

    Rename either target and update only the list row, and every gate stays
    green while the paragraph sends a reader to a file no clone holds. That
    reader is the one this document exists for: a release build has already
    failed, and a dead pointer costs them the wait they were told not to skip.
    """
    named = {document.name: _pointer_names(document) for document in GUIDED_DOCUMENTS}
    # An empty list of pointers compares equal to an empty list of missing
    # files, so a document that stopped naming anything would read as green.
    assert all(named.values()), f"a document names no file of this repository: {named}"

    missing = {
        name: [pointer for pointer in pointers if not (REPO_ROOT / pointer.lstrip("/")).exists()]
        for name, pointers in named.items()
    }
    assert missing == {name: [] for name in named}


def test_the_pointer_scan_reads_a_name_that_follows_a_code_fence(tmp_path: Path) -> None:
    """A code block must not hide the pointers written after it.

    This pins the helper rather than the documents. The fallback document opens
    with a URL block, a curl block, and a tar command, and every pointer it
    holds is written after one of them. A scan that counts the three backticks
    of a fence as inline markup pairs the rest of the file off by one, so the
    prose reads as code and the code reads as prose. It then finds nothing and
    reports no missing file, which is the same green as a document whose
    pointers are all good.
    """
    document = tmp_path / "fenced.md"
    document.write_text(
        "Read `README.md` first.\n\n```sh\ncurl https://example.invalid\n```\n\n"
        "Then read `CLAUDE.md`, and the module in `pipeline/fetch/mcmeta.py`.\n",
        encoding="utf-8",
    )

    assert _pointer_names(document) == ["CLAUDE.md", "README.md", "pipeline/fetch/mcmeta.py"]


# The fallback document repeats two lists that `pipeline.fetch.mcmeta` owns: the
# data groups of Phase 1 and the three files of the `summary` branch. A repeated
# fact rots, the way the README versions would without the gate above, and this
# copy rots in the worst place. It is the shopping list of a hand run: a group
# that mcmeta gains and the document misses is a group the person never packs,
# and the build that follows reports a Minecraft with no advancements rather
# than a document that went stale.
DATA_HALF_HEADING = "### The data half maps path for path"
SUMMARY_HALF_HEADING = "### The summary half needs a reshape"

# `- `recipe``, the whole row and nothing else. The list of groups sits in the
# data-half section, and other sections of the document carry rows that start
# the same way, so the anchors matter as much as the section does.
GROUP_ROW = re.compile(r"^- `(?P<group>[^`]+)`$")

# One row of the payload table: `| `blocks` | `blocks/data.json` |`.
PAYLOAD_ROW = re.compile(r"^\| `(?P<name>[^`]+)` \| `(?P<path>[^`]+)` \|$")


def _fallback_section(heading: str) -> list[str]:
    """Return the lines under one heading of the fallback document.

    A heading that is absent fails here rather than returning an empty list,
    for the reason `_readme_section` gives. The stop rule is every heading
    rather than `## ` alone: both sections read below are `### `, so a `## `
    rule would run one of them into the rest of the document and pick up rows
    that another section owns.
    """
    lines = _document_text(FALLBACK_DOC).split("\n")
    if heading not in lines:
        pytest.fail(f"{FALLBACK_DOC.name} has no `{heading}` heading, so its gate reads nothing")

    body: list[str] = []
    for line in lines[lines.index(heading) + 1 :]:
        if line.startswith("#"):
            break
        body.append(line)
    return body


def test_the_fallback_document_names_the_data_groups_that_the_pipeline_reads() -> None:
    """The document must list `DATA_GROUPS`, in order and in full.

    The hand run packs an archive by hand, and this list is what tells the
    person which directories go in it. A group that the pipeline reads and the
    document does not name is a directory nobody packs, and the read that
    follows returns the other three groups without a word about the fourth.
    """
    listed = [
        match.group("group")
        for line in _fallback_section(DATA_HALF_HEADING)
        if (match := GROUP_ROW.match(line)) is not None
    ]
    assert listed == list(DATA_GROUPS)


def test_the_fallback_document_names_the_summary_payloads_that_the_pipeline_reads() -> None:
    """The document must hold the whole of `SUMMARY_PAYLOADS`, name and path.

    This half is the one the document calls the whole cost of the hatch: the
    person writes the reshape from this table. A row that no longer matches
    sends them to build a file the pipeline does not ask for, or to skip one it
    does, and `fetch_summary_payload` reports the second case as a name that is
    not a summary payload rather than as a document that went stale.
    """
    listed = {
        match.group("name"): match.group("path")
        for line in _fallback_section(SUMMARY_HALF_HEADING)
        if (match := PAYLOAD_ROW.match(line)) is not None
    }
    assert listed == dict(SUMMARY_PAYLOADS)
