import asyncio
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TokenBucket:
    """
    Capacity = a tenant's per-channel rate_limit_* value: a tenant can
    burst up to its full per-minute allowance instantly, then refills
    gradually at that same per-minute rate. `try_acquire` itself is pure,
    synchronous math (easy to unit test) — the `lock` field exists for the
    async caller (dispatch_round) to guard each check, since everything
    here runs on one event loop and the bucket is shared mutable state.
    """

    capacity: int
    refill_per_minute: int
    tokens: float
    last_refill: datetime
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @classmethod
    def full(cls, capacity: int, refill_per_minute: int, now: datetime) -> "TokenBucket":
        return cls(capacity=capacity, refill_per_minute=refill_per_minute, tokens=capacity, last_refill=now)

    def try_acquire(self, now: datetime) -> bool:
        elapsed_seconds = max(0.0, (now - self.last_refill).total_seconds())
        refill_amount = elapsed_seconds * (self.refill_per_minute / 60.0)
        self.tokens = min(self.capacity, self.tokens + refill_amount)
        self.last_refill = now

        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False
