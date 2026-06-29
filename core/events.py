import asyncio
from typing import Any, Callable, Coroutine, Dict, List, Set
from core.models import Tick, Candle, Order
from dataclasses import dataclass

@dataclass(frozen=True)
class Event:
    """Базовый класс события."""
    pass

class EventBus:
    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}  # topic -> list of callbacks
        # Можно также хранить asyncio.Queue для асинхронной обработки, но для простоты будем вызывать callback'и напрямую
        # Для полной асинхронности можно сделать внутреннюю очередь и диспетчер

    def subscribe(self, topic: str, callback: Callable[[Event], Coroutine[Any, Any, None]]):
        """Подписать асинхронный обработчик на тему."""
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        self._subscribers[topic].append(callback)

    def unsubscribe(self, topic: str, callback: Callable):
        if topic in self._subscribers:
            self._subscribers[topic] = [cb for cb in self._subscribers[topic] if cb != callback]
            if not self._subscribers[topic]:
                del self._subscribers[topic]

    async def publish(self, topic: str, event: Event):
        """Опубликовать событие. Вызывает всех подписчиков асинхронно."""
        if topic in self._subscribers:
            tasks = [callback(event) for callback in self._subscribers[topic]]
            # Запускаем все обработчики конкурентно, но ждём завершения всех
            await asyncio.gather(*tasks)

# Некоторые конкретные типы событий для удобства
@dataclass(frozen=True)
class TickEvent(Event):
    tick: Tick

@dataclass(frozen=True)
class CandleEvent(Event):
    candle: Candle

@dataclass(frozen=True)
class OrderPlacedEvent(Event):
    order: Order

@dataclass(frozen=True)
class OrderFilledEvent(Event):
    order_id: str
    fill_volume: float
    fill_price: float
    commission: float
    slippage: float

@dataclass(frozen=True)
class ConnectionStateEvent(Event):
    state: str  # 'connected', 'disconnected', 'reconnecting'

@dataclass(frozen=True)
class OrderCancelledEvent(Event):
    order_id: str

@dataclass(frozen=True)
class OrderRejectedEvent(Event):
    order_id: str
    reason: str

@dataclass(frozen=True)
class OrderRequestEvent(Event):
    order: Order

@dataclass(frozen=True)
class ConnectionStateEvent(Event):
    state: str  # 'connected', 'disconnected', 'reconnecting'