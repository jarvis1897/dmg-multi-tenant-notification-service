import asyncio
from datetime import datetime, timezone

import pytest

from app.delivery.dispatch import DueAttempt, dispatch_round
from app.delivery.rate_limit import TokenBucket


@pytest.mark.asyncio
async def test_flooding_tenant_does_not_starve_a_quiet_tenant():
    now = datetime.now(timezone.utc)

    flooding_tenant = "tenant-flood"
    quiet_tenant = "tenant-quiet"

    # Flooding tenant: 5 items queued, but only 2 tokens available.
    flood_queue: asyncio.Queue[DueAttempt] = asyncio.Queue()
    for i in range(5):
        flood_queue.put_nowait(DueAttempt(id=f"flood-{i}", channel="email"))

    # Quiet tenant: just 1 item, plenty of capacity.
    quiet_queue: asyncio.Queue[DueAttempt] = asyncio.Queue()
    quiet_queue.put_nowait(DueAttempt(id="quiet-0", channel="email"))

    # Insertion order matters for this test: the flooding tenant (with a
    # much bigger backlog) is visited first each round, to prove a large
    # backlog doesn't make the dispatcher linger on one tenant.
    tenant_queues = {flooding_tenant: flood_queue, quiet_tenant: quiet_queue}
    token_buckets = {
        (flooding_tenant, "email"): TokenBucket.full(capacity=2, refill_per_minute=2, now=now),
        (quiet_tenant, "email"): TokenBucket.full(capacity=100, refill_per_minute=100, now=now),
    }
    work_queue: asyncio.Queue[DueAttempt] = asyncio.Queue()

    # Round 1: the flooding tenant gets exactly one item dispatched (one
    # token spent), and so does the quiet tenant -- it is not made to wait
    # behind the flooding tenant's much larger backlog.
    await dispatch_round(tenant_queues, token_buckets, work_queue)
    dispatched_ids = set()
    while not work_queue.empty():
        dispatched_ids.add(work_queue.get_nowait().id)
    assert dispatched_ids == {"flood-0", "quiet-0"}
    assert quiet_queue.empty()
    assert flood_queue.qsize() == 4

    # Round 2: the flooding tenant's last token lets one more through.
    await dispatch_round(tenant_queues, token_buckets, work_queue)
    dispatched_ids = set()
    while not work_queue.empty():
        dispatched_ids.add(work_queue.get_nowait().id)
    assert dispatched_ids == {"flood-1"}
    assert flood_queue.qsize() == 3

    # Round 3: the flooding tenant is now out of tokens -- it is skipped
    # this round rather than blocking, and nothing moves for it.
    await dispatch_round(tenant_queues, token_buckets, work_queue)
    assert work_queue.empty()
    assert flood_queue.qsize() == 3  # unchanged -- still queued, not lost
