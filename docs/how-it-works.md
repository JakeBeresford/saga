---
title: How it works
nav_order: 6
---

# How it works

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
