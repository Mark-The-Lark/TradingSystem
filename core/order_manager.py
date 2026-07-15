import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Set
from core.events import EventBus, OrderPlacedEvent, OrderFilledEvent, OrderCancelledEvent, OrderRejectedEvent, OrderRequestEvent, StopOrderEvent, OrderConnectionEvent
from core.models import Order, OrderStatus, OrderSide, OrderType, TimeInForce
from core.gateway import BaseGateway
from core.commission import CommissionModel
from core.risk_manager import RiskManager, RiskLimitExceeded

logger = logging.getLogger(__name__)

class OrderManager:
    def __init__(self, event_bus: EventBus, gateway: BaseGateway, risk_manager: RiskManager,
                 commission_model: CommissionModel):
        self.event_bus = event_bus
        self.gateway = gateway
        self.risk_manager = risk_manager
        self.commission_model = commission_model
        # client_order_id -> Order
        self._active_orders: Dict[str, Order] = {}
        self._connected_orders: Dict[str, Set[str]] = {}
        self._order_history: List[Order] = []
        self._lock = asyncio.Lock()
        # Подписываемся на события
        self.event_bus.subscribe("order.request", self._on_order_request)
        self.event_bus.subscribe("order.filled", self._on_order_filled)
        self.event_bus.subscribe("order.cancelled", self._on_order_cancelled)
        self.event_bus.subscribe("order.rejected", self._on_order_rejected)
        self.event_bus.subscribe("order.stop", self._on_stop_order)
        self.event_bus.subscribe("order.connect", self._on_connect_orders)

    async def _on_order_request(self, event: OrderRequestEvent):
        order = event.order
        if order.client_order_id in self._active_orders:
            logger.warning(f"Duplicate order request {order.client_order_id}, ignored")
            return
        # Проверка рисков
        try:
            self.risk_manager.check_order(order)
        except RiskLimitExceeded as e:
            logger.warning(f"Order rejected by risk manager: {e}")
            await self.event_bus.publish("order.rejected", OrderRejectedEvent(
                order_id=order.client_order_id, reason=str(e)))
            return

        # Расчёт комиссии
        if order.price:
            estimated_price = order.price
        else:
            # Для рыночных можно получить цену из gateway, но пока заглушка
            estimated_price = await self.gateway.get_last_price(order.symbol)

        if estimated_price is None:
            # fallback: запросить историю (если метод не переопределён)
            candles = await self.gateway.get_history(order.symbol, '1m', 1)
            if candles:
                estimated_price = candles[-1].close
            else:
                raise ValueError(f"Не удалось получить цену для {order.symbol}")
            
        order.commission = self.commission_model.calculate(
            order.symbol, estimated_price, order.volume, order.side)
        order.slippage = 0.0

        # !!! Сразу добавляем ордер в активные со статусом PENDING,
        # чтобы обработчик fill мог его найти
        order.status = OrderStatus.PENDING
        order.updated_at = datetime.utcnow()
        self._active_orders[order.client_order_id] = order
        self._order_history.append(order)

        try:
            gw_id = await self.gateway.send_order(order)
            order.gateway_order_id = gw_id
            order.status = OrderStatus.ACTIVE
            order.updated_at = datetime.utcnow()
            # Теперь, когда статус ACTIVE, публикуем placed
            await self.event_bus.publish("order.placed", OrderPlacedEvent(order=order))
        except Exception as e:
            logger.error(f"Failed to send order: {e}")
            order.status = OrderStatus.REJECTED
            self._active_orders.pop(order.client_order_id, None)
            await self.event_bus.publish("order.rejected", OrderRejectedEvent(
                order_id=order.client_order_id, reason=str(e)))

    async def _on_order_filled(self, event: OrderFilledEvent):
        """Обработка исполнения ордера (полного или частичного)."""
        
        order = self._active_orders.get(event.order_id)
        if not order:
            logger.warning(f"Fill for unknown order {event.order_id}")
            return
        order.filled_volume += event.fill_volume
        order.average_fill_price = (
            (order.average_fill_price * (order.filled_volume - event.fill_volume) + event.fill_price * event.fill_volume)
            / order.filled_volume
        ) if order.filled_volume > 0 else event.fill_price
        order.commission += event.commission  # на случай, если комиссия списывается частями
        order.slippage += event.slippage
        order.updated_at = datetime.utcnow()
        if order.filled_volume >= order.volume or order.time_in_force == TimeInForce.IOC:
            order.status = OrderStatus.FILLED
            self._active_orders.pop(order.client_order_id, None)
            for connected_order_id in self._connected_orders.pop(order.client_order_id, []):
                await self.gateway.cancel_order(connected_order_id)
        else:
            order.status = OrderStatus.PARTIALLY_FILLED
        # Уведомляем риск-менеджер об изменении позиции
        self.risk_manager.update_position(order.strategy_name, event.fill_volume, order.side)
        # Публикуем событие для стратегии
        await self.event_bus.publish(f"strategy.{order.strategy_name}.fill", event)
        logger.info(f"Order filled: {order}")

    async def _on_order_cancelled(self, event: OrderCancelledEvent):
        
        order = self._active_orders.pop(event.order_id, None)
        if order:
            order.status = OrderStatus.CANCELLED
            order.updated_at = datetime.utcnow()
            self._order_history.append(order)
            await self.event_bus.publish(f"strategy.{order.strategy_name}.cancel", event)
            logger.info(f"Order cancelled: {order}")
            for gateway_order_id in self._connected_orders.pop(event.order_id, []):
                await self.gateway.cancel_order(gateway_order_id)

    async def _on_order_rejected(self, event: OrderRejectedEvent):
        order = self._active_orders.pop(event.order_id, None)
        if order:
            order.status = OrderStatus.REJECTED
            order.updated_at = datetime.utcnow()
            self._order_history.append(order)
            await self.event_bus.publish(f"strategy.{order.strategy_name}.reject", event)
            logger.info(f"Order rejected: {order}, reason: {event.reason}")

    async def _on_stop_order(self, event: StopOrderEvent):
        order = event.order
        if order.client_order_id in self._active_orders:
            logger.warning(f"Duplicate order request {order.client_order_id}, ignored")
            return

        # Расчёт комиссии
        if order.price:
            estimated_price = order.price
        else:
            # Для рыночных можно получить цену из gateway, но пока заглушка
            estimated_price = await self.gateway.get_last_price(order.symbol)

        if estimated_price is None:
            # fallback: запросить историю (если метод не переопределён)
            candles = await self.gateway.get_history(order.symbol, '1m', 1)
            if candles:
                estimated_price = candles[-1].close
            else:
                raise ValueError(f"Не удалось получить цену для {order.symbol}")
            
        order.commission = self.commission_model.calculate(
            order.symbol, estimated_price, order.volume, order.side)
        order.slippage = 0.0

        # !!! Сразу добавляем ордер в активные со статусом PENDING,
        # чтобы обработчик fill мог его найти
        order.status = OrderStatus.PENDING
        order.updated_at = datetime.utcnow()
        self._active_orders[order.client_order_id] = order
        self._order_history.append(order)

        try:
            gw_id = await self.gateway.send_stop_order(order)
            order.gateway_order_id = gw_id
            order.status = OrderStatus.ACTIVE
            order.updated_at = datetime.utcnow()
            # Теперь, когда статус ACTIVE, публикуем placed
            await self.event_bus.publish("order.placed", OrderPlacedEvent(order=order))
        except Exception as e:
            logger.error(f"Failed to send order: {e}")
            order.status = OrderStatus.REJECTED
            self._active_orders.pop(order.client_order_id, None)
            await self.event_bus.publish("order.rejected", OrderRejectedEvent(
                order_id=order.client_order_id, reason=str(e)))

    def get_active_orders(self, strategy_name: Optional[str] = None) -> List[Order]:
        if strategy_name:
            return [o for o in self._active_orders.values() if o.strategy_name == strategy_name]
        return list(self._active_orders.values())

    def get_order_history(self, strategy_name: Optional[str] = None) -> List[Order]:
        if strategy_name:
            return [o for o in self._order_history if o.strategy_name == strategy_name]
        return list(self._order_history)
    def get_order_by_client_id(self, client_order_id: str) -> Optional[Order]:
        return self._active_orders.get(client_order_id) or next(
            (o for o in self._order_history if o.client_order_id == client_order_id), None
        )

    async def _on_connect_orders(self, event: OrderConnectionEvent):
        for order in event.order_ids:
            self._connected_orders[order] = event.order_ids
    # --- Сохранение / восстановление состояния ---
    def save_state(self) -> dict:
        """Сериализует активные ордера и историю для сохранения между сессиями."""
        return {
            'active_orders': [o.model_dump(mode='json') for o in self._active_orders.values()],
            'order_history': [o.model_dump(mode='json') for o in self._order_history],
        }

    def load_state(self, state: dict) -> None:
        """
        Восстанавливает историю ордеров из сохранённого состояния.
        Активные ордера при восстановлении помечаются CANCELLED, так как
        их реальный статус неизвестен (нужно сверить с брокером при reconnect).
        """
        from core.models import OrderStatus
        history_data = state.get('order_history', [])
        for raw in history_data:
            try:
                self._order_history.append(Order(**raw))
            except Exception as e:
                logger.warning(f"Skipping invalid order in history: {e}")

        active_data = state.get('active_orders', [])
        for raw in active_data:
            try:
                order = Order(**raw)
                # Помечаем как CANCELLED — статус будет уточнён при reconnect
                order.status = OrderStatus.CANCELLED
                self._order_history.append(order)
                logger.warning(
                    f"Order {order.client_order_id} was active at shutdown; "
                    f"marked CANCELLED. Verify with broker on reconnect."
                )
            except Exception as e:
                logger.warning(f"Skipping invalid active order: {e}")
    async def cancel_order(self, client_order_id: str):
        order = self._active_orders.get(client_order_id)
        if not order:
            return
        if order.order_type in (OrderType.STOP, OrderType.TAKE_PROFIT):
            await self.gateway.kill_stop_order(order.gateway_order_id)
        else:
            await self.gateway.cancel_order(order.gateway_order_id)
    async def cancel_all_orders(self, strategy_name: Optional[str] = None):
        for order in self._active_orders.values():
            if strategy_name and order.strategy_name != strategy_name:
                continue
            await self.cancel_order(order.client_order_id)