# Saga

A CLI tool that generates a self-contained HTML narrative from a git diff — turning code review into a structured story.

## Language

**Saga**:
The top-level artifact: a structured narrative covering all changes between two git refs, composed of ordered Chapters.
_Avoid_: report, summary, review

**Chapter**:
A logical unit of a Saga that groups one or more related Hunks under a title, narration, and confidence level. The primary unit of navigation in the reader UI.
_Avoid_: section, step, story

**Hunk**:
An atomic diff fragment from a unified diff, assigned a stable id (`h0`, `h1`, …) and associated with exactly one file path. Chapters reference Hunks by id.
_Avoid_: diff chunk, diff block, patch

**Narration**:
The 2–4 sentence prose explanation of what a Chapter accomplishes. Written by the LLM. The primary human-readable content of a Chapter.
_Avoid_: description, summary (reserved for the ≤12-word TOC blurb)

**Chapter Video**:
An AI-generated Remotion video that visually demonstrates what a Chapter accomplishes. Rendered alongside the HTML output when `--videos` is passed. Placed above the Narration in the chapter view.
_Avoid_: video summary, chapter animation

**Coverage**:
The invariant that every Hunk in a Saga belongs to at least one Chapter. Validated after generation; generation fails hard if violated.
_Avoid_: completeness, assignment

## Example dialogue

> "Why does this chapter have no video?"
> "The Remotion render failed for that one — it silently skipped. The others rendered fine."

> "Should the Hunk for the migration go in its own Chapter or share one with the model change?"
> "They're tightly related — one Chapter with both Hunks is cleaner. Coverage just requires every Hunk appears somewhere."
