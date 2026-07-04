from abc import ABC, abstractmethod
from core.models import OrderSide

class CommissionModel(ABC):
    @abstractmethod
    def calculate(self, symbol: str, price: float, volume: float, side: OrderSide) -> float:
        ...

class FixedCommission(CommissionModel):
    """Фиксированная комиссия за сделку."""
    def __init__(self, fee: float):
        self.fee = fee

    def calculate(self, symbol: str, price: float, volume: float, side: OrderSide) -> float:
        return self.fee

class PercentageCommission(CommissionModel):
    """Комиссия в процентах от оборота."""
    def __init__(self, percent: float):
        self.percent = percent

    def calculate(self, symbol: str, price: float, volume: float, side: OrderSide) -> float:
        return price * volume * self.percent / 100.0
