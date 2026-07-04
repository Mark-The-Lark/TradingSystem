# core/portfolio_backtest_engine.py

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Type
import pandas as pd

from core.strategy import Strategy
from core.capital_manager import CapitalManager
from core.commission import CommissionModel, FixedCommission
from core.models import Order, OrderSide, Candle, Trade
from core.mocks import MockEventBus, MockOrderManager
from core.metrics import calculate_metrics

logger = logging.getLogger(__name__)


class PortfolioBacktestEngine:
    """
    Портфельный бэктестер: несколько стратегий, общий CapitalManager.
    Ордера исполняются по ценам следующего бара (next_bar_open или next_bar_worst).
    Весь цикл выполняется внутри одного asyncio.run(), что на порядок быстрее
    чем вызывать asyncio.run() на каждой свече.
    """

    def __init__(
        self,
        data: Dict[str, pd.DataFrame],       # ticker -> DataFrame (OHLCV)
        strategy_configs: List[dict],         # список конфигов стратегий
        initial_capital: float = 100_000.0,
        commission: CommissionModel = None,
        execution_model: str = 'next_bar_open',  # 'next_bar_open' | 'next_bar_worst'
    ):
        self.data = data
        self.strategy_configs = strategy_configs
        self.initial_capital = initial_capital
        self.commission = commission or FixedCommission(0.0)
        self.execution_model = execution_model

    def run(self, progress_callback=None) -> dict:
        # ---- 1. Собираем все необходимые тикеры из подписок стратегий ----
        all_tickers: set = set()
        for cfg in self.strategy_configs:
            for sym, tf in cfg.get('subscriptions', []):
                if tf != 'tick':
                    all_tickers.add(sym)

        for ticker in all_tickers:
            if ticker not in self.data:
                raise ValueError(f"Нет данных для тикера '{ticker}'")

        if not all_tickers:
            return self._empty_result()

        # Единый временной ряд
        timestamps = sorted(set().union(*(self.data[t].index for t in all_tickers)))
        if not timestamps:
            return self._empty_result()

        # ---- 2. Создаём CapitalManager и стратегии ----
        capital_mgr = CapitalManager(total_capital=self.initial_capital)
        strategies: Dict[str, Strategy] = {}
        pending_orders: Dict[str, List[Order]] = {}   # strategy_name -> list
        last_prices = {t: self.data[t]['Close'].iloc[0] for t in all_tickers}

        for cfg in self.strategy_configs:
            cls = cfg['class']
            name = cfg['name']
            allocation_pct = cfg.get('allocation_pct', 0.0)
            kwargs = cfg.get('kwargs', {})

            strategy = cls(
                name=name,
                event_bus=MockEventBus(),
                order_manager=MockOrderManager(),
                mode=cfg.get('mode', 'AUTO'),
                subscriptions=cfg.get('subscriptions', []),  # <-- ВАЖНО: передаём подписки
                **kwargs,
            )
            strategy.initial_capital = self.initial_capital * allocation_pct / 100.0
            strategy.current_equity = strategy.initial_capital
            strategy._capital_manager = capital_mgr
            capital_mgr.set_strategy(strategy, allocation_pct)

            # Патчим send_order
            self._patch_send_order(strategy, pending_orders.setdefault(name, []))
            strategies[name] = strategy

        # ---- 3. Главный цикл — один asyncio.run() для всего прогона ----
        portfolio_equity: List[tuple] = [(timestamps[0], self.initial_capital)]
        strategy_equity: Dict[str, List[tuple]] = {name: [] for name in strategies}
        total_bars = len(timestamps)

        async def _main_loop():
            for i, ts in enumerate(timestamps):
                if i % 100 == 0 and progress_callback:
                    progress_callback(i, total_bars)

                # 3a. Исполняем отложенные ордера (по ценам текущего бара)
                for name, orders in pending_orders.items():
                    strategy = strategies[name]
                    for order in list(orders):
                        sym = order.symbol
                        if sym in self.data and ts in self.data[sym].index:
                            row = self.data[sym].loc[ts]
                            self._execute_order(order, row, strategy, ts, last_prices)
                    orders.clear()

                # 3b. Подаём свечи стратегиям
                for name, strategy in strategies.items():
                    for sym, tf in strategy.subscriptions:
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

                # 3c. Обновляем эквити
                total_equity = sum(s.current_equity for s in strategies.values())
                portfolio_equity.append((ts, total_equity))
                for name, strategy in strategies.items():
                    strategy_equity[name].append((ts, strategy.current_equity))

                # 3d. Обновляем last_prices
                for ticker in all_tickers:
                    if ts in self.data[ticker].index:
                        last_prices[ticker] = self.data[ticker].loc[ts]['Close']

        asyncio.run(_main_loop())

        # ---- 4. Сбор результатов ----
        portfolio_eq_df = pd.DataFrame(portfolio_equity, columns=['timestamp', 'equity'])
        portfolio_metrics = calculate_metrics(portfolio_eq_df, trades=None)

        individual_results = {}
        for name, strategy in strategies.items():
            eq_curve = pd.DataFrame(strategy_equity[name], columns=['timestamp', 'equity'])
            ind_metrics = calculate_metrics(eq_curve, strategy.trades)
            individual_results[name] = {
                'equity_curve': eq_curve,
                'trades': strategy.trades,
                'metrics': ind_metrics,
                'final_equity': strategy.current_equity,
            }

        return {
            'portfolio_equity_curve': portfolio_eq_df,
            'portfolio_metrics': portfolio_metrics,
            'individual_results': individual_results,
            'final_equity': sum(s.current_equity for s in strategies.values()),
        }

    # ---- Вспомогательные методы ----
    def _patch_send_order(self, strategy: Strategy, pending: List[Order]):
        async def async_send(order: Order):
            order.strategy_name = strategy.name
            pending.append(order)
            return "pending"
        strategy.send_order = async_send

    def _execute_order(
        self,
        order: Order,
        row: pd.Series,
        strategy: Strategy,
        timestamp: datetime,
        last_prices: Dict[str, float],
    ):
        """Исполняет ордер по Open (или High/Low при next_bar_worst)."""
        symbol = order.symbol
        if self.execution_model == 'next_bar_worst':
            fill_price = row['High'] if order.side == OrderSide.BUY else row['Low']
        else:
            fill_price = row['Open']

        comm = self.commission.calculate(symbol, fill_price, order.volume, order.side)
        delta = order.volume if order.side == OrderSide.BUY else -order.volume

        pos = strategy.positions.get(symbol, 0.0)
        entry = strategy.entry_prices.get(symbol)

        if pos * delta >= 0:  # Наращиваем позицию
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

        else:  # Закрываем позицию
            if entry is None:
                return
            close_volume = min(abs(delta), abs(pos))
            pnl = (
                (fill_price - entry) * close_volume - comm
                if pos > 0
                else (entry - fill_price) * close_volume - comm
            )
            strategy.current_equity += pnl
            new_pos = pos + delta
            strategy.positions[symbol] = new_pos

            if new_pos == 0:
                strategy.entry_prices.pop(symbol, None)
            elif (new_pos > 0) != (pos > 0):
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

        last_prices[symbol] = fill_price
        strategy._last_prices[symbol] = fill_price

    def _empty_result(self):
        return {
            'portfolio_equity_curve': pd.DataFrame(columns=['timestamp', 'equity']),
            'portfolio_metrics': {},
            'individual_results': {},
            'final_equity': 0.0,
        }
