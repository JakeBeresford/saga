"""Git-sourced diff computation for a saga.

Computes the diff of a head ref against a base ref purely from git — no
checkout, no working-tree changes. Stdlib + the ``git`` CLI only.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DiffResult:
    """The computed diff of a ref against a base: text, commit list, diffstat."""

    diff_text: str
    commits: list[str]
    diffstat: str


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )


def compute_diff(repo_root: Path, base: str, ref: str) -> DiffResult:
    """Compute the diff of *ref* against *base* purely from refs (no checkout).

    ``git diff base...ref`` is a symmetric-difference diff, so it never touches
    the working tree and works for any local ref, not just the checked-out
    branch.
    """
    diff_result = _git(repo_root, "diff", f"{base}...{ref}")
    if diff_result.returncode != 0:
        raise RuntimeError(f"git diff failed: {diff_result.stderr.strip()}")

    log_result = _git(repo_root, "log", "--oneline", f"{base}..{ref}")
    commits = (
        log_result.stdout.strip().splitlines() if log_result.returncode == 0 else []
    )

    stat_result = _git(repo_root, "diff", "--stat", f"{base}...{ref}")
    diffstat = stat_result.stdout.strip() if stat_result.returncode == 0 else ""

    return DiffResult(
        diff_text=diff_result.stdout,
        commits=commits,
        diffstat=diffstat,
    )


def rev_parse(repo_root: Path, ref: str) -> str:
    """Return the full SHA *ref* resolves to, or ``""`` if it does not resolve."""
    result = _git(repo_root, "rev-parse", ref)
    return result.stdout.strip() if result.returncode == 0 else ""


def current_branch(repo_root: Path) -> str:
    """The checked-out branch name, or ``"HEAD"`` when detached."""
    result = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    name = result.stdout.strip() if result.returncode == 0 else ""
    return name or "HEAD"


def repo_root_from(path: Path) -> Path | None:
    """The git top-level containing *path*, or ``None`` if not in a repo."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        cwd=path,
    )
    return Path(result.stdout.strip()) if result.returncode == 0 else None
