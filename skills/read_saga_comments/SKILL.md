---
name: saga-comments
description: Read a reviewer's saga comments (inline, per-file, and overall) and act on them in code. Use when the user asks you to address or apply saga review comments, says "read the saga comments" or "/saga-comments", or points at a saga.comments.json file.
---

# Saga comments

A reviewer leaves comments on a saga (the HTML guided tour of a diff) in the browser and
exports them as a `saga.comments.json` sidecar. This skill reads those comments so you can
act on them. The CLI does the reading — your job is to run it, parse the JSON, and address
each comment in code.

## Steps

1. **Check the command is installed.** Run `saga --help`. If it is missing, tell the user
   to install it once (see the tool's README — e.g. `uv tool install saga-cli`), then
   continue.

2. **Locate the sidecar.** It defaults to `saga.comments.json` in the current directory. If
   it lives elsewhere, pass `--comments <path>`. When the user names a saga HTML file, the
   sidecar sits next to it (the reviewer's "Export comments" button downloads it).

3. **Read the comments** from inside the target repo:

   ```sh
   saga comments read --comments saga.comments.json
   ```

   The output is JSON:

   ```json
   {
     "branch": "my-feature",
     "base": "main",
     "overall": "overall review comment, or null",
     "files": {
       "<path>": {
         "file_comment": "per-file note, or null",
         "inline": [ { "line": 88, "side": "RIGHT", "body": "the note" } ]
       }
     }
   }
   ```

   `side` is `RIGHT` (a line in the new/head version of the file) or `LEFT` (a line in the
   old/base version). An empty `files` map with a null `overall` means no comments have been
   authored yet — tell the user and stop.

4. **Act on each comment** as review feedback to resolve:
   - `overall` — the high-level ask; keep it in mind across every change.
   - `file_comment` — a note scoped to the whole file at `<path>`.
   - each `inline` — open `<path>` at `line` (use `side` to know which version the line
     refers to) and address the note there.

5. **Report** what you changed for each comment, and verify (run the tests / relevant
   command) before handing back.

## Notes

- This consumes the local sidecar only — it does **not** fetch from GitHub. Posting the
  comments to a PR is a separate, user-driven action (`saga comments push`).
- If the sidecar exists but is malformed, relay the error (written to stderr).
