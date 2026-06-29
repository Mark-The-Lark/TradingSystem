# strategies/capital_test_strategy.py
import logging
from core.strategy import Strategy
from core.models import Order, OrderSide, OrderType, Candle, Tick
import pandas as pd
logger = logging.getLogger(__name__)

class CapitalTestStrategy(Strategy):
    """
    Простая стратегия для тестирования управления капиталом.
    Покупает на весь доступный капитал при появлении быстрого SMA над медленным,
    продаёт при обратном пересечении.
    Объём позиции рассчитывается через get_position_size().
    """
    def __init__(self, *args, fast=5, slow=15, risk_fraction=1.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.fast = fast
        self.slow = slow
        self.risk_fraction = risk_fraction  # доля доступного капитала для использования

    async def on_candle(self, candle: Candle):
        self.add_candle_to_history(candle)
        df = self.price_history.get(candle.timeframe)
        if df is None or len(df) < self.slow:
            return

        # Рассчитываем SMA
        ts = df['timestamp']
        close = df['close'].values
        close_series = pd.Series(close, index=pd.DatetimeIndex(ts))

        sma_fast = close_series.rolling(window=self.fast).mean()
        sma_slow = close_series.rolling(window=self.slow).mean()
        self.indicators['sma_fast'] = sma_fast
        self.indicators['sma_slow'] = sma_slow

        if len(sma_fast) < 2 or len(sma_slow) < 2:
            return

        # Сигнал на покупку
        if sma_fast.iloc[-2] <= sma_slow.iloc[-2] and sma_fast.iloc[-1] > sma_slow.iloc[-1]:
            if self.position == 0:
                price = candle.close
                volume = self.get_position_size(price, risk_fraction=self.risk_fraction)
                if volume <= 0:
                    logger.info(f"{self.name}: недостаточно капитала для входа")
                    return
                order = Order(
                    client_order_id=f"cap-{candle.timestamp.timestamp()}",
                    strategy_name=self.name,
                    symbol=self.symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    volume=volume
                )
                await self.send_order(order)
                logger.info(f"{self.name}: BUY {volume:.4f} @ {price:.2f}")

        # Сигнал на продажу
        elif sma_fast.iloc[-2] >= sma_slow.iloc[-2] and sma_fast.iloc[-1] < sma_slow.iloc[-1]:
            if self.position > 0:
                price = candle.close
                # Продаём всю позицию
                order = Order(
                    client_order_id=f"cap-{candle.timestamp.timestamp()}",
                    strategy_name=self.name,
                    symbol=self.symbol,
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    volume=self.position  # закрываем полностью
                )
                await self.send_order(order)
                logger.info(f"{self.name}: SELL {self.position:.4f} @ {price:.2f}")

    async def on_tick(self, tick: Tick):
        pass

    def save_state(self) -> dict:
        state = super().save_state()
        state.update({'fast': self.fast, 'slow': self.slow, 'risk_fraction': self.risk_fraction})
        return state

    def load_state(self, state: dict):
        super().load_state(state)
        self.fast = state.get('fast', 5)
        self.slow = state.get('slow', 15)
        self.risk_fraction = state.get('risk_fraction', 1.0)