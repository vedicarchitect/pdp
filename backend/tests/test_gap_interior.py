"""Unit tests for interior-gap detection in gap_backfill.py."""

from pdp.options.gap_backfill import has_interior_gap, nonempty_idx


# ── nonempty_idx ──────────────────────────────────────────────────────────────

def test_nonempty_idx_empty_list():
    assert nonempty_idx([]) == []


def test_nonempty_idx_all_empty():
    assert nonempty_idx([[], [], []]) == []


def test_nonempty_idx_all_nonempty():
    assert nonempty_idx([[1], [2], [3]]) == [0, 1, 2]


def test_nonempty_idx_mixed():
    assert nonempty_idx([[], [1], [], [2], []]) == [1, 3]


# ── has_interior_gap ──────────────────────────────────────────────────────────

def test_interior_gap_data_empty_data():
    # data – empty – data → interior gap → refuse
    assert has_interior_gap([[1], [], [2]]) is True


def test_interior_gap_all_empty():
    # completely empty day → no interior gap (nothing to anchor)
    assert has_interior_gap([[], [], []]) is False


def test_interior_gap_all_present():
    assert has_interior_gap([[1], [2], [3]]) is False


def test_interior_gap_leading_empty():
    # empty – data – data → leading empty is OK, not an interior gap
    assert has_interior_gap([[], [1], [2]]) is False


def test_interior_gap_trailing_empty():
    # data – data – empty → trailing empty is OK
    assert has_interior_gap([[1], [2], []]) is False


def test_interior_gap_multiple_interior_holes():
    assert has_interior_gap([[1], [], [], [2], [], [3]]) is True


def test_interior_gap_single_chunk():
    assert has_interior_gap([[1]]) is False


def test_interior_gap_two_chunks_no_hole():
    assert has_interior_gap([[1], [2]]) is False


def test_interior_gap_two_chunks_with_hole():
    # Only two chunks, both non-empty — no interior gap possible
    assert has_interior_gap([[1], [2]]) is False


def test_interior_gap_three_chunks_middle_empty():
    assert has_interior_gap([[1], [], [2]]) is True
