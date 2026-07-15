"""The embedded comments block — the in-file source of truth for review comments.

A generated saga carries a JSON *envelope* of review comments between two
sentinel comments in the HTML. This module is the only code that reads and
rewrites that block. ``saga serve`` writes to it (autosave); ``saga comments``
reads from it (publish/agent). The write is an atomic, byte-preserving splice:
only the bytes between the sentinels change, so the rest of the self-contained
file is untouched.

Stdlib only — this is part of saga's dependency-free core.

The envelope shape (``schema`` 1)::

    {
      "schema": 1,
      "sagaId": "<hex>",
      "updatedAt": 0,               # ms epoch; max of all child updatedAt
      "overall": {"body": "…", "updatedAt": 0, "deletedAt": null} | null,
      "file":   [{"id", "path", "line", "side", "body", "updatedAt", "deletedAt"}],
      "inline": [{"id", "path", "line", "side", "body", "updatedAt", "deletedAt"}]
    }

``deletedAt`` is a tombstone (non-null ⇒ deleted, kept so a merge cannot
resurrect it). Per-file notes carry a ``line``/``side`` anchor — GitHub's review
API has no file-level comment, so the front end anchors them to the file's first
changed line, exactly as inline comments are anchored.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

SCHEMA = 1

START = "<!--SAGA:COMMENTS:START-->"
END = "<!--SAGA:COMMENTS:END-->"

# Serializes the server's read-modify-write so concurrent autosaves can't
# interleave and lose the block.
_LOCK = threading.Lock()

# window.__sagaData = {…};  — the render-time payload, one line, embedded
# separately from the comments block. Used to recover branch/base for a push.
_SAGA_DATA_RE = re.compile(r"^window\.__sagaData = (.*);$", re.MULTILINE)


class BlockError(Exception):
    """Base error for a malformed or missing embedded block."""


class SentinelsMissing(BlockError):
    """The file has no ``SAGA:COMMENTS`` sentinels — it is not a servable saga."""


def validate_envelope(data: object) -> dict:
    """Light shape check for an envelope, whatever its source (PUT body or a
    hand-written sidecar). Raises ``BlockError`` on an obviously malformed shape.

    Deliberately lenient: it guards the fields the GitHub-push mapper needs
    (``path``/``line`` on inline, ``path`` on file notes) without demanding the
    bookkeeping fields (``id``/``updatedAt``/``deletedAt``) a hand author would
    not write.
    """
    if not isinstance(data, dict):
        raise BlockError("envelope must be a JSON object.")
    for key in ("file", "inline"):
        items = data.get(key, [])
        if not isinstance(items, list):
            raise BlockError(f"'{key}' must be a list.")
        for c in items:
            if not isinstance(c, dict) or "path" not in c or "body" not in c:
                raise BlockError(f"each {key} comment needs a 'path' and a 'body'.")
            if key == "inline" and "line" not in c:
                raise BlockError("each inline comment needs a 'line'.")
    overall = data.get("overall")
    if overall is not None and (not isinstance(overall, dict) or "body" not in overall):
        raise BlockError("'overall' must be null or an object with a 'body'.")
    return data


def empty_envelope(saga_id: str) -> dict:
    """A fresh, comment-free envelope for a newly generated saga."""
    return {
        "schema": SCHEMA,
        "sagaId": saga_id,
        "updatedAt": 0,
        "overall": None,
        "file": [],
        "inline": [],
    }


def _escape(serialized: str) -> str:
    """Escape ``<`` as ``\\u003c`` so a comment body can't close the script tag.

    Applied to the whole serialized JSON; ``<`` only ever appears inside string
    values, and ``\\u003c`` is a valid JSON escape ``json.loads`` decodes back to
    ``<`` — so a body containing ``</script>`` survives a round-trip intact.
    """
    return serialized.replace("<", "\\u003c")


def render_block(envelope: dict) -> str:
    """Build the exact sentinel-wrapped ``<script>`` block for *envelope*.

    The returned string includes both sentinels, so it can be spliced in
    verbatim (``text[:start] + render_block(env) + text[end:]``). ``type=
    "application/json"`` never executes or renders.
    """
    body = _escape(json.dumps(envelope, ensure_ascii=False, indent=2))
    return (
        f"{START}\n"
        f'<script type="application/json" id="saga-comments">\n'
        f"{body}\n"
        f"</script>\n"
        f"{END}"
    )


def extract_envelope(text: str) -> dict:
    """Parse the envelope out of a saga document's HTML text.

    Raises ``SentinelsMissing`` if the block is absent and ``BlockError`` if the
    JSON between the sentinels is unreadable.
    """
    start = text.find(START)
    end = text.find(END)
    if start == -1 or end == -1:
        raise SentinelsMissing("saga comments block sentinels not found.")
    region = text[start:end]
    tag_open_end = region.find(">", region.find("<script"))
    close = region.find("</script>", tag_open_end)
    if tag_open_end == -1 or close == -1:
        raise BlockError("malformed saga comments block.")
    raw = region[tag_open_end + 1 : close]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise BlockError(f"saga comments block is not valid JSON: {e}") from e


def read_envelope(path: str | Path) -> dict:
    """Read and parse the embedded envelope from the saga file at *path*."""
    return extract_envelope(Path(path).read_text(encoding="utf-8"))


def write_envelope(path: str | Path, envelope: dict) -> None:
    """Splice *envelope* into the saga file in place, atomically.

    Holds a process-wide lock for the read-modify-write, preserves every byte
    outside the sentinels, and swaps the file via ``os.replace`` (atomic on
    POSIX and Windows). Raises ``SentinelsMissing`` if the target has no block.
    """
    path = Path(path)
    block = render_block(envelope)
    with _LOCK:
        text = path.read_text(encoding="utf-8")
        start = text.find(START)
        end = text.find(END)
        if start == -1 or end == -1:
            raise SentinelsMissing("saga comments block sentinels not found.")
        spliced = text[:start] + block + text[end + len(END) :]
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(spliced, encoding="utf-8")
        os.replace(tmp, path)


def read_saga_meta(path: str | Path) -> dict:
    """Recover the render-time ``window.__sagaData`` payload from a saga file.

    Comments carry no branch/base of their own, so a GitHub push recovers them
    from the saga's own metadata. Returns ``{}`` if the payload isn't found.
    """
    text = Path(path).read_text(encoding="utf-8")
    m = _SAGA_DATA_RE.search(text)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}
