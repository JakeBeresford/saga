"""Tests for git-sourced diff computation, run against real temp repos."""

from pathlib import Path

from saga.diff import (
    compute_diff,
    current_branch,
    default_base,
    repo_root_from,
    rev_parse,
)


def test_compute_diff_captures_changes_commits_and_stat(git_repo: Path):
    result = compute_diff(git_repo, "main", "feature")

    # The edit and the new file both appear in the diff text.
    assert "diff --git a/foo.py b/foo.py" in result.diff_text
    assert "+B" in result.diff_text
    assert "diff --git a/new.txt b/new.txt" in result.diff_text
    assert "+hello" in result.diff_text

    # One commit separates feature from main.
    assert len(result.commits) == 1
    assert "edit foo and add new.txt" in result.commits[0]

    # The diffstat mentions both files.
    assert "foo.py" in result.diffstat
    assert "new.txt" in result.diffstat


def test_compute_diff_empty_when_no_changes(empty_diff_repo: Path):
    result = compute_diff(empty_diff_repo, "main", "feature")
    assert result.diff_text == ""
    assert result.commits == []


def test_compute_diff_uses_symmetric_difference(git_repo: Path, git_env, tmp_path):
    """base...ref must not include commits made on base after the branch point.

    A commit added to ``main`` after ``feature`` diverged should not leak into
    the feature diff (that's the ``...`` symmetric-difference guarantee).
    """
    import subprocess

    def git(*args):
        subprocess.run(["git", *args], cwd=git_repo, check=True, env=git_env)

    git("checkout", "-q", "main")
    (git_repo / "on_main_only.txt").write_text("later\n")
    git("add", "-A")
    git("commit", "-q", "-m", "main-only")

    result = compute_diff(git_repo, "main", "feature")
    assert "on_main_only.txt" not in result.diff_text


def test_compute_diff_raises_on_bad_ref(git_repo: Path):
    import pytest

    with pytest.raises(RuntimeError, match="git diff failed"):
        compute_diff(git_repo, "main", "does-not-exist")


def test_rev_parse_resolves_and_reports_missing(git_repo: Path):
    sha = rev_parse(git_repo, "feature")
    assert len(sha) == 40
    assert rev_parse(git_repo, "no-such-ref") == ""


def test_current_branch(git_repo: Path):
    assert current_branch(git_repo) == "feature"


def test_current_branch_detached_head(git_repo: Path, git_env):
    import subprocess

    sha = rev_parse(git_repo, "feature")
    subprocess.run(
        ["git", "checkout", "-q", sha], cwd=git_repo, check=True, env=git_env
    )
    assert current_branch(git_repo) == "HEAD"


def test_repo_root_from_inside_repo(git_repo: Path):
    sub = git_repo / "sub"
    sub.mkdir()
    root = repo_root_from(sub)
    assert root is not None
    assert root.resolve() == git_repo.resolve()


def test_repo_root_from_outside_repo(tmp_path: Path):
    outside = tmp_path / "not_a_repo"
    outside.mkdir()
    assert repo_root_from(outside) is None


def test_default_base_falls_back_to_local_main(git_repo: Path):
    """No remote configured: detection falls through to the local ``main``."""
    assert default_base(git_repo) == "main"


def test_default_base_detects_local_master(tmp_path: Path, git_env):
    """A repo whose only default-ish branch is ``master`` resolves to it."""
    import subprocess

    repo = tmp_path / "old_repo"
    repo.mkdir()

    def git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, env=git_env)

    git("init", "-q", "-b", "master")
    (repo / "a.txt").write_text("x\n")
    git("add", "-A")
    git("commit", "-q", "-m", "first")
    assert default_base(repo) == "master"


def test_default_base_prefers_remote_head(tmp_path: Path, git_env):
    """When ``origin/HEAD`` is set, it wins and keeps the ``origin/`` prefix."""
    import subprocess

    upstream = tmp_path / "upstream.git"
    upstream.mkdir()

    def git(cwd, *args):
        subprocess.run(["git", *args], cwd=cwd, check=True, env=git_env)

    git(upstream, "init", "-q", "--bare", "-b", "main")

    clone = tmp_path / "clone"
    clone.mkdir()
    git(clone, "init", "-q", "-b", "main")
    (clone / "a.txt").write_text("x\n")
    git(clone, "add", "-A")
    git(clone, "commit", "-q", "-m", "first")
    git(clone, "remote", "add", "origin", str(upstream))
    git(clone, "push", "-q", "origin", "main")
    git(clone, "remote", "set-head", "origin", "main")

    assert default_base(clone) == "origin/main"
