"""Generate a self-contained PR saga as a static HTML page.

Installs a ``saga`` command usable from any repo. Needs Python 3, git, and
an API key for the chosen provider (``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY`` /
``OPENROUTER_API_KEY``). Run from inside the repo you want to review:

    saga --base main --head my-feature -o saga.html --open

Defaults: base=main, head=current branch (HEAD), output=saga.html,
model=anthropic/claude-opus-4-8 (override with --model or $SAGA_MODEL).
Pass --intent PATH to give the model a plan/spec for richer, plan-aware narration.
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path

from .diff import current_branch, repo_root_from
from .generate import generate
from .model import SagaError
from .render import render


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="saga",
        description="Generate a self-contained PR saga as static HTML.",
    )
    parser.add_argument("--base", default="main", help="base ref (default: main)")
    parser.add_argument(
        "--head", default="HEAD", help="head ref to walk through (default: HEAD)"
    )
    parser.add_argument(
        "--intent",
        type=Path,
        default=None,
        help="optional path to a plan/spec describing the change's intent",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("SAGA_MODEL", "anthropic/claude-opus-4-8"),
        help=(
            "provider/model to use, e.g. anthropic/claude-opus-4-8, openai/gpt-4o, "
            "openrouter/anthropic/claude-3.5-sonnet "
            "(default: $SAGA_MODEL or anthropic/claude-opus-4-8)"
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("saga.html"),
        help="output HTML path (default: saga.html)",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="path inside the target git repo (default: cwd)",
    )
    parser.add_argument(
        "--open",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="open the result in a browser (default: on; use --no-open to disable)",
    )
    args = parser.parse_args(argv)

    repo_root = repo_root_from(args.repo)
    if repo_root is None:
        print(f"error: {args.repo} is not inside a git repository.", file=sys.stderr)
        return 1

    intent = None
    if args.intent is not None:
        try:
            intent = args.intent.read_text()
        except OSError as e:
            print(f"error: could not read intent file: {e}", file=sys.stderr)
            return 1

    head = current_branch(repo_root) if args.head == "HEAD" else args.head
    print(f"Generating saga for {args.base}...{head} …", file=sys.stderr)
    try:
        saga = generate(repo_root, args.base, head, model=args.model, intent=intent)
        html = render(repo_root, saga)
    except SagaError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    args.output.write_text(html)
    print(f"Wrote {args.output} ({len(saga.chapters)} chapters).", file=sys.stderr)
    if args.open:
        webbrowser.open(args.output.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
