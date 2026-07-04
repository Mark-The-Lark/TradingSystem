import pytest
import asyncio
from core.events import EventBus, Event, TickEvent, CandleEvent
from core.models import Tick, Candle
from datetime import datetime

@pytest.mark.asyncio
async def test_event_bus_subscribe_and_publish():
    bus = EventBus()
    received = []

    async def handler(event: Event):
        received.append(event)

    bus.subscribe("test", handler)
    event = Event()
    await bus.publish("test", event)
    assert len(received) == 1
    assert received[0] is event

@pytest.mark.asyncio
async def test_event_bus_multiple_handlers():
    bus = EventBus()
    results = []

    async def handler1(e): results.append(1)
    async def handler2(e): results.append(2)

    bus.subscribe("topic", handler1)
    bus.subscribe("topic", handler2)
    await bus.publish("topic", Event())
    assert sorted(results) == [1, 2]
