"""Unit tests for the pure comments core: the GitHub review payload builder,
the agent view, and envelope resolution from a saga HTML file. The gh/subprocess
paths are side-effectful and are not unit tested (matching the repo's
test-the-pure-core convention)."""

import json

import pytest

from saga import comments_block
from saga.comments import (
    agent_view,
    build_review_payload,
    push,
    read,
    resolve,
)
from saga.model import SagaError


def _rec(id, path, line, side, body, updated=1, deleted=None):
    return {
        "id": id,
        "path": path,
        "line": line,
        "side": side,
        "body": body,
        "updatedAt": updated,
        "deletedAt": deleted,
    }


ENV = {
    "schema": 1,
    "sagaId": "a1b2c3d4",
    "updatedAt": 10,
    "overall": {"body": "Overall this is solid.", "updatedAt": 10, "deletedAt": None},
    "file": [_rec("f1", "calc.py", 1, "RIGHT", "Mixes concerns.")],
    "inline": [
        _rec("i1", "calc.py", 2, "RIGHT", "Clarify this comment."),
        _rec("i2", "calc.py", 9, "LEFT", "Why removed?"),
    ],
}


def _saga_doc(env: dict, branch: str = "feature", base: str = "main") -> str:
    """A saga-shaped document: the embedded block plus a __sagaData line, so
    both the envelope and its branch/base metadata are recoverable."""
    return (
        "<!DOCTYPE html>\n<body>\n"
        f"{comments_block.render_block(env)}\n"
        "<script>\n"
        f'window.__sagaData = {{"branch":"{branch}","base":"{base}"}};\n'
        "</script>\n</body>\n"
    )


# --- build_review_payload -------------------------------------------------


def test_payload_has_body_and_all_comments():
    payload = build_review_payload(ENV)
    assert payload["body"] == "Overall this is solid."
    assert len(payload["comments"]) == 3  # two inline + one file-anchored note


def test_payload_never_sets_event_so_review_is_pending():
    assert "event" not in build_review_payload(ENV)


def test_inline_comments_map_path_line_side_body():
    inline = [
        c
        for c in build_review_payload(ENV)["comments"]
        if not c["body"].startswith("**File-level")
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
    note = next(
        c
        for c in build_review_payload(ENV)["comments"]
        if c["body"].startswith("**File-level")
    )
    assert note["path"] == "calc.py"
    assert note["line"] == 1 and note["side"] == "RIGHT"
    assert note["body"] == "**File-level note:** Mixes concerns."


def test_file_comment_without_anchor_defaults_to_line_1():
    env = {"file": [{"id": "f", "path": "a.py", "body": "note"}], "inline": []}
    note = build_review_payload(env)["comments"][0]
    assert note["line"] == 1 and note["side"] == "RIGHT"


def test_inline_side_defaults_to_right():
    env = {"inline": [{"id": "i", "path": "a.py", "line": 5, "body": "x"}], "file": []}
    assert build_review_payload(env)["comments"][0]["side"] == "RIGHT"


def test_empty_envelope_yields_empty_payload():
    assert build_review_payload(comments_block.empty_envelope("x")) == {}


def test_overall_only_omits_comments():
    env = {
        "overall": {"body": "just a note", "deletedAt": None},
        "file": [],
        "inline": [],
    }
    assert build_review_payload(env) == {"body": "just a note"}


def test_tombstoned_comments_are_skipped():
    env = {
        "overall": {"body": "gone", "deletedAt": 3},
        "file": [_rec("f1", "a.py", 1, "RIGHT", "gone too", deleted=3)],
        "inline": [
            _rec("i1", "a.py", 2, "RIGHT", "kept"),
            _rec("i2", "a.py", 3, "RIGHT", "removed", deleted=4),
        ],
    }
    payload = build_review_payload(env)
    assert "body" not in payload
    assert len(payload["comments"]) == 1
    assert payload["comments"][0]["body"] == "kept"


def test_blank_bodies_are_skipped():
    env = {
        "overall": {"body": "   ", "deletedAt": None},
        "inline": [_rec("i", "a.py", 1, "RIGHT", "  ")],
        "file": [],
    }
    assert build_review_payload(env) == {}


# --- agent_view -----------------------------------------------------------


def test_agent_view_filters_tombstones_and_carries_meta():
    env = {
        "overall": {"body": "keep", "deletedAt": None},
        "file": [_rec("f1", "a.py", 1, "RIGHT", "gone", deleted=2)],
        "inline": [_rec("i1", "a.py", 2, "RIGHT", "keep")],
    }
    view = agent_view(env, {"branch": "feat", "base": "main"})
    assert view["branch"] == "feat" and view["base"] == "main"
    assert view["overall"]["body"] == "keep"
    assert view["file"] == []
    assert len(view["inline"]) == 1


def test_agent_view_drops_deleted_overall():
    env = {"overall": {"body": "gone", "deletedAt": 9}, "file": [], "inline": []}
    assert agent_view(env)["overall"] is None


# --- resolve --------------------------------------------------------------


def test_resolve_reads_envelope_and_meta_from_html(tmp_path):
    path = tmp_path / "saga.html"
    path.write_text(_saga_doc(ENV))
    env, meta = resolve(path)
    assert env["overall"]["body"] == "Overall this is solid."
    assert meta["branch"] == "feature" and meta["base"] == "main"


def test_resolve_missing_html_errors(tmp_path):
    with pytest.raises(SagaError, match="no saga file at"):
        resolve(tmp_path / "nope.html")


def test_resolve_html_without_block_errors(tmp_path):
    path = tmp_path / "plain.html"
    path.write_text("<html>no block</html>")
    with pytest.raises(SagaError, match="not a saga with a comments block"):
        resolve(path)


# --- push / read (no-network paths) ---------------------------------------


def test_push_no_comments_reports_nothing_to_push(tmp_path, capsys):
    path = tmp_path / "saga.html"
    path.write_text(_saga_doc(comments_block.empty_envelope("deadbeef")))
    rc = push(path, tmp_path)
    assert rc == 0
    assert "No comments to push" in capsys.readouterr().err


def test_read_emits_agent_json_from_html(tmp_path, capsys):
    path = tmp_path / "saga.html"
    path.write_text(_saga_doc(ENV))
    rc = read(path)
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["overall"]["body"] == "Overall this is solid."
    assert out["branch"] == "feature"
    assert len(out["inline"]) == 2
