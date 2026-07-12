"""Unit tests for the pure comments core: sidecar validation and the
GitHub review payload builder. The gh/subprocess paths are side-effectful and
are not unit tested (matching the repo's test-the-pure-core convention)."""

import json

import pytest

from saga.comments import build_review_payload, load_sidecar, read
from saga.model import SagaError

SIDECAR = {
    "branch": "feature",
    "base": "main",
    "generated_at": "2026-07-11T20:03:17Z",
    "overall": "Overall this is solid.",
    "files": {
        "calc.py": {
            "file_comment": "Mixes concerns.",
            "file_anchor": {"line": 1, "side": "RIGHT"},
            "inline": [
                {"line": 2, "side": "RIGHT", "body": "Clarify this comment."},
                {"line": 9, "side": "LEFT", "body": "Why removed?"},
            ],
        }
    },
}


# --- build_review_payload -------------------------------------------------


def test_payload_has_body_and_all_comments():
    payload = build_review_payload(SIDECAR)
    assert payload["body"] == "Overall this is solid."
    # two inline + one file-anchored note
    assert len(payload["comments"]) == 3


def test_payload_never_sets_event_so_review_is_pending():
    payload = build_review_payload(SIDECAR)
    assert "event" not in payload


def test_inline_comments_map_path_line_side_body():
    payload = build_review_payload(SIDECAR)
    inline = [
        c for c in payload["comments"] if not c["body"].startswith("**File-level")
    ]
    assert {
        "path": "calc.py",
        "line": 2,
        "side": "RIGHT",
        "body": "Clarify this comment.",
    } in inline
    assert {
        "path": "calc.py",
        "line": 9,
        "side": "LEFT",
        "body": "Why removed?",
    } in inline


def test_file_comment_anchored_and_prefixed():
    payload = build_review_payload(SIDECAR)
    note = next(c for c in payload["comments"] if c["body"].startswith("**File-level"))
    assert note["path"] == "calc.py"
    assert note["line"] == 1 and note["side"] == "RIGHT"
    assert note["body"] == "**File-level note:** Mixes concerns."


def test_file_comment_without_anchor_defaults_to_line_1():
    sidecar = {"files": {"a.py": {"file_comment": "note"}}}
    note = build_review_payload(sidecar)["comments"][0]
    assert note["line"] == 1 and note["side"] == "RIGHT"


def test_inline_side_defaults_to_right():
    sidecar = {"files": {"a.py": {"inline": [{"line": 5, "body": "x"}]}}}
    assert build_review_payload(sidecar)["comments"][0]["side"] == "RIGHT"


def test_empty_sidecar_yields_empty_payload():
    assert build_review_payload({"files": {}, "overall": ""}) == {}


def test_overall_only_omits_comments():
    payload = build_review_payload({"overall": "just a note", "files": {}})
    assert payload == {"body": "just a note"}


# --- load_sidecar ---------------------------------------------------------


def test_load_sidecar_reads_valid_json(tmp_path):
    p = tmp_path / "saga.comments.json"
    p.write_text(json.dumps(SIDECAR))
    assert load_sidecar(p)["branch"] == "feature"


def test_load_sidecar_missing_file_says_no_comments_yet(tmp_path):
    # push (human-run) surfaces the missing sidecar as friendly guidance.
    with pytest.raises(SagaError, match="no comments yet"):
        load_sidecar(tmp_path / "nope.json")


def test_read_missing_file_emits_empty_json_not_an_error(tmp_path, capsys):
    # read (agent-facing) treats a missing sidecar as "no comments yet".
    rc = read(tmp_path / "nope.json")
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["files"] == {} and data["overall"] is None


def test_load_sidecar_bad_json_raises(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json")
    with pytest.raises(SagaError, match="not valid JSON"):
        load_sidecar(p)


def test_load_sidecar_rejects_non_object(tmp_path):
    p = tmp_path / "arr.json"
    p.write_text("[]")
    with pytest.raises(SagaError, match="must be a JSON object"):
        load_sidecar(p)


def test_load_sidecar_rejects_inline_missing_line(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"files": {"a.py": {"inline": [{"body": "x"}]}}}))
    with pytest.raises(SagaError, match="needs a 'line' and a 'body'"):
        load_sidecar(p)
