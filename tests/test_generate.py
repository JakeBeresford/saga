"""Tests for saga generation.

The one real LLM HTTP call is recorded to a VCR cassette (auth headers scrubbed)
and replayed offline. Everything around it — prompt assembly, client selection,
schema→dataclass mapping, and the empty-diff guard — is tested without network.

Re-record with a real key via:  SAGA_RECORD=1 ANTHROPIC_API_KEY=... pytest
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from saga.generate import (
    _build_client,
    _build_message,
    _ChapterOut,
    _QAOut,
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
        qa=_QAOut(status="green", note="ok"),
    )
    ch = _to_chapter(out)
    assert ch.id == "c1"
    assert ch.confidence == "high"
    # Empty-string deviation normalizes to None.
    assert ch.deviation is None
    assert ch.qa == {"status": "green", "note": "ok"}


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
