"""The top-level ``saga`` package is the supported library surface (§5.1)."""

import saga

EXPECTED = {
    "compute_diff",
    "pr_diff",
    "DiffResult",
    "generate",
    "render",
    "build_payload",
    "Saga",
    "Chapter",
    "Hunk",
    "parse_hunks",
    "reconstruct_diff",
    "validate_coverage",
    "SagaError",
    "comments_block",
    "agent_view",
}


def test_all_matches_expected_surface():
    assert set(saga.__all__) == EXPECTED


def test_every_exported_name_is_importable():
    for name in saga.__all__:
        assert hasattr(saga, name), name


def test_reexports_are_the_real_objects():
    from saga import comments as comments_mod
    from saga import comments_block as comments_block_mod
    from saga.diff import compute_diff
    from saga.model import Saga

    assert saga.compute_diff is compute_diff
    assert saga.Saga is Saga
    assert saga.agent_view is comments_mod.agent_view
    assert saga.comments_block is comments_block_mod
