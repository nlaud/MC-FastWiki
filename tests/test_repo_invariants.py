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
