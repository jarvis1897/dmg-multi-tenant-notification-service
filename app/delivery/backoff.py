import random


def compute_backoff(attempt_count: int, base_seconds: float, max_backoff_seconds: float, jitter_seconds: float) -> float:
    """
    Exponential backoff with jitter:
    min(base * 2**attempt_count + uniform(0, jitter), max_backoff)
    """
    backoff = base_seconds * (2**attempt_count) + random.uniform(0, jitter_seconds)
    return min(backoff, max_backoff_seconds)
