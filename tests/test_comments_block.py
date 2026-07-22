"""Unit tests for the embedded comments block: byte-preserving splice, the
``<``-escaping that keeps a comment body from closing the script tag,
idempotence, sentinel validation, and saga-metadata recovery."""

import pytest

from saga import comments_block


def _doc(inner: str) -> str:
    """A minimal saga document wrapping *inner* (a rendered block) in bytes we
    assert are preserved verbatim across a rewrite."""
    return (
        "<!DOCTYPE html>\n<html><body>\n"
        "<div id='saga-reader'></div>\n"
        f"{inner}\n"
        "<script>\n"
        'window.__sagaData = {"branch":"feat"};\n'
        "</script>\n"
        "</body></html>\n"
    )


def test_render_block_round_trips_envelope():
    env = comments_block.empty_envelope("a1b2c3d4")
    text = _doc(comments_block.render_block(env))
    assert comments_block.extract_envelope(text) == env


def test_write_preserves_all_bytes_outside_the_sentinels(tmp_path):
    path = tmp_path / "saga.html"
    path.write_text(
        _doc(comments_block.render_block(comments_block.empty_envelope("deadbeef")))
    )
    before = path.read_text()

    env = comments_block.read_envelope(path)
    env["overall"] = {"body": "looks good", "updatedAt": 5, "deletedAt": None}
    env["updatedAt"] = 5
    comments_block.write_envelope(path, env)

    after = path.read_text()
    # Everything before START and after END is untouched.
    head_before, head_after = (
        before.split(comments_block.START)[0],
        after.split(comments_block.START)[0],
    )
    tail_before = before.split(comments_block.END)[1]
    tail_after = after.split(comments_block.END)[1]
    assert head_before == head_after
    assert tail_before == tail_after
    assert comments_block.read_envelope(path)["overall"]["body"] == "looks good"


def test_body_with_script_close_and_angle_brackets_survives(tmp_path):
    path = tmp_path / "saga.html"
    path.write_text(
        _doc(comments_block.render_block(comments_block.empty_envelope("cafef00d")))
    )

    nasty = "break out </script><b>x</b> and a < b comparison"
    env = comments_block.read_envelope(path)
    env["overall"] = {"body": nasty, "updatedAt": 1, "deletedAt": None}
    comments_block.write_envelope(path, env)

    raw = path.read_text()
    # The literal closing tag must not appear inside the block region.
    region = raw[raw.find(comments_block.START) : raw.find(comments_block.END)]
    assert "</script><b>" not in region
    assert "\\u003c/script>" in region
    # …but it decodes back to the exact original body.
    assert comments_block.read_envelope(path)["overall"]["body"] == nasty


def test_write_is_idempotent(tmp_path):
    path = tmp_path / "saga.html"
    path.write_text(
        _doc(comments_block.render_block(comments_block.empty_envelope("11223344")))
    )
    env = comments_block.read_envelope(path)
    env["inline"] = [
        {
            "id": "c1",
            "path": "a.py",
            "line": 3,
            "side": "RIGHT",
            "body": "x",
            "updatedAt": 2,
            "deletedAt": None,
        }
    ]
    comments_block.write_envelope(path, env)
    once = path.read_text()
    comments_block.write_envelope(path, comments_block.read_envelope(path))
    assert path.read_text() == once


def test_missing_sentinels_raise(tmp_path):
    path = tmp_path / "plain.html"
    path.write_text("<html><body>no block here</body></html>")
    with pytest.raises(comments_block.SentinelsMissing):
        comments_block.read_envelope(path)
    with pytest.raises(comments_block.SentinelsMissing):
        comments_block.write_envelope(path, comments_block.empty_envelope("x"))


def test_extract_rejects_bad_json():
    text = _doc(
        f"{comments_block.START}\n"
        '<script type="application/json" id="saga-comments">\n'
        "{not json}\n</script>\n"
        f"{comments_block.END}"
    )
    with pytest.raises(comments_block.BlockError):
        comments_block.extract_envelope(text)


def test_read_saga_meta_recovers_branch(tmp_path):
    path = tmp_path / "saga.html"
    path.write_text(
        _doc(comments_block.render_block(comments_block.empty_envelope("abcd")))
    )
    assert comments_block.read_saga_meta(path)["branch"] == "feat"


def test_read_saga_meta_missing_returns_empty(tmp_path):
    path = tmp_path / "nometa.html"
    path.write_text("<html></html>")
    assert comments_block.read_saga_meta(path) == {}


# --- validate_envelope: agent-written status/reply ------------------------


def _cmt(**over):
    base = {"id": "c1", "path": "a.py", "line": 3, "side": "RIGHT", "body": "x"}
    base.update(over)
    return base


def test_validate_accepts_agent_status_and_reply():
    env = {
        "overall": {"body": "ok", "status": "addressed", "reply": "fixed it"},
        "file": [_cmt(status="open", reply=None)],
        "inline": [_cmt(status="addressed", reply="done in commit abc")],
    }
    assert comments_block.validate_envelope(env) is env


def test_validate_accepts_comments_without_agent_fields():
    env = {"file": [], "inline": [_cmt()], "overall": {"body": "ok"}}
    assert comments_block.validate_envelope(env) is env


def test_validate_rejects_unknown_status():
    with pytest.raises(comments_block.BlockError, match="status"):
        comments_block.validate_envelope({"inline": [_cmt(status="banana")]})


def test_validate_rejects_non_string_reply():
    with pytest.raises(comments_block.BlockError, match="reply"):
        comments_block.validate_envelope({"inline": [_cmt(reply=5)]})


def test_validate_rejects_bad_status_on_overall():
    with pytest.raises(comments_block.BlockError, match="status"):
        comments_block.validate_envelope({"overall": {"body": "ok", "status": "nope"}})


def test_agent_fields_survive_a_write_round_trip(tmp_path):
    path = tmp_path / "saga.html"
    path.write_text(
        _doc(comments_block.render_block(comments_block.empty_envelope("feedface")))
    )
    env = comments_block.read_envelope(path)
    env["inline"] = [
        {
            "id": "c1",
            "path": "a.py",
            "line": 3,
            "side": "RIGHT",
            "body": "x",
            "updatedAt": 2,
            "deletedAt": None,
            "status": "addressed",
            "reply": "handled",
        }
    ]
    comments_block.write_envelope(path, env)
    back = comments_block.read_envelope(path)["inline"][0]
    assert back["status"] == "addressed"
    assert back["reply"] == "handled"
