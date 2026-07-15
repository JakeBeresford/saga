"""Tests for ``saga serve``: port derivation, the request guards (403/401/409/
422), the session/comments endpoints, and a serve→PUT→reopen round trip plus a
server-restart flush. The server is driven directly over loopback (no TTY, no
auto-serve), matching the spec's T8 acceptance."""

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import pytest

from saga import comments_block, serve
from saga.model import SagaError


def _saga_doc(env: dict) -> str:
    return (
        "<!DOCTYPE html>\n<body>\n<div id='saga-reader'></div>\n"
        f"{comments_block.render_block(env)}\n"
        "<script>\n"
        'window.__sagaData = {"branch":"feature","base":"main"};\n'
        "</script>\n</body>\n"
    )


@pytest.fixture
def saga_file(tmp_path: Path) -> Path:
    path = tmp_path / "saga.html"
    path.write_text(_saga_doc(comments_block.empty_envelope("a1b2c3d4e5f6a7b8")))
    return path


@contextmanager
def _running(path: Path):
    """Start the server in a background thread and yield (base_url, token)."""
    server, port, token = serve.make_server(path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", port, token
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _request(url, *, method="GET", body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read() or "null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or "null")


# --- port derivation ------------------------------------------------------


def test_derive_port_is_deterministic_and_in_range():
    a = serve.derive_port("a1b2c3d4e5f6a7b8")
    b = serve.derive_port("a1b2c3d4e5f6a7b8")
    assert a == b
    assert 49152 <= a <= 65535


def test_derive_port_varies_by_saga_id():
    assert serve.derive_port("aaaa") != serve.derive_port("bbbb")


# --- make_server ----------------------------------------------------------


def test_make_server_rejects_a_file_without_a_block(tmp_path):
    plain = tmp_path / "plain.html"
    plain.write_text("<html>no block</html>")
    with pytest.raises(SagaError):
        serve.make_server(plain)


def test_make_server_uses_derived_port_when_free(saga_file):
    server, port, _ = serve.make_server(saga_file)
    try:
        assert port == serve.derive_port("a1b2c3d4e5f6a7b8")
    finally:
        server.server_close()


# --- endpoints & guards ---------------------------------------------------


def test_session_returns_saga_id_and_token(saga_file):
    with _running(saga_file) as (base, port, token):
        status, body = _request(
            f"{base}/api/session", headers={"Host": f"127.0.0.1:{port}"}
        )
        assert status == 200
        assert body["sagaId"] == "a1b2c3d4e5f6a7b8"
        assert body["token"] == token


def test_get_root_serves_the_file_fresh(saga_file):
    with _running(saga_file) as (base, port, _):
        req = urllib.request.Request(f"{base}/", headers={"Host": f"127.0.0.1:{port}"})
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            assert "SAGA:COMMENTS:START" in resp.read().decode()


def test_bad_origin_is_rejected_403(saga_file):
    with _running(saga_file) as (base, port, _):
        status, _ = _request(
            f"{base}/api/session",
            headers={"Host": f"127.0.0.1:{port}", "Origin": "http://evil.example"},
        )
        assert status == 403


def test_bad_host_is_rejected_403(saga_file):
    with _running(saga_file) as (base, port, _):
        status, _ = _request(f"{base}/api/session", headers={"Host": "evil.example"})
        assert status == 403


def test_put_without_token_is_rejected_401(saga_file):
    with _running(saga_file) as (base, port, _):
        env = comments_block.read_envelope(saga_file)
        status, _ = _request(
            f"{base}/api/comments",
            method="PUT",
            body=env,
            headers={"Host": f"127.0.0.1:{port}"},
        )
        assert status == 401


def test_put_with_wrong_saga_id_is_rejected_409(saga_file):
    with _running(saga_file) as (base, port, token):
        env = comments_block.empty_envelope("wrong-id")
        status, _ = _request(
            f"{base}/api/comments",
            method="PUT",
            body=env,
            headers={"Host": f"127.0.0.1:{port}", "X-Saga-Token": token},
        )
        assert status == 409


def test_put_with_invalid_json_is_rejected_400(saga_file):
    with _running(saga_file) as (base, port, token):
        req = urllib.request.Request(
            f"{base}/api/comments",
            data=b"{not json",
            method="PUT",
            headers={"Host": f"127.0.0.1:{port}", "X-Saga-Token": token},
        )
        try:
            urllib.request.urlopen(req)
            raise AssertionError("expected 400")
        except urllib.error.HTTPError as e:
            assert e.code == 400


def test_put_to_a_file_missing_sentinels_is_422(saga_file):
    with _running(saga_file) as (base, port, token):
        # Simulate the block being stripped out from under the server.
        saga_file.write_text("<html>no block anymore</html>")
        env = comments_block.empty_envelope("a1b2c3d4e5f6a7b8")
        status, _ = _request(
            f"{base}/api/comments",
            method="PUT",
            body=env,
            headers={"Host": f"127.0.0.1:{port}", "X-Saga-Token": token},
        )
        assert status == 422


def test_put_updates_the_file_and_reopen_sees_it(saga_file):
    with _running(saga_file) as (base, port, token):
        env = comments_block.read_envelope(saga_file)
        env["inline"] = [
            {
                "id": "c1",
                "path": "a.py",
                "line": 3,
                "side": "RIGHT",
                "body": "needs a docstring",
                "updatedAt": 111,
                "deletedAt": None,
            }
        ]
        env["updatedAt"] = 111
        status, body = _request(
            f"{base}/api/comments",
            method="PUT",
            body=env,
            headers={"Host": f"127.0.0.1:{port}", "X-Saga-Token": token},
        )
        assert status == 200 and body["updatedAt"] == 111

    # Reopen from disk: the comment is now part of the file.
    reopened = comments_block.read_envelope(saga_file)
    assert reopened["inline"][0]["body"] == "needs a docstring"


def test_restart_with_new_token_still_flushes(saga_file):
    # First session writes one comment, then "crashes".
    with _running(saga_file) as (base, port, token):
        env = comments_block.read_envelope(saga_file)
        env["overall"] = {"body": "first", "updatedAt": 1, "deletedAt": None}
        _request(
            f"{base}/api/comments",
            method="PUT",
            body=env,
            headers={"Host": f"127.0.0.1:{port}", "X-Saga-Token": token},
        )

    # A fresh server mints a new token; the buffered envelope flushes under it.
    with _running(saga_file) as (base, port, token2):
        env = comments_block.read_envelope(saga_file)
        env["overall"] = {"body": "second", "updatedAt": 2, "deletedAt": None}
        status, _ = _request(
            f"{base}/api/comments",
            method="PUT",
            body=env,
            headers={"Host": f"127.0.0.1:{port}", "X-Saga-Token": token2},
        )
        assert status == 200
    assert comments_block.read_envelope(saga_file)["overall"]["body"] == "second"


def test_publish_agent_returns_the_envelope(saga_file):
    env = comments_block.read_envelope(saga_file)
    env["inline"] = [
        {
            "id": "c1",
            "path": "a.py",
            "line": 3,
            "side": "RIGHT",
            "body": "hi",
            "updatedAt": 1,
            "deletedAt": None,
        }
    ]
    comments_block.write_envelope(saga_file, env)
    with _running(saga_file) as (base, port, token):
        status, body = _request(
            f"{base}/api/publish",
            method="POST",
            body={"mode": "agent"},
            headers={"Host": f"127.0.0.1:{port}", "X-Saga-Token": token},
        )
        assert status == 200
        assert body["comments"]["inline"][0]["body"] == "hi"
        assert body["comments"]["branch"] == "feature"
