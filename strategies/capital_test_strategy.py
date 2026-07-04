# strategies/capital_test_strategy.py
import logging
from core.strategy import Strategy
from core.models import Order, OrderSide, OrderType, Candle, Tick
import pandas as pd

logger = logging.getLogger(__name__)


class CapitalTestStrategy(Strategy):
    """
    Тест управления капиталом: покупает на весь доступный капитал
    при пересечении быстрой SMA вверх, закрывает при обратном пересечении.
    """

    def __init__(self, *args, fast: int = 5, slow: int = 15, risk_fraction: float = 1.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.fast = fast
        self.slow = slow
        self.risk_fraction = risk_fraction
        if not self.subscriptions:
            self.subscriptions = [('AFKS', '1m')]

    async def on_tick(self, tick: Tick):
        pass

    async def on_candle(self, candle: Candle):
        self.add_candle_to_history(candle)
        symbol = candle.symbol
        tf = candle.timeframe

        df = self.price_history.get(symbol, {}).get(tf)
        if df is None or len(df) < self.slow:
            return

        close_series = pd.Series(
            df['close'].values,
            index=pd.DatetimeIndex(df['timestamp']),
        )
        sma_fast = close_series.rolling(window=self.fast).mean()
        sma_slow = close_series.rolling(window=self.slow).mean()

        self.indicators[f'sma_fast_{symbol}'] = sma_fast
        self.indicators[f'sma_slow_{symbol}'] = sma_slow

        if len(sma_fast) < 2 or len(sma_slow) < 2:
            return

        pos = self.positions.get(symbol, 0.0)

        # Сигнал на покупку
        if sma_fast.iloc[-2] <= sma_slow.iloc[-2] and sma_fast.iloc[-1] > sma_slow.iloc[-1]:
            if pos == 0:
                price = candle.close
                # get_position_size принимает symbol, price, risk_fraction
                volume = self.get_position_size(symbol, price, risk_fraction=self.risk_fraction)
                if volume <= 0:
                    logger.info(f"{self.name}: недостаточно капитала для входа по {symbol}")
                    return
                order = Order(
                    client_order_id=f"cap-{candle.timestamp.timestamp()}",
                    strategy_name=self.name,
                    symbol=symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    volume=volume,
                )
                await self.send_order(order)
                logger.info(f"{self.name}: BUY {volume:.4f} @ {price:.2f}")

        # Сигнал на продажу
        elif sma_fast.iloc[-2] >= sma_slow.iloc[-2] and sma_fast.iloc[-1] < sma_slow.iloc[-1]:
            if pos > 0:
                price = candle.close
                order = Order(
                    client_order_id=f"cap-{candle.timestamp.timestamp()}",
                    strategy_name=self.name,
                    symbol=symbol,
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    volume=pos,
                )
                await self.send_order(order)
                logger.info(f"{self.name}: SELL {pos:.4f} @ {price:.2f}")

    def get_default_plot_config(self) -> dict:
        if not self.subscriptions:
            return {}
        sym = self.subscriptions[0][0]
        return {"price": [f"sma_fast_{sym}", f"sma_slow_{sym}"]}

    def save_state(self) -> dict:
        state = super().save_state()
        state.update({
            'fast': self.fast,
            'slow': self.slow,
            'risk_fraction': self.risk_fraction,
        })
        return state

    def load_state(self, state: dict):
        super().load_state(state)
        self.fast = state.get('fast', 5)
        self.slow = state.get('slow', 15)
        self.risk_fraction = state.get('risk_fraction', 1.0)
