import asyncio
import random
from typing import Protocol

from app.common.config import settings
from app.common.enums import Channel


class Provider(Protocol):
    async def send(self, recipient: str, subject: str | None, body: str) -> bool: ...


class MockProvider:
    """
    Simulates network latency and a configurable failure rate so retry/
    backoff/DLQ logic actually gets exercised instead of every send
    trivially succeeding.
    """

    def __init__(self, channel: Channel, failure_rate: float = settings.simulate_failure_rate) -> None:
        self.channel = channel
        self.failure_rate = failure_rate

    async def send(self, recipient: str, subject: str | None, body: str) -> bool:
        await asyncio.sleep(0.1)
        return random.random() >= self.failure_rate


def build_provider_registry() -> dict[str, Provider]:
    return {channel.value: MockProvider(channel) for channel in Channel}
