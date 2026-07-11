"""Unit tests for the pure saga model: hunk parsing, diff reconstruction,
and the coverage invariant."""

import pytest

from saga.model import (
    Chapter,
    Saga,
    SagaError,
    parse_hunks,
    reconstruct_diff,
    validate_coverage,
)

# A two-file diff: the first file has two hunks, the second is a new file.
TWO_FILE_DIFF = """\
diff --git a/foo.py b/foo.py
index 1111111..2222222 100644
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,3 @@
 a
-b
+B
 c
@@ -10,2 +10,3 @@
 x
+y
 z
diff --git a/new.txt b/new.txt
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/new.txt
@@ -0,0 +1,2 @@
+hello
+world
"""


def test_parse_hunks_ids_and_files():
    hunks = parse_hunks(TWO_FILE_DIFF)
    assert [h.id for h in hunks] == ["h0", "h1", "h2"]
    assert [h.file_path for h in hunks] == ["foo.py", "foo.py", "new.txt"]
    # Each foo.py hunk shares the same preamble; new.txt has its own.
    assert hunks[0].preamble == hunks[1].preamble
    assert hunks[2].preamble != hunks[0].preamble
    assert hunks[0].body.startswith("@@ -1,3 +1,3 @@")
    assert hunks[2].body.startswith("@@ -0,0 +1,2 @@")


def test_new_file_path_uses_new_side():
    """A new file's path must come from ``+++ b/…``, not the ``/dev/null`` old side."""
    hunks = parse_hunks(TWO_FILE_DIFF)
    assert hunks[2].file_path == "new.txt"


def test_files_without_hunks_are_skipped():
    rename_only = (
        "diff --git a/old.py b/new.py\n"
        "similarity index 100%\n"
        "rename from old.py\n"
        "rename to new.py\n"
    )
    assert parse_hunks(rename_only) == []


def test_reconstruct_full_diff_roundtrips():
    hunks = parse_hunks(TWO_FILE_DIFF)
    assert reconstruct_diff(hunks) == TWO_FILE_DIFF


def test_reconstruct_subset_groups_by_file():
    hunks = parse_hunks(TWO_FILE_DIFF)
    # A chapter interleaving the new file and the second foo.py hunk.
    chapter = reconstruct_diff([hunks[2], hunks[1]])
    # Both files' preambles appear exactly once, in first-seen order.
    assert chapter.count("diff --git a/new.txt") == 1
    assert chapter.count("diff --git a/foo.py") == 1
    assert chapter.index("new.txt") < chapter.index("foo.py")
    assert "@@ -1,3 +1,3 @@" not in chapter  # h0 excluded
    assert "@@ -10,2 +10,3 @@" in chapter  # h1 included


def _chapter(cid, hunks):
    return Chapter(id=cid, title="t", summary="s", narration="n", hunks=hunks)


def test_validate_coverage_accepts_full_coverage():
    hunks = parse_hunks(TWO_FILE_DIFF)
    chapters = [_chapter("ch1", ["h0", "h1"]), _chapter("ch2", ["h2"])]
    validate_coverage(chapters, hunks)  # no raise


def test_validate_coverage_allows_overlap():
    hunks = parse_hunks(TWO_FILE_DIFF)
    chapters = [_chapter("ch1", ["h0", "h1", "h2"]), _chapter("ch2", ["h1"])]
    validate_coverage(chapters, hunks)  # overlap is fine; coverage is the rule


def test_validate_coverage_rejects_unassigned_hunk():
    hunks = parse_hunks(TWO_FILE_DIFF)
    chapters = [_chapter("ch1", ["h0", "h1"])]  # h2 missing
    with pytest.raises(SagaError, match="h2"):
        validate_coverage(chapters, hunks)


def test_validate_coverage_rejects_unknown_hunk():
    hunks = parse_hunks(TWO_FILE_DIFF)
    chapters = [_chapter("ch1", ["h0", "h1", "h2", "h9"])]
    with pytest.raises(SagaError, match="h9"):
        validate_coverage(chapters, hunks)


def test_validate_coverage_rejects_empty():
    hunks = parse_hunks(TWO_FILE_DIFF)
    with pytest.raises(SagaError, match="no chapters"):
        validate_coverage([], hunks)


def test_deleted_file_path_falls_back_to_diff_git_header():
    """A pure deletion has ``+++ /dev/null``; the path must come from the
    ``diff --git a/… b/…`` header instead."""
    delete_diff = (
        "diff --git a/gone.py b/gone.py\n"
        "deleted file mode 100644\n"
        "index 1111111..0000000\n"
        "--- a/gone.py\n"
        "+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n"
        "-a\n"
        "-b\n"
    )
    hunks = parse_hunks(delete_diff)
    assert [h.file_path for h in hunks] == ["gone.py"]


def test_chapter_dict_roundtrip():
    ch = Chapter(
        id="c1",
        title="T",
        summary="S",
        narration="N",
        hunks=["h0", "h1"],
        plan_step="step 2",
        confidence="high",
        deviation="drifted",
        qa={"status": "green", "note": "ok"},
    )
    assert Chapter.from_dict(ch.to_dict()) == ch


def test_chapter_from_dict_defaults_and_normalizes_confidence():
    ch = Chapter.from_dict({"id": "c1", "confidence": "bogus"})
    assert ch.title == "" and ch.hunks == []
    assert ch.confidence == "medium"  # unknown level normalized
    assert ch.deviation is None


def test_saga_dict_roundtrip():
    saga = Saga(
        branch="feature",
        base="main",
        commit_sha="abc123",
        generated_at="2026-07-11T00:00:00Z",
        chapters=[
            Chapter(id="c1", title="t", summary="s", narration="n", hunks=["h0"])
        ],
    )
    restored = Saga.from_dict(saga.to_dict())
    assert restored.to_dict() == saga.to_dict()


def test_verdict_counts():
    saga = Saga(
        branch="b",
        base="main",
        commit_sha="abc",
        chapters=[
            Chapter(id="c1", title="", summary="", narration="", confidence="low"),
            Chapter(id="c2", title="", summary="", narration="", deviation="changed X"),
            Chapter(id="c3", title="", summary="", narration="", confidence="high"),
        ],
    )
    v = saga.verdict(qa_state="green")
    assert v == {"chapters": 3, "deviations": 1, "low_confidence": 1, "qa": "green"}
