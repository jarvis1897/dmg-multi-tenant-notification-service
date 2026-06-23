from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.common.config import settings
from app.common.database import AsyncSessionLocal
from app.delivery.dispatch import DueAttempt, claim_and_send, dispatch_round, poll_due_attempts
from app.delivery.provider import build_provider_registry
from app.delivery.rate_limit import TokenBucket
from app.tenants.models import Tenant

logger = logging.getLogger(__name__)

_DISPATCH_TICK_SECONDS = 0.1


@dataclass
class EngineState:
    tenant_queues: dict[str, asyncio.Queue[DueAttempt]] = field(default_factory=dict)
    token_buckets: dict[tuple[str, str], TokenBucket] = field(default_factory=dict)
    in_flight: set[str] = field(default_factory=set)
    work_queue: asyncio.Queue[DueAttempt] = field(default_factory=asyncio.Queue)


_state: EngineState | None = None
_tasks: list[asyncio.Task] = []
_provider_registry = build_provider_registry()


async def _ensure_token_bucket(session, state: EngineState, tenant_id: str, channel: str) -> None:
    key = (tenant_id, channel)
    if key in state.token_buckets:
        return
    tenant = await session.get(Tenant, tenant_id)
    capacity = getattr(tenant, f"rate_limit_{channel}")
    state.token_buckets[key] = TokenBucket.full(capacity, capacity, datetime.now(timezone.utc))


async def _poll_loop(state: EngineState) -> None:
    while True:
        try:
            async with AsyncSessionLocal() as session:
                due_by_tenant = await poll_due_attempts(session)
                for tenant_id, attempts in due_by_tenant.items():
                    queue = state.tenant_queues.setdefault(tenant_id, asyncio.Queue())
                    for attempt in attempts:
                        if attempt.id in state.in_flight:
                            continue
                        await _ensure_token_bucket(session, state, tenant_id, attempt.channel)
                        state.in_flight.add(attempt.id)
                        await queue.put(DueAttempt(id=attempt.id, channel=attempt.channel))
        except Exception:
            logger.exception("dispatch engine: poll loop tick failed")
        await asyncio.sleep(settings.poll_interval_seconds)


async def _dispatch_loop(state: EngineState) -> None:
    while True:
        try:
            await dispatch_round(state.tenant_queues, state.token_buckets, state.work_queue)
        except Exception:
            logger.exception("dispatch engine: dispatch round failed")
        await asyncio.sleep(_DISPATCH_TICK_SECONDS)


async def _worker_loop(state: EngineState) -> None:
    while True:
        item = await state.work_queue.get()
        try:
            async with AsyncSessionLocal() as session:
                provider = _provider_registry[item.channel]
                await claim_and_send(item.id, session, provider)
        except Exception:
            logger.exception("dispatch engine: worker failed processing %s", item.id)
        finally:
            state.in_flight.discard(item.id)


async def start() -> None:
    global _state
    _state = EngineState()
    _tasks.append(asyncio.create_task(_poll_loop(_state)))
    _tasks.append(asyncio.create_task(_dispatch_loop(_state)))
    for _ in range(settings.worker_pool_size):
        _tasks.append(asyncio.create_task(_worker_loop(_state)))
    logger.info(
        "dispatch engine started: poll_interval=%ss worker_pool_size=%s",
        settings.poll_interval_seconds,
        settings.worker_pool_size,
    )


async def stop() -> None:
    for task in _tasks:
        task.cancel()
    await asyncio.gather(*_tasks, return_exceptions=True)
    _tasks.clear()
