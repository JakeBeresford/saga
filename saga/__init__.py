"""Public library API for :mod:`saga`.

``saga`` is primarily a CLI, but the pipeline it drives — diff → generate →
render, plus the in-HTML comment store — is usable as a library. This module is
the supported, semver-stable surface: the names in ``__all__`` are the only ones
callers should import. Everything else under ``saga.*`` is an internal detail
that may change without notice.

See ``docs/library_api.md`` for the documented contract.
"""

from . import comments_block
from .comments import agent_view
from .diff import DiffResult, compute_diff, pr_diff
from .generate import generate
from .model import (
    Chapter,
    Hunk,
    Saga,
    SagaError,
    parse_hunks,
    reconstruct_diff,
    validate_coverage,
)
from .render import build_payload, render

__all__ = [
    # diff
    "compute_diff",
    "pr_diff",
    "DiffResult",
    # generate
    "generate",
    # render
    "render",
    "build_payload",
    # model
    "Saga",
    "Chapter",
    "Hunk",
    "parse_hunks",
    "reconstruct_diff",
    "validate_coverage",
    "SagaError",
    # comments
    "comments_block",
    "agent_view",
]
