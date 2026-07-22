---
title: Library API
nav_order: 7
---

# Library API

Saga is primarily a CLI, but the pipeline it drives — diff → generate → render,
plus the in-HTML comment store — is importable as a library. The names re-exported
from the top-level `saga` package (and listed in its `__all__`) are the
**supported, semver-stable surface**. Everything else under `saga.*` is an
internal detail that may change without notice; import only from `saga` itself.

```python
import saga

diff = saga.compute_diff(repo_root, base="main", ref="my-branch")
saga_obj = saga.generate(diff, base="main", head="my-branch",
                         commit_sha=diff.head_sha, model="claude-cli")
html = saga.render(saga_obj, diff)
```

## Diff

- **`compute_diff(repo_root, base, ref) -> DiffResult`** — diff two refs purely
  from git (`base...ref`, no checkout).
- **`pr_diff(pr) -> PRDiff`** — fetch the same shape from a GitHub PR via the `gh`
  CLI.
- **`DiffResult`** — the computed change set consumed by `generate`/`render`.

## Generate

- **`generate(diff, *, base, head, commit_sha, model, intent=None) -> Saga`** — one
  structured LLM call that partitions the diff into chapters. `model` is a
  `provider/model` string (e.g. `anthropic/claude-...`, `local/...`, or
  `claude-cli` to shell out to the logged-in Claude Code CLI). `intent` is optional
  markdown describing the change's purpose for plan-aware narration. Raises
  `SagaError` on an empty diff, a provider error, or a coverage gap.

## Render

- **`render(saga, diff, file_links=None) -> str`** — build the single
  self-contained HTML page (diff2html + syntax highlighting + `window.__sagaData`
  + an empty comments block with a minted `sagaId`).
- **`build_payload(saga, diff, file_links=None) -> dict`** — the JSON payload
  `render` inlines, exposed for callers that assemble their own page.

## Model

The pure, stdlib-only core.

- **`Saga`**, **`Chapter`**, **`Hunk`** — the persisted dataclasses.
- **`parse_hunks(diff_text) -> list[Hunk]`** — split a unified diff into
  stable-id (`h0, h1, …`) hunks.
- **`reconstruct_diff(hunks) -> str`** — rebuild a valid unified diff for any
  subset of hunks (same anchors as the full view).
- **`validate_coverage(chapters, hunks) -> None`** — enforce the hard invariant
  that every hunk belongs to at least one chapter; raises `SagaError` on a gap.
- **`SagaError`** — the exception raised for anything user-facing across the
  pipeline.

## Comments

Review comments live as a JSON envelope spliced between sentinel comments inside
the saga HTML.

- **`comments_block`** — the module that reads/rewrites that block. Notable
  members: `read_envelope(path)`, `write_envelope(path, envelope)` (atomic
  sentinel splice), `validate_envelope(data)`, `empty_envelope(saga_id)`,
  `render_block(envelope)`, `read_saga_meta(path)`, and the constants `SCHEMA`,
  `START`, `END`.
- **`agent_view(envelope, meta=None) -> dict`** — the tombstone-filtered,
  normalized view of a comment envelope (`{branch, base, overall, file, inline}`)
  suitable for handing to a coding agent.
