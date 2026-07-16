---
title: Reviewing
nav_order: 5
---

# Reviewing: comments

The saga page is also a lightweight review surface. Leave three kinds of comments

- **inline** (click a line's number in any chapter's diff),
- **per-file** (the "💬 File comment" control in each file header)
- **overall** review comment (the box on the "Wrap up" page).

Comments live **inside the HTML file**, in an embedded block that `saga serve` rewrites in place. That keeps the file a single portable artifact: you can commit it, email it, or open it offline, and the comments travel with it and reload every time. No server needed to _read_ them.

## Open through `saga serve`

Saving comments back into the file needs a local process (a browser can't write to its own file — the File System Access API is Chromium-only, so Safari and Firefox can't).
So an interactive `saga` run **auto-starts a local server** and opens the saga through it:

```
serving at http://127.0.0.1:52345/ — Ctrl-C to stop
```

On that page, edits **autosave into the file** within a second (a status pill shows
`Saved` / `Saving…` / `Reconnecting…`), and two buttons appear:

- **Publish to GitHub**: posts everything as a single **pending** review via the `gh`
  CLI (inline → line comments, per-file → a note anchored to the file's first changed
  line, overall → the review body). Nothing is submitted until you review and submit it on
  GitHub. Requires the [`gh`](https://cli.github.com) CLI, authenticated.
- **Copy for agent**: copies the comments as JSON for a coding agent to act on.

To serve a saga you generated earlier (or received), point `saga serve` at it:

```sh
saga serve ./saga.html
```

The server is loopback-only (`127.0.0.1`), holds no state of its own (the file is the
store), and needs no API key. Stop it with `Ctrl-C`.

## Static mode (no server)

If you open a saga as a bare `file://` — double-clicked, emailed, committed — there is no
server, so **reading works but drafting is browser-only**: a banner appears and the pill
reads `Draft (this browser only)`. Your drafts buffer in that browser's `localStorage`.

**Reopen the file through `saga serve` _before_ commenting** to save into the file and
publish. Drafts made on a bare `file://` page live under a different browser origin than
the served page and cannot be recovered by serving later — so serve is the front door.

## From the command line / a coding agent

The same publish/read paths are available as commands that read the file's embedded block:

```sh
# Post the comments as a single PENDING review (you submit it on GitHub).
saga comments push path/to/saga.html

# Emit the comments as JSON on stdout for a coding agent to act on.
saga comments read path/to/saga.html
```

Both default to `./saga.html`.
