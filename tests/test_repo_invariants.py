"""Repository invariants that CLAUDE.md and AGENTS.md name but no tool checks.

Both fail silently. A mirror that drifts still renders, and a working tree
checked out with CRLF still runs; the damage shows up later as a review diff
nobody wrote or as a format gate that reports every file in the repository.
pytest is the only gate that reads the whole tree, so they live here next to
the version check.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

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


# `/data` does not exist yet. Phase 1 of TODO.md creates it. `git check-ignore`
# reads path names only, so it answers for a path that has no file behind it.
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

# These four must not read as generated. `data/curated` holds the hand-written
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
