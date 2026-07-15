<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/saga-wordmark-dark.svg">
    <img alt="Saga" src="docs/assets/saga-wordmark-light.svg" width="200">
  </picture>
</p>

<p align="center">
  <a href="https://pypi.org/project/saga-cli/"><img alt="PyPI" src="https://img.shields.io/pypi/v/saga-cli?style=flat-square&color=0e7490"></a>
  <a href="https://pypi.org/project/saga-cli/"><img alt="Python versions" src="https://img.shields.io/pypi/pyversions/saga-cli?style=flat-square&color=0e7490"></a>
  <a href="https://github.com/JakeBeresford/saga/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/JakeBeresford/saga/ci.yml?style=flat-square&label=CI"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-0e7490?style=flat-square"></a>
</p>

Generate a **chapter-by-chapter guided tour** of a code change as a single,
self-contained static HTML page, a _saga_ of your diff. It partitions a diff into
ordered chapters that tell one coherent story, each with a plain-language narration
and just the hunks that belong to it. Large PRs become easy to review without
losing the thread.

The output is one HTML file with everything inlined (diff2html, syntax highlighting,
the data). Open it offline, email it, commit it, or drop it on any static host.

[**See an example saga**](https://jakeberesford.github.io/saga/example.html) · [**Read the announcement**](https://jakeberesford.com/blog/saga) · [**Docs**](https://jakeberesford.github.io/saga/)

## Quickstart

To run saga with no install, diff your current branch with origin/main

```sh
cd your-repo
uvx --from saga-cli saga
```

Or generate a saga from a GitHub PR:

```sh
uvx --from saga-cli saga https://github.com/owner/repo/pull/5
```

## Installation

Using saga regularly? Install it once so the command is just `saga`:
`uv tool install saga-cli` (or `pipx install saga-cli`).

## Documentation

Full docs live at **<https://jakeberesford.github.io/saga/>**:

- [Installation](https://jakeberesford.github.io/saga/installation.html) — requirements and how to install.
- [Usage](https://jakeberesford.github.io/saga/usage.html) — running on a branch or a PR, and every flag.
- [Providers](https://jakeberesford.github.io/saga/providers.html) — Anthropic, OpenAI, OpenRouter, local LLMs, and the Claude Code CLI.
- [Reviewing](https://jakeberesford.github.io/saga/reviewing.html) — leaving comments on a saga and publishing them to GitHub.
- [How it works](https://jakeberesford.github.io/saga/how-it-works.html) — the pipeline, end to end.

Contributing? See [AGENTS.md](AGENTS.md) for the validation gate and architecture.
