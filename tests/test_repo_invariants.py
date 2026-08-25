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
