# core/backtest_engine.py

import asyncio
import logging
import pandas as pd
from datetime import datetime
from typing import Dict, Type, Optional, Callable, List
from core.strategy import Strategy
from core.models import Order, OrderSide, Candle, Trade
from core.commission import CommissionModel, FixedCommission
from core.metrics import calculate_metrics
from core.mocks import MockEventBus, MockOrderManager

logger = logging.getLogger(__name__)


class BacktestEngine:
    """
    Одиночный бэктестер: один символ, одна стратегия.
    Стратегия создаётся без symbol/timeframes (новый API).
    Данные подаются по subscriptions стратегии; если их нет — по symbol из strategy_params.
    """

    def __init__(
        self,
        data: Dict[str, pd.DataFrame],       # ticker -> DataFrame (OHLCV)
        strategy_class: Type[Strategy],
        strategy_params: dict,                # name, mode, [state]
        initial_capital: float = 100_000.0,
        commission: Optional[CommissionModel] = None,
        execution_model: str = 'next_bar_open',  # 'next_bar_open' | 'next_bar_worst'
    ):
        self.data = data
        self.strategy_class = strategy_class
        self.strategy_params = strategy_params
        self.initial_capital = initial_capital
        self.commission = commission or FixedCommission(0.0)
        self.execution_model = execution_model

    def run(
        self,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> dict:
        # Создаём стратегию через новый API (без symbol/timeframes)
        event_bus = MockEventBus()
        order_manager = MockOrderManager()

        strategy = self.strategy_class(
            name=self.strategy_params.get('name', 'backtest'),
            event_bus=event_bus,
            order_manager=order_manager,
            mode=self.strategy_params.get('mode', 'AUTO'),
        )
        strategy.initial_capital = self.initial_capital
        strategy.current_equity = self.initial_capital

        if 'state' in self.strategy_params:
            strategy.load_state(self.strategy_params['state'])

        # Определяем тикеры/таймфреймы для подачи свечей
        subscriptions = strategy.subscriptions
        if not subscriptions:
            # Fallback: берём symbol из params и таймфрейм 1m
            symbol = self.strategy_params.get('symbol')
            if symbol:
                subscriptions = [(symbol, '1m')]
            else:
                return self._empty_result(error="strategy.subscriptions пуст и symbol не указан в params")

        # Проверяем наличие данных для всех тикеров
        for sym, tf in subscriptions:
            if tf != 'tick' and sym not in self.data:
                return self._empty_result(error=f"Нет данных для символа {sym}")

        # Строим общий временной ряд из всех подписок
        all_timestamps = set()
        for sym, tf in subscriptions:
            if tf != 'tick' and sym in self.data:
                all_timestamps.update(self.data[sym].index)
        timestamps = sorted(all_timestamps)

        if not timestamps:
            return self._empty_result()

        logger.info(
            f"Запуск бэктеста: {[sym for sym,_ in subscriptions]}, "
            f"свечей: {len(timestamps)}, модель: {self.execution_model}"
        )
        if progress_callback:
            progress_callback(0, len(timestamps))

        # Отложенные ордера: symbol -> list[Order]
        pending_orders: List[Order] = []

        # Патчим send_order
        self._patch_send_order(strategy, pending_orders)

        equity_curve = [(timestamps[0], self.initial_capital)]

        async def _run_backtest():
            for i, ts in enumerate(timestamps):
                if i % 100 == 0:
                    logger.debug(f"Свеча {i}/{len(timestamps)}")
                    if progress_callback:
                        progress_callback(i, len(timestamps))

                # 1. Исполняем отложенные ордера
                for order in list(pending_orders):
                    sym = order.symbol
                    if sym in self.data and ts in self.data[sym].index:
                        row = self.data[sym].loc[ts]
                        self._execute_order(order, row, strategy, ts)
                pending_orders.clear()

                # 2. Подаём свечи стратегии
                for sym, tf in subscriptions:
                    if tf == 'tick':
                        continue
                    if sym in self.data and ts in self.data[sym].index:
                        row = self.data[sym].loc[ts]
                        candle = Candle(
                            symbol=sym, timeframe=tf,
                            open=row['Open'], high=row['High'],
                            low=row['Low'], close=row['Close'],
                            volume=row['Volume'],
                            timestamp=ts, is_complete=True,
                        )
                        await strategy.on_candle(candle)

                # 3. Фиксируем эквити
                equity_curve.append((ts, strategy.current_equity))

        asyncio.run(_run_backtest())

        eq_df = pd.DataFrame(equity_curve, columns=['timestamp', 'equity'])
        metrics = calculate_metrics(eq_df, strategy.trades)
        logger.info(
            f"Бэктест завершён. Сделок: {len(strategy.trades)}, "
            f"финальная эквити: {strategy.current_equity:.2f}"
        )

        return {
            'equity_curve': eq_df,
            'trades': strategy.trades,
            'metrics': metrics,
            'final_equity': strategy.current_equity,
            'num_candles': len(timestamps),
        }

    def _execute_order(self, order: Order, row: pd.Series, strategy: Strategy, timestamp: datetime):
        """Исполняет ордер по Open следующего бара (или по High/Low при next_bar_worst)."""
        symbol = order.symbol
        if self.execution_model == 'next_bar_worst':
            fill_price = row['High'] if order.side == OrderSide.BUY else row['Low']
        else:
            fill_price = row['Open']

        comm = self.commission.calculate(symbol, fill_price, order.volume, order.side)
        delta = order.volume if order.side == OrderSide.BUY else -order.volume

        pos = strategy.positions.get(symbol, 0.0)
        entry = strategy.entry_prices.get(symbol)

        if pos * delta >= 0:  # Наращиваем / открываем позицию
            if pos == 0:
                strategy.entry_prices[symbol] = fill_price
            elif entry is not None:
                total_abs = abs(pos) + order.volume
                strategy.entry_prices[symbol] = (
                    entry * abs(pos) + fill_price * order.volume
                ) / total_abs
            else:
                strategy.entry_prices[symbol] = fill_price
            strategy.positions[symbol] = pos + delta
            strategy.current_equity -= comm

        else:  # Закрываем / переворачиваем позицию
            if entry is None:
                logger.warning(f"Закрытие без цены входа по {symbol}, пропускаем")
                return
            close_volume = min(abs(delta), abs(pos))
            if pos > 0:
                pnl = (fill_price - entry) * close_volume - comm
            else:
                pnl = (entry - fill_price) * close_volume - comm

            strategy.current_equity += pnl
            new_pos = pos + delta
            strategy.positions[symbol] = new_pos

            if new_pos == 0:
                strategy.entry_prices.pop(symbol, None)
            elif (new_pos > 0) != (pos > 0):  # переворот
                strategy.entry_prices[symbol] = fill_price

            direction = 'long' if delta < 0 else 'short'
            strategy.trades.append(Trade(
                entry_time=timestamp, exit_time=timestamp,
                symbol=symbol,
                direction=direction,
                entry_price=entry,
                exit_price=fill_price,
                volume=close_volume,
                commission=comm,
                slippage=0.0,
                pnl=pnl,
                exit_reason='signal',
            ))

        strategy._last_prices[symbol] = fill_price

    def _patch_send_order(self, strategy: Strategy, pending_orders: List[Order]):
        async def async_send(order: Order) -> str:
            pending_orders.append(order)
            return "pending"
        strategy.send_order = async_send

    def _empty_result(self, error: str = None) -> dict:
        return {
            'equity_curve': pd.DataFrame(columns=['timestamp', 'equity']),
            'trades': [],
            'metrics': {},
            'final_equity': self.initial_capital,
            'num_candles': 0,
            'error': error,
        }
