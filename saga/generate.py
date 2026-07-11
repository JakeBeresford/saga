"""Generate a saga for one change set via a single structured LLM call.

The call takes the full diff (every hunk labeled by a stable id), the commit
messages, and an optional intent document, and returns strict, schema-validated
JSON. Coverage is re-validated in code before trusting it — nothing the model
returns is assumed complete.

Provider-agnostic: the model is chosen by a ``provider/model`` string (e.g.
``anthropic/claude-opus-4-8``, ``openai/gpt-4o``,
``openrouter/anthropic/claude-3.5-sonnet``) and dispatched through ``instructor``.
The API key is read from the provider's standard environment variable
(``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY`` / ``OPENROUTER_API_KEY``).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Optional

import instructor
from pydantic import BaseModel, Field

from .diff import DiffResult, compute_diff, rev_parse
from .model import (
    Chapter,
    Hunk,
    Saga,
    SagaError,
    parse_hunks,
    validate_coverage,
)

_MAX_TOKENS = 16000
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "saga.md"


# ---------------------------------------------------------------------------
# LLM response schema — what the model must return (validated by instructor).
# Mapped onto the persisted ``Chapter`` dataclass below so model.py's core,
# validate_coverage, and render.py stay untouched.
# ---------------------------------------------------------------------------


class _QAOut(BaseModel):
    status: str
    note: str = ""


class _ChapterOut(BaseModel):
    id: str
    title: str
    summary: str
    narration: str
    hunks: list[str] = Field(default_factory=list)
    plan_step: Optional[str] = None
    confidence: Literal["high", "medium", "low"] = "medium"
    deviation: Optional[str] = None
    qa: Optional[_QAOut] = None


class _SagaOut(BaseModel):
    chapters: list[_ChapterOut]


def _to_chapter(c: _ChapterOut) -> Chapter:
    return Chapter(
        id=c.id,
        title=c.title,
        summary=c.summary,
        narration=c.narration,
        hunks=list(c.hunks),
        plan_step=c.plan_step,
        confidence=c.confidence,
        deviation=c.deviation or None,
        qa=c.qa.model_dump() if c.qa else None,
    )


def labeled_diff(hunks: list[Hunk]) -> str:
    """Render the diff for the prompt with each hunk headed by its stable id."""
    out: list[str] = []
    for h in hunks:
        first = h.body.splitlines()[0] if h.body else ""
        out.append(f"### HUNK {h.id} — {h.file_path}  ({first.strip()})")
        out.append(h.body.rstrip("\n"))
    return "\n".join(out)


def _build_message(diff: DiffResult, hunks: list[Hunk], intent: str | None) -> str:
    """Assemble the user message: intent (optional), commits, and labeled diff."""
    commits = "\n".join(diff.commits) or "(no commit messages)"
    intent_block = (
        ["# Intent (what this change set out to do)", intent.strip(), ""]
        if intent and intent.strip()
        else []
    )
    return "\n".join(
        [
            *intent_block,
            "# Commits",
            commits,
            "",
            "# Full diff (every hunk must be assigned to a chapter)",
            labeled_diff(hunks),
        ]
    )


def _build_client(model: str) -> instructor.Instructor:
    """Build an instructor client for a ``provider/model`` string.

    OpenRouter is OpenAI-compatible, so it needs an explicit base URL and its own
    key; Anthropic and OpenAI resolve their keys from the SDK's standard env vars.
    """
    provider = model.split("/", 1)[0]
    try:
        if provider == "openrouter":
            key = os.environ.get("OPENROUTER_API_KEY")
            if not key:
                raise SagaError("OPENROUTER_API_KEY is not set.")
            return instructor.from_provider(
                model, base_url=_OPENROUTER_BASE_URL, api_key=key
            )
        return instructor.from_provider(model)
    except SagaError:
        raise
    except Exception as e:
        raise SagaError(f"Could not initialize model {model!r}: {e}")


def generate(
    repo_root: Path,
    base: str,
    head: str,
    *,
    model: str,
    intent: str | None = None,
) -> Saga:
    """Generate the saga for *base*...*head*.

    Raises ``SagaError`` on an empty diff, a provider/model error, or a
    coverage gap. The caller renders the error as a user-facing message.
    """
    diff = compute_diff(repo_root, base, head)
    hunks = parse_hunks(diff.diff_text)
    if not hunks:
        raise SagaError("No reviewable hunks in this change set.")

    client = _build_client(model)
    system_prompt = _PROMPT_PATH.read_text()
    kwargs: dict = {}
    if model.split("/", 1)[0] == "openrouter":
        # Ask OpenRouter to route only to providers that support the params we
        # send (structured output), so schema enforcement is honored.
        kwargs["extra_body"] = {"provider": {"require_parameters": True}}

    try:
        result: _SagaOut = client.create(
            response_model=_SagaOut,
            max_tokens=_MAX_TOKENS,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": _build_message(diff, hunks, intent)},
            ],
            **kwargs,
        )
    except SagaError:
        raise
    except Exception as e:
        raise SagaError(f"Saga generation failed: {e}")

    chapters = [_to_chapter(c) for c in result.chapters]
    validate_coverage(chapters, hunks)

    return Saga(
        branch=head,
        base=base,
        commit_sha=rev_parse(repo_root, head),
        chapters=chapters,
    )
