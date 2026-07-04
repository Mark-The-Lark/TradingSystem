from datetime import datetime
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field, PositiveFloat

class OrderSide(str, Enum):
    BUY = 'buy'
    SELL = 'sell'

class OrderType(str, Enum):
    MARKET = 'market'
    LIMIT = 'limit'
    STOP = 'stop'
    TAKE_PROFIT = 'take_profit'

class OrderStatus(str, Enum):
    PENDING = 'pending'
    ACTIVE = 'active'
    FILLED = 'filled'
    PARTIALLY_FILLED = 'partially_filled'
    CANCELLED = 'cancelled'
    REJECTED = 'rejected'

class TimeInForce(str, Enum):
    GTC = 'GTC'
    IOC = 'IOC'
    FOK = 'FOK'

class Order(BaseModel):
    client_order_id: str
    gateway_order_id: Optional[str] = None
    strategy_name: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    price: Optional[float] = None  # None для market
    stop_price: Optional[float] = None
    volume: PositiveFloat
    filled_volume: float = 0.0
    average_fill_price: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    time_in_force: TimeInForce = TimeInForce.GTC
    expiry_time: Optional[datetime] = None
    commission: float = 0.0
    slippage: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class Tick(BaseModel):
    timestamp: datetime
    symbol: str
    bid: float
    ask: float
    last: float
    volume: float

class Candle(BaseModel):
    symbol: str
    timeframe: str  # например "1m"
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp: datetime  # время закрытия свечи
    is_complete: bool = True

class Trade(BaseModel):
    entry_time: datetime
    exit_time: datetime
    symbol: str
    direction: str  # 'long' или 'short'
    entry_price: float
    exit_price: float
    volume: float
    commission: float
    slippage: float
    pnl: float
    exit_reason: str
