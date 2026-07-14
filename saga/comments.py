"""The ``saga comments`` subcommands: comment IO, GitHub push, agent read.

A reviewer authors comments in the browser (see ``assets/saga.js``); the page's
"Copy" buttons put a ready-to-run command on the clipboard, with the comments
base64-encoded inline as ``--data`` — so nothing has to be found on disk. This
module consumes those comments two ways:

* ``push`` bundles every comment into a single **pending** PR review via the
  ``gh`` CLI (``event`` omitted ⇒ PENDING) — the reviewer submits it on GitHub.
* ``read`` emits a normalized JSON view on stdout for a coding agent.

Both accept the base64 ``--data`` payload or, as a scripting escape hatch, a
``--comments`` file. The GitHub subprocess calls mirror ``diff._git`` — stdlib
+ the ``gh`` CLI only. ``build_review_payload`` is a pure function so the
payload shape is unit-tested without touching the network.
"""

from __future__ import annotations

import base64
import binascii
import json
import subprocess
import sys
from pathlib import Path

import typer

from .diff import repo_root_from
from .model import SagaError

_DEFAULT_SIDECAR = Path("saga.comments.json")
_FILE_NOTE_PREFIX = "**File-level note:** "


# ---------------------------------------------------------------------------
# Comment IO
# ---------------------------------------------------------------------------


def _validate(data: object) -> dict:
    """Validate a decoded comments object, whatever source it came from.

    Raises ``SagaError`` with a reviewer-facing message on any malformed shape —
    a non-object, a bad ``files`` map, or an inline comment lacking
    ``line``/``body``.
    """
    if not isinstance(data, dict):
        raise SagaError("comments must be a JSON object.")
    files = data.get("files", {})
    if not isinstance(files, dict):
        raise SagaError("'files' must be a JSON object keyed by file path.")
    for fpath, entry in files.items():
        if not isinstance(entry, dict):
            raise SagaError(f"file entry for {fpath} must be an object.")
        inline = entry.get("inline", [])
        if not isinstance(inline, list):
            raise SagaError(f"'inline' for {fpath} must be a list.")
        for c in inline:
            if not isinstance(c, dict) or "line" not in c or "body" not in c:
                raise SagaError(
                    f"inline comment on {fpath} needs a 'line' and a 'body'."
                )
    return data


def load_sidecar(path: Path) -> dict:
    """Read and validate a ``saga.comments.json`` file (the scripting fallback).

    Callers handle a *missing* file themselves (it means "no comments yet"); an
    unreadable or malformed file is a real error.
    """
    try:
        raw = Path(path).read_text()
    except OSError as e:
        raise SagaError(f"could not read comments file {path}: {e}") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SagaError(f"comments file {path} is not valid JSON: {e}") from e
    return _validate(data)


def decode_payload(encoded: str) -> dict:
    """Decode+validate the base64 comments payload from the page's Copy button."""
    try:
        raw = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError) as e:
        raise SagaError(f"comments payload is not valid base64: {e}") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SagaError(f"comments payload is not valid JSON: {e}") from e
    return _validate(data)


def _resolve(data: str | None, sidecar_path: Path) -> dict:
    """Resolve comments from the ``--data`` payload or a ``--comments`` file.

    ``--data`` is the primary path and wins when present. A *missing* file means
    "no comments yet" (empty dict); a bad payload or malformed file is an error.
    """
    if data is not None:
        return decode_payload(data)
    path = Path(sidecar_path)
    return load_sidecar(path) if path.exists() else {}


# ---------------------------------------------------------------------------
# GitHub review payload (pure)
# ---------------------------------------------------------------------------


def build_review_payload(sidecar: dict) -> dict:
    """Assemble the body for GitHub's create-review endpoint from a sidecar.

    Inline comments map straight to ``{path, line, side, body}``. Per-file
    comments are anchored to the file's first changed line (``file_anchor``) and
    prefixed — GitHub's batch review API has no file-level comment type, so this
    keeps them inside the one pending review. The overall comment becomes the
    review ``body``. ``event`` is deliberately absent so the review is PENDING.
    """
    body = (sidecar.get("overall") or "").strip()
    comments: list[dict] = []
    for path, entry in sidecar.get("files", {}).items():
        for c in entry.get("inline", []):
            comments.append(
                {
                    "path": path,
                    "line": c["line"],
                    "side": c.get("side", "RIGHT"),
                    "body": c["body"],
                }
            )
        file_comment = (entry.get("file_comment") or "").strip()
        if file_comment:
            anchor = entry.get("file_anchor") or {}
            comments.append(
                {
                    "path": path,
                    "line": anchor.get("line", 1),
                    "side": anchor.get("side", "RIGHT"),
                    "body": _FILE_NOTE_PREFIX + file_comment,
                }
            )

    payload: dict = {}
    if body:
        payload["body"] = body
    if comments:
        payload["comments"] = comments
    return payload


def _normalize_for_agent(sidecar: dict) -> dict:
    """A lean, stable view for a coding agent — drops GitHub-only anchors."""
    files = {}
    for path, entry in sidecar.get("files", {}).items():
        files[path] = {
            "file_comment": (entry.get("file_comment") or None),
            "inline": [
                {"line": c["line"], "side": c.get("side", "RIGHT"), "body": c["body"]}
                for c in entry.get("inline", [])
            ],
        }
    return {
        "branch": sidecar.get("branch", ""),
        "base": sidecar.get("base", ""),
        "overall": (sidecar.get("overall") or None),
        "files": files,
    }


# ---------------------------------------------------------------------------
# gh CLI shell
# ---------------------------------------------------------------------------


def _gh(
    repo_root: Path, *args: str, input: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        cwd=repo_root,
        input=input,
    )


def _pr_info(repo_root: Path, branch: str) -> tuple[int, str]:
    """Return ``(pr_number, pr_url)`` for the PR whose head is *branch*."""
    result = _gh(repo_root, "pr", "view", branch, "--json", "number,url")
    if result.returncode != 0:
        raise SagaError(
            f"could not find an open PR for branch '{branch}': {result.stderr.strip()}"
        )
    try:
        data = json.loads(result.stdout)
        return int(data["number"]), str(data["url"])
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        raise SagaError(f"unexpected gh pr view output: {e}") from e


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def push(
    sidecar_path: Path, repo_root: Path, *, data: str | None = None, web: bool = False
) -> int:
    """Post the reviewer's comments as a single pending review on the PR."""
    sidecar = _resolve(data, sidecar_path)

    payload = build_review_payload(sidecar)
    if not payload:
        print("No comments to push.", file=sys.stderr)
        return 0

    branch = sidecar.get("branch")
    if not branch:
        raise SagaError("comments file is missing 'branch'; cannot locate the PR.")

    pr_number, pr_url = _pr_info(repo_root, branch)
    result = _gh(
        repo_root,
        "api",
        "--method",
        "POST",
        f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/reviews",
        "--input",
        "-",
        input=json.dumps(payload),
    )
    if result.returncode != 0:
        raise SagaError(f"gh api failed: {result.stderr.strip()}")

    n = len(payload.get("comments", []))
    print(
        f"Created a PENDING review on PR #{pr_number} "
        f"({n} comment{'s' if n != 1 else ''}). Review and submit it on GitHub:\n"
        f"  {pr_url}/files",
        file=sys.stderr,
    )
    if web:
        _gh(repo_root, "pr", "view", branch, "--web")
    return 0


def read(sidecar_path: Path, *, data: str | None = None) -> int:
    """Print the reviewer's comments as normalized JSON on stdout.

    This command feeds a coding agent, so *no comments* is not an error —
    an absent ``--data`` and a missing file both report a valid, empty JSON
    document. A payload or file that exists but is malformed still errors.
    """
    sidecar = _resolve(data, sidecar_path)
    print(json.dumps(_normalize_for_agent(sidecar), indent=2, ensure_ascii=False))
    return 0


comments_app = typer.Typer(
    help="Push saga review comments to GitHub, or read them as JSON.",
    no_args_is_help=True,
)


_DATA_HELP = "base64 comments payload from the saga page's Copy button"


@comments_app.command("push")
def push_cmd(
    data: str = typer.Option(None, "--data", help=_DATA_HELP),
    comments: Path = typer.Option(_DEFAULT_SIDECAR, "--comments"),
    repo: Path = typer.Option(Path.cwd(), "--repo"),
    web: bool = typer.Option(
        False, "--web", help="open the PR in a browser after pushing"
    ),
) -> None:
    """Post comments to the PR as a pending GitHub review."""
    repo_root = repo_root_from(repo)
    if repo_root is None:
        typer.echo(f"error: {repo} is not inside a git repository.", err=True)
        raise typer.Exit(1)
    try:
        push(comments, repo_root, data=data, web=web)
    except SagaError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from e


@comments_app.command("read")
def read_cmd(
    data: str = typer.Option(None, "--data", help=_DATA_HELP),
    comments: Path = typer.Option(_DEFAULT_SIDECAR, "--comments"),
) -> None:
    """Print comments as JSON on stdout (for a coding agent)."""
    try:
        read(comments, data=data)
    except SagaError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from e
