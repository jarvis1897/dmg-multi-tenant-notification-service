from datetime import datetime, timedelta, timezone

from app.delivery.rate_limit import TokenBucket


def test_full_bucket_allows_burst_up_to_capacity():
    now = datetime.now(timezone.utc)
    bucket = TokenBucket.full(capacity=5, refill_per_minute=60, now=now)

    results = [bucket.try_acquire(now) for _ in range(5)]
    assert results == [True] * 5


def test_exhausted_bucket_rejects_until_refill():
    now = datetime.now(timezone.utc)
    bucket = TokenBucket.full(capacity=5, refill_per_minute=60, now=now)
    for _ in range(5):
        bucket.try_acquire(now)

    assert bucket.try_acquire(now) is False


def test_bucket_refills_over_time_at_configured_rate():
    now = datetime.now(timezone.utc)
    # 60 tokens/minute == 1 token/second
    bucket = TokenBucket.full(capacity=5, refill_per_minute=60, now=now)
    for _ in range(5):
        bucket.try_acquire(now)

    later = now + timedelta(seconds=3)
    # ~3 tokens should have refilled
    assert bucket.try_acquire(later) is True
    assert bucket.try_acquire(later) is True
    assert bucket.try_acquire(later) is True
    assert bucket.try_acquire(later) is False


def test_refill_never_exceeds_capacity():
    now = datetime.now(timezone.utc)
    bucket = TokenBucket.full(capacity=2, refill_per_minute=600, now=now)

    much_later = now + timedelta(minutes=10)
    acquired = [bucket.try_acquire(much_later) for _ in range(5)]
    # capacity caps the burst at 2, regardless of how much time elapsed
    assert acquired == [True, True, False, False, False]
