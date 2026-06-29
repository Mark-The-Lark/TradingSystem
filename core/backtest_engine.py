# core/backtest_engine.py (замена)

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
    def __init__(
        self,
        data: Dict[str, pd.DataFrame],
        strategy_class: Type[Strategy],
        strategy_params: dict,
        initial_capital: float = 100_000.0,
        commission: Optional[CommissionModel] = None,
        execution_model: str = 'next_bar_worst'  # 'current_close' или 'next_bar_worst'
    ):
        self.data = data
        self.strategy_class = strategy_class
        self.strategy_params = strategy_params
        self.initial_capital = initial_capital
        self.commission = commission or FixedCommission(0.0)
        self.execution_model = execution_model

    def run(
        self,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> dict:
        symbol = self.strategy_params.get('symbol')
        if symbol not in self.data:
            raise ValueError(f"Нет данных для символа {symbol}")

        df = self.data[symbol].copy()
        if df.empty:
            return self._empty_result()

        logger.info(f"Запуск бэктеста: {symbol}, свечей: {len(df)}, модель: {self.execution_model}")
        if progress_callback:
            progress_callback(0, len(df))

        # Моки
        event_bus = MockEventBus()
        order_manager = MockOrderManager()

        # Стратегия
        strategy = self.strategy_class(
            name=self.strategy_params.get('name', 'backtest'),
            symbol=symbol,
            event_bus=event_bus,
            order_manager=order_manager,
            mode=self.strategy_params.get('mode', 'AUTO'),
            timeframes=self.strategy_params.get('timeframes', ['1m'])
        )
        strategy.initial_capital = self.initial_capital
        strategy.current_equity = self.initial_capital
        if 'state' in self.strategy_params:
            strategy.load_state(self.strategy_params['state'])

        # Переменные для отложенных ордеров
        pending_orders: List[Order] = []  # ордера, ожидающие исполнения на следующем баре
        equity_curve = [(df.index[0], self.initial_capital)]
        strategy._bt_entry_price = None  # используется в _patch_send_order

        # Подмена send_order (добавляет ордер в очередь вместо немедленного исполнения)
        self._patch_send_order(strategy, pending_orders)

        try:
            for i, (ts, row) in enumerate(df.iterrows()):
                if i % 100 == 0:
                    logger.debug(f"Свеча {i}/{len(df)}")
                    if progress_callback:
                        progress_callback(i, len(df))

                candle = Candle(
                    symbol=symbol, timeframe='1m',
                    open=row['Open'], high=row['High'], low=row['Low'],
                    close=row['Close'], volume=row['Volume'],
                    timestamp=ts, is_complete=True
                )

                # 1. Сначала исполняем отложенные ордера по ценам этой свечи
                for order in pending_orders:
                    self._execute_order(order, candle, strategy, ts)

                pending_orders.clear()

                # 2. Обрабатываем свечу стратегией (она может добавить новые ордера)
                asyncio.run(strategy.on_candle(candle))

                # 3. Фиксируем эквити (после возможных исполнений и сигналов)
                equity_curve.append((ts, strategy.current_equity))

        except Exception as e:
            logger.exception(f"Ошибка на свече {i}: {e}")
            return self._empty_result(error=str(e))

        # Метрики
        eq_df = pd.DataFrame(equity_curve, columns=['timestamp', 'equity'])
        metrics = calculate_metrics(eq_df, strategy.trades)
        logger.info(f"Бэктест завершён. Сделок: {len(strategy.trades)}, финальная эквити: {strategy.current_equity:.2f}")

        return {
            'equity_curve': eq_df,
            'trades': strategy.trades,
            'metrics': metrics,
            'final_equity': strategy.current_equity,
            'num_candles': len(df),
        }

    def _execute_order(self, order: Order, candle: Candle, strategy: Strategy, timestamp: datetime):
        """Исполняет ордер по худшей цене следующей свечи (или по Open)."""
        # Выбор цены исполнения (можно изменить на candle.open при необходимости)
        # if order.side == OrderSide.BUY:
        #     fill_price = candle.high   # худшая для покупки
        # else:
        #     fill_price = candle.low    # худшая для продажи
        fill_price = candle.open     # раскомментировать для исполнения по Open

        comm = self.commission.calculate(order.symbol, fill_price, order.volume, order.side)
        delta = order.volume if order.side == OrderSide.BUY else -order.volume

        if strategy.position * delta >= 0:          # Наращиваем позицию (в ту же сторону)
            if strategy.position == 0:
                strategy._bt_entry_price = fill_price
            else:
                total_abs = abs(strategy.position) + order.volume
                strategy._bt_entry_price = (
                    strategy._bt_entry_price * abs(strategy.position) + fill_price * order.volume
                ) / total_abs
            strategy.position += delta
            strategy.current_equity -= comm

        else:                                       # Закрываем позицию (частично или полностью)
            close_volume = min(abs(delta), abs(strategy.position))
            if strategy.position > 0:               # Закрываем лонг
                pnl = (fill_price - strategy._bt_entry_price) * close_volume - comm
            else:                                   # Закрываем шорт
                pnl = (strategy._bt_entry_price - fill_price) * close_volume - comm

            strategy.current_equity += pnl
            strategy.position += delta

            # Фиксируем сделку
            direction = 'long' if delta < 0 else 'short'  # если продаём, значит закрывали лонг
            strategy.trades.append(Trade(
                entry_time=timestamp, exit_time=timestamp,
                symbol=order.symbol,
                direction=direction,
                entry_price=strategy._bt_entry_price,
                exit_price=fill_price,
                volume=close_volume,
                commission=comm,
                slippage=0.0,
                pnl=pnl,
                exit_reason='signal'
            ))

            # Сброс или обновление цены входа
            if strategy.position == 0:
                strategy._bt_entry_price = None
            elif (strategy.position > 0) != (delta > 0):  # произошёл переворот позиции
                strategy._bt_entry_price = fill_price

    def _patch_send_order(self, strategy: Strategy, pending_orders: List[Order]):
        """Подменяет send_order, чтобы он добавлял ордер в список отложенных."""
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
            'error': error
        }