"""Tests for HTML rendering: payload assembly, script-safe JSON escaping, the
self-contained document shell, and the vendored-asset cache."""

from pathlib import Path

import pytest

import saga.render as render_mod
from saga.model import Chapter, Saga


def _saga_for(git_repo_branch: str = "feature") -> Saga:
    """A saga whose hunk ids match the git_repo fixture's three-hunk diff."""
    return Saga(
        branch=git_repo_branch,
        base="main",
        commit_sha="deadbeef",
        chapters=[
            Chapter(
                id="c1",
                title="Edit foo",
                summary="s",
                narration="n",
                hunks=["h0", "h1"],
            ),
            Chapter(
                id="c2", title="Add file", summary="s", narration="n", hunks=["h2"]
            ),
        ],
    )


@pytest.fixture
def stub_vendored(monkeypatch):
    """Replace CDN downloads with tiny stubs so document-assembly tests stay
    offline. Requested only by the tests that call ``render()``."""
    monkeypatch.setattr(render_mod, "_vendored", lambda name: f"/* {name} */")


def test_build_payload_attaches_reconstructed_diffs(git_repo: Path):
    payload = render_mod.build_payload(git_repo, _saga_for())

    assert payload["branch"] == "feature"
    assert payload["base"] == "main"
    assert payload["verdict"]["chapters"] == 2

    chapters = payload["chapters"]
    assert len(chapters) == 2
    # c1 covers the two foo.py hunks; its diff is real reconstructed unified diff.
    assert "diff --git a/foo.py b/foo.py" in chapters[0]["diff"]
    assert "+B" in chapters[0]["diff"]
    # c2 covers only the new file.
    assert "diff --git a/new.txt b/new.txt" in chapters[1]["diff"]
    assert "foo.py" not in chapters[1]["diff"]


def test_build_payload_skips_unknown_hunk_ids(git_repo: Path):
    """A chapter referencing a hunk id absent from the live diff must not crash;
    the unknown id is simply dropped from the reconstructed diff."""
    saga = _saga_for()
    saga.chapters[0].hunks = ["h0", "h99"]
    payload = render_mod.build_payload(git_repo, saga)
    assert "h99" not in payload["chapters"][0]["diff"]
    assert "diff --git a/foo.py" in payload["chapters"][0]["diff"]


def test_render_produces_self_contained_document(git_repo: Path, stub_vendored):
    html = render_mod.render(git_repo, _saga_for())

    assert html.startswith("<!DOCTYPE html>")
    assert "<title>Saga · feature</title>" in html
    # Inlined stubs for every vendored bundle and asset.
    assert "/* diff2html.min.css */" in html
    assert "/* diff2html-ui.min.js */" in html
    assert "/* marked.min.js */" in html
    # Saga data is embedded as a JS global.
    assert "window.__sagaData =" in html
    # base...head crumb.
    assert "main...feature" in html


def test_render_escapes_angle_brackets_in_payload(
    git_repo: Path, monkeypatch, stub_vendored
):
    """A diff containing ``</script>`` must be escaped so it cannot break out of
    the inlined ``<script>`` tag."""

    def fake_payload(repo_root, saga, *, qa_state="n/a"):
        return {
            "branch": "b",
            "base": "m",
            "verdict": {},
            "chapters": [{"diff": "</script><b>x"}],
        }

    monkeypatch.setattr(render_mod, "build_payload", fake_payload)
    html = render_mod.render(git_repo, _saga_for())
    assert "</script><b>" not in html
    assert "\\u003c/script>" in html


def test_json_for_script_escapes_all_left_angle_brackets():
    out = render_mod._json_for_script({"k": "a<b<c"})
    assert "<" not in out
    assert out.count("\\u003c") == 2


def test_vendored_downloads_once_and_caches(tmp_path, monkeypatch):
    """_vendored fetches a bundle on first call, caches it, and serves the cache
    without a second network hit."""
    monkeypatch.setattr(render_mod, "_CACHE", tmp_path / "cache")

    calls = []

    class FakeResp:
        def read(self):
            return b"CDN-BYTES"

    def fake_urlopen(url):
        calls.append(url)
        return FakeResp()

    monkeypatch.setattr(render_mod, "urlopen", fake_urlopen)

    first = render_mod._vendored("marked.min.js")
    second = render_mod._vendored("marked.min.js")

    assert first == second == "CDN-BYTES"
    assert len(calls) == 1  # cached on the second call
    assert (tmp_path / "cache" / "marked.min.js").read_bytes() == b"CDN-BYTES"


def test_cache_dir_respects_xdg(monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", "/custom/cache")
    assert render_mod._cache_dir() == Path("/custom/cache/saga")


def test_cache_dir_defaults_to_home(monkeypatch):
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr(
        render_mod.Path, "home", classmethod(lambda cls: Path("/home/u"))
    )
    assert render_mod._cache_dir() == Path("/home/u/.cache/saga")
