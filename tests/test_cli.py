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

    def fake_generate(repo_root, base, head, *, model, intent=None):
        calls["generate"] = dict(
            repo_root=repo_root, base=base, head=head, model=model, intent=intent
        )
        return Saga(
            branch=head,
            base=base,
            commit_sha="abc",
            chapters=[Chapter(id="c1", title="t", summary="s", narration="n")],
        )

    def fake_render(repo_root, saga):
        calls["render"] = dict(repo_root=repo_root, saga=saga)
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


def test_main_resolves_head_from_current_branch(
    git_repo: Path, tmp_path, stub_pipeline
):
    """With the default --head HEAD, the checked-out branch name is resolved."""
    result = runner.invoke(
        app, ["--repo", str(git_repo), "-o", str(tmp_path / "o.html"), "--no-open"]
    )
    assert result.exit_code == 0
    assert stub_pipeline["generate"]["head"] == "feature"


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
