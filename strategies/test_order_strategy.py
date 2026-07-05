from core.strategy import Strategy
from core.models import Order, OrderSide, OrderType
import logging

logger = logging.getLogger(__name__)

class TestOrderStrategy(Strategy):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.step = 0
        if not self.subscriptions:
            # По умолчанию один символ – можно задать через параметры
            self.subscriptions = [('AKU6', '1m')]
            self.symbol = self.subscriptions[0][0]

    async def on_init(self):
        logger.info(f"{self.name}: TestOrderStrategy initialized, symbol={self.symbol}")

    async def on_candle(self, candle):
        if self.step >= 3:
            return
        if candle.symbol != self.symbol:
            return
        self.add_candle_to_history(candle)

        if self.step == 0:
            # Отправляем рыночный ордер на покупку
            order = Order(
                client_order_id=f"{self.name}_buy_{int(candle.timestamp.timestamp())}",
                strategy_name=self.name,
                symbol=self.symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                volume=1,
            )
            await self.send_order(order)
            self.step = 1
            logger.info(f"{self.name}: Отправлен ордер на покупку {self.symbol} (1 лот)")

        elif self.step == 1:
            # Ждём открытия позиции
            pos = self.positions.get(self.symbol, 0.0)
            if pos > 0:
                order = Order(
                    client_order_id=f"{self.name}_sell_{int(candle.timestamp.timestamp())}",
                    strategy_name=self.name,
                    symbol=self.symbol,
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    volume=abs(pos),
                )
                await self.send_order(order)
                self.step = 2
                logger.info(f"{self.name}: Отправлен ордер на продажу {self.symbol} (закрытие {abs(pos)})")
            else:
                logger.debug(f"{self.name}: Позиция ещё не открыта, ждём...")

        elif self.step == 2:
            pos = self.positions.get(self.symbol, 0.0)
            if pos == 0:
                self.step = 3
                logger.info(f"{self.name}: Позиция закрыта, тест завершён")
                self.set_status('STOPPED')
            else:
                logger.debug(f"{self.name}: Позиция ещё не закрыта, ждём...")

    async def on_tick(self, tick):
        pass