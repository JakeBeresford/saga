# Saga

Generate a **chapter-by-chapter guided tour** of a code change as a single,
self-contained static HTML page, a _saga_ of your diff. It partitions a diff into
ordered chapters that tell one coherent story, each with a plain-language narration
and just the hunks that belong to it. Large PRs become easy to review without
losing the thread.

The output is one HTML file with everything inlined (diff2html, syntax highlighting,
the data). Open it offline, email it, commit it, or drop it on any static host.

## Requirements

- Python 3.11+
- `git`
- An API key for your chosen provider, in the standard environment variable:
  `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `OPENROUTER_API_KEY`

Generation is one structured LLM call made through [`instructor`](https://python.useinstructor.com).

## Install

Install once and the `saga` command is available from any repo:

```sh
uv tool install saga-cli     # recommended
# or
pipx install saga-cli
# or, into the current environment
pip install saga-cli
```

Installing from a local checkout instead? Point the installer at this directory,
e.g. `uv tool install /path/to/saga`. To upgrade: `uv tool install --force saga-cli`.

## Usage

From inside the repo you want to review:

```sh
saga --base main --head my-feature -o saga.html --open
```

Run it from anywhere with `--repo`:

```sh
saga --repo ~/src/some-project --base main --head my-feature -o out.html
```

| Flag                   | Default                     | Meaning                                                                                            |
| ---------------------- | --------------------------- | -------------------------------------------------------------------------------------------------- |
| `--base`               | `main`                      | Base ref to diff against                                                                           |
| `--head`               | current branch              | Head ref to walk through                                                                           |
| `--intent PATH`        | —                           | Optional plan/spec describing the change's intent, for plan-aware narration and deviation flagging |
| `--model`              | `anthropic/claude-opus-4-8` | `provider/model` string (see [Providers](#providers)); also `$SAGA_MODEL`                          |
| `-o, --output`         | `saga.html`                 | Output file                                                                                        |
| `--repo`               | cwd                         | A path inside the target git repo                                                                  |
| `--open` / `--no-open` | on                          | Open the result in a browser (on by default; `--no-open` to disable)                               |

## Providers

The model is a single `provider/model` string, dispatched through `instructor`.
Choose it with `--model` or the `SAGA_MODEL` environment variable, and set
the matching API key:

| Provider   | `--model` example                        | API key env var      |
| ---------- | ---------------------------------------- | -------------------- |
| Anthropic  | `anthropic/claude-opus-4-8`              | `ANTHROPIC_API_KEY`  |
| OpenAI     | `openai/gpt-4o`                          | `OPENAI_API_KEY`     |
| OpenRouter | `openrouter/anthropic/claude-3.5-sonnet` | `OPENROUTER_API_KEY` |

```sh
export SAGA_MODEL=openai/gpt-4o
export OPENAI_API_KEY=sk-…
saga --base main --head my-feature -o saga.html
```

## As a Claude Code skill

The `skills/` directory contains two Claude Code skills. To install both:

```sh
cp -R "$(pwd)/skills" ~/.claude/skills/saga
```

- **`saga`** — say **"/saga"** (or "give me a walkthrough of this branch") to generate a
  saga. It resolves the base/head refs and runs the tool for you.
- **`saga-comments`** — say **"/saga-comments"** (or "address the saga comments") to read an
  exported `saga.comments.json` and act on the reviewer's feedback in code.

## Reviewing: comments

The saga page is also a lightweight review surface. Open `saga.html` and leave three
kinds of comments — **inline** (click a line's number in any chapter's diff), **per-file**
(the "💬 File comment" control in each file header), and one **overall** review comment
(the box at the top of the Chapters list). Comments are drafted in your browser's
`localStorage`, so they survive a reload.

When you're done, click **Export comments** to download a `saga.comments.json` sidecar next
to the HTML. Two commands consume it:

```sh
# Post everything as a single PENDING review on the PR (you submit it on GitHub).
saga comments push --comments saga.comments.json

# Emit the comments as JSON on stdout — for a coding agent to act on.
saga comments read --comments saga.comments.json
```

`push` uses the `gh` CLI: it finds the open PR for the sidecar's branch and creates one
pending review (inline → line comments, per-file → a note anchored to the file's first
changed line, overall → the review body). Nothing is submitted until you review and submit
it on GitHub. Requires the [`gh`](https://cli.github.com) CLI, authenticated.

## How it works

1. `diff.py` computes `git diff base...head` (no checkout) and the commit list.
2. `model.py` splits the diff into stable-id hunks (`h0, h1, …`).
3. `generate.py` sends the labeled diff + commits (+ optional intent) to the chosen
   model via `instructor`, which returns chapters as schema-validated JSON. Coverage
   is **re-validated in code** — every hunk must belong to a chapter or generation fails.
4. `render.py` reconstructs each chapter's diff and inlines everything into one
   self-contained HTML file.

## Not included (yet)

- A GitHub Action to generate on PRs.
