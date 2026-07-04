# core/quik_gateway.py
"""
QUIK gateway — реальная торговля через терминал QUIK.

ТРЕБОВАНИЯ:
  - Windows OS (QuikPy использует именованные каналы к терминалу QUIK)
  - Запущенный терминал QUIK с включённым LUA-скриптом QuikPy
  - pip install QuikPy

КОНФИГУРАЦИЯ (пример):
    from core.quik_gateway import QuikGateway
    gateway = QuikGateway(
        event_bus=event_bus,
        asyncio_loop=async_loop.loop,          # loop из AsyncLoopThread
        class_code_map={                        # маппинг тикер → класс QUIK
            'SBER': 'TQBR',
            'GAZP': 'TQBR',
            'AFKS': 'TQBR',
            'Si-9.25': 'SPBFUT',               # фьючерс
        },
        account='L01-00000F00',                 # торговый счёт
    )

АРХИТЕКТУРА МОСТИКА (sync QuikPy → async EventBus):
    QuikPy вызывает коллбеки из собственного потока синхронно.
    Все коллбеки немедленно диспатчат async-корутину в asyncio-цикл через
        asyncio.run_coroutine_threadsafe(coro, self._loop)
    Это thread-safe, не блокирует поток QuikPy и позволяет обрабатывать
    события через EventBus в том же event loop, что и стратегии.

КОДЫ ТАЙМФРЕЙМОВ QUIK (QLua interval constants):
    1m→1, 2m→2, 3m→3, 4m→4, 5m→5, 6m→6, 10m→7, 15m→8, 20m→9, 30m→10,
    1h→11, 2h→12, 4h→13, 1d→14, 1w→15, 1M→16
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from core.gateway import BaseGateway
from core.events import (
    EventBus,
    CandleEvent,
    TickEvent,
    OrderFilledEvent,
    OrderCancelledEvent,
    OrderPlacedEvent,
    ConnectionStateEvent,
)
from core.models import Order, OrderSide, OrderType, Candle, Tick

logger = logging.getLogger(__name__)

# ── Таймфреймы ────────────────────────────────────────────────────────────────
_TF_TO_INTERVAL: Dict[str, int] = {
    '1m': 1, '2m': 2, '3m': 3, '4m': 4, '5m': 5, '6m': 6,
    '10m': 7, '15m': 8, '20m': 9, '30m': 10,
    '1h': 11, '2h': 12, '4h': 13,
    '1d': 14, '1w': 15, '1M': 16,
}
_INTERVAL_TO_TF: Dict[int, str] = {v: k for k, v in _TF_TO_INTERVAL.items()}


class QuikGateway(BaseGateway):
    """
    Реализация BaseGateway для торговли через QUIK.

    Принципы дизайна (вариант B/B):
      - class_code: хранится в class_code_map в конфиге шлюза, не в Order.
        Это позволяет Order оставаться брокеро-агностичным.
      - account:    один счёт на шлюз, задаётся при инициализации.
    """

    def __init__(
        self,
        event_bus: EventBus,
        asyncio_loop: asyncio.AbstractEventLoop,
        class_code_map: Dict[str, str],
        account: str,
        host: str = 'localhost',
        port_main: int = 34130,
        port_callback: int = 34131,
    ):
        """
        Args:
            event_bus:      шина событий проекта
            asyncio_loop:   asyncio-цикл для диспатча из коллбеков QuikPy
                            (передайте async_loop.loop из AsyncLoopThread)
            class_code_map: {тикер: класс QUIK}, например {'SBER': 'TQBR'}
            account:        номер торгового счёта/клиентского кода в QUIK
            host:           хост QuikPy (по умолчанию localhost)
            port_main:      основной порт QuikPy
            port_callback:  порт коллбеков QuikPy
        """
        super().__init__(event_bus)
        self._loop = asyncio_loop
        self.class_code_map = class_code_map
        self.account = account
        self.host = host
        self.port_main = port_main
        self.port_callback = port_callback

        self._qp = None   # экземпляр QuikPy (создаётся при connect)

        # Счётчик транзакций и двусторонний маппинг идентификаторов
        self._trans_id_counter: int = 0
        self._trans_id_to_client: Dict[int, str] = {}   # trans_id → client_order_id
        self._client_to_quik_num: Dict[str, int] = {}   # client_order_id → QUIK order_num
        self._quik_num_to_client: Dict[int, str] = {}   # QUIK order_num → client_order_id
        # Для cancel_order нужно знать symbol; сохраняем при send_order
        self._client_to_symbol: Dict[str, Tuple[str, str]] = {}  # client_id → (symbol, class_code)

        # Datasource-дескрипторы для свечных подписок
        self._datasources: Dict[Tuple[str, str], object] = {}   # (symbol, tf) → ds
        self._tick_symbols: Set[str] = set()   # символы, на тики которых подписаны

    # ─────────────────────────────────────────────────────────────────────────
    # BaseGateway: connect / disconnect
    # ─────────────────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Подключается к QUIK через QuikPy. Требует Windows + запущенный QUIK."""
        try:
            from QuikPy import QuikPy  # Windows only
        except ImportError as exc:
            raise ImportError(
                "QuikPy не найден. Установите: pip install QuikPy\n"
                "QuikGateway работает только на Windows с запущенным QUIK."
            ) from exc

        logger.info(f"Подключение к QUIK ({self.host}:{self.port_main})…")
        self._qp = QuikPy(
            Host=self.host,
            RequestPort=self.port_main,
            CallbackPort=self.port_callback,
        )

        # Проверяем подключение QUIK к серверу брокера
        resp = self._qp.isConnected()
        if not resp.get('data', 0):
            raise ConnectionError(
                "Терминал QUIK не подключён к серверу брокера. "
                "Проверьте статус соединения в QUIK."
            )

        # Регистрируем коллбеки
        self._qp.OnOrder    = self._on_quik_order
        self._qp.OnTrade    = self._on_quik_trade
        self._qp.OnAllTrade = self._on_quik_all_trade

        self._connected = True
        await self.event_bus.publish('connection', ConnectionStateEvent(state='connected'))
        logger.info("QUIK gateway подключён")

    async def disconnect(self) -> None:
        """Закрывает все datasource и соединение с QuikPy."""
        self._connected = False
        for key, ds in list(self._datasources.items()):
            try:
                ds.Close()
            except Exception as e:
                logger.warning(f"Ошибка закрытия datasource {key}: {e}")
        self._datasources.clear()

        if self._qp is not None:
            try:
                self._qp.close()
            except Exception as e:
                logger.warning(f"Ошибка закрытия QuikPy: {e}")
            self._qp = None

        await self.event_bus.publish('connection', ConnectionStateEvent(state='disconnected'))
        logger.info("QUIK gateway отключён")

    # ─────────────────────────────────────────────────────────────────────────
    # BaseGateway: subscribe / unsubscribe
    # ─────────────────────────────────────────────────────────────────────────

    async def subscribe(
        self,
        strategy_name: str,
        symbol: str,
        data_type: str,
        timeframe: Optional[str] = None,
    ) -> None:
        class_code = self._get_class_code(symbol)
        if data_type == 'tick':
            self._tick_symbols.add(symbol)
            logger.debug(f"Тик-подписка: {symbol} ({class_code})")
        elif data_type == 'candle' and timeframe:
            await self._subscribe_candle(symbol, class_code, timeframe)

    async def unsubscribe(
        self,
        strategy_name: str,
        symbol: str,
        data_type: str,
        timeframe: Optional[str] = None,
    ) -> None:
        if data_type == 'tick':
            self._tick_symbols.discard(symbol)
        elif data_type == 'candle' and timeframe:
            key = (symbol, timeframe)
            ds = self._datasources.pop(key, None)
            if ds is not None:
                try:
                    ds.Close()
                except Exception as e:
                    logger.warning(f"Ошибка отписки от {symbol}/{timeframe}: {e}")

    async def _subscribe_candle(
        self, symbol: str, class_code: str, timeframe: str
    ) -> None:
        key = (symbol, timeframe)
        if key in self._datasources:
            return   # уже подписаны

        interval = _TF_TO_INTERVAL.get(timeframe)
        if interval is None:
            logger.error(
                f"Неизвестный таймфрейм '{timeframe}'. "
                f"Поддерживаются: {list(_TF_TO_INTERVAL.keys())}"
            )
            return

        def _create() -> object:
            """Создаём datasource синхронно в executor."""
            ds = self._qp.CreateDataSource(class_code, symbol, interval)
            if ds is None:
                raise RuntimeError(
                    f"QUIK вернул None для CreateDataSource({class_code}, {symbol}, {interval})"
                )
            # Коллбек вызывается синхронно из потока QuikPy при появлении новой свечи
            def _cb(index: int):
                self._dispatch(self._handle_candle(ds, symbol, timeframe, index))
            ds.SetUpdateCallback(_cb)
            return ds

        loop = asyncio.get_event_loop()
        ds = await loop.run_in_executor(None, _create)
        self._datasources[key] = ds
        logger.info(f"Свечная подписка: {symbol} {timeframe} ({class_code})")

    # ─────────────────────────────────────────────────────────────────────────
    # BaseGateway: send_order / cancel_order / modify_order
    # ─────────────────────────────────────────────────────────────────────────

    async def send_order(self, order: Order) -> str:
        """Отправляет рыночную или лимитную заявку в QUIK."""
        self._trans_id_counter += 1
        trans_id = self._trans_id_counter
        self._trans_id_to_client[trans_id] = order.client_order_id

        class_code = self._get_class_code(order.symbol)
        # Сохраняем для cancel_order
        self._client_to_symbol[order.client_order_id] = (order.symbol, class_code)

        operation = 'B' if order.side == OrderSide.BUY else 'S'
        if order.order_type == OrderType.MARKET:
            order_type_code = 'M'
            price_str = '0'
        elif order.order_type == OrderType.LIMIT:
            order_type_code = 'L'
            price_str = str(order.price or 0)
        else:
            # STOP и TAKE_PROFIT в QUIK реализуются стоп-заявками (другой механизм)
            raise NotImplementedError(
                f"Тип заявки {order.order_type} не поддерживается напрямую QUIK. "
                f"Используйте MARKET или LIMIT."
            )

        transaction: dict = {
            'TRANS_ID': str(trans_id),
            'ACTION':   'NEW_ORDER',
            'ACCOUNT':  self.account,
            'CLASSCODE': class_code,
            'SECCODE':  order.symbol,
            'OPERATION': operation,
            'TYPE':     order_type_code,
            'PRICE':    price_str,
            'QUANTITY': str(int(order.volume)),
        }

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: self._qp.sendTransaction(transaction)
        )

        if not result.get('result', False):
            msg = result.get('message', 'нет сообщения от QUIK')
            raise RuntimeError(
                f"QUIK отклонил заявку '{order.client_order_id}': {msg}"
            )

        gw_id = f"quik-trans-{trans_id}"
        logger.info(
            f"Заявка отправлена: {order.client_order_id} "
            f"({operation} {order.volume} {order.symbol}) → trans_id={trans_id}"
        )
        return gw_id

    async def cancel_order(self, client_order_id: str) -> None:
        """Снимает активную заявку."""
        quik_num = self._client_to_quik_num.get(client_order_id)
        if not quik_num:
            logger.warning(
                f"cancel_order: нет QUIK-номера для '{client_order_id}'. "
                f"Возможно, заявка ещё не зарегистрирована в системе."
            )
            return

        sym_pair = self._client_to_symbol.get(client_order_id)
        if not sym_pair:
            logger.error(f"cancel_order: нет символа для '{client_order_id}'")
            return
        symbol, class_code = sym_pair

        self._trans_id_counter += 1
        kill_trans_id = self._trans_id_counter

        transaction: dict = {
            'TRANS_ID':  str(kill_trans_id),
            'ACTION':    'KILL_ORDER',
            'CLASSCODE': class_code,
            'SECCODE':   symbol,
            'ORDER_KEY': str(quik_num),
        }

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: self._qp.sendTransaction(transaction)
        )
        if not result.get('result', False):
            msg = result.get('message', 'нет сообщения')
            logger.error(f"QUIK не смог снять заявку {client_order_id}: {msg}")
        else:
            logger.info(f"Заявка снята: {client_order_id} (quik_num={quik_num})")

    async def modify_order(self, client_order_id: str, **kwargs) -> None:
        """QUIK не поддерживает модификацию. Эмулируем: cancel + new order."""
        logger.info(
            f"modify_order({client_order_id}): QUIK не поддерживает изменение заявки. "
            f"Выполняем cancel. Для изменения параметров создайте новую заявку."
        )
        await self.cancel_order(client_order_id)

    # ─────────────────────────────────────────────────────────────────────────
    # BaseGateway: get_history
    # ─────────────────────────────────────────────────────────────────────────

    async def get_history(
        self, symbol: str, timeframe: str, count: int
    ) -> List[Candle]:
        """Загружает исторические свечи через getCandles QUIK."""
        class_code = self._get_class_code(symbol)
        interval = _TF_TO_INTERVAL.get(timeframe)
        if interval is None:
            logger.error(f"get_history: неизвестный таймфрейм '{timeframe}'")
            return []

        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(
            None,
            lambda: self._qp.getCandles(class_code, symbol, interval, count),
        )

        candles: List[Candle] = []
        for bar in raw.get('data', []):
            try:
                ts = self._parse_datetime(bar.get('datetime', {}))
                candles.append(Candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    open=float(bar.get('open', 0)),
                    high=float(bar.get('high', 0)),
                    low=float(bar.get('low', 0)),
                    close=float(bar.get('close', 0)),
                    volume=float(bar.get('volume', 0)),
                    timestamp=ts,
                    is_complete=True,
                ))
            except Exception as e:
                logger.warning(f"get_history: ошибка парсинга бара {symbol}: {e}")
        return candles

    # ─────────────────────────────────────────────────────────────────────────
    # QuikPy callbacks — вызываются синхронно из потока QuikPy
    # ─────────────────────────────────────────────────────────────────────────

    def _on_quik_order(self, data: dict) -> None:
        """Изменение статуса заявки (новая/изменена/снята)."""
        self._dispatch(self._handle_order_update(data))

    def _on_quik_trade(self, data: dict) -> None:
        """Сделка по нашей заявке (fill)."""
        self._dispatch(self._handle_fill(data))

    def _on_quik_all_trade(self, data: dict) -> None:
        """Любая рыночная сделка → тик для подписанных символов."""
        self._dispatch(self._handle_tick(data))

    def _dispatch(self, coro) -> None:
        """Thread-safe бридж: ставит async-корутину в наш asyncio-цикл."""
        asyncio.run_coroutine_threadsafe(coro, self._loop)

    # ─────────────────────────────────────────────────────────────────────────
    # Async handlers
    # ─────────────────────────────────────────────────────────────────────────

    async def _handle_order_update(self, data: dict) -> None:
        """Обрабатывает обновление статуса заявки от QUIK."""
        quik_num = int(data.get('order_num', 0))
        trans_id  = int(data.get('trans_id', 0))
        flags     = int(data.get('flags', 0))
        # flags бит 1 (0x1) = активна; бит 2 (0x2) = снята/отклонена

        # Маппим trans_id → client_order_id при первом получении order_num
        if trans_id and trans_id in self._trans_id_to_client:
            client_id = self._trans_id_to_client[trans_id]
            if quik_num and client_id not in self._client_to_quik_num:
                self._client_to_quik_num[client_id] = quik_num
                self._quik_num_to_client[quik_num] = client_id
                logger.debug(
                    f"Заявка зарегистрирована: {client_id} → quik_num={quik_num}"
                )

        client_id = self._quik_num_to_client.get(quik_num)
        if not client_id:
            return

        is_killed = bool(flags & 0x2)
        if is_killed:
            await self.event_bus.publish(
                'order.cancelled',
                OrderCancelledEvent(order_id=client_id),
            )
            logger.info(f"Заявка снята QUIK: {client_id}")

    async def _handle_fill(self, data: dict) -> None:
        """Обрабатывает исполнение нашей заявки."""
        quik_num  = int(data.get('order_num', 0))
        client_id = self._quik_num_to_client.get(quik_num)
        if not client_id:
            return

        qty   = float(data.get('qty', 0))
        price = float(data.get('price', 0))

        # QUIK не всегда передаёт комиссию в OnTrade; берём 0 — OrderManager
        # рассчитает по своей CommissionModel
        await self.event_bus.publish(
            'order.filled',
            OrderFilledEvent(
                order_id=client_id,
                fill_volume=qty,
                fill_price=price,
                commission=0.0,
                slippage=0.0,
            ),
        )
        logger.info(f"Fill: {client_id}  qty={qty} @ {price:.4f}")

    async def _handle_tick(self, data: dict) -> None:
        """Рыночная сделка → публикуем тик для подписанных символов."""
        symbol = data.get('sec_code', '')
        if symbol not in self._tick_symbols:
            return

        price = float(data.get('price', 0))
        qty   = float(data.get('qty', 0))
        ts    = self._parse_datetime(data.get('datetime', {}))

        tick = Tick(
            timestamp=ts,
            symbol=symbol,
            bid=price,    # OnAllTrade не содержит bid/ask отдельно
            ask=price,
            last=price,
            volume=qty,
        )
        await self.event_bus.publish(f'market.tick.{symbol}', TickEvent(tick=tick))

    async def _handle_candle(
        self, ds, symbol: str, timeframe: str, index: int
    ) -> None:
        """Новая/обновлённая свеча в datasource QUIK."""
        try:
            candle = Candle(
                symbol=symbol,
                timeframe=timeframe,
                open=float(ds.O(index)),
                high=float(ds.H(index)),
                low=float(ds.L(index)),
                close=float(ds.C(index)),
                volume=float(ds.V(index)),
                timestamp=self._parse_datetime(ds.T(index)),
                is_complete=True,
            )
            await self.event_bus.publish(
                f'market.candle.{symbol}.{timeframe}',
                CandleEvent(candle=candle),
            )
        except Exception as e:
            logger.error(f"_handle_candle {symbol}/{timeframe}: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _get_class_code(self, symbol: str) -> str:
        code = self.class_code_map.get(symbol)
        if not code:
            raise KeyError(
                f"class_code не найден для '{symbol}'. "
                f"Добавьте запись в class_code_map при создании QuikGateway.\n"
                f"Пример: QuikGateway(..., class_code_map={{'{symbol}': 'TQBR'}})"
            )
        return code

    @staticmethod
    def _parse_datetime(data) -> datetime:
        """
        Парсит дату/время из формата QUIK.

        QUIK может передавать datetime как:
          - dict: {'year': 2024, 'month': 1, 'day': 5, 'hour': 10, 'min': 30, 'sec': 0}
          - str:  '20240105103000', '05.01.2024 10:30:00'
          - None / непарсируемое → текущее UTC-время
        """
        try:
            if isinstance(data, dict):
                return datetime(
                    int(data.get('year',  2000)),
                    int(data.get('month', 1)),
                    int(data.get('day',   1)),
                    int(data.get('hour',  0)),
                    int(data.get('min',   0)),
                    int(data.get('sec',   0)),
                )
            if isinstance(data, str) and data:
                for fmt in ('%Y%m%d%H%M%S', '%d.%m.%Y %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
                    try:
                        return datetime.strptime(data, fmt)
                    except ValueError:
                        continue
        except Exception:
            pass
        return datetime.utcnow()
