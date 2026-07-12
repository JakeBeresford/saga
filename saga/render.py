"""Render a ``Saga`` into one self-contained static HTML file.

Everything is inlined — the design tokens, diff2html's CSS/JS (which bundles
highlight.js), marked, our saga JS, and the saga data itself — so
the output is a single file that opens offline and can be emailed, committed, or
dropped on any static host. The vendored CDN bundles are fetched once and cached
under ``.assets-cache/`` next to the package.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.request import urlopen

from .diff import compute_diff
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


def build_payload(repo_root: Path, saga: Saga, *, qa_state: str = "n/a") -> dict:
    """Attach each chapter's reconstructed diff to the saga for the client.

    The hunk map is recomputed from the live diff of the saga's own
    base...head, so every stored hunk id resolves to its current diff text.
    """
    diff = compute_diff(repo_root, saga.base, saga.branch)
    hmap = {h.id: h for h in parse_hunks(diff.diff_text)}
    chapters = []
    for ch in saga.chapters:
        d = ch.to_dict()
        d["diff"] = reconstruct_diff([hmap[h] for h in ch.hunks if h in hmap])
        chapters.append(d)
    return {
        "branch": saga.branch,
        "base": saga.base,
        "verdict": saga.verdict(qa_state=qa_state),
        "chapters": chapters,
    }


def _json_for_script(payload: dict) -> str:
    """JSON-encode *payload* safe to inline in a ``<script>`` tag.

    Escaping ``<`` to ``\\u003c`` means diff content containing ``</script>`` or
    ``<!--`` cannot break out of the tag.
    """
    return json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")


def render(repo_root: Path, saga: Saga, *, qa_state: str = "n/a") -> str:
    """Build the complete self-contained HTML document for *saga*."""
    payload = build_payload(repo_root, saga, qa_state=qa_state)
    title = f"Saga · {saga.branch}"
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
    <span class="saga-crumb-current">Saga</span>
    <span class="saga-crumb-sep">&rsaquo;</span>
    <span class="mono">{saga.base}...{saga.branch}</span>
  </nav>
  <h1>Saga</h1>
  <div id="saga-verdict" class="saga-verdict"></div>
</div>
<div id="saga-notice"></div>
<div id="saga-toc" class="saga-toc"></div>
<div id="saga-reader" class="saga-reader" hidden></div>
<script>
{scripts}
</script>
</body>
</html>"""
