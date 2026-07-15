"""``saga serve`` — the local writer that persists review comments into the file.

A browser page cannot write to its own file on disk portably (the File System
Access API is Chromium-only), so saga owns a tiny loopback HTTP server that does
it. The server holds **no state of its own**: the saga HTML file is the durable
store (comments live in its embedded block, see ``comments_block.py``), ``localStorage``
is the browser's outage buffer, and the write token lives only in memory.

Security, even though it's local: it binds ``127.0.0.1`` only, validates the
``Host`` and ``Origin`` headers (defeating DNS rebinding), never emits CORS
headers, and requires a per-run token on every write. The token is never written
to disk or into the file.

The port is derived from the ``sagaId`` so the origin is stable across restarts
— ``localStorage`` is origin-scoped (origin includes the port), and a stable
port is what lets the browser's outage buffer survive a restart and flush after
reconnect. If the derived port is taken, the bind scans upward; that rare case
lands on a different origin (see the drift caveat in the spec) and is acceptable
for v1. Everything here is stdlib: ``http.server``, ``hashlib``, ``secrets``.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast

from . import comments_block
from .comments import agent_view, create_github_review
from .diff import repo_root_from
from .model import SagaError

# The IANA dynamic/private port range; the derived port and any upward scan stay
# inside it.
_PORT_LOW = 49152
_PORT_HIGH = 65535


def derive_port(saga_id: str) -> int:
    """Map a ``sagaId`` to a stable primary port in ``[49152, 65535]``.

    Deterministic so the same saga serves from the same origin across restarts —
    the property the outage buffer relies on.
    """
    digest = hashlib.sha256(saga_id.encode()).hexdigest()
    return _PORT_LOW + (int(digest, 16) % (_PORT_HIGH - _PORT_LOW + 1))


class SagaServer(ThreadingHTTPServer):
    """A loopback server bound to exactly one saga file, its id, and a token."""

    def __init__(self, address, handler, *, saga_file: Path, saga_id: str, token: str):
        super().__init__(address, handler)
        self.saga_file = saga_file
        self.saga_id = saga_id
        self.saga_token = token


class _Handler(BaseHTTPRequestHandler):
    """Serves the one saga document and its ``/api/*`` routes (see the spec §6)."""

    # Silence the default per-request stderr logging; the foreground process
    # prints its own concise lines.
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass

    @property
    def _srv(self) -> SagaServer:
        return cast(SagaServer, self.server)

    # --- responses --------------------------------------------------------

    def _send_json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, code: int, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # --- guards -----------------------------------------------------------

    def _guarded(self) -> bool:
        """Enforce loopback Host + matching port and, if present, a same-origin
        ``Origin``. Writes a ``403`` and returns ``False`` on any violation."""
        port = self._srv.server_address[1]
        host = self.headers.get("Host", "")
        hostname, _, host_port = host.rpartition(":")
        if hostname not in ("127.0.0.1", "localhost") or host_port != str(port):
            self._send_json(403, {"error": "bad host"})
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in (
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
        ):
            self._send_json(403, {"error": "bad origin"})
            return False
        return True

    def _token_ok(self) -> bool:
        if self.headers.get("X-Saga-Token") != self._srv.saga_token:
            self._send_json(401, {"error": "bad or missing token"})
            return False
        return True

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    # --- routes -----------------------------------------------------------

    def do_GET(self) -> None:
        if not self._guarded():
            return
        if self.path == "/":
            # Read fresh from disk so a reload always reflects the latest write.
            self._send_html(200, self._srv.saga_file.read_text(encoding="utf-8"))
        elif self.path == "/api/session":
            self._send_json(
                200,
                {
                    "schema": comments_block.SCHEMA,
                    "sagaId": self._srv.saga_id,
                    "token": self._srv.saga_token,
                },
            )
        else:
            self._send_json(404, {"error": "not found"})

    def do_PUT(self) -> None:
        if not self._guarded() or not self._token_ok():
            return
        if self.path != "/api/comments":
            self._send_json(404, {"error": "not found"})
            return
        try:
            data = json.loads(self._read_body())
        except (json.JSONDecodeError, ValueError):
            self._send_json(400, {"error": "invalid JSON"})
            return
        if not isinstance(data, dict) or data.get("sagaId") != self._srv.saga_id:
            self._send_json(409, {"error": "sagaId mismatch"})
            return
        try:
            comments_block.validate_envelope(data)
        except comments_block.BlockError as e:
            self._send_json(400, {"error": str(e)})
            return
        try:
            comments_block.write_envelope(self._srv.saga_file, data)
        except comments_block.SentinelsMissing:
            self._send_json(422, {"error": "comments block sentinels missing"})
            return
        self._send_json(200, {"ok": True, "updatedAt": data.get("updatedAt", 0)})

    def do_POST(self) -> None:
        if not self._guarded() or not self._token_ok():
            return
        if self.path != "/api/publish":
            self._send_json(404, {"error": "not found"})
            return
        try:
            mode = json.loads(self._read_body()).get("mode")
        except (json.JSONDecodeError, ValueError, AttributeError):
            self._send_json(400, {"error": "invalid JSON"})
            return

        envelope = comments_block.read_envelope(self._srv.saga_file)
        meta = comments_block.read_saga_meta(self._srv.saga_file)
        if mode == "github":
            repo_root = repo_root_from(Path.cwd()) or Path.cwd()
            try:
                summary = create_github_review(repo_root, envelope, meta)
            except SagaError as e:
                self._send_json(502, {"error": str(e)})
                return
            self._send_json(200, {"ok": True, "summary": summary})
        elif mode == "agent":
            self._send_json(200, {"ok": True, "comments": agent_view(envelope, meta)})
        else:
            self._send_json(400, {"error": "unknown publish mode"})


def make_server(
    file_path: str | Path, *, port: int | None = None, token: str | None = None
) -> tuple[SagaServer, int, str]:
    """Build (but don't run) the server for *file_path*.

    Reads the sagaId from the file's embedded block (raising ``SagaError`` if it
    isn't a servable saga), mints an in-memory token, and binds loopback on the
    derived port, scanning upward if it's taken. Returns ``(server, port,
    token)``. Split out from ``serve`` so tests can drive it without a TTY.
    """
    file_path = Path(file_path)
    try:
        env = comments_block.read_envelope(file_path)
    except comments_block.SentinelsMissing as e:
        raise SagaError(
            f"{file_path} has no saga comments block — it is not a servable saga."
        ) from e
    except OSError as e:
        raise SagaError(f"could not read {file_path}: {e}") from e

    saga_id = env.get("sagaId") or ""
    if not saga_id:
        raise SagaError(f"{file_path} has no sagaId; regenerate it with this version.")

    token = token or secrets.token_urlsafe(32)
    start = port if port else derive_port(saga_id)
    span = _PORT_HIGH - _PORT_LOW + 1
    for i in range(span):
        candidate = _PORT_LOW + (((start - _PORT_LOW) + i) % span)
        try:
            server = SagaServer(
                ("127.0.0.1", candidate),
                _Handler,
                saga_file=file_path,
                saga_id=saga_id,
                token=token,
            )
        except OSError:
            continue
        return server, candidate, token
    raise SagaError("no free port available in the loopback range.")


def serve(
    file_path: str | Path, *, port: int | None = None, open_browser: bool = True
) -> None:
    """Serve *file_path* in the foreground until ``Ctrl-C`` (clean shutdown)."""
    server, actual_port, _ = make_server(file_path, port=port)
    url = f"http://127.0.0.1:{actual_port}/"
    print(f"serving at {url} — Ctrl-C to stop", file=sys.stderr)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.", file=sys.stderr)
    finally:
        server.server_close()
