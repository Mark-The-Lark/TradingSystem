from typing import Dict, Optional
from core.models import Order, OrderSide

class RiskLimitExceeded(Exception):
    def __init__(self, message: str):
        self.message = message

class RiskManager:
    def __init__(self):
        self._position_limits: Dict[str, float] = {}  # strategy_name -> max absolute position
        self._current_positions: Dict[str, float] = {}  # strategy_name -> current position (sum of volumes, sign sensitive)

    def set_position_limit(self, strategy_name: str, max_position: float):
        self._position_limits[strategy_name] = max_position

    def update_position(self, strategy_name: str, filled_volume: float, side: OrderSide):
        delta = filled_volume if side == OrderSide.BUY else -filled_volume
        self._current_positions[strategy_name] = self._current_positions.get(strategy_name, 0.0) + delta

    def check_order(self, order: Order) -> None:
        """Проверяет, не нарушит ли ордер лимиты. Выбрасывает RiskLimitExceeded."""
        strategy = order.strategy_name
        if strategy in self._position_limits:
            max_pos = self._position_limits[strategy]
            current = self._current_positions.get(strategy, 0.0)
            delta = order.volume if order.side == OrderSide.BUY else -order.volume
            new_pos = current + delta
            if abs(new_pos) > max_pos:
                raise RiskLimitExceeded(
                    f"Order would exceed position limit {max_pos} for strategy {strategy}"
                )