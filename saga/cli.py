"""Generate a self-contained PR saga as a static HTML page.

Installs a ``saga`` command usable from any repo. Needs Python 3, git, and
an API key for the chosen provider (``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY`` /
``OPENROUTER_API_KEY``) — or, with a ``local/`` model, a running Ollama or
LM Studio server and no key. Run from inside the repo you want to review:

    saga --base main --head my-feature -o saga.html --open

Defaults: base=main, head=current branch (HEAD), output=saga.html,
model=anthropic/claude-opus-4-8 (override with --model or $SAGA_MODEL).
Pass --intent PATH to give the model a plan/spec for richer, plan-aware narration.
"""

from __future__ import annotations

import webbrowser
from pathlib import Path

import typer

from .comments import comments_app
from .diff import current_branch, repo_root_from
from .generate import generate
from .model import SagaError
from .render import render

app = typer.Typer(
    name="saga",
    help="Generate a self-contained PR saga as static HTML.",
    add_completion=False,
)
app.add_typer(comments_app, name="comments")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    base: str = typer.Option("main", help="base ref (default: main)"),
    head: str = typer.Option("HEAD", help="head ref to walk through (default: HEAD)"),
    intent: Path | None = typer.Option(
        None, help="optional path to a plan/spec describing the change's intent"
    ),
    model: str = typer.Option(
        "anthropic/claude-opus-4-8",
        envvar="SAGA_MODEL",
        help=(
            "provider/model to use, e.g. anthropic/claude-opus-4-8, openai/gpt-4o, "
            "openrouter/anthropic/claude-3.5-sonnet, local/qwen2.5-coder:14b "
            "(local/ targets Ollama or LM Studio; see $SAGA_LOCAL_BASE_URL) "
            "(default: $SAGA_MODEL or anthropic/claude-opus-4-8)"
        ),
    ),
    output: Path = typer.Option(
        Path("saga.html"),
        "-o",
        "--output",
        help="output HTML path (default: saga.html)",
    ),
    repo: Path = typer.Option(
        Path.cwd(), "--repo", help="path inside the target git repo (default: cwd)"
    ),
    open_browser: bool = typer.Option(
        True,
        "--open/--no-open",
        help="open the result in a browser (default: on; use --no-open to disable)",
    ),
) -> None:
    """Generate a self-contained PR saga as static HTML."""
    if ctx.invoked_subcommand is not None:
        return

    repo_root = repo_root_from(repo)
    if repo_root is None:
        typer.echo(f"error: {repo} is not inside a git repository.", err=True)
        raise typer.Exit(1)

    intent_text = None
    if intent is not None:
        try:
            intent_text = intent.read_text()
        except OSError as e:
            typer.echo(f"error: could not read intent file: {e}", err=True)
            raise typer.Exit(1) from e

    resolved_head = current_branch(repo_root) if head == "HEAD" else head
    typer.echo(f"Generating saga for {base}...{resolved_head} …", err=True)
    try:
        saga = generate(repo_root, base, resolved_head, model=model, intent=intent_text)
        html = render(repo_root, saga)
    except SagaError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from e

    output.write_text(html)
    typer.echo(f"Wrote {output} ({len(saga.chapters)} chapters).", err=True)
    if open_browser:
        webbrowser.open(output.resolve().as_uri())


if __name__ == "__main__":
    app()
