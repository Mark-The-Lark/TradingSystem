import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Set
import pandas as pd
from core.gateway import BaseGateway
from core.events import EventBus, CandleEvent, ConnectionStateEvent
from core.models import Order, OrderSide, OrderType, OrderStatus, Candle, Tick
from core.time_provider import SimulatedTimeProvider

class HistoricalDataGateway(BaseGateway):
    """
    Шлюз для бэктестинга на исторических свечах.
    Поддерживает только подписку на свечи (типы 'candle'), тики не генерируются.
    """
    def __init__(self, event_bus: EventBus, clock: SimulatedTimeProvider, data: Dict[str, pd.DataFrame]):
        super().__init__(event_bus)
        self.clock = clock
        self.data = data              # ticker -> DataFrame свечей (минутные)
        self._subscriptions: Dict[str, Set[tuple]] = {}  # strategy_name -> set of (ticker, timeframe)
        self._last_index: Dict[tuple, datetime] = {}      # (ticker, timeframe) -> последнее отданное время
        # Для поддержки таймфреймов, отличных от 1m, потребуется ресамплинг. Пока упростим – только 1m.
        # Если стратегия подписывается на 5m, мы будем ресамплить на лету.

    async def connect(self):
        self._connected = True
        await self.event_bus.publish("connection", ConnectionStateEvent(state="connected"))

    async def disconnect(self):
        self._connected = False
        await self.event_bus.publish("connection", ConnectionStateEvent(state="disconnected"))

    async def subscribe(self, strategy_name: str, symbol: str, data_type: str, timeframe: Optional[str] = None):
        if data_type != 'candle':
            # тики не поддерживаются
            return
        if symbol not in self.data:
            raise ValueError(f"Нет данных для символа {symbol}")
        self._subscriptions.setdefault(strategy_name, set()).add((symbol, timeframe or '1m'))
        # Устанавливаем начальную точку для этого символа/таймфрейма
        key = (symbol, timeframe or '1m')
        if key not in self._last_index:
            # Начинаем с первой доступной даты
            self._last_index[key] = self.data[symbol].index[0]

    async def unsubscribe(self, strategy_name: str, symbol: str, data_type: str, timeframe: Optional[str] = None):
        if strategy_name in self._subscriptions:
            self._subscriptions[strategy_name].discard((symbol, timeframe or '1m'))

    async def send_order(self, order: Order) -> str:
        # В бэктесте исполнение происходит мгновенно по текущей цене из данных
        # OrderManager сам вызовет fill после небольшой задержки, а мы в Gateway публикуем fill сразу.
        # Но поскольку у нас синхронный режим прогона, мы можем прямо здесь публиковать fill.
        # Для согласованности с реальным Gateway отложим fill через asyncio.create_task (sleep 0).
        # В бэктест-движке мы будем прогонять все задачи, поэтому это сработает.
        asyncio.create_task(self._immediate_fill(order))
        return "bt-gw-1"  # фиктивный gateway_order_id

    async def _immediate_fill(self, order: Order):
        await asyncio.sleep(0)
        # Получаем текущую цену из данных
        symbol = order.symbol
        if symbol in self.data:
            # Находим последнюю свечу, соответствующую текущему времени (или последнюю доступную)
            current_time = self.clock.utc_now()
            df = self.data[symbol]
            # Берем свечу, ближайшую слева
            available = df[df.index <= current_time]
            if not available.empty:
                fill_price = available.iloc[-1]['Close']  # исполняем по Close текущей свечи
            else:
                fill_price = df.iloc[0]['Close']  # если нет, самую первую
        else:
            fill_price = 100.0  # заглушка
        from core.events import OrderFilledEvent
        await self.event_bus.publish("order.filled", OrderFilledEvent(
            order_id=order.client_order_id,
            fill_volume=order.volume,
            fill_price=fill_price,
            commission=0.0,    # комиссия будет добавлена в OrderManager
            slippage=0.0
        ))

    async def cancel_order(self, client_order_id: str) -> None:
        from core.events import OrderCancelledEvent
        await self.event_bus.publish("order.cancelled", OrderCancelledEvent(order_id=client_order_id))

    async def modify_order(self, client_order_id: str, **kwargs) -> None:
        # Пока не реализовано
        pass

    async def step(self, until: datetime) -> bool:
        """
        Продвигает время до указанного момента, публикуя все свечи, которые должны были быть сгенерированы
        за этот интервал. Возвращает True, если были опубликованы какие-либо данные.
        """
        published = False
        # Для каждой подписки находим свечи в интервале [self._last_index[key], until]
        for strategy_name, subs in self._subscriptions.items():
            for symbol, tf in subs:
                if symbol not in self.data:
                    continue
                key = (symbol, tf)
                df = self.data[symbol]
                start = self._last_index.get(key, df.index[0])
                # Ищем свечи до времени until
                mask = (df.index > start) & (df.index <= until)
                new_candles = df.loc[mask]
                if new_candles.empty:
                    continue
                # Для каждой свечи публикуем событие
                for ts, row in new_candles.iterrows():
                    candle = Candle(
                        symbol=symbol,
                        timeframe=tf,
                        open=row['Open'],
                        high=row['High'],
                        low=row['Low'],
                        close=row['Close'],
                        volume=row['Volume'],
                        timestamp=ts,
                        is_complete=True
                    )
                    # Сначала переводим часы на время свечи, чтобы стратегии видели актуальное время
                    self.clock.set_time(ts + timedelta(seconds=1))  # после закрытия свечи
                    await self.event_bus.publish(f"market.candle.{symbol}.{tf}", CandleEvent(candle=candle))
                    published = True
                # Обновляем последний индекс
                self._last_index[key] = new_candles.index[-1]
        return published