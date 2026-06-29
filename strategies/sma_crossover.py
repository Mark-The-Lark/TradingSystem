# import logging
# from core.strategy import Strategy
# from core.models import Order, OrderSide, OrderType, Tick, Candle
# import pandas as pd
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
# )
# logger = logging.getLogger(__name__)
# class SMACrossoverStrategy(Strategy):
#     def __init__(self, *args, fast=10, slow=30, **kwargs):
#         super().__init__(*args, **kwargs)
#         self.fast = fast
#         self.slow = slow
#         self.indicators = {}
#         self._last_signal = None

#     async def on_candle(self, candle: Candle):
#         self.add_candle_to_history(candle)
#         df = self.price_history.get(candle.timeframe)
#         if df is None or len(df) < self.slow:
#             return

#         # Переводим в DatetimeIndex для корректной работы с индикаторами
#         ts = df['timestamp']
#         close = df['close'].values
#         # Создаём Series с DatetimeIndex
#         close_series = pd.Series(close, index=pd.DatetimeIndex(ts))

#         sma_fast = close_series.rolling(window=self.fast).mean()
#         sma_slow = close_series.rolling(window=self.slow).mean()

#         # Сохраняем с правильным индексом
#         self.indicators['sma_fast'] = sma_fast
#         self.indicators['sma_slow'] = sma_slow

#         # Сигналы
#         if len(sma_fast) < 2 or len(sma_slow) < 2:
#             return
#         if sma_fast.iloc[-2] <= sma_slow.iloc[-2] and sma_fast.iloc[-1] > sma_slow.iloc[-1]:
#             if self.position == 0:
#                 order = Order(
#                     client_order_id=f"sma-{candle.timestamp.timestamp()}",
#                     strategy_name=self.name,
#                     symbol=self.symbol,
#                     side=OrderSide.BUY,
#                     order_type=OrderType.MARKET,
#                     volume=1
#                 )
#                 await self.send_order(order)
#         elif sma_fast.iloc[-2] >= sma_slow.iloc[-2] and sma_fast.iloc[-1] < sma_slow.iloc[-1]:
#             if self.position > 0:
#                 order = Order(
#                     client_order_id=f"sma-{candle.timestamp.timestamp()}",
#                     strategy_name=self.name,
#                     symbol=self.symbol,
#                     side=OrderSide.SELL,
#                     order_type=OrderType.MARKET,
#                     volume=1
#                 )
#                 await self.send_order(order)

#     async def on_tick(self, tick: Tick):
#         pass


from core.strategy import Strategy
from core.models import Order, OrderSide, OrderType, Candle, Tick
import pandas as pd

class SMACrossoverStrategy(Strategy):
    def __init__(self, *args, fast=10, slow=30, **kwargs):
        super().__init__(*args, **kwargs)
        self.fast = fast
        self.slow = slow
        if not self.subscriptions:
            # По умолчанию один символ – можно задать через параметры
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

        ts = df['timestamp']
        close = df['close'].values
        # Создаём Series с DatetimeIndex
        close_series = pd.Series(close, index=pd.DatetimeIndex(ts))
        sma_fast = close_series.rolling(window=self.fast).mean()
        sma_slow = close_series.rolling(window=self.slow).mean()

        self.indicators[f'sma_fast_{symbol}'] = sma_fast
        self.indicators[f'sma_slow_{symbol}'] = sma_slow

        if len(sma_fast) < 2 or len(sma_slow) < 2:
            return

        pos = self.positions.get(symbol, 0.0)

        if sma_fast.iloc[-2] <= sma_slow.iloc[-2] and sma_fast.iloc[-1] > sma_slow.iloc[-1]:
            if pos == 0:
                price = candle.close
                order = Order(
                    client_order_id=f"sma-{candle.timestamp.timestamp()}",
                    strategy_name=self.name,
                    symbol=symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    volume=1
                )
                await self.send_order(order)

        elif sma_fast.iloc[-2] >= sma_slow.iloc[-2] and sma_fast.iloc[-1] < sma_slow.iloc[-1]:
            if pos > 0:
                price = candle.close
                order = Order(
                    client_order_id=f"sma-{candle.timestamp.timestamp()}",
                    strategy_name=self.name,
                    symbol=symbol,
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    volume=pos
                )
                await self.send_order(order)
    def get_default_plot_config(self) -> dict:
        if not self.subscriptions:
            return {}
        sym = self.subscriptions[0][0]  # первый символ
        return {
            "price": [f"sma_fast_{sym}", f"sma_slow_{sym}"]
        }