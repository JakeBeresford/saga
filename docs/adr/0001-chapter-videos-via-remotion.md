# Chapter Videos via AI-Generated Remotion Compositions

Saga is a Python CLI that outputs a single self-contained HTML file. To add video demonstrations of what each Chapter accomplishes, we bundle a Remotion (Node.js/React) project inside the repo and invoke it via subprocess when the user passes `--videos`.

Videos are AI-generated: each Chapter's title, narration, and diff text are fed to an LLM which produces a Remotion composition that visually demonstrates the change. This makes each video specific to the actual code change rather than generic animated text.

## Output shape

`saga --videos -o saga.html` produces `saga.html` plus a sibling `saga-videos/` directory containing one mp4 per Chapter. The single-file guarantee is preserved for the default (no `--videos`) path. Videos are embedded above the Narration in the chapter view, autoplay-muted on chapter open.

## Failure handling

If a Chapter's Remotion render fails (broken generated code, Node.js error, timeout), that Chapter's video is silently skipped and the HTML shows a placeholder. The saga still opens. This keeps `--videos` safe to use in automated workflows.

## Considered options

- **Fixed Remotion template** (data-driven, no LLM): consistent visual style, zero per-chapter LLM cost, but produces generic motion graphics rather than code-specific demos. Rejected in favour of AI-generated demos; can be added as a fallback later.
- **Separate `saga videos` subcommand**: preserves `saga` CLI speed, enables per-chapter re-renders, but adds friction. Rejected for now in favour of the simpler inline `--videos` flag.
- **Embedded video in HTML** (base64): preserves single-file portability but makes the HTML impractically large. Rejected in favour of the sidecar directory.
