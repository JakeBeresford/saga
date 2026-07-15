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
   saga --base <base> --head <head> -o saga.html --no-serve --open
   ```

   Requires `git` and an API key for the chosen provider (`ANTHROPIC_API_KEY`,
   `OPENAI_API_KEY`, or `OPENROUTER_API_KEY`). The model defaults to
   `anthropic/claude-opus-4-8`; override with `--model <provider/model>` or the
   `SAGA_MODEL` env var. Generation runs one LLM call and can take a minute on
   a large diff.

   Pass `--no-serve` so the command writes the file and exits. Without it, an
   interactive `saga` run stays in the foreground serving the file (so a reviewer's
   comments save back into it); `--no-serve` is the right choice when running the
   tool on the user's behalf.

5. **Report** the output path (`saga.html`) and the chapter count printed on
   stderr. The file is fully self-contained — it can be opened offline, emailed, or
   hosted anywhere.

   If the user wants to leave review comments, tell them to open the file through
   the server so comments persist into it and can be published:

   ```sh
   saga serve ./saga.html
   ```

## Notes

- If generation fails (e.g. empty diff, missing API key, coverage gap), relay the
  error message to the user; it is written to stderr.
- To act on a reviewer's comments, read them straight from the file:
  `saga comments read ./saga.html` (JSON on stdout), or
  `saga comments push ./saga.html` to post them as a pending GitHub review.
