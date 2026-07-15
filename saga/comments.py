"""The ``saga comments`` subcommands: publish to GitHub, or read for an agent.

A reviewer authors comments in the browser (see ``assets/saga.js``), which are
persisted **inside** the saga HTML as a JSON envelope (see ``block.py``). This
module reads that envelope and consumes it two ways:

* ``push`` bundles every comment into a single **pending** PR review via the
  ``gh`` CLI (``event`` omitted ⇒ PENDING) — the reviewer submits it on GitHub.
* ``read`` emits a normalized JSON view on stdout for a coding agent.

Both read the envelope straight from the saga HTML file (``saga comments push
./saga.html``); ``--comments`` still accepts a hand-written JSON envelope as a
scripting escape hatch. The GitHub subprocess calls mirror ``diff._git`` —
stdlib + the ``gh`` CLI only. ``build_review_payload`` and ``agent_view`` are
pure functions so their shapes are unit-tested without touching the network.

``create_github_review`` and ``agent_view`` are the shared core reused by
``saga serve``'s ``POST /api/publish`` (see ``serve.py``).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import typer

from . import block
from .diff import repo_root_from
from .model import SagaError

_DEFAULT_SAGA = Path("saga.html")
_FILE_NOTE_PREFIX = "**File-level note:** "


# ---------------------------------------------------------------------------
# Envelope resolution (HTML file or hand-written sidecar)
# ---------------------------------------------------------------------------


def _load_sidecar(path: Path) -> dict:
    """Read and validate a hand-written JSON envelope (the scripting fallback)."""
    try:
        raw = path.read_text()
    except OSError as e:
        raise SagaError(f"could not read comments file {path}: {e}") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SagaError(f"comments file {path} is not valid JSON: {e}") from e
    try:
        return block.validate_envelope(data)
    except block.BlockError as e:
        raise SagaError(str(e)) from e


def resolve(saga_file: Path | None, comments: Path | None) -> tuple[dict, dict]:
    """Resolve the ``(envelope, meta)`` pair from the CLI's inputs.

    ``--comments`` (a hand-written envelope) wins when given; a *missing* sidecar
    means "no comments yet" (an empty envelope), while a malformed one errors.
    Otherwise the envelope is read from the saga HTML file (default
    ``saga.html``) and *meta* (branch/base) is recovered from its ``__sagaData``.
    A hand-written sidecar may carry its own top-level ``branch``/``base``.
    """
    if comments is not None:
        if not comments.exists():
            return block.empty_envelope(""), {}
        env = _load_sidecar(comments)
        return env, {"branch": env.get("branch", ""), "base": env.get("base", "")}

    path = saga_file or _DEFAULT_SAGA
    if not path.exists():
        raise SagaError(
            f"no saga file at {path}. Pass the saga HTML path "
            "(saga comments push ./saga.html) or a --comments file."
        )
    try:
        env = block.read_envelope(path)
    except block.BlockError as e:
        raise SagaError(f"{path} is not a saga with a comments block: {e}") from e
    return env, block.read_saga_meta(path)


# ---------------------------------------------------------------------------
# Pure transforms: envelope -> GitHub review payload / agent view
# ---------------------------------------------------------------------------


def build_review_payload(envelope: dict) -> dict:
    """Assemble the body for GitHub's create-review endpoint from an envelope.

    Inline comments map straight to ``{path, line, side, body}``. Per-file notes
    are anchored to the file's first changed line (the ``line``/``side`` the
    front end stored) and prefixed — GitHub's batch review API has no file-level
    comment type, so this keeps them inside the one pending review. The overall
    comment becomes the review ``body``. Tombstoned (``deletedAt``) and empty
    comments are skipped. ``event`` is deliberately absent so the review is
    PENDING.
    """
    comments: list[dict] = []
    for c in envelope.get("inline", []):
        if c.get("deletedAt"):
            continue
        body = (c.get("body") or "").strip()
        if not body:
            continue
        comments.append(
            {
                "path": c["path"],
                "line": c["line"],
                "side": c.get("side", "RIGHT"),
                "body": body,
            }
        )
    for f in envelope.get("file", []):
        if f.get("deletedAt"):
            continue
        body = (f.get("body") or "").strip()
        if not body:
            continue
        comments.append(
            {
                "path": f["path"],
                "line": f.get("line", 1),
                "side": f.get("side", "RIGHT"),
                "body": _FILE_NOTE_PREFIX + body,
            }
        )

    overall = envelope.get("overall")
    body = ""
    if overall and not overall.get("deletedAt"):
        body = (overall.get("body") or "").strip()

    payload: dict = {}
    if body:
        payload["body"] = body
    if comments:
        payload["comments"] = comments
    return payload


def agent_view(envelope: dict, meta: dict | None = None) -> dict:
    """A lean, tombstone-filtered view of the envelope for a coding agent.

    branch/base come from the saga's own metadata (comments carry none). The
    same shape backs ``saga comments read`` and ``serve``'s agent publish mode.
    """
    meta = meta or {}
    overall = envelope.get("overall")
    return {
        "branch": meta.get("branch", ""),
        "base": meta.get("base", ""),
        "overall": overall if overall and not overall.get("deletedAt") else None,
        "file": [f for f in envelope.get("file", []) if not f.get("deletedAt")],
        "inline": [c for c in envelope.get("inline", []) if not c.get("deletedAt")],
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


def _pr_info(repo_root: Path, branch: str | None) -> tuple[int, str]:
    """Return ``(pr_number, pr_url)`` for *branch*'s PR (or the current branch's
    when *branch* is unknown)."""
    args = ["pr", "view", "--json", "number,url"]
    if branch:
        args.insert(2, branch)
    result = _gh(repo_root, *args)
    if result.returncode != 0:
        where = f"branch '{branch}'" if branch else "the current branch"
        raise SagaError(
            f"could not find an open PR for {where}: {result.stderr.strip()}"
        )
    try:
        data = json.loads(result.stdout)
        return int(data["number"]), str(data["url"])
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        raise SagaError(f"unexpected gh pr view output: {e}") from e


# ---------------------------------------------------------------------------
# Shared publish core (reused by the server)
# ---------------------------------------------------------------------------


def create_github_review(repo_root: Path, envelope: dict, meta: dict) -> str:
    """Post the envelope's comments as one pending review; return a summary.

    Raises ``SagaError`` (surfaced as a readable message / a ``502`` in the
    server) if ``gh`` is missing, unauthenticated, or the PR can't be found.
    """
    payload = build_review_payload(envelope)
    if not payload:
        return "No comments to push."

    pr_number, pr_url = _pr_info(repo_root, meta.get("branch"))
    try:
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
    except FileNotFoundError as e:
        raise SagaError(
            "gh CLI not found. Install the GitHub CLI and authenticate "
            "(https://cli.github.com)."
        ) from e
    if result.returncode != 0:
        raise SagaError(f"gh api failed: {result.stderr.strip()}")

    n = len(payload.get("comments", []))
    return (
        f"Created a PENDING review on PR #{pr_number} "
        f"({n} comment{'s' if n != 1 else ''}). Review and submit it on GitHub:\n"
        f"  {pr_url}/files"
    )


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


def push(
    saga_file: Path | None,
    repo_root: Path,
    *,
    comments: Path | None = None,
    web: bool = False,
) -> int:
    """Post the reviewer's comments as a single pending review on the PR."""
    envelope, meta = resolve(saga_file, comments)
    summary = create_github_review(repo_root, envelope, meta)
    print(summary, file=sys.stderr)
    if web and meta.get("branch"):
        _gh(repo_root, "pr", "view", meta["branch"], "--web")
    return 0


def read(saga_file: Path | None, *, comments: Path | None = None) -> int:
    """Print the reviewer's comments as normalized JSON on stdout (for an agent)."""
    envelope, meta = resolve(saga_file, comments)
    print(json.dumps(agent_view(envelope, meta), indent=2, ensure_ascii=False))
    return 0


comments_app = typer.Typer(
    help="Push saga review comments to GitHub, or read them as JSON.",
    no_args_is_help=True,
)

_FILE_HELP = "path to the saga HTML file (default: saga.html)"
_COMMENTS_HELP = "read a hand-written JSON envelope instead of a saga HTML file"


@comments_app.command("push")
def push_cmd(
    saga_file: Path = typer.Argument(None, metavar="[FILE]", help=_FILE_HELP),
    comments: Path = typer.Option(None, "--comments", help=_COMMENTS_HELP),
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
        push(saga_file, repo_root, comments=comments, web=web)
    except SagaError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from e


@comments_app.command("read")
def read_cmd(
    saga_file: Path = typer.Argument(None, metavar="[FILE]", help=_FILE_HELP),
    comments: Path = typer.Option(None, "--comments", help=_COMMENTS_HELP),
) -> None:
    """Print comments as JSON on stdout (for a coding agent)."""
    try:
        read(saga_file, comments=comments)
    except SagaError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from e
