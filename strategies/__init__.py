from strategies.test_stategy import TestStrategy
from .sma_crossover import SMACrossoverStrategy
from .capital_test_strategy import CapitalTestStrategy
from .sma_2 import SMACrossoverStrategy2

STRATEGY_REGISTRY = {
    'TestStrategy': TestStrategy,
    'SMACrossoverStrategy': SMACrossoverStrategy,
    'SMACrossoverStrategy2': SMACrossoverStrategy2,
    # 'CapitalTestStrategy': CapitalTestStrategy,
}
