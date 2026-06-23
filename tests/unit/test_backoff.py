from app.delivery.backoff import compute_backoff


def test_backoff_doubles_each_attempt_before_capping():
    base, max_backoff, jitter = 2.0, 1000.0, 0.0  # jitter=0 makes this deterministic

    assert compute_backoff(1, base, max_backoff, jitter) == base * 2**1
    assert compute_backoff(2, base, max_backoff, jitter) == base * 2**2
    assert compute_backoff(3, base, max_backoff, jitter) == base * 2**3


def test_backoff_is_capped_at_max_backoff_seconds():
    base, max_backoff, jitter = 2.0, 60.0, 0.0

    # 2 * 2**10 = 2048, far past the cap
    assert compute_backoff(10, base, max_backoff, jitter) == max_backoff


def test_backoff_jitter_adds_bounded_randomness():
    base, max_backoff, jitter = 2.0, 1000.0, 1.0
    expected_floor = base * 2**1

    values = [compute_backoff(1, base, max_backoff, jitter) for _ in range(50)]
    assert all(expected_floor <= v <= expected_floor + jitter for v in values)
    # not all identical -- jitter is actually doing something
    assert len(set(values)) > 1


def test_backoff_never_negative_or_zero_for_first_attempt():
    value = compute_backoff(0, base_seconds=2.0, max_backoff_seconds=60.0, jitter_seconds=1.0)
    assert value > 0
