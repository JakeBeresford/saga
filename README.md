# Saga

Generate a **chapter-by-chapter guided tour** of a code change as a single,
self-contained static HTML page, a _saga_ of your diff. It partitions a diff into
ordered chapters that tell one coherent story, each with a plain-language narration
and just the hunks that belong to it. Large PRs become easy to review without
losing the thread.

The output is one HTML file with everything inlined (diff2html, syntax highlighting,
the data). Open it offline, email it, commit it, or drop it on any static host.

[**See an example saga**](https://jakeberesford.github.io/saga/example.html).

## Requirements

- Python 3.11+
- `git`
- The [`gh`](https://cli.github.com) CLI, authenticated — only for reviewing a PR
  by URL (`saga <pr-url>`) or pushing review comments
- An API key for your chosen provider, in the standard environment variable:
  `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `OPENROUTER_API_KEY` — or a running
  local server (Ollama / LM Studio) and no key, with a `local/` model

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

From inside the repo, on the branch you want to review:

```sh
saga
```

From inside the repo, reviewing a different branch:

```sh
saga --base main --head my-feature -o saga.html --open
```

Run it from anywhere with `--repo`:

```sh
saga --repo ~/src/some-project --base main --head my-feature -o out.html
```

### From a GitHub PR URL

Point saga straight at a pull request by passing its URL as the first argument.
No checkout is needed and it works from any directory:

```sh
saga https://github.com/owner/repo/pull/5
saga https://github.com/owner/repo/pull/5 --model openai/gpt-4o -o pr5.html
```

This fetches the PR's diff, commits, and branch names with the
[`gh`](https://cli.github.com) CLI (so `gh` must be installed and authenticated),
then builds the saga exactly as it would for a local branch. In this mode the PR
defines the change set, so `--base`, `--head`, and `--repo` are ignored.

The optional positional argument is a GitHub PR URL (as above); all flags below
apply to both modes.

| Flag                     | Default                     | Meaning                                                                                                                                                          |
| ------------------------ | --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--base`                 | auto-detected               | Base ref to diff against (defaults to the repo's default branch, e.g. `origin/main`); local mode only                                                            |
| `--head`                 | current branch              | Head ref to walk through; local mode only                                                                                                                        |
| `--intent PATH`          | —                           | Optional plan/spec describing the change's intent, for plan-aware narration and deviation flagging                                                               |
| `--model`                | `anthropic/claude-opus-4-8` | `provider/model` string (see [Providers](#providers)); also `$SAGA_MODEL`                                                                                        |
| `-o, --output`           | `saga.html`                 | Output file                                                                                                                                                      |
| `--repo`                 | cwd                         | A path inside the target git repo; local mode only                                                                                                               |
| `--open` / `--no-open`   | on                          | Open the result in a browser (the served URL when serving, else the `file://` page)                                                                              |
| `--serve` / `--no-serve` | on                          | On an interactive terminal, serve the saga after generating so comments save into the file (see [Reviewing](#reviewing-comments)); `--no-serve` writes and exits |

## Providers

The model is a single `provider/model` string, dispatched through `instructor`.
Choose it with `--model` or the `SAGA_MODEL` environment variable, and set
the matching API key:

| Provider   | `--model` example                        | API key env var          |
| ---------- | ---------------------------------------- | ------------------------ |
| Anthropic  | `anthropic/claude-opus-4-8`              | `ANTHROPIC_API_KEY`      |
| OpenAI     | `openai/gpt-4o`                          | `OPENAI_API_KEY`         |
| OpenRouter | `openrouter/anthropic/claude-3.5-sonnet` | `OPENROUTER_API_KEY`     |
| Local      | `local/qwen2.5-coder:14b`                | none                     |
| Claude CLI | `claude-cli` or `claude-cli/sonnet`      | none (Claude Code login) |

```sh
export SAGA_MODEL=openai/gpt-4o
export OPENAI_API_KEY=sk-…
saga --base main --head my-feature -o saga.html
```

### Local LLMs (Ollama / LM Studio)

A `local/` model runs against any OpenAI-compatible local server, with no API
key. Pull a capable coder model first (`ollama pull qwen2.5-coder:14b`), then:

```sh
saga --model local/qwen2.5-coder:14b --base main --head my-feature
```

`local/` defaults to Ollama's endpoint (`http://localhost:11434/v1`). Point it
at another server — e.g. LM Studio — with `SAGA_LOCAL_BASE_URL`:

```sh
export SAGA_LOCAL_BASE_URL=http://localhost:1234/v1   # LM Studio
saga --model local/your-loaded-model --base main --head my-feature
```

Two caveats: saga requires schema-valid JSON output, so use an instruction-tuned
model that follows JSON prompting reliably; and the full diff plus a 16k output
budget can exceed a small model's context window — prefer larger-context models
and expect weaker narration than a frontier hosted model.

### Claude Code CLI (no API key)

If you don't have an Anthropic API key but you are logged into the
[Claude Code](https://claude.com/claude-code) CLI — for example with a Claude
Pro/Max subscription — the `claude-cli` model routes generation through
`claude -p` instead of the API, reusing that login:

```sh
saga --model claude-cli --base main --head my-feature
saga --model claude-cli/sonnet --base main --head my-feature   # pin a model
```

This shells out to the `claude` binary (which must be on your `PATH` and logged
in), constrains its output to saga's schema via `--json-schema`, and runs it as
a plain transform with no tools. `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN`
are dropped for the subprocess so it uses your Claude Code login rather than
silently billing an API key. It is slower than a direct API call (Claude Code
boots an agent per run) and subject to your subscription's usage limits.

## As a Claude Code skill

The `skills/` directory contains a Claude Code skill. To install it:

```sh
cp -R "$(pwd)/skills" ~/.claude/skills/saga
```

- **`saga`** — say **"/saga"** (or "give me a walkthrough of this branch") to generate a
  saga. It resolves the base/head refs and runs the tool for you.

## Reviewing: comments

The saga page is also a lightweight review surface. Leave three kinds of comments —
**inline** (click a line's number in any chapter's diff), **per-file** (the "💬 File
comment" control in each file header), and one **overall** review comment (the box on the
**Wrap up** page — reach it with the "Wrap up →" button in any chapter's nav or the card at
the end of the chapters list).

Comments live **inside the HTML file**, in an embedded block that `saga serve` rewrites
in place. That keeps the file a single portable artifact: you can commit it, email it, or
open it offline, and the comments travel with it and reload every time — no server needed
to _read_ them.

### Open through `saga serve`

Saving comments back into the file needs a local process (a browser can't portably write
to its own file — the File System Access API is Chromium-only, so Safari and Firefox can't).
So an interactive `saga` run **auto-starts a local server** and opens the saga through it:

```
serving at http://127.0.0.1:52345/ — Ctrl-C to stop
```

On that page, edits **autosave into the file** within a second (a status pill shows
`Saved` / `Saving…` / `Reconnecting…`), and two buttons appear:

- **Publish to GitHub** — posts everything as a single **pending** review via the `gh`
  CLI (inline → line comments, per-file → a note anchored to the file's first changed
  line, overall → the review body). Nothing is submitted until you review and submit it on
  GitHub. Requires the [`gh`](https://cli.github.com) CLI, authenticated.
- **Copy for agent** — copies the comments as JSON for a coding agent to act on.

To serve a saga you generated earlier (or received), point `saga serve` at it:

```sh
saga serve ./saga.html
```

The server is loopback-only (`127.0.0.1`), holds no state of its own (the file is the
store), and needs no API key. Stop it with `Ctrl-C`.

### Static mode (no server)

If you open a saga as a bare `file://` — double-clicked, emailed, committed — there is no
server, so **reading works but drafting is browser-only**: a banner appears and the pill
reads `Draft (this browser only)`. Your drafts buffer in that browser's `localStorage`.

**Reopen the file through `saga serve` _before_ commenting** to save into the file and
publish. Drafts made on a bare `file://` page live under a different browser origin than
the served page and cannot be recovered by serving later — so serve is the front door.

### From the command line / a coding agent

The same publish/read paths are available as commands that read the file's embedded block:

```sh
# Post the comments as a single PENDING review (you submit it on GitHub).
saga comments push path/to/saga.html

# Emit the comments as JSON on stdout for a coding agent to act on.
saga comments read path/to/saga.html
```

Both default to `./saga.html`.

## How it works

1. `diff.py` computes `git diff base...head` (no checkout) and the commit list —
   or, given a PR URL, fetches the same diff and metadata from GitHub via `gh`.
2. `model.py` splits the diff into stable-id hunks (`h0, h1, …`).
3. `generate.py` sends the labeled diff + commits (+ optional intent) to the chosen
   model via `instructor`, which returns chapters as schema-validated JSON. Coverage
   is **re-validated in code** — every hunk must belong to a chapter or generation fails.
4. `render.py` reconstructs each chapter's diff and inlines everything into one
   self-contained HTML file, including an empty comments block (`comments_block.py`) and a
   per-file `sagaId`.
5. `serve.py` serves that file on a loopback port derived from the `sagaId` and rewrites
   the comments block in place as you review; `comments.py` reads the same block to
   publish to GitHub or hand comments to an agent.

## Not included (yet)

- A GitHub Action to auto-generate saga on PRs.
