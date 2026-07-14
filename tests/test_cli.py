"""Tests for the CLI entry point: argument handling, repo detection, intent
loading, browser opening, and error-to-exit-code mapping. The LLM/render layers
are stubbed — generation itself is covered in test_generate.py. The Typer app is
driven through Typer's CliRunner, which reports the process exit code."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

import saga.cli as cli
from saga.cli import app
from saga.model import Chapter, Saga, SagaError

runner = CliRunner()


@pytest.fixture
def stub_pipeline(monkeypatch):
    """Stub generate() and render() and capture the args they were called with."""
    calls = {}

    def fake_generate(diff, *, base, head, commit_sha, model, intent=None):
        calls["generate"] = dict(
            diff=diff,
            base=base,
            head=head,
            commit_sha=commit_sha,
            model=model,
            intent=intent,
        )
        return Saga(
            branch=head,
            base=base,
            commit_sha=commit_sha or "abc",
            chapters=[Chapter(id="c1", title="t", summary="s", narration="n")],
        )

    def fake_render(saga, diff, file_links=None):
        calls["render"] = dict(saga=saga, diff=diff, file_links=file_links)
        return "<html>saga</html>"

    monkeypatch.setattr(cli, "generate", fake_generate)
    monkeypatch.setattr(cli, "render", fake_render)
    # Never actually open a browser during tests.
    monkeypatch.setattr(cli.webbrowser, "open", lambda *a, **k: True)
    return calls


def test_main_happy_path_writes_output(git_repo: Path, tmp_path: Path, stub_pipeline):
    out = tmp_path / "saga.html"
    result = runner.invoke(
        app,
        [
            "--repo",
            str(git_repo),
            "--base",
            "main",
            "--head",
            "feature",
            "-o",
            str(out),
            "--no-open",
        ],
    )
    assert result.exit_code == 0
    assert out.read_text() == "<html>saga</html>"
    assert stub_pipeline["generate"]["base"] == "main"
    assert stub_pipeline["generate"]["head"] == "feature"
    assert stub_pipeline["generate"]["intent"] is None


def test_main_local_file_links_use_editor_scheme(
    git_repo: Path, tmp_path, stub_pipeline, monkeypatch
):
    """A local saga links each path to the file, opened in the reader's editor."""
    monkeypatch.setenv("EDITOR", "/usr/local/bin/code --wait")
    monkeypatch.delenv("VISUAL", raising=False)
    result = runner.invoke(
        app, ["--repo", str(git_repo), "-o", str(tmp_path / "o.html"), "--no-open"]
    )
    assert result.exit_code == 0
    fl = stub_pipeline["render"]["file_links"]
    assert fl == {"type": "local", "root": str(git_repo), "scheme": "vscode"}


def test_main_unknown_editor_falls_back_to_file_scheme(
    git_repo: Path, tmp_path, stub_pipeline, monkeypatch
):
    """A terminal/unrecognised $EDITOR can't be opened from a browser, so file://."""
    monkeypatch.setenv("EDITOR", "vim")
    monkeypatch.delenv("VISUAL", raising=False)
    result = runner.invoke(
        app, ["--repo", str(git_repo), "-o", str(tmp_path / "o.html"), "--no-open"]
    )
    assert result.exit_code == 0
    assert stub_pipeline["render"]["file_links"]["scheme"] == "file"


def test_main_resolves_head_from_current_branch(
    git_repo: Path, tmp_path, stub_pipeline
):
    """With the default --head HEAD, the checked-out branch name is resolved."""
    result = runner.invoke(
        app, ["--repo", str(git_repo), "-o", str(tmp_path / "o.html"), "--no-open"]
    )
    assert result.exit_code == 0
    assert stub_pipeline["generate"]["head"] == "feature"


def test_main_auto_detects_base_when_omitted(git_repo: Path, tmp_path, stub_pipeline):
    """With no --base, the base is detected (local main here) rather than assumed."""
    result = runner.invoke(
        app, ["--repo", str(git_repo), "-o", str(tmp_path / "o.html"), "--no-open"]
    )
    assert result.exit_code == 0
    assert stub_pipeline["generate"]["base"] == "main"


def test_main_reads_intent_file(git_repo: Path, tmp_path, stub_pipeline):
    intent = tmp_path / "intent.md"
    intent.write_text("Do the thing.")
    result = runner.invoke(
        app,
        [
            "--repo",
            str(git_repo),
            "--intent",
            str(intent),
            "-o",
            str(tmp_path / "o.html"),
            "--no-open",
        ],
    )
    assert result.exit_code == 0
    assert stub_pipeline["generate"]["intent"] == "Do the thing."


def test_main_missing_intent_file_errors(git_repo: Path, tmp_path, stub_pipeline):
    result = runner.invoke(
        app,
        [
            "--repo",
            str(git_repo),
            "--intent",
            str(tmp_path / "nope.md"),
            "-o",
            str(tmp_path / "o.html"),
            "--no-open",
        ],
    )
    assert result.exit_code == 1
    assert "could not read intent file" in result.output


def test_main_not_a_git_repo_errors(tmp_path: Path, stub_pipeline):
    outside = tmp_path / "plain"
    outside.mkdir()
    result = runner.invoke(
        app, ["--repo", str(outside), "-o", str(tmp_path / "o.html"), "--no-open"]
    )
    assert result.exit_code == 1
    assert "not inside a git repository" in result.output


def test_main_saga_error_maps_to_exit_1(git_repo: Path, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise SagaError("no reviewable hunks")

    monkeypatch.setattr(cli, "generate", boom)
    result = runner.invoke(
        app, ["--repo", str(git_repo), "-o", str(tmp_path / "o.html"), "--no-open"]
    )
    assert result.exit_code == 1
    assert "no reviewable hunks" in result.output


def test_main_opens_browser_by_default(
    git_repo: Path, tmp_path, stub_pipeline, monkeypatch
):
    opened = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda uri: opened.append(uri))
    out = tmp_path / "o.html"
    result = runner.invoke(app, ["--repo", str(git_repo), "-o", str(out)])
    assert result.exit_code == 0
    assert opened and opened[0].startswith("file://")


def test_version_flag_prints_version_and_exits():
    """--version reports the installed version and exits before any generation."""
    from importlib.metadata import version as package_version

    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"saga {package_version('saga-cli')}"


def test_main_pr_url_uses_pr_metadata(tmp_path, stub_pipeline, monkeypatch):
    """A PR URL routes through gh (stubbed) and its base/head/sha drive the saga —
    no local repo is consulted."""
    from saga.diff import DiffResult, PRDiff

    pr = PRDiff(
        diff=DiffResult(diff_text="d", commits=["c"], diffstat=""),
        base="release",
        head="fix-branch",
        head_sha="f" * 40,
        url="https://github.com/o/r/pull/9",
    )
    captured = {}

    def fake_pr_diff(target):
        captured["target"] = target
        return pr

    monkeypatch.setattr(cli, "pr_diff", fake_pr_diff)

    out = tmp_path / "o.html"
    # Options after the positional URL must parse (`saga <url> --model …`).
    result = runner.invoke(
        app,
        [
            "https://github.com/o/r/pull/9",
            "--model",
            "openai/gpt-4o",
            "-o",
            str(out),
            "--no-open",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["target"] == "https://github.com/o/r/pull/9"
    g = stub_pipeline["generate"]
    assert g["base"] == "release"
    assert g["head"] == "fix-branch"
    assert g["commit_sha"] == "f" * 40
    assert g["model"] == "openai/gpt-4o"
    assert out.read_text() == "<html>saga</html>"
    # No local checkout, so file paths link to the file on GitHub at the head sha.
    assert stub_pipeline["render"]["file_links"] == {
        "type": "github",
        "base": "https://github.com/o/r/blob/" + "f" * 40,
    }


def test_main_pr_error_maps_to_exit_1(tmp_path, monkeypatch):
    def boom(target):
        raise SagaError("gh CLI not found")

    monkeypatch.setattr(cli, "pr_diff", boom)
    result = runner.invoke(
        app,
        ["https://github.com/o/r/pull/9", "-o", str(tmp_path / "o.html"), "--no-open"],
    )
    assert result.exit_code == 1
    assert "gh CLI not found" in result.output


def test_main_model_flag_is_passed_through(git_repo: Path, tmp_path, stub_pipeline):
    runner.invoke(
        app,
        [
            "--repo",
            str(git_repo),
            "--model",
            "openai/gpt-4o",
            "-o",
            str(tmp_path / "o.html"),
            "--no-open",
        ],
    )
    assert stub_pipeline["generate"]["model"] == "openai/gpt-4o"
