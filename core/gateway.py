from abc import ABC, abstractmethod
from typing import Optional, List
from core.events import EventBus
from core.models import Order, Candle

class BaseGateway(ABC):
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @abstractmethod
    async def connect(self) -> None:
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        ...

    @abstractmethod
    async def subscribe(self, strategy_name: str, symbol: str, data_type: str, timeframe: Optional[str] = None) -> None:
        ...

    @abstractmethod
    async def unsubscribe(self, strategy_name: str, symbol: str, data_type: str, timeframe: Optional[str] = None) -> None:
        ...

    @abstractmethod
    async def send_order(self, order: Order) -> str:  # возвращает gateway_order_id
        ...

    @abstractmethod
    async def cancel_order(self, client_order_id: str) -> None:
        ...

    @abstractmethod
    async def modify_order(self, client_order_id: str, **kwargs) -> None:
        ...

    @abstractmethod
    async def get_history(self, symbol: str, timeframe: str, count: int) -> List[Candle]:
        ...