import sys
import asyncio
import threading
import logging
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from core.events import EventBus
from core.simulation_gateway import SimulationGateway
from core.time_provider import RealTimeProvider
from core.commission import FixedCommission
from core.risk_manager import RiskManager
from core.order_manager import OrderManager
from core.strategy_manager import StrategyManager
from core.state_store import JsonStateStore
from core.capital_manager import CapitalManager
from gui.main_window import MainWindow
from strategies import STRATEGY_REGISTRY

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class AsyncLoopThread(threading.Thread):
    """Поток, в котором работает выделенный asyncio event loop."""
    def __init__(self):
        super().__init__(daemon=True)
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()

    def run(self):
        asyncio.set_event_loop(self.loop)
        self.ready.set()
        self.loop.run_forever()

    def run_coroutine(self, coro):
        """Запускает корутину в этом цикле и возвращает concurrent.futures.Future."""
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)

def main():
    app = QApplication(sys.argv)

    # Запускаем фоновый asyncio loop
    async_loop = AsyncLoopThread()
    async_loop.start()
    async_loop.ready.wait()          # ждём, пока цикл запустится
    logger.info("Async event loop started")

    # Инициализация синхронных компонентов ядра
    event_bus = EventBus()
    time_provider = RealTimeProvider()
    gateway = SimulationGateway(event_bus, time_provider, base_prices={"AFKS": 150.0, "GOOGL": 2800.0})
    risk_manager = RiskManager()
    commission = FixedCommission(1.0)
    order_manager = OrderManager(event_bus, gateway, risk_manager, commission)
    capital_manager = CapitalManager(total_capital=100000.0, max_leverage=1.0)

    # Хранилище состояний
    data_path = Path(__file__).parent / 'data'
    (data_path / 'states').mkdir(parents=True, exist_ok=True)
    state_store = JsonStateStore(base_path=str(data_path / 'states'))

    strategy_manager = StrategyManager(event_bus, gateway, order_manager, state_store, capital_manager)

    # Загружаем сохранённые стратегии (используем фоновый цикл)
    async def load_initial():
        saved = await state_store.load_strategies_list()
        for meta in saved:
            cls = STRATEGY_REGISTRY.get(meta['class_name'])
            if cls:
                strategy = cls(
                    name=meta['name'],
                    # symbol=meta['symbol'],
                    event_bus=event_bus,
                    order_manager=order_manager,
                    mode=meta.get('mode', 'AUTO'),
                    # timeframes=meta.get('timeframes', ['1m'])
                )
                await strategy_manager.add_strategy(strategy)
                logger.info(f"Loaded strategy {meta['name']}")

    # Ожидаем завершения загрузки, чтобы окно увидело уже существующие стратегии
    async_loop.run_coroutine(load_initial()).result()

    # Создаём главное окно
    window = MainWindow(event_bus, strategy_manager, STRATEGY_REGISTRY, async_loop)
    window.show()

    # Запускаем Qt event loop
    exit_code = app.exec()

    # Останавливаем asyncio event loop и ждём завершения потока
    async_loop.stop()
    async_loop.join(timeout=2)
    sys.exit(exit_code)

if __name__ == "__main__":
    main()