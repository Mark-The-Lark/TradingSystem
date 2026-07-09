
"""
QuikGateway — полностью событийный шлюз для QUIK на основе библиотеки quik-python.

Использует:
- quik.events.add_on_order() — для получения событий по заявкам (изменение статуса)
- quik.events.add_on_trade() — для получения событий исполнения (сделки)
- quik.events.add_on_trans_reply() — для подтверждения транзакций
- quik.events.add_on_all_trade() — для получения рыночных сделок (тиков)
- quik.candles.add_new_candle_handler() — для новых свечей
"""

import asyncio
import logging
from typing import Dict, List, Optional, Set, Tuple, Any
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from quik_python import Quik, LuaException
from quik_python.data_structures import (
    CandleInterval,
    Candle,
    Order,
    Trade,
    TransactionReply,
    AllTrade,
    OrderBook,
    Operation,
    TransactionType,
)
from quik_python.exceptions import TimeoutException

from core.gateway import BaseGateway
from core.events import (
    EventBus,
    CandleEvent,
    TickEvent,
    OrderPlacedEvent,
    OrderFilledEvent,
    OrderCancelledEvent,
    ConnectionStateEvent,
)
from core.models import Order as OurOrder, OrderSide, OrderType, Candle, Tick

logger = logging.getLogger(__name__)

_TF_TO_INTERVAL: Dict[str, CandleInterval] = {
    '1m': CandleInterval.M1,
    '2m': CandleInterval.M2,
    '3m': CandleInterval.M3,
    '4m': CandleInterval.M4,
    '5m': CandleInterval.M5,
    '6m': CandleInterval.M6,
    '10m': CandleInterval.M10,
    '15m': CandleInterval.M15,
    '20m': CandleInterval.M20,
    '30m': CandleInterval.M30,
    '1h': CandleInterval.H1,
    '2h': CandleInterval.H2,
    '4h': CandleInterval.H4,
    '1d': CandleInterval.D1,
    '1w': CandleInterval.W1,
    '1M': CandleInterval.MN,
}


class QuikGateway(BaseGateway):
    def __init__(
        self,
        event_bus: EventBus,
        class_code_map: Dict[str, str],
        account: str,
        host: str = 'localhost',
        poll_interval: float = 0.5,  # оставим на случай, но не используется
    ):
        super().__init__(event_bus)
        self.class_code_map = class_code_map
        self.account = account
        self.host = host

        self._quik: Optional[Quik] = None
        self._connected = False
        self._last_trade_price: Dict[str, float] = {}

        # Маппинг client_order_id → order_num
        self._client_to_quik_order: Dict[str, int] = {}
        self._quik_order_to_client: Dict[int, str] = {}
        self._client_to_symbol: Dict[str, Tuple[str, str]] = {}   # client_id → (symbol, class_code)
        self._client_to_strategy: Dict[str, str] = {}             # client_id → strategy_name

        # Хранилище обработчиков для отписки
        self._order_handler = None
        self._trade_handler = None
        self._trans_reply_handler = None
        self._all_trade_handler = None
        self._candle_handlers: List[callable] = []

        # Подписки на свечи (для информации)
        self._subscribed_candles: Set[Tuple[str, str, CandleInterval]] = set()

    # ===================== Подключение / отключение =====================

    async def connect(self) -> None:
        try:
            self._quik = Quik(host=self.host)
            await self._quik.initialize()
            if not await self._quik.service.is_connected():
                raise ConnectionError("Терминал QUIK не подключён к серверу брокера.")

            # --- Регистрация обработчиков событий ---

            # 1. Заявки (изменение статуса)
            def on_order(order: Order):
                asyncio.create_task(self._handle_order_event(order))
            self._quik.events.add_on_order(on_order)
            self._order_handler = on_order

            # 2. Сделки (исполнения)
            def on_trade(trade: Trade):
                asyncio.create_task(self._handle_trade_event(trade))
            self._quik.events.add_on_trade(on_trade)
            self._trade_handler = on_trade

            # 3. Ответы на транзакции (подтверждение)
            def on_trans_reply(reply: TransactionReply):
                asyncio.create_task(self._handle_trans_reply(reply))
            self._quik.events.add_on_trans_reply(on_trans_reply)
            self._trans_reply_handler = on_trans_reply

            # 4. Все рыночные сделки (тики) — опционально
            def on_all_trade(all_trade: AllTrade):
                asyncio.create_task(self._handle_all_trade(all_trade))
            self._quik.events.add_on_all_trade(on_all_trade)
            self._all_trade_handler = on_all_trade

            # 5. Свечи — через CandleFunctions (обработчик регистрируется позже, при подписке)
            # Обработчик для свечей будет добавляться в _subscribe_candle

            self._connected = True
            await self.event_bus.publish('connection', ConnectionStateEvent(state='connected'))
            logger.info("QUIK gateway подключён (событийный режим)")

        except LuaException as e:
            logger.error(f"Ошибка Lua: {e}")
            raise
        except Exception as e:
            logger.error(f"Ошибка подключения: {e}", exc_info=True)
            raise

    async def disconnect(self) -> None:
        self._connected = False
        quik = self._quik  # сохраняем ссылку
        self._quik = None  # сбрасываем заранее, чтобы не было повторных вызовов

        if quik is None:
            await self.event_bus.publish('connection', ConnectionStateEvent(state='disconnected'))
            logger.info("QUIK gateway уже отключён")
            return

        try:
            # Удаляем обработчики событий
            if self._order_handler:
                try:
                    quik.events.remove_on_order(self._order_handler)
                except Exception as e:
                    logger.debug(f"Ошибка удаления обработчика заявок: {e}")
            if self._trade_handler:
                try:
                    quik.events.remove_on_trade(self._trade_handler)
                except Exception as e:
                    logger.debug(f"Ошибка удаления обработчика сделок: {e}")
            if self._trans_reply_handler:
                try:
                    quik.events.remove_on_trans_reply(self._trans_reply_handler)
                except Exception as e:
                    logger.debug(f"Ошибка удаления обработчика транзакций: {e}")
            if self._all_trade_handler:
                try:
                    quik.events.remove_on_all_trade(self._all_trade_handler)
                except Exception as e:
                    logger.debug(f"Ошибка удаления обработчика тиков: {e}")
            for handler in self._candle_handlers:
                try:
                    quik.candles.remove_new_candle_handler(handler)
                except Exception as e:
                    logger.debug(f"Ошибка удаления обработчика свечей: {e}")
            # Останавливаем сервис
            if hasattr(quik, 'stop_service'):
                quik.stop_service()
            elif hasattr(quik, 'close'):
                await quik.close()
            else:
                # Если нет ни stop_service, ни close, попробуем закрыть через __aexit__
                logger.warning("У Quik нет метода stop_service или close, пытаемся вызвать __aexit__")
                if hasattr(quik, '__aexit__'):
                    await quik.__aexit__(None, None, None)

            # Даём время на завершение внутренних задач
            await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            logger.debug("Отключение прервано")
        except Exception as e:
            logger.error(f"Ошибка при остановке Quik: {e}")
        finally:
            # Сбрасываем все обработчики
            self._order_handler = None
            self._trade_handler = None
            self._trans_reply_handler = None
            self._all_trade_handler = None
            self._candle_handlers.clear()
            self._subscribed_candles.clear()

        await self.event_bus.publish('connection', ConnectionStateEvent(state='disconnected'))
        logger.info("QUIK gateway отключён")

    # ===================== Обработчики событий =====================

    async def _handle_order_event(self, order: Order):
        """Обработка изменения заявки (новая, частичное исполнение, отмена)."""
        order_num = getattr(order, 'order_num', None)
        if order_num is None:
            return
        client_id = self._quik_order_to_client.get(order_num)
        if not client_id:
            return

        flags = getattr(order, 'flags', 0)
        if flags & 0x02:
            # Заявка снята или отклонена
            await self.event_bus.publish(
                'order.cancelled',
                OrderCancelledEvent(order_id=client_id)
            )
            logger.info(f"Заявка {client_id} снята/отклонена (order_num={order_num})")
            # Удаляем из маппинга
            self._quik_order_to_client.pop(order_num, None)
            self._client_to_quik_order.pop(client_id, None)
            return

        # Проверяем, полностью ли исполнена
        balance = getattr(order, 'balance', None)
        qty = getattr(order, 'qty', None)
        if qty is None:
            qty = getattr(order, 'quantity', None)
        if balance is not None and qty is not None and balance == 0 and qty > 0:
            # Полностью исполнена – событие будет также через _handle_trade_event
            # Но можно дополнительно обработать здесь
            logger.debug(f"Заявка {client_id} полностью исполнена (balance=0)")

    async def _handle_trade_event(self, trade: Trade):
        """Обработка сделки (исполнения)."""
        # Поле order_num может называться order_num или order_number
        order_num = getattr(trade, 'order_num', None)
        if order_num is None:
            order_num = getattr(trade, 'order_number', None)
        if order_num is None:
            logger.warning(f"Получена сделка без order_num: {trade}")
            return

        client_id = self._quik_order_to_client.get(order_num)
        if not client_id:
            logger.debug(f"Сделка по чужой заявке order_num={order_num}, игнорируем")
            return

        qty = getattr(trade, 'qty', 0)
        if qty == 0:
            qty = getattr(trade, 'quantity', 0)
        price = getattr(trade, 'price', 0.0)
        commission = getattr(trade, 'commission', 0.0)
        if commission is None:
            commission = getattr(trade, 'comission', 0.0)  # возможная опечатка
        if commission is None:
            commission = 0.0

        # Публикуем событие исполнения
        strategy_name = self._client_to_strategy.get(client_id, 'unknown')
        await self.event_bus.publish(
            f"strategy.{strategy_name}.fill",
            OrderFilledEvent(
                order_id=client_id,
                fill_volume=float(qty),
                fill_price=float(price),
                commission=float(commission),
                slippage=0.0,
            )
        )
        # Также публикуем в глобальный канал
        await self.event_bus.publish(
            'order.filled',
            OrderFilledEvent(
                order_id=client_id,
                fill_volume=float(qty),
                fill_price=float(price),
                commission=float(commission),
                slippage=0.0,
            )
        )
        logger.info(f"Исполнение: {client_id} qty={qty} price={price}")

    async def _handle_trans_reply(self, reply: TransactionReply):
        """Подтверждение транзакции (успех/ошибка)."""
        # Пробуем разные варианты поля результата
        result_code = getattr(reply, 'result', None)
        if result_code is None:
            result_code = getattr(reply, 'status', None)
        if result_code is None:
            # Если нет поля, считаем успехом (QUIK часто возвращает 0 при успехе)
            logger.debug(f"Транзакция {getattr(reply, 'trans_id', '?')}: нет поля результата, считаем успешной")
            return
        if result_code == 0:
            order_num = getattr(reply, 'order_num', None)
            logger.debug(f"Транзакция {reply.trans_id} успешна, order_num={order_num}")
        else:
            msg = getattr(reply, 'message', 'неизвестная ошибка')
            logger.warning(f"Транзакция {reply.trans_id} ошибка: {msg} (code={result_code})")

    async def _handle_all_trade(self, all_trade: AllTrade):
        """Обработка рыночных сделок (тики)."""
        # Проверяем, подписаны ли мы на тики этого символа
        # Для простоты можно фильтровать по символу, но у нас нет списка подписанных тиков
        # Если подписка на тики не используется, можно игнорировать
        if not self._subscribed_ticks:  # добавим позже
            return
        if all_trade.sec_code not in self._subscribed_ticks:
            return
        tick = Tick(
            timestamp=datetime(
                all_trade.datetime.year,
                all_trade.datetime.month,
                all_trade.datetime.day,
                all_trade.datetime.hour,
                all_trade.datetime.min,
                all_trade.datetime.sec,
            ),
            symbol=all_trade.sec_code,
            bid=all_trade.price,   # AllTrade не содержит bid/ask отдельно
            ask=all_trade.price,
            last=all_trade.price,
            volume=all_trade.quantity,
        )
        self._last_price_cache[all_trade.sec_code] = all_trade.price
        await self.event_bus.publish(f'market.tick.{all_trade.sec_code}', TickEvent(tick=tick))

    # ===================== Свечи (через CandleFunctions) =====================

    async def _subscribe_candle(self, symbol: str, class_code: str, timeframe: str):
        interval = _TF_TO_INTERVAL.get(timeframe)
        if not interval:
            logger.error(f"Неизвестный таймфрейм {timeframe}")
            return

        # Регистрируем обработчик для свечей (если ещё не зарегистрирован)
        # Обработчик будет общим для всех символов, но мы фильтруем по символу и интервалу
        # Чтобы не дублировать, создадим один обработчик, который будет вызываться для всех свечей,
        # а внутри будем проверять, подписан ли символ.
        if not self._candle_handlers:
            def on_new_candle(candle: Candle):
                # Проверяем, есть ли подписка на этот символ и интервал
                for sym, tf, interval_sub in self._subscribed_candles:
                    if candle.sec_code == sym and candle.interval == interval_sub:
                        asyncio.create_task(self._handle_candle(candle, sym, tf))
                        break
            self._quik.candles.add_new_candle_handler(on_new_candle)
            self._candle_handlers.append(on_new_candle)
            logger.debug("Глобальный обработчик свечей зарегистрирован")

        # Подписываемся на получение свечей (активирует поток)
        await self._quik.candles.subscribe(class_code, symbol, interval)
        self._subscribed_candles.add((symbol, timeframe, interval))
        logger.info(f"Подписка на свечи: {symbol} {timeframe} (через коллбэк)")

    async def _handle_candle(self, candle: Candle, symbol: str, timeframe: str):
        logger.info(f"Получена свеча: {symbol} {timeframe} open={candle.open} close={candle.close}")
        """Преобразует свечу QUIK в нашу модель и публикует."""
        dt_utc = datetime(
            candle.datetime.year,
            candle.datetime.month,
            candle.datetime.day,
            candle.datetime.hour,
            candle.datetime.min,
            candle.datetime.sec
        )
        local_tz = timezone(timedelta(hours=3))
        dt_local = dt_utc.astimezone(local_tz)
        our_candle = Candle(
            symbol=symbol,
            timeframe=timeframe,
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=float(candle.volume),
            timestamp=dt_local,
            is_complete=True,
        )
        self._last_price_cache[symbol] = candle.close
        await self.event_bus.publish(
            f'market.candle.{symbol}.{timeframe}',
            CandleEvent(candle=our_candle),
        )

    # ===================== Подписки =====================

    async def subscribe(
        self,
        strategy_name: str,
        symbol: str,
        data_type: str,
        timeframe: Optional[str] = None,
    ) -> None:
        if not self._connected:
            raise RuntimeError("Шлюз не подключён.")
        class_code = self._get_class_code(symbol)
        if data_type == 'candle' and timeframe:
            await self._subscribe_candle(symbol, class_code, timeframe)
        elif data_type == 'tick':
            # Для тиков мы уже зарегистрировали общий обработчик, добавляем символ в список
            if not hasattr(self, '_subscribed_ticks'):
                self._subscribed_ticks = set()
            self._subscribed_ticks.add(symbol)
            # Подписка на тики через события AllTrade — уже есть
            logger.info(f"Подписка на тики: {symbol}")
        else:
            logger.warning(f"Неподдерживаемый тип подписки: {data_type}")

    async def unsubscribe(
        self,
        strategy_name: str,
        symbol: str,
        data_type: str,
        timeframe: Optional[str] = None,
    ) -> None:
        if not self._quik:
            return
        class_code = self._get_class_code(symbol)
        if data_type == 'candle' and timeframe:
            interval = _TF_TO_INTERVAL.get(timeframe)
            if interval:
                await self._quik.candles.unsubscribe(class_code, symbol, interval)
                self._subscribed_candles.discard((symbol, timeframe, interval))
        elif data_type == 'tick':
            if hasattr(self, '_subscribed_ticks'):
                self._subscribed_ticks.discard(symbol)

    # ===================== Отправка и отмена заявок =====================

    async def send_order(self, order: OurOrder) -> str:
        if not self._connected:
            raise RuntimeError("Шлюз не подключён.")

        class_code = self._get_class_code(order.symbol)
        self._client_to_symbol[order.client_order_id] = (order.symbol, class_code)
        self._client_to_strategy[order.client_order_id] = order.strategy_name

        operation = Operation.BUY if order.side == OrderSide.BUY else Operation.SELL
        order_type = TransactionType.L if order.order_type == OrderType.LIMIT else TransactionType.M
        price = Decimal(str(order.price)) if order.price else Decimal('0')

        try:
            # Отправляем заявку через send_order с именованными параметрами
            result = await self._quik.orders.send_order(
                class_code=class_code,
                security_code=order.symbol,
                account_id=self.account,
                operation=operation,
                price=price,
                qty=int(order.volume),
                order_type=order_type,
            )
            # result — это объект Order
            if not hasattr(result, 'order_num'):
                raise RuntimeError(f"QUIK не вернул order_num. Ответ: {result}")
            order_num = result.order_num
            self._quik_order_to_client[order_num] = order.client_order_id
            self._client_to_quik_order[order.client_order_id] = order_num
            logger.info(f"Заявка отправлена: {order.client_order_id} -> order_num={order_num}")
            return f"quik-{order_num}"
        except Exception as e:
            logger.error(f"Ошибка отправки заявки: {e}")
            raise

    async def cancel_order(self, client_order_id: str) -> None:
        order_num = self._client_to_quik_order.get(client_order_id)
        if not order_num:
            logger.warning(f"Нет QUIK-номера для {client_order_id}, возможно уже исполнена.")
            return
        try:
            await self._quik.orders.kill_order(order_num)
            logger.info(f"Заявка {client_order_id} (order_num={order_num}) снята")
        except Exception as e:
            logger.error(f"Ошибка отмены заявки {client_order_id}: {e}")
            raise

    async def modify_order(self, client_order_id: str, **kwargs) -> None:
        logger.warning("QUIK не поддерживает изменение заявок. Отменяем и создайте новую.")
        await self.cancel_order(client_order_id)

    # ===================== Получение истории =====================

    async def get_history(self, symbol: str, timeframe: str, count: int) -> List[Candle]:
        class_code = self._get_class_code(symbol)
        interval = _TF_TO_INTERVAL.get(timeframe)
        if not interval:
            return []
        try:
            candles = await self._quik.candles.get_last_candles(class_code, symbol, interval, count)
            result = []
            for c in candles:
                dt_utc = datetime(
                    c.datetime.year,
                    c.datetime.month,
                    c.datetime.day,
                    c.datetime.hour,
                    c.datetime.min,
                    c.datetime.sec
                )

                local_tz = timezone(timedelta(hours=3))
                dt_local = dt_utc.astimezone(local_tz)
                result.append(Candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    open=c.open,
                    high=c.high,
                    low=c.low,
                    close=c.close,
                    volume=float(c.volume),
                    timestamp=dt_local,
                    is_complete=True,
                ))
            return result
        except Exception as e:
            logger.error(f"Ошибка получения истории {symbol}: {e}")
            return []

    # ===================== Вспомогательные =====================

    def _get_class_code(self, symbol: str) -> str:
        code = self.class_code_map.get(symbol)
        if not code:
            raise KeyError(f"class_code не найден для '{symbol}'")
        return code
    async def get_last_price(self, symbol: str) -> Optional[float]:
        return self._last_trade_price.get(symbol)