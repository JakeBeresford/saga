"""Unit tests for the embedded comments block: byte-preserving splice, the
``<``-escaping that keeps a comment body from closing the script tag,
idempotence, sentinel validation, and saga-metadata recovery."""

import pytest

from saga import block


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
    env = block.empty_envelope("a1b2c3d4")
    text = _doc(block.render_block(env))
    assert block.extract_envelope(text) == env


def test_write_preserves_all_bytes_outside_the_sentinels(tmp_path):
    path = tmp_path / "saga.html"
    path.write_text(_doc(block.render_block(block.empty_envelope("deadbeef"))))
    before = path.read_text()

    env = block.read_envelope(path)
    env["overall"] = {"body": "looks good", "updatedAt": 5, "deletedAt": None}
    env["updatedAt"] = 5
    block.write_envelope(path, env)

    after = path.read_text()
    # Everything before START and after END is untouched.
    head_before, head_after = before.split(block.START)[0], after.split(block.START)[0]
    tail_before = before.split(block.END)[1]
    tail_after = after.split(block.END)[1]
    assert head_before == head_after
    assert tail_before == tail_after
    assert block.read_envelope(path)["overall"]["body"] == "looks good"


def test_body_with_script_close_and_angle_brackets_survives(tmp_path):
    path = tmp_path / "saga.html"
    path.write_text(_doc(block.render_block(block.empty_envelope("cafef00d"))))

    nasty = "break out </script><b>x</b> and a < b comparison"
    env = block.read_envelope(path)
    env["overall"] = {"body": nasty, "updatedAt": 1, "deletedAt": None}
    block.write_envelope(path, env)

    raw = path.read_text()
    # The literal closing tag must not appear inside the block region.
    region = raw[raw.find(block.START) : raw.find(block.END)]
    assert "</script><b>" not in region
    assert "\\u003c/script>" in region
    # …but it decodes back to the exact original body.
    assert block.read_envelope(path)["overall"]["body"] == nasty


def test_write_is_idempotent(tmp_path):
    path = tmp_path / "saga.html"
    path.write_text(_doc(block.render_block(block.empty_envelope("11223344"))))
    env = block.read_envelope(path)
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
    block.write_envelope(path, env)
    once = path.read_text()
    block.write_envelope(path, block.read_envelope(path))
    assert path.read_text() == once


def test_missing_sentinels_raise(tmp_path):
    path = tmp_path / "plain.html"
    path.write_text("<html><body>no block here</body></html>")
    with pytest.raises(block.SentinelsMissing):
        block.read_envelope(path)
    with pytest.raises(block.SentinelsMissing):
        block.write_envelope(path, block.empty_envelope("x"))


def test_extract_rejects_bad_json():
    text = _doc(
        f"{block.START}\n"
        '<script type="application/json" id="saga-comments">\n'
        "{not json}\n</script>\n"
        f"{block.END}"
    )
    with pytest.raises(block.BlockError):
        block.extract_envelope(text)


def test_read_saga_meta_recovers_branch(tmp_path):
    path = tmp_path / "saga.html"
    path.write_text(_doc(block.render_block(block.empty_envelope("abcd"))))
    assert block.read_saga_meta(path)["branch"] == "feat"


def test_read_saga_meta_missing_returns_empty(tmp_path):
    path = tmp_path / "nometa.html"
    path.write_text("<html></html>")
    assert block.read_saga_meta(path) == {}
