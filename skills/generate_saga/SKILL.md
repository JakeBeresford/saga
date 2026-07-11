---
name: saga
description: Generate a self-contained static HTML saga of a code change — a chapter-by-chapter guided tour of a diff. Use when the user asks for a "saga" or "walkthrough" of a branch/PR, wants to make a large diff easy to review, or says "/saga".
---

# Saga

Generate a chapter-based, guided tour of a git diff as a single static HTML
file. The heavy lifting is done by a script — your job is to resolve the refs and
run it.

## Steps

1. **Check the command is installed.** Run `saga --help`. If it is missing,
   tell the user to install it once (see the tool's README — e.g.
   `uv tool install saga-cli` or `pipx install saga-cli`), then continue.

2. **Resolve base and head.**
   - `head` defaults to the current branch. Use `--head <ref>` only if the user
     names a different branch/commit.
   - `base` defaults to `main`. If the repo's default branch is not `main`
     (check with `git symbolic-ref refs/remotes/origin/HEAD` or ask), pass the
     right one with `--base <ref>`.
   - If the user references a GitHub PR, resolve it to its base and head branches
     (e.g. via `gh pr view <n> --json baseRefName,headRefName`) and pass those.

3. **Optional intent.** If the user points at a plan/spec/design doc describing what
   the change was meant to do, pass it with `--intent <path>` for richer, plan-aware
   narration (it lets the saga flag deviations from intent).

4. **Run it** from inside the target repo:

   ```sh
   saga --base <base> --head <head> -o saga.html --open
   ```

   Requires `git` and an API key for the chosen provider (`ANTHROPIC_API_KEY`,
   `OPENAI_API_KEY`, or `OPENROUTER_API_KEY`). The model defaults to
   `anthropic/claude-opus-4-8`; override with `--model <provider/model>` or the
   `SAGA_MODEL` env var. Generation runs one LLM call and can take a minute on
   a large diff.

5. **Report** the output path (`saga.html`) and the chapter count printed on
   stderr. The file is fully self-contained — it can be opened offline, emailed, or
   hosted anywhere.

## Reading review comments

If the user has reviewed a saga in the browser and exported a `saga.comments.json`
sidecar, read their comments as JSON with:

```sh
saga comments read --comments saga.comments.json
```

The output is `{branch, base, overall, files: {<path>: {file_comment, inline: [{line, side, body}]}}}`
— use it to act on the reviewer's inline / per-file / overall feedback. (`saga comments push`
posts the same comments to the PR as a pending GitHub review; that is the user's action, not
yours, unless they ask.)

## Notes

- If generation fails (e.g. empty diff, missing API key, coverage gap), relay the
  error message to the user; it is written to stderr.
