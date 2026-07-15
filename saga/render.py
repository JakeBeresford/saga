"""Render a ``Saga`` into one self-contained static HTML file.

Everything is inlined — the design tokens, diff2html's CSS/JS (which bundles
highlight.js), marked, our saga JS, and the saga data itself — so
the output is a single file that opens offline and can be emailed, committed, or
dropped on any static host. The vendored CDN bundles are fetched once and cached
under ``.assets-cache/`` next to the package.
"""

from __future__ import annotations

import html
import json
import os
import secrets
from pathlib import Path
from urllib.request import urlopen

from . import block
from .diff import DiffResult
from .model import Saga, parse_hunks, reconstruct_diff

_ASSETS = Path(__file__).resolve().parent / "assets"


def _cache_dir() -> Path:
    """User-level cache for the vendored CDN bundles.

    Uses ``$XDG_CACHE_HOME`` when set, else ``~/.cache`` — never the install dir,
    which may be read-only under site-packages.
    """
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(base) / "saga"


_CACHE = _cache_dir()

_CDN = {
    "diff2html.min.css": "https://cdn.jsdelivr.net/npm/diff2html/bundles/css/diff2html.min.css",
    "diff2html-ui.min.js": "https://cdn.jsdelivr.net/npm/diff2html/bundles/js/diff2html-ui.min.js",
    "marked.min.js": "https://cdn.jsdelivr.net/npm/marked/marked.min.js",
}


def _vendored(name: str) -> str:
    """Return a cached CDN bundle, downloading it once on first use."""
    cached = _CACHE / name
    if not cached.exists():
        _CACHE.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(urlopen(_CDN[name]).read())  # noqa: S310
    return cached.read_text()


def _asset(name: str) -> str:
    return (_ASSETS / name).read_text()


def _diffstat(diff_text: str) -> dict:
    """Files-changed and line counts scanned straight from the unified diff.

    Files are counted by ``diff --git`` headers (so renames/mode-only changes
    still count); added/removed exclude the ``+++``/``---`` file markers.
    """
    files = added = removed = 0
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            files += 1
        elif line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return {"files": files, "added": added, "removed": removed}


def build_payload(saga: Saga, diff: DiffResult, file_links: dict | None = None) -> dict:
    """Attach each chapter's reconstructed diff to the saga for the client.

    The hunk map is built from the same *diff* generation used, so every stored
    hunk id resolves to its diff text — whether the diff came from local git or
    a fetched PR. *file_links* tells the client how to turn each diff file path
    into a link (a local editor/file URL, or a GitHub blob URL); ``None`` leaves
    the paths as plain text.
    """
    hmap = {h.id: h for h in parse_hunks(diff.diff_text)}
    chapters = []
    for ch in saga.chapters:
        d = ch.to_dict()
        d["diff"] = reconstruct_diff([hmap[h] for h in ch.hunks if h in hmap])
        chapters.append(d)
    return {
        "branch": saga.branch,
        "base": saga.base,
        "title": saga.title,
        "summary": saga.summary,
        "commit_sha": saga.commit_sha,
        "generated_at": saga.generated_at,
        "verdict": saga.verdict(),
        "stats": _diffstat(diff.diff_text),
        "file_links": file_links,
        "chapters": chapters,
    }


def _json_for_script(payload: dict) -> str:
    """JSON-encode *payload* safe to inline in a ``<script>`` tag.

    Escaping ``<`` to ``\\u003c`` means diff content containing ``</script>`` or
    ``<!--`` cannot break out of the tag.
    """
    return json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")


def render(saga: Saga, diff: DiffResult, file_links: dict | None = None) -> str:
    """Build the complete self-contained HTML document for *saga*."""
    payload = build_payload(saga, diff, file_links)
    # The comments block is the durable, in-file store review comments live in
    # (rewritten by `saga serve`). Its sagaId — minted once here — is the front
    # end's only source of the id, so it is never injected into __sagaData.
    comments_block = block.render_block(block.empty_envelope(secrets.token_hex(8)))
    title = f"{html.escape(saga.title) or 'Saga'} · {html.escape(saga.branch)}"
    styles = "\n".join(
        [
            _asset("tokens.css"),
            _vendored("diff2html.min.css"),
            _asset("base.css"),
            _asset("saga.css"),
        ]
    )
    scripts = "\n".join(
        [
            _vendored("diff2html-ui.min.js"),
            _vendored("marked.min.js"),
            f"window.__sagaData = {_json_for_script(payload)};",
            _asset("saga-merge.js"),
            _asset("saga.js"),
        ]
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<script>
// Apply the saved theme before first paint so there is no flash.
try {{
  var t = localStorage.getItem('saga-theme');
  if (t === 'light' || t === 'dark') {{
    document.documentElement.setAttribute('data-theme', t);
  }}
}} catch (e) {{}}
</script>
<style>
{styles}
</style>
</head>
<body>
<div class="saga-rail" id="saga-rail"></div>
<div class="header">
  <button id="saga-theme" class="saga-theme-toggle" type="button"
          aria-label="Toggle light or dark theme" title="Toggle theme"></button>
  <nav class="saga-crumbs">
    <span class="mono">{saga.base}...{saga.branch}</span>
  </nav>
  <h1 id="saga-title">Saga</h1>
  <p id="saga-summary" class="saga-summary" hidden></p>
  <div class="saga-statusline">
    <div id="saga-verdict" class="saga-verdict"></div>
    <div id="saga-meta" class="saga-meta"></div>
  </div>
</div>
<div id="saga-notice"></div>
<div id="saga-toc" class="saga-toc"></div>
<div id="saga-reader" class="saga-reader" hidden></div>
{comments_block}
<script>
{scripts}
</script>
</body>
</html>"""
