"""Orchestrate Chapter Video rendering via the bundled Remotion project.

Calls ``saga/remotion/render.mjs`` as a subprocess. Node.js (>=18) must be
installed. npm dependencies are auto-installed on first use. The Remotion
renderer downloads a Chromium binary on first use (~100 MB, cached).

All failures are non-fatal: a chapter with no video is still rendered
correctly; the HTML simply omits the video element for that chapter.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .diff import DiffResult
from .model import Saga, parse_hunks, reconstruct_diff

# remotion/ lives inside the saga package so it's included in the installed wheel.
_REMOTION_DIR = Path(__file__).resolve().parent / "remotion"
_RENDER_SCRIPT = _REMOTION_DIR / "render.mjs"


def _warn(msg: str) -> None:
    print(f"  warning: {msg}", file=sys.stderr)


def _node_available() -> bool:
    try:
        r = subprocess.run(["node", "--version"], capture_output=True, timeout=10)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        _warn("Node.js not found — install Node.js >=18 to enable video generation.")
        return False


def _ensure_deps() -> bool:
    """Run ``npm install`` if ``node_modules`` is absent. Return True on success."""
    if not _REMOTION_DIR.exists():
        _warn(f"Remotion project not found at {_REMOTION_DIR}")
        return False
    if (_REMOTION_DIR / "node_modules").exists():
        return True
    print("  Installing Remotion dependencies (first run only)…", file=sys.stderr)
    try:
        r = subprocess.run(
            ["npm", "install"],
            cwd=_REMOTION_DIR,
            capture_output=True,
            timeout=300,
        )
        if r.returncode != 0:
            _warn(f"npm install failed:\n{r.stderr.decode(errors='replace')}")
            return False
        return True
    except FileNotFoundError:
        _warn("npm not found — install Node.js >=18 to enable video generation.")
        return False
    except subprocess.TimeoutExpired:
        _warn("npm install timed out.")
        return False


def render_videos(
    saga: Saga,
    diff: DiffResult,
    videos_dir: Path,
    *,
    model: str,
) -> dict[str, str]:
    """Render a Chapter Video for each chapter in *saga*.

    Returns ``{chapter_id: relative_path}`` for every chapter that
    rendered successfully (e.g. ``{"ch1": "saga-videos/ch1.mp4"}``).
    Chapters that fail are silently omitted.
    """
    if not _node_available():
        return {}
    if not _ensure_deps():
        return {}

    videos_dir.mkdir(parents=True, exist_ok=True)

    hmap = {h.id: h for h in parse_hunks(diff.diff_text)}

    chapters_payload = [
        {
            "id": ch.id,
            "title": ch.title,
            "narration": ch.narration,
            "confidence": ch.confidence,
            "diff": reconstruct_diff([hmap[h] for h in ch.hunks if h in hmap]),
        }
        for ch in saga.chapters
    ]

    # Use the saga model for video generation if it's Anthropic; else fall back.
    env = {**os.environ, "OUTPUT_DIR": str(videos_dir)}
    if model.startswith("anthropic/"):
        env["SAGA_VIDEO_MODEL"] = model.split("/", 1)[1]
    else:
        env["SAGA_VIDEO_MODEL"] = "claude-opus-4-8"

    try:
        result = subprocess.run(
            ["node", str(_RENDER_SCRIPT)],
            input=json.dumps(chapters_payload).encode(),
            stdout=subprocess.PIPE,
            # Inherit stderr so Remotion's progress messages reach the terminal.
            timeout=600,
            env=env,
        )
    except subprocess.TimeoutExpired:
        _warn("Video render timed out after 10 minutes.")
        return {}
    except OSError as e:
        _warn(f"Failed to launch node: {e}")
        return {}

    if result.returncode != 0:
        _warn(f"render.mjs exited with code {result.returncode}")
        return {}

    if not result.stdout:
        _warn("render.mjs produced no output")
        return {}

    try:
        rendered: dict[str, str] = json.loads(result.stdout)
    except (ValueError, TypeError) as e:
        _warn(f"Could not parse render output: {e}")
        return {}

    # Return paths relative to the HTML file's directory (its sibling directory).
    return {
        chapter_id: f"{videos_dir.name}/{filename}"
        for chapter_id, filename in rendered.items()
    }
