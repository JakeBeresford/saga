---
title: Home
nav_order: 1
---

# Saga

Generate a **chapter-by-chapter guided tour** of a code change as a single,
self-contained static HTML page, a _saga_ of your diff. It partitions a diff into
ordered chapters that tell one coherent story, each with a plain-language narration
and just the hunks that belong to it. Large PRs become easy to review without
losing the thread.

The output is one HTML file with everything inlined (diff2html, syntax highlighting,
the data). Open it offline, email it, commit it, or drop it on any static host.

[**See an example saga**](example.html){: .btn .btn-primary }
[Read the announcement](https://jakeberesford.com/blog/saga){: .btn }

## Quickstart

```sh
cd your-repo
uvx --from saga-cli saga
```

That runs saga with no install and opens a saga of the current branch against
its default base. Using it regularly? `uv tool install saga-cli` so the command
is just `saga`. See [Installation]({% link installation.md %}) and
[Usage]({% link usage.md %}) for the details.

## Documentation

- [Installation]({% link installation.md %}) — requirements and how to install.
- [Usage]({% link usage.md %}) — running saga on a branch or a GitHub PR, and every flag.
- [Providers]({% link providers.md %}) — Anthropic, OpenAI, OpenRouter, local LLMs, and the Claude Code CLI.
- [Reviewing]({% link reviewing.md %}) — leaving comments on a saga and publishing them to GitHub.
- [How it works]({% link how-it-works.md %}) — the pipeline, end to end.
