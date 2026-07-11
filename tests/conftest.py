"""Shared test fixtures: throwaway git repos and a scrubbed VCR for LLM calls.

The ``git_repo`` fixture builds a real, self-contained git repository in a temp
dir so ``diff.py``/``generate.py``/``render.py`` can be exercised end-to-end
against actual ``git`` output — no mocking of git itself.

``vcr_cassette`` replays the one real LLM HTTP call from a cassette so the suite
runs offline and deterministically. Auth headers and cookies are stripped from
whatever gets recorded, so cassettes are safe to commit. Set
``SAGA_RECORD=1`` (with a real API key) to re-record.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import vcr

CASSETTE_DIR = Path(__file__).parent / "cassettes"

# Request headers VCR scrubs before recording (credentials).
_SENSITIVE_HEADERS = [
    "authorization",
    "x-api-key",
    "api-key",
    "openai-organization",
    "openai-project",
    "cookie",
    "set-cookie",
]

# Response headers that identify the account/request — stripped from cassettes
# so nothing account-specific is committed. Not credentials, but not ours to ship.
_SENSITIVE_RESPONSE_HEADERS = [
    "anthropic-organization-id",
    "openai-organization",
    "request-id",
    "x-request-id",
    "cf-ray",
    "traceresponse",
    "set-cookie",
]


def _scrub_request(request):
    # Body carries the diff/prompt only — no secrets — so it is left intact,
    # which also lets it double as a matched-on field if ever needed.
    return request


def _scrub_response(response):
    headers = response.get("headers", {})
    for name in list(headers):
        if name.lower() in _SENSITIVE_RESPONSE_HEADERS:
            headers[name] = ["REDACTED"]
    return response


def _git(repo: Path, *args: str, env: dict | None = None) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture
def git_env() -> dict:
    """Deterministic identity/config so commits don't depend on the host git."""
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
        }
    )
    return env


@pytest.fixture
def git_repo(tmp_path: Path, git_env: dict) -> Path:
    """A repo with a ``main`` baseline and a ``feature`` branch that edits one
    file and adds another — a two-file, three-hunk change set."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main", env=git_env)

    foo = repo / "foo.py"
    foo.write_text("a\nb\nc\n\n\n\n\n\n\nx\nz\n")
    _git(repo, "add", "foo.py", env=git_env)
    _git(repo, "commit", "-q", "-m", "baseline", env=git_env)

    _git(repo, "checkout", "-q", "-b", "feature", env=git_env)
    foo.write_text("a\nB\nc\n\n\n\n\n\n\nx\ny\nz\n")
    (repo / "new.txt").write_text("hello\nworld\n")
    _git(repo, "add", "-A", env=git_env)
    _git(repo, "commit", "-q", "-m", "edit foo and add new.txt", env=git_env)

    return repo


@pytest.fixture
def empty_diff_repo(tmp_path: Path, git_env: dict) -> Path:
    """A repo whose ``feature`` branch has no diff against ``main``."""
    repo = tmp_path / "empty"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main", env=git_env)
    (repo / "a.txt").write_text("same\n")
    _git(repo, "add", "-A", env=git_env)
    _git(repo, "commit", "-q", "-m", "only commit", env=git_env)
    _git(repo, "branch", "feature", env=git_env)
    return repo


@pytest.fixture
def vcr_cassette(request):
    """Yield a VCR configured to replay (or, with SAGA_RECORD=1, record) the
    named cassette with all auth material scrubbed."""
    record_mode = "once" if os.environ.get("SAGA_RECORD") else "none"
    my_vcr = vcr.VCR(
        cassette_library_dir=str(CASSETTE_DIR),
        record_mode=record_mode,
        match_on=["method", "scheme", "host", "port", "path"],
        filter_headers=[(h, "REDACTED") for h in _SENSITIVE_HEADERS],
        before_record_request=_scrub_request,
        before_record_response=_scrub_response,
    )
    return my_vcr
