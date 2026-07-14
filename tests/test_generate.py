"""Tests for saga generation.

The one real LLM HTTP call is recorded to a VCR cassette (auth headers scrubbed)
and replayed offline. Everything around it — prompt assembly, client selection,
schema→dataclass mapping, and the empty-diff guard — is tested without network.

Re-record with a real key via:  SAGA_RECORD=1 ANTHROPIC_API_KEY=... pytest
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

import saga.generate as gen
from saga.generate import (
    _MAX_ATTEMPTS,
    _MAX_CHAPTERS,
    _build_client,
    _build_message,
    _ChapterOut,
    _generate_via_claude_cli,
    _SagaOut,
    _to_chapter,
    generate,
    labeled_diff,
)
from saga.model import SagaError, parse_hunks

# ---------------------------------------------------------------------------
# Prompt assembly (pure)
# ---------------------------------------------------------------------------

TWO_FILE_DIFF = (
    "diff --git a/foo.py b/foo.py\n"
    "--- a/foo.py\n+++ b/foo.py\n"
    "@@ -1,2 +1,2 @@\n a\n-b\n+B\n"
)


def test_labeled_diff_heads_each_hunk_with_id():
    hunks = parse_hunks(TWO_FILE_DIFF)
    out = labeled_diff(hunks)
    assert "### HUNK h0 — foo.py" in out
    assert "@@ -1,2 +1,2 @@" in out


def test_build_message_includes_intent_commits_and_diff():
    from saga.diff import DiffResult

    diff = DiffResult(diff_text=TWO_FILE_DIFF, commits=["abc fix bug"], diffstat="")
    hunks = parse_hunks(TWO_FILE_DIFF)
    msg = _build_message(diff, hunks, intent="Fix the bug.")
    assert "# Intent" in msg
    assert "Fix the bug." in msg
    assert "abc fix bug" in msg
    assert "### HUNK h0" in msg


def test_build_message_omits_intent_block_when_absent():
    from saga.diff import DiffResult

    diff = DiffResult(diff_text=TWO_FILE_DIFF, commits=[], diffstat="")
    hunks = parse_hunks(TWO_FILE_DIFF)
    msg = _build_message(diff, hunks, intent=None)
    assert "# Intent" not in msg
    assert "(no commit messages)" in msg


def test_to_chapter_maps_schema_to_dataclass():
    out = _ChapterOut(
        id="c1",
        title="T",
        summary="S",
        narration="N",
        hunks=["h0"],
        confidence="high",
        deviation="",
        qa="Visually check the panel on mobile.",
    )
    ch = _to_chapter(out)
    assert ch.id == "c1"
    assert ch.confidence == "high"
    # Empty-string deviation normalizes to None.
    assert ch.deviation is None
    assert ch.qa == "Visually check the panel on mobile."


# ---------------------------------------------------------------------------
# Client selection / error handling (no network)
# ---------------------------------------------------------------------------


def test_build_client_openrouter_without_key_raises(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(SagaError, match="OPENROUTER_API_KEY"):
        _build_client("openrouter/anthropic/claude-3.5-sonnet")


def test_build_client_unknown_provider_raises_sagaerror(monkeypatch):
    with pytest.raises(SagaError, match="Could not initialize model"):
        _build_client("bogusprovider/some-model")


def _capture_from_provider(monkeypatch) -> dict:
    """Patch instructor.from_provider to record its args instead of building a
    real client, so local-provider wiring can be checked without a server."""
    import saga.generate as gen

    captured: dict = {}

    def fake(model, **kwargs):
        captured["model"] = model
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(gen.instructor, "from_provider", fake)
    return captured


def test_build_client_local_defaults_to_ollama(monkeypatch):
    import saga.generate as gen

    monkeypatch.delenv("SAGA_LOCAL_BASE_URL", raising=False)
    captured = _capture_from_provider(monkeypatch)
    _build_client("local/qwen2.5-coder:14b")
    # local/ is dispatched through the OpenAI SDK at Ollama's endpoint, key unused.
    assert captured["model"] == "openai/qwen2.5-coder:14b"
    assert captured["base_url"] == "http://localhost:11434/v1"
    assert captured["api_key"]
    assert captured["mode"] == gen.instructor.Mode.JSON


def test_build_client_local_honors_base_url_override(monkeypatch):
    # Point local/ at LM Studio (or any OpenAI-compatible server) via the env var.
    monkeypatch.setenv("SAGA_LOCAL_BASE_URL", "http://localhost:1234/v1")
    captured = _capture_from_provider(monkeypatch)
    _build_client("local/lmstudio-community/Qwen2.5-Coder-GGUF")
    assert captured["base_url"] == "http://localhost:1234/v1"
    # A slash-bearing model id keeps its slashes after the local/ prefix is stripped.
    assert captured["model"] == "openai/lmstudio-community/Qwen2.5-Coder-GGUF"


def test_generate_empty_diff_raises_before_any_network(empty_diff_repo: Path):
    with pytest.raises(SagaError, match="No reviewable hunks"):
        generate(empty_diff_repo, "main", "feature", model="anthropic/claude-opus-4-8")


# ---------------------------------------------------------------------------
# Full generation, replayed from a scrubbed cassette
# ---------------------------------------------------------------------------


def test_generate_full_saga_from_cassette(git_repo: Path, vcr_cassette, monkeypatch):
    # Replay needs a syntactically-valid key for client construction; the real
    # HTTP is served by the cassette. Don't clobber a real key while recording.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy")

    with vcr_cassette.use_cassette("generate_anthropic.yaml"):
        saga = generate(git_repo, "main", "feature", model="anthropic/claude-opus-4-8")

    assert saga.base == "main"
    assert saga.branch == "feature"
    assert saga.commit_sha and len(saga.commit_sha) == 40
    assert len(saga.chapters) >= 1
    # generate() re-validates coverage internally, so reaching here means every
    # hunk in the live diff was assigned. Confirm the chapters carry content.
    assert all(c.id for c in saga.chapters)
    assert any(c.hunks for c in saga.chapters)


def test_generate_wraps_provider_errors_as_sagaerror(git_repo: Path, monkeypatch):
    """A failure from the LLM client is surfaced as a SagaError, not a raw
    provider exception."""
    import saga.generate as gen

    class BoomClient:
        def create(self, **kwargs):
            raise RuntimeError("upstream 529 overloaded")

    monkeypatch.setattr(gen, "_build_client", lambda model: BoomClient())
    with pytest.raises(SagaError, match="Saga generation failed"):
        generate(git_repo, "main", "feature", model="anthropic/claude-opus-4-8")


def test_cassette_is_scrubbed():
    """Committed cassette must not carry a real API key."""
    cassette = Path(__file__).parent / "cassettes" / "generate_anthropic.yaml"
    if not cassette.exists():
        pytest.skip("cassette not recorded yet")
    text = cassette.read_text()
    assert "sk-ant-" not in text
    assert "REDACTED" in text


# ---------------------------------------------------------------------------
# claude-cli provider (subprocess out to `claude -p`), no network / no binary
# ---------------------------------------------------------------------------

_ENVELOPE_CHAPTERS = {
    "chapters": [
        {"id": "c1", "title": "T", "summary": "S", "narration": "N", "hunks": ["h0"]}
    ]
}


def _envelope(**fields) -> str:
    """Serialize a `claude -p --output-format json` envelope for stubbed stdout."""
    return json.dumps(fields)


def _fake_claude(monkeypatch, *, stdout: str, returncode: int = 0) -> dict:
    """Patch subprocess.run to skip the real binary and record how it was called."""
    import saga.generate as gen

    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(gen.subprocess, "run", fake_run)
    return captured


def test_claude_cli_parses_structured_output(monkeypatch):
    stdout = _envelope(is_error=False, structured_output=_ENVELOPE_CHAPTERS)
    _fake_claude(monkeypatch, stdout=stdout)
    result = _generate_via_claude_cli("claude-cli", "sys prompt", "the diff")
    assert result.chapters[0].id == "c1"
    assert result.chapters[0].hunks == ["h0"]


def test_claude_cli_command_pins_model_and_scrubs_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-be-dropped")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-should-be-dropped")
    captured = _fake_claude(
        monkeypatch, stdout=_envelope(structured_output=_ENVELOPE_CHAPTERS)
    )

    _generate_via_claude_cli("claude-cli/sonnet", "sys prompt", "the diff")

    cmd = captured["cmd"]
    assert cmd[:2] == ["claude", "-p"]
    assert "--json-schema" in cmd
    # claude-cli/<alias> pins the model; bare claude-cli would omit --model.
    assert cmd[cmd.index("--model") + 1] == "sonnet"
    # The diff is piped on stdin, not passed as an argument.
    assert captured["kwargs"]["input"] == "the diff"
    # API-key env vars are dropped so the subprocess uses the Claude Code login.
    env = captured["kwargs"]["env"]
    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env


def test_claude_cli_bare_model_omits_model_flag(monkeypatch):
    captured = _fake_claude(
        monkeypatch, stdout=_envelope(structured_output=_ENVELOPE_CHAPTERS)
    )
    _generate_via_claude_cli("claude-cli", "sys prompt", "the diff")
    assert "--model" not in captured["cmd"]


def test_claude_cli_tolerates_leading_warning_line(monkeypatch):
    # Claude Code prints a stray warning before the JSON envelope on some setups.
    stdout = "⚠ connectors disabled\n" + _envelope(structured_output=_ENVELOPE_CHAPTERS)
    _fake_claude(monkeypatch, stdout=stdout)
    result = _generate_via_claude_cli("claude-cli", "sys prompt", "the diff")
    assert result.chapters[0].id == "c1"


def test_claude_cli_missing_binary_raises_sagaerror(monkeypatch):
    import saga.generate as gen

    def boom(cmd, **kwargs):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(gen.subprocess, "run", boom)
    with pytest.raises(SagaError, match="claude CLI not found"):
        _generate_via_claude_cli("claude-cli", "sys prompt", "the diff")


def test_claude_cli_nonzero_exit_raises_sagaerror(monkeypatch):
    _fake_claude(monkeypatch, stdout="", returncode=1)
    with pytest.raises(SagaError, match="claude CLI failed"):
        _generate_via_claude_cli("claude-cli", "sys prompt", "the diff")


def test_claude_cli_missing_structured_output_raises_sagaerror(monkeypatch):
    _fake_claude(monkeypatch, stdout=_envelope(is_error=False, result="text only"))
    with pytest.raises(SagaError, match="no structured_output"):
        _generate_via_claude_cli("claude-cli", "sys prompt", "the diff")


# ---------------------------------------------------------------------------
# Chapter-count ceiling: reject over-limit sagas and retry to consolidate
# ---------------------------------------------------------------------------


def _n_chapters(n: int) -> dict:
    return {
        "chapters": [
            {
                "id": f"c{i}",
                "title": "T",
                "summary": "S",
                "narration": "N",
                "hunks": ["h0"],
            }
            for i in range(n)
        ]
    }


def test_saga_out_rejects_more_than_max_chapters():
    # At the ceiling is fine; one over is rejected.
    _SagaOut.model_validate(_n_chapters(_MAX_CHAPTERS))
    with pytest.raises(ValidationError, match="at most"):
        _SagaOut.model_validate(_n_chapters(_MAX_CHAPTERS + 1))


def test_claude_cli_retries_and_consolidates_when_over_limit(monkeypatch):
    calls: list[str] = []

    def fake_run(cmd, **kwargs):
        calls.append(kwargs["input"])
        n = _MAX_CHAPTERS + 1 if len(calls) == 1 else 1  # over limit, then fixed
        stdout = _envelope(structured_output=_n_chapters(n))
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(gen.subprocess, "run", fake_run)
    result = _generate_via_claude_cli("claude-cli", "sys prompt", "the diff")
    assert len(result.chapters) == 1
    assert len(calls) == 2
    # The retry feeds the rejection reason back so the model can correct.
    assert "Previous attempt was rejected" in calls[1]


def test_claude_cli_gives_up_after_max_attempts_over_limit(monkeypatch):
    attempts = 0

    def fake_run(cmd, **kwargs):
        nonlocal attempts
        attempts += 1
        stdout = _envelope(structured_output=_n_chapters(_MAX_CHAPTERS + 1))
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(gen.subprocess, "run", fake_run)
    with pytest.raises(SagaError, match="did not match the saga schema"):
        _generate_via_claude_cli("claude-cli", "sys prompt", "the diff")
    assert attempts == _MAX_ATTEMPTS


def test_generate_dispatches_to_claude_cli(git_repo: Path, monkeypatch):
    """A claude-cli model routes through the subprocess path, not instructor."""
    import saga.generate as gen

    called: dict = {}

    def fake_cli(model, system_prompt, user_message):
        called["model"] = model
        return _SagaOut.model_validate(_ENVELOPE_CHAPTERS)

    def no_client(model):
        pytest.fail("should not build an instructor client")

    monkeypatch.setattr(gen, "_generate_via_claude_cli", fake_cli)
    monkeypatch.setattr(gen, "_build_client", no_client)
    # Coverage against git_repo's real hunks isn't the point of this test — the
    # stub chapters don't span them — so neutralize the check here.
    monkeypatch.setattr(gen, "validate_coverage", lambda chapters, hunks: None)
    saga = generate(git_repo, "main", "feature", model="claude-cli/sonnet")
    assert called["model"] == "claude-cli/sonnet"
    assert len(saga.chapters) >= 1
