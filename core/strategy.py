
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import pandas as pd
from core.events import EventBus, OrderFilledEvent, OrderCancelledEvent, OrderRejectedEvent, OrderRequestEvent, StopOrderEvent, OrderConnectionEvent
from core.models import Order, OrderSide, OrderType, Trade, Tick, Candle
from core.order_manager import OrderManager

logger = logging.getLogger(__name__)

class Strategy(ABC):
    def __init__(
        self,
        name: str,
        event_bus: EventBus,
        order_manager: OrderManager,
        mode: str = 'AUTO',
        subscriptions: Optional[List[Tuple[str, str]]] = None
    ):
        self.name = name
        self.event_bus = event_bus
        self.order_manager = order_manager
        self.mode = mode
        self.using_cap = 1.0 
        # Подписки: список (symbol, timeframe), где timeframe может быть 'tick'
        self.subscriptions: List[Tuple[str, str]] = subscriptions or []

        # Капитал, плечо и вес
        # leverage — персональный множитель плеча (default 1.0):
        #            CapitalManager умножает выделенный капитал на это значение,
        #            позволяя стратегии развёртывать больше / меньше выделенной квоты.
        #            Итоговое плечо ограничено CapitalManager.max_leverage.
        # weight   — коэффициент масштабирования объёма внутри get_position_size.
        self._capital_manager = None

        # Позиция и цены входа — посимвольно
        self.positions: Dict[str, float] = {}
        self.entry_prices: Dict[str, float] = {}
        self._last_prices: Dict[str, float] = {}

        # Общая эквити
        self.current_equity = 0.0
        self.initial_capital = 0.0

        # Индикаторы: ключ — имя (с суффиксом символа), значение — Series
        self.indicators: Dict[str, pd.Series] = {}

        # История цен: symbol → timeframe → DataFrame
        self.price_history: Dict[str, Dict[str, pd.DataFrame]] = {}
        # Инициализировать при первой записи

        # Эквити-кривая
        self.equity_history = pd.DataFrame({
            'timestamp': pd.Series(dtype='datetime64[ns]'),
            'equity': pd.Series(dtype='float')
        })

        self.trades: List[Trade] = []
        self.active_signals = []
        self._status = 'STOPPED'

        # Стоп-лосс и тейк-профит — управляются стратегией, не брокером.
        # Ключ: symbol, значение: уровень цены.
        # Проверка срабатывания: вызовите `await self.check_sl_tp(candle)` в on_candle().
        self._stop_losses:  Dict[str, float] = {}
        self._take_profits: Dict[str, float] = {}

        self._setup_event_handlers()

    def _setup_event_handlers(self):
        self.event_bus.subscribe(f"strategy.{self.name}.fill", self._on_fill)
        self.event_bus.subscribe(f"strategy.{self.name}.cancel", self._on_cancel)
        self.event_bus.subscribe(f"strategy.{self.name}.reject", self._on_reject)

    async def _on_fill(self, event: OrderFilledEvent):
        order = self.order_manager.get_order_by_client_id(event.order_id)
        if not order:
            return
        symbol = order.symbol
        fill_price = event.fill_price
        fill_volume = event.fill_volume
        comm = event.commission
        delta = fill_volume if order.side == OrderSide.BUY else -fill_volume

        # Текущая позиция по символу
        pos = self.positions.get(symbol, 0.0)
        entry = self.entry_prices.get(symbol)

        if pos * delta >= 0:  # Увеличение позиции
            if pos == 0:
                self.entry_prices[symbol] = fill_price
            else:
                if entry is not None:
                    total_abs = abs(pos) + fill_volume
                    self.entry_prices[symbol] = (entry * abs(pos) + fill_price * fill_volume) / total_abs
                else:
                    logger.warning(f"No entry price for {symbol}, setting to fill price")
                    self.entry_prices[symbol] = fill_price
            self.positions[symbol] = pos + delta
            self.current_equity -= comm
        else:  # Закрытие
            if entry is None:
                logger.warning(f"Попытка закрытия без цены входа по {symbol}. Игнорируем.")
                return
            close_volume = min(abs(delta), abs(pos))
            if pos > 0:  # Закрываем лонг
                pnl = (fill_price - entry) * close_volume - comm
            else:        # Закрываем шорт
                pnl = (entry - fill_price) * close_volume - comm
            self.current_equity += pnl
            new_pos = pos + delta
            self.positions[symbol] = new_pos
            if new_pos == 0:
                del self.entry_prices[symbol]
            elif (new_pos > 0) != (pos > 0):  # Переворот
                self.entry_prices[symbol] = fill_price
        self.update_equity_snapshot()

    async def _on_cancel(self, event: OrderCancelledEvent):
        pass

    async def _on_reject(self, event: OrderRejectedEvent):
        pass

    @abstractmethod
    async def on_tick(self, tick: Tick):
        ...

    @abstractmethod
    async def on_candle(self, candle: Candle):
        ...

    async def on_init(self):
        pass

    async def send_order(self, order: Order):
        order.strategy_name = self.name
        if self.mode == 'AUTO':
            await self.event_bus.publish("order.request", OrderRequestEvent(order=order))
        else:
            self.active_signals.append(order)

    # --- Снимки ---
    def get_light_snapshot(self) -> dict:
        """Быстрый снимок для таблицы."""
        # Строка позиций
        pos_str = ", ".join(f"{sym}:{pos}" for sym, pos in self.positions.items() if pos != 0) or "—"
        # Общий P&L
        total_pnl = 0.0
        for sym, pos in self.positions.items():
            if pos != 0 and sym in self._last_prices and sym in self.entry_prices:
                last = self._last_prices[sym]
                entry = self.entry_prices[sym]
                if pos > 0:
                    total_pnl += (last - entry) * pos
                else:
                    total_pnl += (entry - last) * abs(pos)
        return {
            'name': self.name,
            'symbols': list(self.positions.keys()),  # для совместимости
            'mode': self.mode,
            'position_str': pos_str,
            'equity': self.current_equity,
            'pnl': total_pnl,
            'status': self._status,
            'signals': len(self.active_signals),
        }

    def get_snapshot(self) -> dict:
        """Подробный снимок для детальной панели."""
        snap = self.get_light_snapshot()
        snap['indicator_names'] = list(self.indicators.keys())
        snap['timeframes'] = list(set(tf for _, tf in self.subscriptions if tf != 'tick'))
        # Конфигурация графиков по умолчанию
        snap['default_plots'] = self.get_default_plot_config()
        return snap

    def get_default_plot_config(self) -> dict:
        """Может быть переопределено: возвращает словарь с предустановленными кривыми."""
        return {}

    def set_status(self, status: str):
        self._status = status

    # --- История цен ---
    def add_candle_to_history(self, candle: Candle):
        sym = candle.symbol
        tf = candle.timeframe
        if sym not in self.price_history:
            self.price_history[sym] = {}
        if tf not in self.price_history[sym]:
            self.price_history[sym][tf] = pd.DataFrame({
                'timestamp': pd.Series(dtype='datetime64[ns]'),
                'open': pd.Series(dtype='float64'),
                'high': pd.Series(dtype='float64'),
                'low': pd.Series(dtype='float64'),
                'close': pd.Series(dtype='float64'),
                'volume': pd.Series(dtype='float64')
            })
        new_row = pd.DataFrame([{
            'timestamp': candle.timestamp,
            'open': candle.open,
            'high': candle.high,
            'low': candle.low,
            'close': candle.close,
            'volume': candle.volume
        }])
        df = self.price_history[sym][tf]
        if df.empty:
            self.price_history[sym][tf] = new_row
        else:
            self.price_history[sym][tf] = pd.concat([df, new_row], ignore_index=True)
        # Ограничение размера
        MAX_LEN = 500
        if len(self.price_history[sym][tf]) > MAX_LEN:
            self.price_history[sym][tf] = self.price_history[sym][tf].iloc[-MAX_LEN:]
        # Обновляем последнюю цену
        self._last_prices[sym] = candle.close

    def update_equity_snapshot(self):
        new_row = pd.DataFrame([{
            'timestamp': datetime.utcnow(),
            'equity': self.current_equity
        }])
        if self.equity_history.empty:
            self.equity_history = new_row
        else:
            self.equity_history = pd.concat([self.equity_history, new_row], ignore_index=True)
        MAX_EQ_LEN = 500
        if len(self.equity_history) > MAX_EQ_LEN:
            self.equity_history = self.equity_history.iloc[-MAX_EQ_LEN:]

    def get_plot_data(self, symbol: str, timeframe: str = '1m') -> dict:
        sym_hist = self.price_history.get(symbol, {})
        df = sym_hist.get(timeframe)
        if df is None or df.empty:
            return {}
        price_ts = [t.timestamp() for t in df['timestamp']]
        plot_data = {
            'price': {
                'timestamps': price_ts,
                'open': df['open'].tolist(),
                'high': df['high'].tolist(),
                'low': df['low'].tolist(),
                'close': df['close'].tolist()
            },
            'indicators': {},
            'equity': {
                'timestamps': [t.timestamp() for t in self.equity_history['timestamp']],
                'values': self.equity_history['equity'].tolist()
            }
        }
        # Добавляем только индикаторы, содержащие имя символа
        suffix = f"_{symbol}"
        for name, series in self.indicators.items():
            if name.endswith(suffix) and isinstance(series, pd.Series) and not series.empty:
                if isinstance(series.index, pd.DatetimeIndex):
                    ts = [t.timestamp() for t in series.index]
                else:
                    ts = list(range(len(series)))
                plot_data['indicators'][name] = {
                    'timestamps': ts,
                    'values': series.tolist()
                }
        return plot_data

    # --- Капитал и риск-менеджмент ---
    def get_available_capital(self) -> float:
        if self._capital_manager:
            return self._capital_manager.get_available_capital(self.name)
        return 0.0

    def compute_atr_stop(
        self,
        symbol: str,
        timeframe: str,
        entry_price: float,
        direction: str = 'long',
        atr_period: int = 14,
        atr_multiplier: float = 2.0,
    ) -> Optional[float]:
        """Возвращает уровень стоп-лосса на основе ATR.

        stop = entry_price ∓ atr * multiplier
        (минус для лонга, плюс для шорта)

        Returns:
            Уровень стоп-лосса или None если ATR вычислить невозможно.
        """
        atr = self.compute_atr(symbol, timeframe, atr_period)
        if atr is None:
            return None
        if direction == 'long':
            return entry_price - atr * atr_multiplier
        else:
            return entry_price + atr * atr_multiplier

    # --- Стоп-лосс / тейк-профит ---
    async def set_stop_loss(self, symbol: str, price: float, volume: float, offset: float = None, slippage: float = None) -> str:
        side = OrderSide.SELL
        if volume < 0:
            side = OrderSide.BUY
        order = Order(
                    client_order_id=f"{self.name}_{symbol}_sl_{price}",
                    strategy_name=self.name,
                    symbol=symbol,
                    side=side,
                    order_type=OrderType.STOP,
                    volume=abs(volume),
                    stop_price=price,
                    price= price - (offset or 0.0) if side == OrderSide.SELL else price + (offset or 0.0),
                    slippage=slippage or 0.0
                )
        await self.event_bus.publish("order.stop", StopOrderEvent(order=order))

        return order.client_order_id

    async def set_take_profit(self, symbol: str, price: float, volume: float, offset: float = None, slippage: float = None) -> str:
        side = OrderSide.SELL
        if volume < 0:
            side = OrderSide.BUY
        order = Order(
                    client_order_id=f"{self.name}_{symbol}_tp_{price}",
                    strategy_name=self.name,
                    symbol=symbol,
                    side=side,
                    order_type=OrderType.TAKE_PROFIT,
                    volume=abs(volume),
                    stop_price=price,
                    price= price + (offset or 0.0) if side == OrderSide.SELL else price - (offset or 0.0),
                    slippage=slippage or 0.0
                )
        await self.event_bus.publish("order.stop", StopOrderEvent(order=order))

        return order.client_order_id
    
    async def set_limit(self, symbol: str, price: float, volume: float) -> str:
        side = OrderSide.BUY
        if volume < 0:
            side = OrderSide.SELL
        order = Order(
                    client_order_id=f"{self.name}_{symbol}_lim_{price}",
                    strategy_name=self.name,
                    symbol=symbol,
                    side=side,
                    order_type=OrderType.LIMIT,
                    volume=abs(volume),
                    price= price,
                )
        await self.event_bus.publish("order.stop", StopOrderEvent(order=order))

        return order.client_order_id
    
    async def set_market(self, symbol: str, volume: float) -> str:
        side = OrderSide.BUY
        if volume < 0:
            side = OrderSide.SELL
        order = Order(
                    client_order_id=f"{self.name}_{symbol}_market",
                    strategy_name=self.name,
                    symbol=symbol,
                    side=side,
                    order_type=OrderType.MARKET,
                    volume=abs(volume),
                )
        await self.event_bus.publish("order.stop", StopOrderEvent(order=order))

        return order.client_order_id

    async def connect_orders(self, *args) -> None:
        await self.event_bus.publish("order.connect", OrderConnectionEvent(order_ids=args))

    # --- Сохранение / загрузка ---
    def save_state(self) -> dict:
        return {
            'positions': self.positions,
            'entry_prices': self.entry_prices,
            'current_equity': self.current_equity,
            'price_history': {
                sym: {tf: df.to_dict(orient='records') for tf, df in tf_dict.items()}
                for sym, tf_dict in self.price_history.items()
            },
            'equity_history': self.equity_history.to_dict(orient='records'),
        }

    def load_state(self, state: dict):
        self.positions = state.get('positions', {})
        self.entry_prices = state.get('entry_prices', {})
        self.current_equity = state.get('current_equity', 0.0)
        ph = state.get('price_history', {})
        for sym, tf_dict in ph.items():
            self.price_history.setdefault(sym, {})
            for tf, records in tf_dict.items():
                if records:
                    df = pd.DataFrame(records)
                    if 'timestamp' in df.columns:
                        df['timestamp'] = pd.to_datetime(df['timestamp'])
                    self.price_history[sym][tf] = df
        eq = state.get('equity_history', [])
        if eq:
            df_eq = pd.DataFrame(eq)
            if 'timestamp' in df_eq.columns:
                df_eq['timestamp'] = pd.to_datetime(df_eq['timestamp'])
            self.equity_history = df_eq
            if 'current_equity' not in state:
                self.current_equity = df_eq['equity'].iloc[-1]
        # Восстановить _last_prices из price_history
        for sym, sym_hist in self.price_history.items():
            for tf, df in sym_hist.items():
                if not df.empty:
                    self._last_prices[sym] = df['close'].iloc[-1]

    async def emergency_exit(self):
        """Закрывает все открытые позиции рыночными ордерами."""
        for symbol, pos in self.positions.items():
            if pos == 0:
                continue
            side = OrderSide.SELL if pos > 0 else OrderSide.BUY
            order = Order(
                client_order_id=f"emergency_{symbol}_{int(datetime.now().timestamp())}",
                strategy_name=self.name,
                symbol=symbol,
                side=side,
                order_type=OrderType.MARKET,
                volume=abs(pos),
            )
            await self.send_order(order)
            logger.info(f"Экстренное закрытие {symbol}: {pos} по рынку")
            self.positions[symbol] = 0
            self.entry_prices.pop(symbol, None)
    def set_using_cap(self, value: float):
        self.using_cap = max(0.0, min(1.0, value))
        # Триггерим перераспределение
        if self._capital_manager:
            self._capital_manager.redistribute()