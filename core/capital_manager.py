import logging
from typing import Dict, Optional
from core.strategy import Strategy

logger = logging.getLogger(__name__)

class CapitalManager:
    """
    Управляет общим капиталом и распределяет его между стратегиями.
    Каждая стратегия получает долю (percentage) от total_capital.
    Неиспользуемый капитал (разница между выделенным и текущим эквити стратегии)
    может быть перераспределён другим стратегиям.
    """
    def __init__(self, total_capital: float = 100000.0, max_leverage: float = 1.0):
        self.total_capital = total_capital
        self.max_leverage = max_leverage
        self.shares: Dict[str, int] = {}  # целые доли
        self._strategies: Dict[str, Strategy] = {}

    def set_share(self, name: str, share: int):
        self.shares[name] = share

    def get_share(self, name: str) -> int:
        return self.shares.get(name, 0)

    def set_strategy(self, strategy: Strategy, share: int = 0):
        self.shares[strategy.name] = share
        self._strategies[strategy.name] = strategy

    def remove_strategy(self, name: str):
        self.shares.pop(name, None)
        self._strategies.pop(name, None)

    def get_allocated_capital(self, name: str) -> float:
        total_shares = sum(self.shares.values())
        if total_shares == 0:
            return 0.0
        return self.total_capital * self.shares.get(name, 0) / total_shares

    def get_available_capital(self, strategy_name: str) -> float:
        """
        Доступный капитал = выделенный – (текущая стоимость позиций).
        Стоимость позиций считается как сумма(abs(pos) * last_price) по всем символам стратегии.
        """
        strategy = self._strategies.get(strategy_name)
        if not strategy:
            return 0.0
        allocated = self.get_allocated_capital(strategy_name)
        used = 0.0
        for sym, pos in strategy.positions.items():
            price = strategy._last_prices.get(sym, 0.0)
            if price > 0:
                used += abs(pos) * price
        return max(0.0, allocated - used)

    def redistribute(self):
        # заглушка
        pass