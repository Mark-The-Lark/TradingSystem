import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from core.gateway import BaseGateway
from core.events import EventBus, TickEvent, CandleEvent, OrderPlacedEvent, OrderFilledEvent, OrderCancelledEvent, OrderRejectedEvent, ConnectionStateEvent
from core.models import Order, OrderSide, OrderType, OrderStatus, Tick, Candle, TimeInForce

class SimulatedMarket:
    def __init__(self):
        self._prices: Dict[str, float] = {}  # последняя цена
        self._pending_orders: List[Order] = []  # лимитные/стоп ордера
        self._order_callbacks: Dict[str, asyncio.Task] = {}  # задачи проверки условий ордеров (упростим без задач, будем проверять при каждом тике)

    def set_price(self, symbol: str, price: float):
        self._prices[symbol] = price

    def get_price(self, symbol: str) -> float:
        return self._prices.get(symbol, 100.0)

    def add_order(self, order: Order) -> None:
        if order.order_type in (OrderType.LIMIT, OrderType.STOP, OrderType.TAKE_PROFIT):
            self._pending_orders.append(order)

    def remove_order(self, client_order_id: str) -> None:
        self._pending_orders = [o for o in self._pending_orders if o.client_order_id != client_order_id]

    def check_orders(self, symbol: str, current_price: float) -> List[Order]:
        triggered = []
        for order in self._pending_orders[:]:
            if order.symbol != symbol:
                continue
            if order.order_type == OrderType.LIMIT:
                if (order.side == OrderSide.BUY and current_price <= order.price) or \
                   (order.side == OrderSide.SELL and current_price >= order.price):
                    triggered.append(order)
                    self._pending_orders.remove(order)
            elif order.order_type == OrderType.STOP:
                if (order.side == OrderSide.BUY and current_price >= order.stop_price) or \
                   (order.side == OrderSide.SELL and current_price <= order.stop_price):
                    triggered.append(order)
                    self._pending_orders.remove(order)
        return triggered

class SimulationGateway(BaseGateway):
    def __init__(self, event_bus, time_provider, base_prices=None):
        super().__init__(event_bus)
        self.time_provider = time_provider
        self._market = SimulatedMarket()
        if base_prices:
            for sym, price in base_prices.items():
                self._market.set_price(sym, price)
        self._subscriptions: Dict[str, List[Dict]] = {}
        self._generator_task: Optional[asyncio.Task] = None
        # Для агрегации свечей
        self._active_candles: Dict[tuple, Candle] = {}   # (symbol, timeframe) -> Candle
        self._candle_intervals = {"1m": 1, "5m": 5, "1h": 60}  # секунды для теста
        self._last_candle_close: Dict[tuple, float] = {}  # время последнего закрытия
    async def connect(self):
        self._connected = True
        await self.event_bus.publish("connection", ConnectionStateEvent(state="connected"))
        self._start_data_generation()

    async def disconnect(self):
        self._connected = False
        if self._generator_task and not self._generator_task.done():
            self._generator_task.cancel()
        await self.event_bus.publish("connection", ConnectionStateEvent(state="disconnected"))

    async def subscribe(self, strategy_name, symbol, data_type, timeframe=None):
        sub = {"symbol": symbol, "data_type": data_type, "timeframe": timeframe}
        self._subscriptions.setdefault(strategy_name, []).append(sub)
        self._start_data_generation()

    async def unsubscribe(self, strategy_name, symbol, data_type, timeframe=None):
        if strategy_name in self._subscriptions:
            self._subscriptions[strategy_name] = [
                s for s in self._subscriptions[strategy_name]
                if not (s["symbol"] == symbol and s["data_type"] == data_type and s.get("timeframe") == timeframe)
            ]
        self._start_data_generation()

    def _start_data_generation(self):
        if self._generator_task and not self._generator_task.done():
            self._generator_task.cancel()
        if not self._connected:
            return
        # Собираем все символы, на которые есть подписки (тики или свечи)
        symbols = set()
        for subs in self._subscriptions.values():
            for sub in subs:
                symbols.add(sub["symbol"])
        if symbols:
            self._generator_task = asyncio.create_task(self._generate_all(symbols))

    async def _generate_all(self, symbols: set):
        """Главный генератор: тики + агрегация свечей."""
        # Инициализируем активные свечи для всех запрошенных таймфреймов
        for sym in symbols:
            for tf in self._candle_intervals.keys():
                self._active_candles[(sym, tf)] = self._create_new_candle(sym, tf)

        while self._connected:
            await self.time_provider.sleep(0.1)  # 10 тиков в секунду для плавности
            now = self.time_provider.utc_now()

            for sym in symbols:
                # Генерация тика
                import random
                current_price = self._market.get_price(sym)
                delta = random.uniform(-0.1, 0.1)
                new_price = max(0.01, current_price + delta)
                self._market.set_price(sym, new_price)
                tick = Tick(
                    timestamp=now,
                    symbol=sym,
                    bid=new_price - 0.01,
                    ask=new_price + 0.01,
                    last=new_price,
                    volume=random.randint(1, 100)
                )
                await self.event_bus.publish(f"market.tick.{sym}", TickEvent(tick=tick))

                # Проверка лимитных ордеров
                triggered = self._market.check_orders(sym, new_price)
                for order in triggered:
                    asyncio.create_task(self._delayed_fill(order, str(uuid.uuid4())))

                # Обновление всех активных свечей для этого символа
                for tf in self._candle_intervals.keys():
                    key = (sym, tf)
                    candle = self._active_candles[key]
                    candle.high = max(candle.high, new_price)
                    candle.low = min(candle.low, new_price)
                    candle.close = new_price
                    candle.volume += tick.volume
                    # Проверяем, не пора ли закрыть свечу
                    interval_secs = self._candle_intervals[tf]
                    last_close = self._last_candle_close.get(key, candle.timestamp)
                    if (now - last_close).total_seconds() >= interval_secs:
                        candle.timestamp = now
                        candle.is_complete = True
                        await self.event_bus.publish(
                            f"market.candle.{sym}.{tf}",
                            CandleEvent(candle=candle)
                        )
                        # Начинаем новую свечу
                        self._active_candles[key] = self._create_new_candle(sym, tf)
                        self._last_candle_close[key] = now

    def _create_new_candle(self, symbol: str, timeframe: str) -> Candle:
        price = self._market.get_price(symbol)
        now = self.time_provider.utc_now()
        return Candle(
            symbol=symbol,
            timeframe=timeframe,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=0,
            timestamp=now,
            is_complete=False
        )

    async def _delayed_fill(self, order: Order, gw_id: str):
        await asyncio.sleep(0)  # даём зарегистрироваться
        fill_price = self._market.get_price(order.symbol)
        await self.event_bus.publish("order.filled", OrderFilledEvent(
            order_id=order.client_order_id,
            fill_volume=order.volume,
            fill_price=fill_price,
            commission=0.0,
            slippage=0.0
        ))

    async def send_order(self, order: Order) -> str:
        gw_id = str(uuid.uuid4())
        if order.order_type == OrderType.MARKET:
            asyncio.create_task(self._delayed_fill(order, gw_id))
            return gw_id
        else:
            self._market.add_order(order)
            await self.event_bus.publish("order.placed", OrderPlacedEvent(order=order))
            return gw_id

    async def cancel_order(self, client_order_id: str) -> None:
        self._market.remove_order(client_order_id)
        await self.event_bus.publish("order.cancelled", OrderCancelledEvent(order_id=client_order_id))

    async def modify_order(self, client_order_id: str, **kwargs) -> None:
        await self.cancel_order(client_order_id)

    async def get_history(self, symbol: str, timeframe: str, count: int) -> List[Candle]:
        """Генерирует 'count' фиктивных свечей в прошлое от текущего времени."""
        tf_map = {'1m': 1, '5m': 5, '1h': 60}
        step = tf_map.get(timeframe, 1)
        now = self.time_provider.utc_now()
        candles = []
        price = self._market.get_price(symbol)
        import random
        for i in range(count, 0, -1):
            ts = now - timedelta(seconds=step * i)
            o = price
            h = price * (1 + random.uniform(0, 0.002))
            l = price * (1 - random.uniform(0, 0.002))
            c = (o + h + l) / 3 + random.uniform(-0.001, 0.001)
            v = random.randint(10, 1000)
            candles.append(Candle(symbol=symbol, timeframe=timeframe,
                                open=o, high=h, low=l, close=c,
                                volume=v, timestamp=ts, is_complete=True))
        return candles
