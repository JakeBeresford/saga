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

The ``local/`` prefix targets any OpenAI-compatible local server — Ollama or
LM Studio — with no API key. It defaults to Ollama's endpoint; point it at a
different server (e.g. LM Studio on port 1234) with ``$SAGA_LOCAL_BASE_URL``.

The ``claude-cli`` provider shells out to a local Claude Code CLI (``claude -p``)
instead of the Anthropic SDK, so it uses whatever the user's Claude Code is
logged in with — including a Claude Pro/Max subscription, with no API key. The
saga schema is enforced via ``claude``'s ``--json-schema`` flag.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import instructor
from pydantic import BaseModel, Field, ValidationError, model_validator

from .diff import DiffResult
from .model import (
    Chapter,
    Hunk,
    Saga,
    SagaError,
    parse_hunks,
    validate_coverage,
)

_MAX_TOKENS = 16000
# Hard ceiling on chapters — more than this means the diff was chunked too small.
# Enforced as a schema validator so the model is asked to consolidate and retry
# rather than the whole saga being thrown away.
_MAX_CHAPTERS = 10
# Total attempts (initial + retries) to coax a within-limit saga out of a model.
_MAX_ATTEMPTS = 3
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Ollama's OpenAI-compatible endpoint; override with $SAGA_LOCAL_BASE_URL (e.g.
# http://localhost:1234/v1 for LM Studio).
_LOCAL_DEFAULT_BASE_URL = "http://localhost:11434/v1"
# Claude Code boot + generation for a full saga can take a while; be generous.
_CLAUDE_CLI_TIMEOUT = 300
_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "saga.md"


# ---------------------------------------------------------------------------
# LLM response schema — what the model must return (validated by instructor).
# Mapped onto the persisted ``Chapter`` dataclass below so model.py's core,
# validate_coverage, and render.py stay untouched.
# ---------------------------------------------------------------------------


class _ChapterOut(BaseModel):
    id: str
    title: str
    summary: str
    narration: str
    hunks: list[str] = Field(default_factory=list)
    plan_step: str | None = None
    confidence: Literal["high", "medium", "low"] = "medium"
    deviation: str | None = None
    qa: str | None = None


def _chapter_limit_message(n: int) -> str:
    return (
        f"Returned {n} chapters, but a walkthrough may have at most {_MAX_CHAPTERS}. "
        "Consolidate: merge finely-split chapters into fewer, broader ones, and fold "
        "each test/spec hunk into the chapter that adds the functionality it covers "
        "instead of giving tests their own chapters."
    )


class _SagaOut(BaseModel):
    # Saga-level headline + one-line summary for the page header. Defaulted so an
    # older model (or replayed cassette) that omits them still validates.
    title: str = ""
    summary: str = ""
    chapters: list[_ChapterOut]

    @model_validator(mode="after")
    def _enforce_chapter_limit(self) -> _SagaOut:
        if len(self.chapters) > _MAX_CHAPTERS:
            raise ValueError(_chapter_limit_message(len(self.chapters)))
        return self


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
        qa=c.qa or None,
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
    ``local`` targets an OpenAI-compatible local server (Ollama/LM Studio) via the
    OpenAI SDK — no key, and forced JSON mode since local models' tool-calling is
    unreliable and saga depends on schema-valid output.
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
        if provider == "local":
            model_name = model.split("/", 1)[1]
            base_url = os.environ.get("SAGA_LOCAL_BASE_URL", _LOCAL_DEFAULT_BASE_URL)
            return instructor.from_provider(
                f"openai/{model_name}",
                base_url=base_url,
                api_key="local",  # unused by the local server, but must be non-empty
                mode=instructor.Mode.JSON,
            )
        return instructor.from_provider(model)
    except SagaError:
        raise
    except Exception as e:
        raise SagaError(f"Could not initialize model {model!r}: {e}") from e


def _generate_via_claude_cli(
    model: str, system_prompt: str, user_message: str
) -> _SagaOut:
    """Generate a saga through a local Claude Code CLI (``claude -p``).

    Unlike the ``anthropic/`` provider (which needs ``ANTHROPIC_API_KEY``), this
    runs the ``claude`` binary and reuses its stored login, so a user with only a
    Claude Pro/Max subscription can generate sagas. Output is constrained to the
    saga schema with ``--json-schema`` and read back from the JSON envelope's
    ``structured_output`` field. ``model`` is ``claude-cli`` (Claude Code's
    default model) or ``claude-cli/<alias>`` (e.g. ``claude-cli/sonnet``).
    """
    parts = model.split("/", 1)
    cmd = [
        "claude",
        "-p",
        "--output-format",
        "json",
        # Replace Claude Code's default system prompt with saga's — a focused,
        # tool-free transform rather than a coding agent.
        "--system-prompt",
        system_prompt,
        "--allowedTools",
        "",  # no tools: prompt in, schema-valid JSON out
        "--json-schema",
        json.dumps(_SagaOut.model_json_schema()),
    ]
    if len(parts) == 2 and parts[1]:
        cmd += ["--model", parts[1]]

    # ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN outrank the Claude Code login, so a
    # stray key would silently bill the API instead of the subscription this
    # provider exists to use. Drop them for the subprocess.
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
    }

    # --json-schema constrains the field shape but not the chapter-count rule
    # (a pydantic model_validator), so an over-limit saga is caught by
    # model_validate below. Retry with the error fed back — like instructor does
    # for the SDK providers — before giving up.
    message = user_message
    last_error: Exception | None = None
    for _ in range(_MAX_ATTEMPTS):
        try:
            proc = subprocess.run(
                cmd,
                input=message,
                capture_output=True,
                text=True,
                env=env,
                timeout=_CLAUDE_CLI_TIMEOUT,
            )
        except FileNotFoundError as e:
            raise SagaError(
                "claude CLI not found. Install Claude Code and log in "
                "(https://claude.com/claude-code), or choose a different --model."
            ) from e
        except subprocess.TimeoutExpired as e:
            raise SagaError(
                f"claude CLI timed out after {_CLAUDE_CLI_TIMEOUT}s."
            ) from e

        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip()
            raise SagaError(f"claude CLI failed (exit {proc.returncode}): {detail}")

        # stdout may carry a leading warning line before the JSON object; start at
        # the first brace.
        text = proc.stdout.strip()
        start = text.find("{")
        if start == -1:
            raise SagaError(f"claude CLI returned no JSON:\n{text[:500]}")
        try:
            envelope = json.loads(text[start:])
        except json.JSONDecodeError as e:
            raise SagaError(f"could not parse claude CLI output: {e}") from e

        if envelope.get("is_error"):
            raise SagaError(f"claude CLI reported an error: {envelope.get('result')}")
        structured = envelope.get("structured_output")
        if structured is None:
            raise SagaError(
                "claude CLI returned no structured_output — the model did not "
                "produce schema-valid output."
            )
        try:
            return _SagaOut.model_validate(structured)
        except ValidationError as e:
            # Re-ask with the rejection reason (usually: too many chapters).
            last_error = e
            message = f"{user_message}\n\n# Previous attempt was rejected\n{e}"

    raise SagaError(f"claude CLI output did not match the saga schema: {last_error}")


def generate(
    diff: DiffResult,
    *,
    base: str,
    head: str,
    commit_sha: str,
    model: str,
    intent: str | None = None,
) -> Saga:
    """Generate the saga for an already-computed *diff*.

    ``base``/``head`` label the change set (they may be local refs or a PR's
    branch names) and ``commit_sha`` identifies the head. Keeping the diff a
    parameter makes generation source-agnostic — local git or a fetched PR.

    Raises ``SagaError`` on an empty diff, a provider/model error, or a
    coverage gap. The caller renders the error as a user-facing message.
    """
    hunks = parse_hunks(diff.diff_text)
    if not hunks:
        raise SagaError("No reviewable hunks in this change set.")

    provider = model.split("/", 1)[0]
    system_prompt = _PROMPT_PATH.read_text()
    user_message = _build_message(diff, hunks, intent)

    if provider == "claude-cli":
        result = _generate_via_claude_cli(model, system_prompt, user_message)
    else:
        client = _build_client(model)
        kwargs: dict = {}
        if provider == "openrouter":
            # Ask OpenRouter to route only to providers that support the params we
            # send (structured output), so schema enforcement is honored.
            kwargs["extra_body"] = {"provider": {"require_parameters": True}}

        try:
            result: _SagaOut = client.create(
                response_model=_SagaOut,
                max_tokens=_MAX_TOKENS,
                # Retry (feeding the validation error back) so an over-limit saga
                # is regenerated smaller instead of failing outright.
                max_retries=_MAX_ATTEMPTS - 1,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                **kwargs,
            )
        except SagaError:
            raise
        except Exception as e:
            raise SagaError(f"Saga generation failed: {e}") from e

    chapters = [_to_chapter(c) for c in result.chapters]
    validate_coverage(chapters, hunks)

    return Saga(
        branch=head,
        base=base,
        commit_sha=commit_sha,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        title=result.title,
        summary=result.summary,
        chapters=chapters,
    )
