"""Generate a self-contained PR saga as a static HTML page.

Installs a ``saga`` command usable from any repo. Needs Python 3, git, and
an API key for the chosen provider (``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY`` /
``OPENROUTER_API_KEY``) — or, with a ``local/`` model, a running Ollama or
LM Studio server and no key, or the ``claude-cli`` model, a logged-in Claude
Code CLI (e.g. a Claude subscription, no key). Run from inside the repo you
want to review:

    saga --base main --head my-feature -o saga.html --open

Or point it straight at a pull request by URL (via the ``gh`` CLI; no checkout
needed, works from any directory):

    saga https://github.com/owner/repo/pull/5 --model openai/gpt-4o

Defaults: base=auto-detected (e.g. origin/main), head=current branch (HEAD),
output=saga.html, model=anthropic/claude-opus-4-8 (override --model or $SAGA_MODEL).
Pass --intent PATH to give the model a plan/spec for richer, plan-aware narration.
"""

from __future__ import annotations

import webbrowser
from importlib.metadata import version as package_version
from pathlib import Path

import typer
from typer.core import TyperArgument, TyperGroup

from .comments import comments_app
from .diff import (
    compute_diff,
    current_branch,
    default_base,
    pr_diff,
    repo_root_from,
    rev_parse,
)
from .generate import generate
from .model import SagaError
from .render import render
from .video import render_videos


class SagaGroup(TyperGroup):
    """Let the top-level command take an optional positional target (a PR URL)
    while still dispatching subcommands like ``saga comments``.

    Click would otherwise make the group's positional argument swallow a
    subcommand name, and it forbids options after a positional. So: when the
    first token names a subcommand, drop the positional for that parse; otherwise
    allow options to follow the target (``saga <url> --model …``).
    """

    def parse_args(self, ctx, args):
        if args and args[0] in self.commands:
            saved = self.params
            self.params = [p for p in saved if not isinstance(p, TyperArgument)]
            try:
                return super().parse_args(ctx, args)
            finally:
                self.params = saved
        ctx.allow_interspersed_args = True
        return super().parse_args(ctx, args)


app = typer.Typer(
    name="saga",
    help="Generate a self-contained PR saga as static HTML.",
    add_completion=False,
    cls=SagaGroup,
)
app.add_typer(comments_app, name="comments")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"saga {package_version('saga-cli')}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    target: str | None = typer.Argument(
        None,
        help=(
            "a GitHub PR URL to build a saga for "
            "(e.g. https://github.com/owner/repo/pull/5); "
            "omit to use local git refs"
        ),
    ),
    version: bool = typer.Option(
        False,
        "--version",
        help="show the installed saga version and exit",
        is_eager=True,
        callback=_version_callback,
    ),
    base: str | None = typer.Option(
        None, help="base ref (default: auto-detected, e.g. origin/main)"
    ),
    head: str = typer.Option("HEAD", help="head ref to walk through (default: HEAD)"),
    intent: Path | None = typer.Option(
        None, help="optional path to a plan/spec describing the change's intent"
    ),
    model: str = typer.Option(
        "anthropic/claude-opus-4-8",
        envvar="SAGA_MODEL",
        help=(
            "provider/model to use, e.g. anthropic/claude-opus-4-8, openai/gpt-4o, "
            "openrouter/anthropic/claude-3.5-sonnet, local/qwen2.5-coder:14b, "
            "claude-cli or claude-cli/sonnet "
            "(local/ targets Ollama or LM Studio; see $SAGA_LOCAL_BASE_URL. "
            "claude-cli routes through your logged-in Claude Code CLI) "
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
    videos: bool = typer.Option(
        False,
        "--videos/--no-videos",
        help=(
            "generate an AI demo video for each chapter (requires Node.js and "
            "ANTHROPIC_API_KEY); videos are written to a sibling "
            "<output>-videos/ directory"
        ),
    ),
) -> None:
    """Generate a self-contained PR saga as static HTML."""
    if ctx.invoked_subcommand is not None:
        return

    intent_text = None
    if intent is not None:
        try:
            intent_text = intent.read_text()
        except OSError as e:
            typer.echo(f"error: could not read intent file: {e}", err=True)
            raise typer.Exit(1) from e

    try:
        if target is not None:
            # PR mode: fetch the diff from GitHub; base/head/sha come from the PR,
            # so --base/--head and a local checkout are not needed.
            typer.echo(f"Fetching PR {target} …", err=True)
            pr = pr_diff(target)
            diff = pr.diff
            resolved_base, resolved_head, commit_sha = pr.base, pr.head, pr.head_sha
            repo_root = None
        else:
            # Local mode: diff two refs straight from git.
            repo_root = repo_root_from(repo)
            if repo_root is None:
                typer.echo(f"error: {repo} is not inside a git repository.", err=True)
                raise typer.Exit(1)
            resolved_base = base if base is not None else default_base(repo_root)
            resolved_head = current_branch(repo_root) if head == "HEAD" else head
            diff = compute_diff(repo_root, resolved_base, resolved_head)
            commit_sha = rev_parse(repo_root, resolved_head)

        typer.echo(f"Generating saga for {resolved_base}...{resolved_head} …", err=True)
        saga = generate(
            diff,
            base=resolved_base,
            head=resolved_head,
            commit_sha=commit_sha,
            model=model,
            intent=intent_text,
        )
    except SagaError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from e

    video_paths: dict[str, str] | None = None
    if videos:
        if repo_root is None:
            typer.echo(
                "  warning: --videos is not supported for PR URL targets.", err=True
            )
        else:
            abs_output = output.resolve()
            videos_dir = abs_output.parent / f"{abs_output.stem}-videos"
            typer.echo(
                f"Generating videos for {len(saga.chapters)} chapters "
                f"(writing to {videos_dir.name}/) …",
                err=True,
            )
            video_paths = render_videos(saga, diff, videos_dir, model=model)
            n = len(video_paths)
            skipped = len(saga.chapters) - n
            msg = f"Rendered {n} of {len(saga.chapters)} videos"
            if skipped:
                msg += f" ({skipped} skipped)"
            typer.echo(msg + ".", err=True)

    try:
        html = render(saga, diff, video_paths=video_paths)
    except SagaError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from e

    output.write_text(html)
    typer.echo(f"Wrote {output} ({len(saga.chapters)} chapters).", err=True)
    if open_browser:
        webbrowser.open(output.resolve().as_uri())


if __name__ == "__main__":
    app()
