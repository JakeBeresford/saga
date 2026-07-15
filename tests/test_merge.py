"""Unit tests for the front-end merge (assets/saga-merge.js): last-write-wins by
updatedAt, tombstone survival, and offline-draft precedence. The module is pure
and DOM-free, so it runs under node; the whole file skips if node is absent."""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_MERGE_JS = Path(__file__).resolve().parent.parent / "saga" / "assets" / "saga-merge.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node not available"
)


def _run_merge(file_state: dict, buffer, saga_id: str = "sid") -> dict:
    """Run mergeEnvelope(file_state, buffer, saga_id) in node and return the result."""
    script = textwrap.dedent(f"""
        const M = require({json.dumps(str(_MERGE_JS))});
        const out = M.mergeEnvelope(
            {json.dumps(file_state)}, {json.dumps(buffer)}, {json.dumps(saga_id)}
        );
        process.stdout.write(JSON.stringify(out));
    """)
    proc = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(proc.stdout)


def _inline(id, body, updated, deleted=None):
    return {
        "id": id,
        "path": "a.py",
        "line": 1,
        "side": "RIGHT",
        "body": body,
        "updatedAt": updated,
        "deletedAt": deleted,
    }


def test_buffer_only_when_file_is_empty():
    file_state = {"overall": None, "file": [], "inline": []}
    buffer = {"overall": None, "file": [], "inline": [_inline("c1", "draft", 5)]}
    out = _run_merge(file_state, buffer)
    assert [c["body"] for c in out["inline"]] == ["draft"]
    assert out["sagaId"] == "sid"
    assert out["updatedAt"] == 5


def test_newer_record_wins_regardless_of_source():
    # Same id in both; the file copy is newer and must win.
    file_state = {"overall": None, "file": [], "inline": [_inline("c1", "new", 10)]}
    buffer = {"overall": None, "file": [], "inline": [_inline("c1", "old", 2)]}
    out = _run_merge(file_state, buffer)
    assert len(out["inline"]) == 1
    assert out["inline"][0]["body"] == "new"


def test_offline_draft_not_clobbered_by_older_file_copy():
    file_state = {"overall": None, "file": [], "inline": [_inline("c1", "old", 2)]}
    buffer = {"overall": None, "file": [], "inline": [_inline("c1", "draft", 9)]}
    out = _run_merge(file_state, buffer)
    assert out["inline"][0]["body"] == "draft"


def test_tombstone_survives_and_is_not_resurrected():
    # File still has the live comment; buffer tombstoned it later.
    file_state = {"overall": None, "file": [], "inline": [_inline("c1", "live", 3)]}
    buffer = {
        "overall": None,
        "file": [],
        "inline": [_inline("c1", "live", 8, deleted=8)],
    }
    out = _run_merge(file_state, buffer)
    assert out["inline"][0]["deletedAt"] == 8


def test_overall_merges_by_updated_at():
    file_state = {
        "overall": {"body": "file", "updatedAt": 4, "deletedAt": None},
        "file": [],
        "inline": [],
    }
    buffer = {
        "overall": {"body": "buffer", "updatedAt": 7, "deletedAt": None},
        "file": [],
        "inline": [],
    }
    out = _run_merge(file_state, buffer)
    assert out["overall"]["body"] == "buffer"
    assert out["updatedAt"] == 7


def test_union_keeps_records_unique_to_each_side():
    file_state = {"overall": None, "file": [], "inline": [_inline("a", "fromfile", 1)]}
    buffer = {"overall": None, "file": [], "inline": [_inline("b", "frombuffer", 1)]}
    out = _run_merge(file_state, buffer)
    ids = sorted(c["id"] for c in out["inline"])
    assert ids == ["a", "b"]


def test_absent_buffer_returns_file_state():
    file_state = {"overall": None, "file": [], "inline": [_inline("c1", "only", 3)]}
    out = _run_merge(file_state, None)
    assert out["inline"][0]["body"] == "only"
    assert out["updatedAt"] == 3
