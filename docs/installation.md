---
title: Installation
nav_order: 2
---

# Installation

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

To install saga, just install the package from pypi.

```sh
# recommended
uv tool install saga-cli
# or
pipx install saga-cli
# or, into the current environment
pip install saga-cli
```

### Install for development

Installing from a local checkout instead? Point the installer at this directory,
e.g. `uv tool install --editable /path/to/saga`.
To upgrade: `uv tool install --force --editable /path/to/saga`.
