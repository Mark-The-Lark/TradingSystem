# # core/strategy_manager.py
# import asyncio
# import logging
# from typing import Dict, Optional, List
# from core.events import EventBus, TickEvent, CandleEvent
# from core.strategy import Strategy
# from core.gateway import BaseGateway
# from core.order_manager import OrderManager
# from core.state_store import StateStore
# from core.capital_manager import CapitalManager

# logger = logging.getLogger(__name__)

# class StrategyManager:
#     def __init__(self, event_bus: EventBus, gateway: BaseGateway, order_manager: OrderManager,
#                  state_store: StateStore, capital_manager=None):
#         self.event_bus = event_bus
#         self.gateway = gateway
#         self.order_manager = order_manager
#         self.capital_manager = capital_manager or CapitalManager()
#         self.state_store = state_store
#         self._strategies: Dict[str, Strategy] = {}
#         self._handlers: Dict[str, dict] = {}  # strategy_name -> {'tick': handler, 'candles': {tf: handler}}
#         self._auto_save_task: Optional[asyncio.Task] = None

#     async def add_strategy(self, strategy: Strategy) -> None:
#         # print(f"DEBUG: add_strategy called for {strategy.name}")
#         if strategy.name in self._strategies:
#                 raise ValueError(f"Strategy with name {strategy.name} already exists")
#         self._strategies[strategy.name] = strategy
#         # print("DEBUG: subscribing...")
#         await self._subscribe_strategy_data(strategy)
#         # print("DEBUG: loading state...")
#         saved_state = await self.state_store.load_strategy_state(strategy.name)
#         if saved_state:
#             strategy.load_state(saved_state)
#         # print("DEBUG: saving list...")
#         await self._save_strategies_list()
#         # print("DEBUG: add_strategy complete")
#         strategy._capital_manager = self.capital_manager
#         num_strategies = len(self._strategies)
#         if num_strategies > 0:
#             self.capital_manager.set_strategy(strategy, 1)
#         # У остальных пересчитываем доли, чтобы сумма была 100
#         self._rebalance_allocations()

#     async def remove_strategy(self, name: str) -> None:
#         strategy = self._strategies.pop(name, None)
#         if strategy:
#             await self._unsubscribe_strategy_data(strategy)
#             await self.state_store.delete_strategy_state(name)
#             await self._save_strategies_list()
#             logger.info(f"Strategy {name} removed")

#     async def start_strategy(self, name: str) -> None:
#         strategy = self._strategies.get(name)
#         if not strategy:
#             return
#         strategy.set_status('RUNNING')
#         await strategy.on_init()
#         # Подписка уже была добавлена при add_strategy, но на случай если отписывались — повторяем
#         if name not in self._handlers:
#             await self._subscribe_strategy_data(strategy)
#         logger.info(f"Strategy {name} started")

#     async def stop_strategy(self, name: str) -> None:
#         strategy = self._strategies.get(name)
#         if not strategy:
#             return
#         strategy.set_status('STOPPED')
#         await self._unsubscribe_strategy_data(strategy)
#         await self.state_store.save_strategy_state(name, strategy.save_state())
#         logger.info(f"Strategy {name} stopped")

#     async def start_all(self) -> None:
#         await self.gateway.connect()
#         for name in list(self._strategies.keys()):
#             await self.start_strategy(name)
#         # Отменяем предыдущее автосохранение, если есть
#         if self._auto_save_task and not self._auto_save_task.done():
#             self._auto_save_task.cancel()
#         self._auto_save_task = asyncio.create_task(self._auto_save())

#     async def stop_all(self) -> None:
#         if self._auto_save_task and not self._auto_save_task.done():
#             self._auto_save_task.cancel()
#             self._auto_save_task = None
#         for name in list(self._strategies.keys()):
#             await self.stop_strategy(name)
#         await self.gateway.disconnect()

#     async def _auto_save(self, interval: int = 300) -> None:
#         try:
#             while True:
#                 await asyncio.sleep(interval)
#                 for name, strategy in self._strategies.items():
#                     if strategy._status == 'RUNNING':
#                         await self.state_store.save_strategy_state(name, strategy.save_state())
#                 logger.debug("Auto-save completed")
#         except asyncio.CancelledError:
#             logger.debug("Auto-save task cancelled")
#             raise

#     async def _subscribe_strategy_data(self, strategy: Strategy) -> None:
#         await self.gateway.subscribe(strategy.name, strategy.symbol, 'tick')
#         for tf in strategy.timeframes:
#             await self.gateway.subscribe(strategy.name, strategy.symbol, 'candle', tf)

#         async def tick_handler(event: TickEvent):
#             await strategy.on_tick(event.tick)

#         async def candle_handler(event: CandleEvent):
#             await strategy.on_candle(event.candle)

#         handlers = {'tick': tick_handler, 'candles': {}}
#         tick_topic = f"market.tick.{strategy.symbol}"
#         self.event_bus.subscribe(tick_topic, tick_handler)
#         for tf in strategy.timeframes:
#             candle_topic = f"market.candle.{strategy.symbol}.{tf}"
#             self.event_bus.subscribe(candle_topic, candle_handler)
#             handlers['candles'][tf] = candle_handler
#         self._handlers[strategy.name] = handlers

#     async def _unsubscribe_strategy_data(self, strategy: Strategy) -> None:
#         await self.gateway.unsubscribe(strategy.name, strategy.symbol, 'tick')
#         for tf in strategy.timeframes:
#             await self.gateway.unsubscribe(strategy.name, strategy.symbol, 'candle', tf)

#         handlers = self._handlers.pop(strategy.name, None)
#         if not handlers:
#             return
#         tick_topic = f"market.tick.{strategy.symbol}"
#         self.event_bus.unsubscribe(tick_topic, handlers['tick'])
#         for tf, handler in handlers['candles'].items():
#             candle_topic = f"market.candle.{strategy.symbol}.{tf}"
#             self.event_bus.unsubscribe(candle_topic, handler)

#     async def _save_strategies_list(self) -> None:
#         strategies_meta = []
#         for s in self._strategies.values():
#             strategies_meta.append({
#                 'name': s.name,
#                 'class_name': s.__class__.__name__,
#                 'symbol': s.symbol,
#                 'mode': s.mode,
#                 'timeframes': s.timeframes
#             })
#         await self.state_store.save_strategies_list(strategies_meta)

#     def get_all_snapshots(self) -> List[dict]:
#         return [s.get_snapshot() for s in self._strategies.values()]

#     def get_strategy_snapshot(self, name: str) -> Optional[dict]:
#         s = self._strategies.get(name)
#         return s.get_snapshot() if s else None
    
#     def _rebalance_allocations(self):
#         """Равномерно распределяет доли между всеми стратегиями."""
#         count = len(self._strategies)
#         if count == 0:
#             return
#         for name in self._strategies:
#             self.capital_manager.set_share(name, 1)


# core/strategy_manager.py

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
        # strategy = self._strategies.get(name)
        # if not strategy:
        #     return
        # strategy.set_status('RUNNING')
        # await strategy.on_init()

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
        await self.gateway.disconnect()

    async def _auto_save(self, interval: int = 300) -> None:
        try:
            while True:
                await asyncio.sleep(interval)
                for name, strategy in self._strategies.items():
                    if strategy._status == 'RUNNING':
                        await self.state_store.save_strategy_state(name, strategy.save_state())
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