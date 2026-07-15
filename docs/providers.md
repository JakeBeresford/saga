---
title: Providers
nav_order: 4
---

# Providers

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

## Local LLMs (Ollama / LM Studio)

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

## Claude Code CLI (no API key)

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
