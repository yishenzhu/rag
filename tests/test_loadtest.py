"""Load test helper tests."""

from scripts.loadtest import percentile


def test_percentile_nearest_rank():
    values = [1.0, 2.0, 3.0, 4.0]
    assert percentile(values, 50) == 3.0
    assert percentile(values, 99) == 4.0
    assert percentile([0.5], 99) == 0.5
    assert percentile([], 95) == 0.0
