---
title: Usage
nav_order: 3
---

# Usage

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

## From a GitHub PR URL

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

## Flags

All flags are documented in `saga --help`, the following flags apply to local and GitHub usage.



| Flag                     | Default                     | Meaning                                                                                                                                                              |
| ------------------------ | --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--base`                 | auto-detected               | Base ref to diff against (defaults to the repo's default branch, e.g. `origin/main`); local mode only                                                                |
| `--head`                 | current branch              | Head ref to walk through; local mode only                                                                                                                            |
| `--intent PATH`          | —                           | Optional plan/spec describing the change's intent, for plan-aware narration and deviation flagging                                                                   |
| `--model`                | `anthropic/claude-opus-4-8` | `provider/model` string (see [Providers]({% link providers.md %})); also `$SAGA_MODEL`                                                                               |
| `-o, --output`           | `saga.html`                 | Output file                                                                                                                                                          |
| `--repo`                 | cwd                         | A path inside the target git repo; local mode only                                                                                                                   |
| `--open` / `--no-open`   | on                          | Open the result in a browser (the served URL when serving, else the `file://` page)                                                                                  |
| `--serve` / `--no-serve` | on                          | On an interactive terminal, serve the saga after generating so comments save into the file (see [Reviewing]({% link reviewing.md %})); `--no-serve` writes and exits |

## As a Claude Code skill

The `skills/` directory contains a Claude Code skill. To install it:

```sh
cp -R "$(pwd)/skills" ~/.claude/skills/saga
```

- **`saga`** — say **"/saga"** (or "give me a walkthrough of this branch") to generate a
  saga. It resolves the base/head refs and runs the tool for you.
