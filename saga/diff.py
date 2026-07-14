"""Diff computation for a saga, from local git refs or a GitHub PR.

``compute_diff`` builds the diff of a head ref against a base ref purely from
git — no checkout, no working-tree changes. ``pr_diff`` fetches the same shape
for a pull request through the ``gh`` CLI. Stdlib + the ``git``/``gh`` CLIs only.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .model import SagaError


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


def default_base(repo_root: Path) -> str:
    """Best guess at the repo's default base ref, preferring the remote's.

    Tries the remote's recorded HEAD (``git symbolic-ref`` on
    ``refs/remotes/origin/HEAD``, e.g. ``origin/main``), then the first of a few
    common candidates that actually resolves, and finally falls back to
    ``"main"``. All local — no network access.
    """
    head = _git(repo_root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if head.returncode == 0 and head.stdout.strip():
        return head.stdout.strip()

    for candidate in ("origin/main", "origin/master", "main", "master"):
        if rev_parse(repo_root, candidate):
            return candidate

    return "main"


def repo_root_from(path: Path) -> Path | None:
    """The git top-level containing *path*, or ``None`` if not in a repo."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        cwd=path,
    )
    return Path(result.stdout.strip()) if result.returncode == 0 else None


# ---------------------------------------------------------------------------
# Pull-request diffs (via the ``gh`` CLI)
# ---------------------------------------------------------------------------

# Metadata gh returns for a PR: the base/head branch names, the head commit, the
# commit list, and the canonical URL.
_PR_VIEW_FIELDS = "baseRefName,headRefName,headRefOid,commits,url"


@dataclass
class PRDiff:
    """A pull request's diff plus the identity a saga needs, fetched from GitHub."""

    diff: DiffResult
    base: str
    head: str
    head_sha: str
    url: str


def _gh(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the ``gh`` CLI (mirrors ``_git``); cwd is the current directory.

    A full PR URL is self-contained, so no repo checkout is needed; a bare PR
    number or branch resolves against the repo the command is run from.
    """
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def pr_diff(pr: str) -> PRDiff:
    """Fetch a pull request's diff and metadata through the ``gh`` CLI.

    *pr* is anything ``gh`` accepts — most usefully a full PR URL, which works
    from any directory. Raises ``SagaError`` if ``gh`` is missing or the PR
    cannot be read (not found, no access, not authenticated).
    """
    try:
        diff_result = _gh("pr", "diff", pr)
        view_result = _gh("pr", "view", pr, "--json", _PR_VIEW_FIELDS)
    except FileNotFoundError as e:
        raise SagaError(
            "gh CLI not found. Install the GitHub CLI and authenticate "
            "(https://cli.github.com), or generate from local refs instead."
        ) from e

    if diff_result.returncode != 0:
        raise SagaError(f"could not fetch PR diff: {diff_result.stderr.strip()}")
    if view_result.returncode != 0:
        raise SagaError(f"could not fetch PR details: {view_result.stderr.strip()}")

    try:
        meta = json.loads(view_result.stdout)
        # Mirror `git log --oneline`: short sha + subject, oldest-first as gh returns.
        commits = [
            f"{c['oid'][:9]} {c['messageHeadline']}" for c in meta.get("commits", [])
        ]
        return PRDiff(
            diff=DiffResult(
                diff_text=diff_result.stdout, commits=commits, diffstat=""
            ),
            base=meta["baseRefName"],
            head=meta["headRefName"],
            head_sha=meta["headRefOid"],
            url=meta["url"],
        )
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise SagaError(f"unexpected gh pr view output: {e}") from e
