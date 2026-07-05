# from abc import ABC, abstractmethod
# from typing import Dict, List, Optional
# from datetime import datetime
# import logging
# import pandas as pd
# from core.events import EventBus, OrderFilledEvent, OrderCancelledEvent, OrderRejectedEvent, OrderRequestEvent
# from core.models import Order, OrderSide, Trade, Tick, Candle
# from core.order_manager import OrderManager
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
# )
# logger = logging.getLogger(__name__)
# class Strategy(ABC):
#     def __init__(self, name: str, symbol: str, event_bus: EventBus, order_manager: OrderManager,
#                  mode: str = 'AUTO', timeframes: Optional[List[str]] = None):
#         self.name = name
#         self.symbol = symbol
#         self.event_bus = event_bus
#         self.order_manager = order_manager
#         self.mode = mode
#         self.timeframes = timeframes or ['1m']
#         self.indicators = {}
#         self.position = 0.0
#         self.current_equity = 0.0  # начальный капитал будет задаваться извне
#         self.initial_capital = 0.0
#         self._entry_price = None
#         # Исторические данные: окно свечей
#         self.price_history = {
#             tf: pd.DataFrame({
#                 'timestamp': pd.Series(dtype='datetime64[ns]'),
#                 'open': pd.Series(dtype='float64'),
#                 'high': pd.Series(dtype='float64'),
#                 'low': pd.Series(dtype='float64'),
#                 'close': pd.Series(dtype='float64'),
#                 'volume': pd.Series(dtype='float64')
#             })
#             for tf in self.timeframes
#         }
#         self.equity_history = pd.DataFrame({'timestamp': pd.Series(dtype='datetime64[ns]'), 'equity': pd.Series(dtype='float')})    
#         self.trades: List[Trade] = []
#         self.active_signals = []  # для SIGNAL режима
#         self._indicators = {}
#         self._status = 'STOPPED'  # возможные значения: 'RUNNING', 'STOPPED', 'ERROR'
#         # Подписки на события стратегии
#         self._setup_event_handlers()

#     def _setup_event_handlers(self):
#         # Обработчики fill, cancel, reject приходят через event bus
#         self.event_bus.subscribe(f"strategy.{self.name}.fill", self._on_fill)
#         self.event_bus.subscribe(f"strategy.{self.name}.cancel", self._on_cancel)
#         self.event_bus.subscribe(f"strategy.{self.name}.reject", self._on_reject)
#         # Также можно подписаться на рыночные данные, но это сделает StrategyManager


#     async def _on_fill(self, event: OrderFilledEvent):
#         order = self.order_manager.get_order_by_client_id(event.order_id)
#         if not order:
#             return

#         fill_price = event.fill_price
#         fill_volume = event.fill_volume
#         comm = event.commission
#         delta = fill_volume if order.side == OrderSide.BUY else -fill_volume

#         # Увеличиваем позицию (или открываем)
#         if self.position * delta >= 0:
#             if self.position == 0:
#                 self._entry_price = fill_price
#             else:
#                 # Усреднение, только если цена входа уже задана
#                 if self._entry_price is not None:
#                     total_abs = abs(self.position) + fill_volume
#                     self._entry_price = (self._entry_price * abs(self.position) + fill_price * fill_volume) / total_abs
#                 else:
#                     logger.warning("_entry_price was None when increasing position. Setting to fill price.")
#                     self._entry_price = fill_price
#             self.position += delta
#             self.current_equity -= comm

#         # Закрываем позицию
#         else:
#             if self._entry_price is None:
#                 logger.warning(f"Попытка закрытия без цены входа (позиция {self.position}). Игнорируем fill.")
#                 return

#             close_volume = min(abs(delta), abs(self.position))
#             if self.position > 0:          # Закрываем лонг
#                 pnl = (fill_price - self._entry_price) * close_volume - comm
#             else:                          # Закрываем шорт
#                 pnl = (self._entry_price - fill_price) * close_volume - comm

#             self.current_equity += pnl
#             self.position += delta

#             if self.position == 0:
#                 self._entry_price = None
#             elif (self.position > 0) != (delta > 0):  # произошёл переворот
#                 self._entry_price = fill_price
#         self.update_equity_snapshot()

#     async def _on_cancel(self, event: OrderCancelledEvent):
#         pass

#     async def _on_reject(self, event: OrderRejectedEvent):
#         pass

#     async def on_init(self):
#         """Загрузка исторических данных и восстановление состояния."""
#         pass

#     @abstractmethod
#     async def on_tick(self, tick: Tick):
#         ...

#     @abstractmethod
#     async def on_candle(self, candle: Candle):
#         ...

#     async def send_order(self, order: Order):
#         order.strategy_name = self.name
#         if self.mode == 'AUTO':
#             await self.event_bus.publish("order.request", OrderRequestEvent(order=order))
#         else:
#             # SIGNAL: сохраняем сигнал и уведомляем GUI (через EventBus)
#             self.active_signals.append(order)
#             # TODO: publish signal event

#     def get_snapshot(self) -> dict:
#         snapshot = {
#             'name': self.name,
#             'symbol': self.symbol,
#             'mode': self.mode,
#             'position': self.position,
#             'equity': self.current_equity,
#             'status': self._status,
#             'signals': len(self.active_signals),
#             'indicator_names': list(self.indicators.keys()),
#             'timeframes': self.timeframes,
#         }
#         # Рассчитываем нереализованный P&L
#         pnl = 0.0
#         if self.position != 0 and hasattr(self, '_entry_price') and self._entry_price is not None:
#             # Получаем последнюю цену из истории (первый таймфрейм)
#             primary_tf = self.timeframes[0] if self.timeframes else '1m'
#             df = self.price_history.get(primary_tf)
#             if df is not None and not df.empty:
#                 last_price = df['close'].iloc[-1]
#                 if self.position > 0:
#                     pnl = (last_price - self._entry_price) * self.position
#                 else:
#                     pnl = (self._entry_price - last_price) * abs(self.position)
#         snapshot['pnl'] = pnl
#         return snapshot
#     def set_status(self, status: str):
#         self._status = status

#     def add_candle_to_history(self, candle: Candle):
#         """Сохраняет свечу в историю для указанного таймфрейма."""
#         tf = candle.timeframe
#         new_row = pd.DataFrame([{
#             'timestamp': candle.timestamp,
#             'open': candle.open,
#             'high': candle.high,
#             'low': candle.low,
#             'close': candle.close,
#             'volume': candle.volume
#         }])
#         if self.price_history[tf].empty:
#             self.price_history[tf] = new_row
#         else:
#             self.price_history[tf] = pd.concat([self.price_history[tf], new_row], ignore_index=True)
#         # Ограничим длину истории в оперативной памяти
#         MAX_LEN = 500
#         if len(self.price_history[tf]) > MAX_LEN:
#             self.price_history[tf] = self.price_history[tf].iloc[-MAX_LEN:]

#     def update_equity_snapshot(self):
#         """Добавляет текущее состояние эквити в историю."""
#         new_row = pd.DataFrame([{
#             'timestamp': datetime.utcnow(),
#             'equity': self.current_equity
#         }])
#         if self.equity_history.empty:
#             self.equity_history = new_row
#         else:
#             self.equity_history = pd.concat([self.equity_history, new_row], ignore_index=True)
#         MAX_EQ_LEN = 500
#         if len(self.equity_history) > MAX_EQ_LEN:
#             self.equity_history = self.equity_history.iloc[-MAX_EQ_LEN:]
#     def save_state(self) -> dict:
#         """Сериализует состояние стратегии."""
#         return {
#             'position': self.position,
#             'current_equity': self.current_equity,
#             'price_history': {tf: df.to_dict(orient='records') for tf, df in self.price_history.items()},
#             'equity_history': self.equity_history.to_dict(orient='records'),
#         }
#     def load_state(self, state: dict):
#         """Восстанавливает состояние стратегии."""
#         self.position = state.get('position', 0.0)
        

#         ph = state.get('price_history', {})
#         for tf, records in ph.items():
#             if records:
#                 df = pd.DataFrame(records)
#                 if 'timestamp' in df.columns:
#                     df['timestamp'] = pd.to_datetime(df['timestamp'])
#                 self.price_history[tf] = df
#             else:
#                 self.price_history[tf] = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

#         eq = state.get('equity_history', [])
#         if eq:
#             df_eq = pd.DataFrame(eq)
#             if 'timestamp' in df_eq.columns:
#                 df_eq['timestamp'] = pd.to_datetime(df_eq['timestamp'])
#             self.equity_history = df_eq
#             self.current_equity = state.get('current_equity', df_eq['equity'].iloc[-1])
#         else:
#             self.equity_history = pd.DataFrame({'timestamp': pd.Series(dtype='datetime64[ns]'),
#                                                 'equity': pd.Series(dtype='float')})
#             self.current_equity = state.get('current_equity', 0.0)
#     def get_plot_data(self, timeframe: str = '1m') -> dict:
#         """Возвращает данные для построения графиков (временные метки в секундах)."""
#         df = self.price_history.get(timeframe)
#         if df is None or df.empty:
#             return {}

#         # Числовые timestamp'ы для pyqtgraph
#         price_ts = [t.timestamp() for t in df['timestamp']]

#         plot_data = {
#             'price': {
#                 'timestamps': price_ts,
#                 'open': df['open'].tolist(),
#                 'high': df['high'].tolist(),
#                 'low': df['low'].tolist(),
#                 'close': df['close'].tolist()
#             },
#             'indicators': {},
#             'equity': {
#                 'timestamps': [t.timestamp() for t in self.equity_history['timestamp']],
#                 'values': self.equity_history['equity'].tolist()
#             }
#         }

#         for name, series in self.indicators.items():
#             if isinstance(series, pd.Series) and not series.empty:
#                 # индекс должен быть DatetimeIndex
#                 if isinstance(series.index, pd.DatetimeIndex):
#                     ts = [t.timestamp() for t in series.index]
#                 else:
#                     # на случай, если индекс другой
#                     ts = list(range(len(series)))
#                 plot_data['indicators'][name] = {
#                     'timestamps': ts,
#                     'values': series.tolist()
#                 }
#         return plot_data
    
#     def get_available_capital(self) -> float:
#         """Запрашивает у CapitalManager доступный капитал для этой стратегии."""
#         # Предполагаем, что strategy_manager и capital_manager доступны
#         # Мы сохраним ссылку на менеджер в стратегии при инициализации (см. ниже)
#         if hasattr(self, '_capital_manager') and self._capital_manager:
#             return self._capital_manager.get_available_capital(self.name)
#         return 0.0
    
#     def get_position_size(self, price: float, risk_fraction: float = 1.0) -> float:
#         """Рассчитывает размер позиции в лотах (объём) на основе доступного капитала."""
#         available = self.get_available_capital()
#         if available <= 0:
#             return 0.0
#         # Простой вариант: инвестируем весь доступный капитал в один актив
#         max_volume = available / price
#         # Можно умножить на risk_fraction, чтобы использовать только часть капитала
#         return max_volume * risk_fraction


# core/strategy.py (новый код)
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import pandas as pd
from core.events import EventBus, OrderFilledEvent, OrderCancelledEvent, OrderRejectedEvent, OrderRequestEvent
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

        # Подписки: список (symbol, timeframe), где timeframe может быть 'tick'
        self.subscriptions: List[Tuple[str, str]] = subscriptions or []

        # Капитал, плечо и вес
        # leverage — персональный множитель плеча (default 1.0):
        #            CapitalManager умножает выделенный капитал на это значение,
        #            позволяя стратегии развёртывать больше / меньше выделенной квоты.
        #            Итоговое плечо ограничено CapitalManager.max_leverage.
        # weight   — коэффициент масштабирования объёма внутри get_position_size.
        self.leverage: float = 1.0
        self.weight: float = 1.0
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

    def get_position_size(self, symbol: str, price: float, risk_fraction: float = 1.0) -> float:
        """Размер позиции как доля доступного капитала.
        
        volume = (available_capital * risk_fraction * weight) / price
        """
        available = self.get_available_capital()
        if available <= 0 or price <= 0:
            return 0.0
        max_volume = available / price
        return max_volume * risk_fraction * self.weight

    def get_position_size_by_risk(
        self,
        symbol: str,
        entry_price: float,
        stop_price: float,
        risk_pct: float = 0.01,
    ) -> float:
        """Размер позиции по методу фиксированного % риска на сделку.

        Формула: volume = (available * risk_pct) / |entry_price - stop_price|
        
        Args:
            symbol:       торгуемый символ (для логирования)
            entry_price:  предполагаемая цена входа
            stop_price:   уровень стоп-лосса
            risk_pct:     доля капитала, которой рискуем в сделке (по умолчанию 1%)
        
        Returns:
            Объём в лотах (float). 0.0 если капитала нет или стоп совпадает с ценой входа.
        """
        if entry_price == stop_price:
            logger.warning(f"{self.name}: entry_price == stop_price для {symbol}, размер позиции = 0")
            return 0.0
        available = self.get_available_capital()
        if available <= 0:
            return 0.0
        risk_amount = available * risk_pct * self.weight
        price_risk = abs(entry_price - stop_price)
        return risk_amount / price_risk

    def compute_atr(self, symbol: str, timeframe: str, period: int = 14) -> Optional[float]:
        """Вычисляет ATR (Average True Range) по последним barам истории.

        ATR = среднее True Range за `period` баров.
        True Range = max(H-L, |H-prev_C|, |L-prev_C|)

        Returns:
            ATR в единицах цены, или None если данных недостаточно.
        """
        import numpy as np
        df = self.price_history.get(symbol, {}).get(timeframe)
        if df is None or len(df) < period + 1:
            return None
        high  = df['high'].values.astype(float)
        low   = df['low'].values.astype(float)
        close = df['close'].values.astype(float)
        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(
                np.abs(high[1:] - close[:-1]),
                np.abs(low[1:] - close[:-1]),
            ),
        )
        return float(np.mean(tr[-period:]))

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
    def set_stop_loss(self, symbol: str, price: float) -> None:
        """Устанавливает уровень стоп-лосса для символа.

        При вызове check_sl_tp() на свече, где low/high достигает уровня,
        автоматически отправляется закрывающий ордер по рынку.
        """
        self._stop_losses[symbol] = price

    def set_take_profit(self, symbol: str, price: float) -> None:
        """Устанавливает уровень тейк-профита для символа."""
        self._take_profits[symbol] = price

    def clear_sl_tp(self, symbol: str) -> None:
        """Снимает SL и TP для символа (после закрытия позиции)."""
        self._stop_losses.pop(symbol, None)
        self._take_profits.pop(symbol, None)

    async def check_sl_tp(self, candle: Candle) -> bool:
        """Проверяет, достигла ли свеча уровней SL/TP, и закрывает позицию.

        Вызывайте в начале on_candle() перед логикой сигналов:

            async def on_candle(self, candle):
                self.add_candle_to_history(candle)
                if await self.check_sl_tp(candle):
                    return   # позиция закрыта, дальнейшая логика не нужна
                # ... остальная логика ...

        Принцип проверки (позиционно-нейтральная):
          - Лонг: SL срабатывает когда low ≤ sl_price; TP когда high ≥ tp_price.
          - Шорт: SL срабатывает когда high ≥ sl_price; TP когда low ≤ tp_price.

        При одновременном срабатывании SL имеет приоритет.

        Returns:
            True если ордер на закрытие был отправлен, иначе False.
        """
        symbol = candle.symbol
        pos = self.positions.get(symbol, 0.0)
        if pos == 0.0:
            return False

        sl = self._stop_losses.get(symbol)
        tp = self._take_profits.get(symbol)
        if sl is None and tp is None:
            return False

        hit_sl = hit_tp = False
        if pos > 0:   # лонг
            hit_sl = sl is not None and candle.low <= sl
            hit_tp = tp is not None and candle.high >= tp
        else:         # шорт
            hit_sl = sl is not None and candle.high >= sl
            hit_tp = tp is not None and candle.low <= tp

        if not (hit_sl or hit_tp):
            return False

        exit_reason = 'stop_loss' if hit_sl else 'take_profit'
        close_side = OrderSide.SELL if pos > 0 else OrderSide.BUY
        close_volume = abs(pos)

        order = Order(
            client_order_id=f"sl_tp-{symbol}-{int(candle.timestamp.timestamp())}",
            strategy_name=self.name,
            symbol=symbol,
            side=close_side,
            order_type=OrderType.MARKET,
            volume=close_volume,
        )
        await self.send_order(order)
        self.clear_sl_tp(symbol)
        logger.info(
            f"{self.name}: {exit_reason.upper()} triggered for {symbol} "
            f"pos={pos:.2f} @ candle {candle.timestamp}"
        )
        return True

    # --- Сохранение / загрузка ---
    def save_state(self) -> dict:
        return {
            'positions': self.positions,
            'entry_prices': self.entry_prices,
            'current_equity': self.current_equity,
            'leverage': self.leverage,
            'weight': self.weight,
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
        self.leverage = state.get('leverage', 1.0)
        self.weight = state.get('weight', 1.0)
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
