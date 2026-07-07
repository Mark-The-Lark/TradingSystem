
import asyncio
import logging
from typing import Dict, Optional, List
from core.events import EventBus, TickEvent, CandleEvent
from core.strategy import Strategy
from core.gateway import BaseGateway
from core.order_manager import OrderManager
from core.state_store import StateStore
from core.capital_manager import CapitalManager

logger = logging.getLogger(__name__)

class StrategyManager:
    def __init__(self, event_bus: EventBus, gateway: BaseGateway, order_manager: OrderManager,
                 state_store: StateStore, capital_manager: Optional[CapitalManager] = None):
        self.event_bus = event_bus
        self.gateway = gateway
        self.order_manager = order_manager
        self.state_store = state_store
        self.capital_manager = capital_manager or CapitalManager()
        self._strategies: Dict[str, Strategy] = {}
        self._handlers: Dict[str, dict] = {}  # strategy_name -> {'tick': handler, 'candle': handler}
        self._auto_save_task: Optional[asyncio.Task] = None

    async def add_strategy(self, strategy: Strategy) -> None:
        if strategy.name in self._strategies:
            raise ValueError(f"Strategy with name {strategy.name} already exists")
        self._strategies[strategy.name] = strategy

        # Передаём ссылку на capital manager
        strategy._capital_manager = self.capital_manager

        # Регистрируем в капитал-менеджере с равной долей
        num = len(self._strategies)
        equal_pct = 100.0 / num
        # Пересчитываем доли всем
        for name in self._strategies:
            self.capital_manager.set_strategy(self._strategies[name], equal_pct)

        await self._subscribe_strategy_data(strategy)
        saved_state = await self.state_store.load_strategy_state(strategy.name)
        if saved_state:
            strategy.load_state(saved_state)
        await self._save_strategies_list()
        logger.info(f"Strategy {strategy.name} added")

    async def remove_strategy(self, name: str) -> None:
        strategy = self._strategies.pop(name, None)
        if strategy:
            await self._unsubscribe_strategy_data(strategy)
            self.capital_manager.remove_strategy(name)
            await self.state_store.delete_strategy_state(name)
            # Пересчитать доли оставшихся
            self._rebalance_allocations()
            await self._save_strategies_list()
            logger.info(f"Strategy {name} removed")

    async def start_strategy(self, name: str) -> None:
        try:
            strategy = self._strategies.get(name)
            if not strategy:
                return
            # Заполняем историю (прогрев)
            for sym, tf in strategy.subscriptions:
                if tf == 'tick':
                    continue
                candles = await self.gateway.get_history(sym, tf, 200)
                for c in candles:
                    strategy.add_candle_to_history(c)
            strategy.set_status('RUNNING')
            await strategy.on_init()
            # Подписки уже добавлены в add_strategy, но на случай если отписывались — повторяем
            if name not in self._handlers:
                await self._subscribe_strategy_data(strategy)
            logger.info(f"Strategy {name} started")
        except Exception as e:
            logger.error(f"Failed to start strategy {name}: {e}")
            strategy.set_status('ERROR')

    async def stop_strategy(self, name: str) -> None:
        strategy = self._strategies.get(name)
        if not strategy:
            return
        strategy.set_status('STOPPED')
        await self._unsubscribe_strategy_data(strategy)
        await self.state_store.save_strategy_state(name, strategy.save_state())
        logger.info(f"Strategy {name} stopped")

    async def start_all(self) -> None:
        await self.gateway.connect()
        for name in list(self._strategies.keys()):
            await self.start_strategy(name)
        if self._auto_save_task and not self._auto_save_task.done():
            self._auto_save_task.cancel()
        self._auto_save_task = asyncio.create_task(self._auto_save())

    async def stop_all(self) -> None:
        if self._auto_save_task and not self._auto_save_task.done():
            self._auto_save_task.cancel()
            self._auto_save_task = None
        for name in list(self._strategies.keys()):
            await self.stop_strategy(name)
        await self._save_component_states()
        await self.gateway.disconnect()

    async def emergency_exit(self, strategy_name: str):
        strategy = self._strategies.get(strategy_name)
        if strategy:
            await strategy.emergency_exit()
    async def cancel_all_orders_for_strategy(self, strategy_name: str):
        orders = self.get_active_orders(strategy_name)
        for order in orders:
            await self.cancel_order(order.client_order_id)

    async def _save_component_states(self) -> None:
        """Сохраняет состояния OrderManager и CapitalManager."""
        try:
            await self.state_store.save_component_state(
                'order_manager', self.order_manager.save_state()
            )
            await self.state_store.save_component_state(
                'capital_manager', self.capital_manager.save_state()
            )
            logger.info("Component states saved (OrderManager, CapitalManager)")
        except Exception as e:
            logger.error(f"Failed to save component states: {e}")

    async def load_component_states(self) -> None:
        """Загружает состояния OrderManager и CapitalManager при старте приложения."""
        om_state = await self.state_store.load_component_state('order_manager')
        if om_state:
            self.order_manager.load_state(om_state)
            logger.info("OrderManager state restored")

        cm_state = await self.state_store.load_component_state('capital_manager')
        if cm_state:
            self.capital_manager.load_state(cm_state)
            logger.info("CapitalManager state restored")

    async def _auto_save(self, interval: int = 300) -> None:
        try:
            while True:
                await asyncio.sleep(interval)
                for name, strategy in self._strategies.items():
                    if strategy._status == 'RUNNING':
                        await self.state_store.save_strategy_state(name, strategy.save_state())
                await self._save_component_states()
                logger.debug("Auto-save completed")
        except asyncio.CancelledError:
            logger.debug("Auto-save task cancelled")
            raise

    async def _subscribe_strategy_data(self, strategy: Strategy) -> None:
        # Подписка на тики и свечи согласно списку subscriptions
        for sym, tf in strategy.subscriptions:
            if tf == 'tick':
                await self.gateway.subscribe(strategy.name, sym, 'tick')
            else:
                await self.gateway.subscribe(strategy.name, sym, 'candle', tf)

        # Создаём общие обработчики (один раз на стратегию)
        if strategy.name not in self._handlers:
            async def tick_handler(event: TickEvent):
                await strategy.on_tick(event.tick)

            async def candle_handler(event: CandleEvent):
                await strategy.on_candle(event.candle)

            self._handlers[strategy.name] = {
                'tick': tick_handler,
                'candle': candle_handler
            }

        handlers = self._handlers[strategy.name]
        tick_handler = handlers['tick']
        candle_handler = handlers['candle']

        # Подписка на конкретные топики
        for sym, tf in strategy.subscriptions:
            if tf == 'tick':
                topic = f"market.tick.{sym}"
                self.event_bus.subscribe(topic, tick_handler)
            else:
                topic = f"market.candle.{sym}.{tf}"
                self.event_bus.subscribe(topic, candle_handler)

    async def _unsubscribe_strategy_data(self, strategy: Strategy) -> None:
        for sym, tf in strategy.subscriptions:
            if tf == 'tick':
                await self.gateway.unsubscribe(strategy.name, sym, 'tick')
            else:
                await self.gateway.unsubscribe(strategy.name, sym, 'candle', tf)

        handlers = self._handlers.pop(strategy.name, None)
        if not handlers:
            return
        tick_handler = handlers['tick']
        candle_handler = handlers['candle']

        for sym, tf in strategy.subscriptions:
            if tf == 'tick':
                topic = f"market.tick.{sym}"
                self.event_bus.unsubscribe(topic, tick_handler)
            else:
                topic = f"market.candle.{sym}.{tf}"
                self.event_bus.unsubscribe(topic, candle_handler)

    def _rebalance_allocations(self):
        """Равномерно распределяет доли между оставшимися стратегиями."""
        count = len(self._strategies)
        if count == 0:
            return
        equal_pct = 100.0 / count
        for name, strategy in self._strategies.items():
            self.capital_manager.set_strategy(strategy, equal_pct)

    async def _save_strategies_list(self) -> None:
        strategies_meta = []
        for s in self._strategies.values():
            strategies_meta.append({
                'name': s.name,
                'class_name': s.__class__.__name__,
                'subscriptions': s.subscriptions,
                'mode': s.mode,
            })
        await self.state_store.save_strategies_list(strategies_meta)

    def get_all_snapshots(self) -> List[dict]:
        return [s.get_light_snapshot() for s in self._strategies.values()]

    def get_strategy_snapshot(self, name: str) -> Optional[dict]:
        s = self._strategies.get(name)
        return s.get_snapshot() if s else None
