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
        self._limits: Dict[str, float] = {}
        self._used: Dict[str, float] = {}
        self._using_cap: Dict[str, float] = {}
        self._extra: Dict[str, float] = {}        # дополнительный капитал (сверх лимита)
        self._free = total_capital 

    def set_share(self, strategy_name: str, share: int):
        self.shares[strategy_name] = share
        self._used.pop(strategy_name, None)
        self._using_cap.pop(strategy_name, None)
        self._extra.pop(strategy_name, None)
        self._redistribute()

    def set_used(self, strategy_name: str, amount: float) -> None:
        """Устанавливает реально занятый капитал (из OrderManager)."""
        if strategy_name not in self._strategies:
            return
        self._used[strategy_name] = min(amount, self._limits[strategy_name])
        self._redistribute()

    def set_strategy(self, strategy: Strategy, share: int = 0):
        self.shares[strategy.name] = share
        self._strategies[strategy.name] = strategy
        self._using_cap[strategy.name] = 1.0

    def remove_strategy(self, name: str):
        self.shares.pop(name, None)
        self._strategies.pop(name, None)
        self._using_cap.pop(name, None)

    def get_allocated_capital(self, name: str) -> float:
        total_shares = sum(self.shares.values())
        if total_shares == 0:
            return 0.0
        return self.total_capital * self.shares.get(name, 0) / total_shares

    def get_available_capital(self, strategy_name: str) -> float:
        """
        Доступный капитал с учётом персонального плеча стратегии.

        Формула:
            effective = allocated * min(strategy.leverage, self.max_leverage)
            available = effective - used_margin

        strategy.leverage > 1.0 → стратегия может использовать больше выделенной квоты
                                   (заёмный капитал в рамках max_leverage).
        strategy.leverage < 1.0 → стратегия работает консервативно, использует только
                                   часть выделенного капитала.
        """
        strategy = self._strategies.get(strategy_name)
        if not strategy:
            return 0.0
        allocated = self.get_allocated_capital(strategy_name)
        # Применяем плечо стратегии, ограниченное глобальным max_leverage
        leverage = getattr(strategy, 'leverage', 1.0)
        effective_leverage = min(leverage, self.max_leverage)
        effective_capital = allocated * effective_leverage
        # Вычитаем текущую маржу (рыночная стоимость открытых позиций)
        used = 0.0
        for sym, pos in strategy.positions.items():
            price = strategy._last_prices.get(sym, 0.0)
            if price > 0:
                used += abs(pos) * price
        return max(0.0, effective_capital - used)

    def redistribute(self):
        # заглушка
        pass

    # --- Сохранение / восстановление состояния ---
    def save_state(self) -> dict:
        """Сериализует конфигурацию капитала."""
        return {
            'total_capital': self.total_capital,
            'max_leverage': self.max_leverage,
            'shares': dict(self.shares),
        }

    def load_state(self, state: dict) -> None:
        """Восстанавливает конфигурацию капитала. Стратегии регистрируются позже через set_strategy."""
        self.total_capital = state.get('total_capital', self.total_capital)
        self.max_leverage = state.get('max_leverage', self.max_leverage)
        saved_shares = state.get('shares', {})
        for name, share in saved_shares.items():
            self.shares[name] = share
        logger.info(
            f"CapitalManager state loaded: total_capital={self.total_capital}, "
            f"shares={self.shares}"
        )
