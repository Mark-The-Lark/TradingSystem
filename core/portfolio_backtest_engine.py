# core/portfolio_backtest_engine.py

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Type
import pandas as pd
import numpy as np

from core.strategy import Strategy
from core.capital_manager import CapitalManager
from core.commission import CommissionModel, FixedCommission
from core.models import Order, OrderSide, OrderType, Candle, Trade, OrderStatus
from core.mocks import MockEventBus, MockOrderManager
from core.metrics import calculate_metrics

logger = logging.getLogger(__name__)

class PortfolioBacktestEngine:
    def __init__(
        self,
        data: Dict[str, pd.DataFrame],          # ticker -> DataFrame (минутные бары)
        strategy_configs: List[dict],           # список конфигураций стратегий
        initial_capital: float = 100_000.0,
        commission: CommissionModel = None,
        execution_model: str = 'next_bar_open'  # 'next_bar_worst' или 'next_bar_open'
    ):
        self.data = data
        self.strategy_configs = strategy_configs
        self.initial_capital = initial_capital
        self.commission = commission or FixedCommission(0.0)
        self.execution_model = execution_model

    def run(self, progress_callback=None) -> dict:
        # ---- 1. Подготовка данных ----
        # Собираем все тикеры, необходимые для подписок стратегий
        all_tickers = set()
        for cfg in self.strategy_configs:
            subs = cfg.get('subscriptions', [])
            for sym, tf in subs:
                if tf != 'tick':
                    all_tickers.add(sym)
        # Проверяем наличие данных
        for ticker in all_tickers:
            if ticker not in self.data:
                raise ValueError(f"Нет данных для {ticker}")

        # Объединяем все временные метки и удаляем дубликаты
        timestamps = sorted(set().union(*(self.data[t].index for t in all_tickers)))
        if not timestamps:
            return self._empty_result()

        # ---- 2. Создаём CapitalManager и стратегии ----
        capital_mgr = CapitalManager(total_capital=self.initial_capital)

        strategies: Dict[str, Strategy] = {}
        # Для каждой стратегии храним список её подписок и отложенные ордера
        pending_orders: Dict[str, List[Order]] = {}  # strategy_name -> list

        for cfg in self.strategy_configs:
            cls = cfg['class']
            name = cfg['name']
            allocation_pct = cfg.get('allocation_pct', 0.0)

            # Создаём стратегию (с моками, бэктест не использует реальный event_bus)
            strategy = cls(
                name=name,
                event_bus=MockEventBus(),
                order_manager=MockOrderManager(),
                mode=cfg.get('mode', 'AUTO'),
                # subscriptions=cfg.get('subscriptions', [])
            )
            strategy.initial_capital = self.initial_capital * allocation_pct / 100.0
            strategy.current_equity = strategy.initial_capital
            strategy._capital_manager = capital_mgr

            # Регистрируем в капитал-менеджере
            capital_mgr.set_strategy(strategy, allocation_pct)

            # Подменяем send_order на добавление в отложенные
            self._patch_send_order(strategy, pending_orders.setdefault(name, []))

            strategies[name] = strategy

        # ---- 3. Главный цикл по времени ----
        portfolio_equity = [(timestamps[0], self.initial_capital)]

        # Для каждой стратегии храним последнее известное эквити для построения кривой
        strategy_equity = {name: [] for name in strategies}

        # Очередь отложенных ордеров (для каждой стратегии)
        # pending_orders[name] уже есть, но нужно также обрабатывать исполнение
        # Мы будем исполнять ордера в начале каждого нового бара (следующая свеча)

        total_bars = len(timestamps)
        last_timestamp = timestamps[0]

        # Словарь для хранения последней цены по тикеру (для расчёта used capital)
        last_prices = {t: self.data[t]['Close'].iloc[0] for t in all_tickers}

        for i, ts in enumerate(timestamps):
            if i % 100 == 0 and progress_callback:
                progress_callback(i, total_bars)

            # ---- 3a. Исполняем отложенные ордера для всех стратегий ----
            for name, orders in pending_orders.items():
                strategy = strategies[name]
                # Для каждого ордера ищем цену исполнения на текущем баре
                for order in orders[:]:  # копируем список
                    symbol = order.symbol
                    if symbol in self.data:
                        # Ближайшая свеча к ts (текущий бар)
                        df = self.data[symbol]
                        # Ищем свечу, соответствующую ts (она уже должна быть, т.к. ts – метка свечи)
                        if ts in df.index:
                            candle_row = df.loc[ts]
                            # Определяем цену исполнения
                            if self.execution_model == 'next_bar_worst':
                                fill_price = candle_row['High'] if order.side == OrderSide.BUY else candle_row['Low']
                            else:  # next_bar_open
                                fill_price = candle_row['Open']
                        else:
                            # Если точного совпадения нет, берём последнюю доступную цену
                            candle_row = df.iloc[-1]
                            fill_price = candle_row['Close']  # запасной вариант

                        # Исполняем ордер (синхронно)
                        self._execute_order(order, fill_price, strategy, ts, last_prices)
                        orders.remove(order)

            # ---- 3b. Подаём свечи стратегиям ----
            for name, strategy in strategies.items():
                for sym, tf in strategy.subscriptions:
                    if tf == 'tick':
                        continue
                    if sym in self.data and ts in self.data[sym].index:
                        row = self.data[sym].loc[ts]
                        candle = Candle(
                            symbol=sym,
                            timeframe=tf,
                            open=row['Open'],
                            high=row['High'],
                            low=row['Low'],
                            close=row['Close'],
                            volume=row['Volume'],
                            timestamp=ts,
                            is_complete=True
                        )
                        # Вызываем обработчик свечи (асинхронный, но мы в синхронном контексте)
                        # Используем asyncio.run для совместимости
                        asyncio.run(strategy.on_candle(candle))

            # ---- 3c. Обновляем общую эквити (сумма эквити всех стратегий) ----
            total_equity = sum(s.current_equity for s in strategies.values())
            portfolio_equity.append((ts, total_equity))

            # Сохраняем историю эквити каждой стратегии
            for name, strategy in strategies.items():
                strategy_equity[name].append((ts, strategy.current_equity))

            # Обновляем последние цены для капитал-менеджера
            for ticker in all_tickers:
                if ts in self.data[ticker].index:
                    last_prices[ticker] = self.data[ticker].loc[ts]['Close']
                # Стратегии обновляют свои _last_prices через add_candle_to_history,
                # но мы можем форсировать обновление, если нужно.

            last_timestamp = ts

        # ---- 4. Сбор результатов ----
        # Общая кривая эквити
        portfolio_eq_df = pd.DataFrame(portfolio_equity, columns=['timestamp', 'equity'])
        portfolio_metrics = calculate_metrics(portfolio_eq_df, trades=None)  # сделки на уровне портфеля пока не собираем

        # Индивидуальные результаты
        individual_results = {}
        for name, strategy in strategies.items():
            eq_curve = pd.DataFrame(strategy_equity[name], columns=['timestamp', 'equity'])
            ind_metrics = calculate_metrics(eq_curve, strategy.trades)
            individual_results[name] = {
                'equity_curve': eq_curve,
                'trades': strategy.trades,
                'metrics': ind_metrics,
                'final_equity': strategy.current_equity
            }

        return {
            'portfolio_equity_curve': portfolio_eq_df,
            'portfolio_metrics': portfolio_metrics,
            'individual_results': individual_results,
            'final_equity': sum(s.current_equity for s in strategies.values())
        }

    # ---- Вспомогательные методы ----
    def _patch_send_order(self, strategy: Strategy, pending: List[Order]):
        """Заменяет send_order на добавление в список pending."""
        async def async_send(order: Order):
            order.strategy_name = strategy.name
            pending.append(order)
            return "pending"
        strategy.send_order = async_send

    def _execute_order(self, order: Order, fill_price: float, strategy: Strategy,
                       timestamp: datetime, last_prices: Dict[str, float]):
        """Исполняет ордер по указанной цене."""
        comm = self.commission.calculate(order.symbol, fill_price, order.volume, order.side)
        delta = order.volume if order.side == OrderSide.BUY else -order.volume
        symbol = order.symbol

        pos = strategy.positions.get(symbol, 0.0)
        entry = strategy.entry_prices.get(symbol)

        if pos * delta >= 0:
            # Увеличение позиции
            if pos == 0:
                strategy.entry_prices[symbol] = fill_price
            else:
                if entry is not None:
                    total_abs = abs(pos) + order.volume
                    strategy.entry_prices[symbol] = (entry * abs(pos) + fill_price * order.volume) / total_abs
                else:
                    strategy.entry_prices[symbol] = fill_price
            strategy.positions[symbol] = pos + delta
            strategy.current_equity -= comm
        else:
            # Закрытие
            if entry is None:
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
                del strategy.entry_prices[symbol]
            elif (new_pos > 0) != (pos > 0):
                strategy.entry_prices[symbol] = fill_price

            # Фиксируем сделку
            direction = 'long' if delta < 0 else 'short'
            strategy.trades.append(Trade(
                entry_time=timestamp,
                exit_time=timestamp,
                symbol=symbol,
                direction=direction,
                entry_price=entry,
                exit_price=fill_price,
                volume=close_volume,
                commission=comm,
                slippage=0.0,
                pnl=pnl,
                exit_reason='signal'
            ))

        # Обновляем последнюю цену
        last_prices[symbol] = fill_price
        strategy._last_prices[symbol] = fill_price

    def _empty_result(self):
        return {
            'portfolio_equity_curve': pd.DataFrame(columns=['timestamp', 'equity']),
            'portfolio_metrics': {},
            'individual_results': {},
            'final_equity': 0.0
        }