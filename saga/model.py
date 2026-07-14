"""Data model for PR sagas — the chapter-based review of one change set.

A saga partitions a change set's whole diff into ordered *chapters* that
tell a coherent story. This module is the pure, side-effect-light core:

* ``parse_hunks`` splits a unified diff into individually addressable ``Hunk``s
  (stable ``h0, h1, …`` ids in diff order), and ``reconstruct_diff`` rebuilds a
  valid unified-diff string for any subset of them — so the browser can render a
  single chapter through diff2html with the *same* file/line anchors the full
  diff uses.
* ``Chapter``/``Saga`` are the persisted shape (``to_dict``/``from_dict``).
* ``validate_coverage`` enforces the hard invariant: every hunk belongs to at
  least one chapter. It raises ``SagaError`` loudly on any gap.

Stdlib only — this is the standalone core and has no external dependencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CONFIDENCE_LEVELS = ("high", "medium", "low")


class SagaError(Exception):
    """Raised when a saga is malformed or fails the coverage invariant.

    Carries a human-readable message surfaced to the reviewer as a non-blocking
    notice before falling back to the standard diff.
    """


# ---------------------------------------------------------------------------
# Hunk parsing / diff reconstruction
# ---------------------------------------------------------------------------

_DIFF_GIT_RE = re.compile(r"^diff --git ", re.MULTILINE)


@dataclass(frozen=True)
class Hunk:
    """One ``@@`` hunk of a unified diff, addressable by a stable id.

    ``preamble`` is the file-level header (``diff --git`` … through the ``+++``
    line) shared by every hunk of that file; ``body`` is the ``@@`` line plus its
    context/change lines. Reconstructing a file emits the preamble once followed
    by each of its hunks' bodies — a valid unified diff diff2html can render.
    """

    id: str
    file_path: str
    preamble: str
    body: str


def _file_path_from_preamble(preamble: str) -> str:
    """The new-side path diff2html shows in its file header (``+++ b/<path>``).

    Falls back to the ``diff --git b/<path>`` side for pure renames/deletes with
    no ``+++`` line.
    """
    for line in preamble.splitlines():
        if line.startswith("+++ "):
            target = line[4:].strip()
            if target and target != "/dev/null":
                return target[2:] if target.startswith(("a/", "b/")) else target
    m = re.search(r"^diff --git a/.* b/(.*)$", preamble, re.MULTILINE)
    return m.group(1).strip() if m else ""


def parse_hunks(diff_text: str) -> list[Hunk]:
    """Split a unified diff into ``Hunk``s with stable ``h0, h1, …`` ids.

    Files with no ``@@`` hunk (pure renames, mode-only changes) contribute no
    hunks — there is nothing line-addressable to review.
    """
    hunks: list[Hunk] = []
    starts = [m.start() for m in _DIFF_GIT_RE.finditer(diff_text)]
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(diff_text)
        block = diff_text[start:end]
        at_idx = block.find("\n@@")
        if at_idx == -1:
            continue  # no hunks in this file block
        preamble = block[: at_idx + 1]  # keep the trailing newline
        rest = block[at_idx + 1 :]
        file_path = _file_path_from_preamble(preamble)
        # Each hunk runs from an "@@" line to the next "@@" (or end of block).
        for m in re.finditer(r"(?m)^@@ ", rest):
            h_start = m.start()
            nxt = rest.find("\n@@ ", h_start + 1)
            h_end = nxt + 1 if nxt != -1 else len(rest)
            hunks.append(
                Hunk(
                    id=f"h{len(hunks)}",
                    file_path=file_path,
                    preamble=preamble,
                    body=rest[h_start:h_end],
                )
            )
    return hunks


def reconstruct_diff(hunks: list[Hunk]) -> str:
    """Rebuild a valid unified diff from an ordered subset of hunks.

    Hunks are grouped by file (first-seen order preserved); each file's preamble
    is emitted once, then its selected hunk bodies in the given order. The result
    renders through diff2html exactly like the full view.
    """
    out: list[str] = []
    seen_preamble: set[str] = set()
    for hunk in hunks:
        if hunk.preamble not in seen_preamble:
            out.append(hunk.preamble)
            seen_preamble.add(hunk.preamble)
        out.append(hunk.body)
    return "".join(out)


# ---------------------------------------------------------------------------
# Chapter / Saga model
# ---------------------------------------------------------------------------


@dataclass
class Chapter:
    """One ordered chapter of a saga.

    ``hunks`` lists the hunk ids this chapter covers. ``deviation`` is set (to the
    agent's explanation) only when the implementation diverged from the stated
    intent; ``qa`` carries an optional manual-QA recommendation (a short
    sentence), set only when the chapter's changes are not well-covered by
    automated tests. Both are ``None`` when nothing is worth flagging.
    """

    id: str
    title: str
    summary: str
    narration: str
    hunks: list[str] = field(default_factory=list)
    plan_step: str | None = None
    confidence: str = "medium"
    deviation: str | None = None
    qa: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> Chapter:
        confidence = d.get("confidence", "medium")
        if confidence not in CONFIDENCE_LEVELS:
            confidence = "medium"
        return cls(
            id=d["id"],
            title=d.get("title", ""),
            summary=d.get("summary", ""),
            narration=d.get("narration", ""),
            hunks=list(d.get("hunks", [])),
            plan_step=d.get("plan_step"),
            confidence=confidence,
            deviation=d.get("deviation") or None,
            qa=d.get("qa"),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "narration": self.narration,
            "hunks": self.hunks,
            "plan_step": self.plan_step,
            "confidence": self.confidence,
            "deviation": self.deviation,
            "qa": self.qa,
        }


@dataclass
class Saga:
    """A change set's saga: ordered chapters + diff context."""

    branch: str
    base: str
    commit_sha: str
    generated_at: str = ""
    title: str = ""
    summary: str = ""
    chapters: list[Chapter] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> Saga:
        return cls(
            branch=d.get("branch", ""),
            base=d.get("base", ""),
            commit_sha=d.get("commit_sha", ""),
            generated_at=d.get("generated_at", ""),
            title=d.get("title", ""),
            summary=d.get("summary", ""),
            chapters=[Chapter.from_dict(c) for c in d.get("chapters", [])],
        )

    def to_dict(self) -> dict:
        return {
            "branch": self.branch,
            "base": self.base,
            "commit_sha": self.commit_sha,
            "generated_at": self.generated_at,
            "title": self.title,
            "summary": self.summary,
            "chapters": [c.to_dict() for c in self.chapters],
        }

    def verdict(self) -> dict:
        """The top-line summary rendered above the table of contents.

        Computed here (not trusted from the LLM) so the counts always match the
        chapters actually present.
        """
        return {
            "chapters": len(self.chapters),
            "deviations": sum(1 for c in self.chapters if c.deviation),
            "low_confidence": sum(1 for c in self.chapters if c.confidence == "low"),
        }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_coverage(chapters: list[Chapter], hunks: list[Hunk]) -> None:
    """Enforce the hard invariant: every hunk belongs to at least one chapter.

    Raises ``SagaError`` if any chapter references an unknown hunk id or
    if any hunk is left unassigned. Chapters overlapping (a hunk in two chapters)
    is allowed — coverage, not partition, is the contract.
    """
    if not chapters:
        raise SagaError("Saga has no chapters.")

    all_ids = {h.id for h in hunks}
    referenced: set[str] = set()
    for ch in chapters:
        for hid in ch.hunks:
            referenced.add(hid)

    unknown = referenced - all_ids
    if unknown:
        raise SagaError(
            f"Chapters reference unknown hunks: {', '.join(sorted(unknown))}."
        )

    unassigned = all_ids - referenced
    if unassigned:
        raise SagaError(
            f"{len(unassigned)} hunk(s) not assigned to any chapter: "
            f"{', '.join(sorted(unassigned))}."
        )
