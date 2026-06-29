import asyncio
from abc import ABC, abstractmethod
from datetime import datetime

class TimeProvider(ABC):
    @abstractmethod
    def utc_now(self) -> datetime:
        ...

    @abstractmethod
    async def sleep(self, seconds: float) -> None:
        ...

class RealTimeProvider(TimeProvider):
    def utc_now(self) -> datetime:
        return datetime.utcnow()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

from datetime import timedelta

class SimulatedTimeProvider(TimeProvider):
    def __init__(self, start_time: datetime):
        self._current = start_time

    def utc_now(self) -> datetime:
        return self._current

    async def sleep(self, seconds: float) -> None:
        self._current += timedelta(seconds=seconds)
        await asyncio.sleep(0)