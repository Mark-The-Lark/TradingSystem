# Аудит и доработка — итоговый отчёт

## 1. Исправленные баги (Critical → Minor)

### CRITICAL (runtime errors)
| # | Файл | Ошибка | Исправление |
|---|------|--------|-------------|
| 1 | `core/order_manager.py` | `TimeInForce` используется, но не импортирован → `NameError` на partial fill | Добавлен импорт |
| 2 | `core/strategy.py` | Дублирующий `on_init()`: второй (`pass`) затирает первый; первый вызывает несуществующий `_get_gateway()` | Удалён сломанный первый `on_init` |
| 3 | `core/backtest_engine.py` | Использует старый конструктор стратегии (`symbol=`, `timeframes=`) — не совместим с новым `Strategy` | Переписан под новый API |
| 4 | `core/backtest_engine.py` | Использует `strategy.position` (старый скаляр) вместо `strategy.positions` (dict) | Переход на dict |
| 5 | `gui/capital_panel.py` | `for name in .items()` итерирует кортежи `(key, value)` вместо ключей | Заменено на `.keys()` |

### SERIOUS (incorrect behavior)
| # | Файл | Ошибка | Исправление |
|---|------|--------|-------------|
| 6 | `core/portfolio_backtest_engine.py` | `subscriptions=` закомментирован → стратегии не получают свечей | Раскомментировано |
| 7 | `core/portfolio_backtest_engine.py` | `asyncio.run()` вызывался на каждой свече (×100K+) → extreme slowness | Один `asyncio.run()` на весь прогон |
| 8 | `core/backtest_engine.py` | То же: `asyncio.run()` per-candle | Один `asyncio.run()` |
| 9 | `gui/detail_panel.py` | `active_signals` содержит объекты `Order`, но код обращается к ним как к `dict` (`.get(...)`) | Переход на атрибуты объекта |

### MINOR
| # | Файл | Ошибка | Исправление |
|---|------|--------|-------------|
| 10 | `strategies/capital_test_strategy.py` | Весь файл — старый API: `self.position`, `self.symbol`, `price_history[tf]`, `get_position_size(price)` | Полностью переписан под новый API |
| 11 | `core/events.py` | `ConnectionStateEvent` определён дважды — второе определение затирает первое | Удалён дубликат |
| 12 | `strategies/__init__.py` | `SMACrossoverStrategy2` → `SMACrossoverStrategy` (неправильный класс) | Исправлен маппинг |

---

## 2. Реализованное: сохранение состояний

### `core/state_store.py`
Добавлены методы в `StateStore` ABC и `JsonStateStore`:
- `save_component_state(name, state)` — сохраняет `<name>_state.json`
- `load_component_state(name)` — загружает, возвращает `None` если файл не найден

### `core/order_manager.py`
- `save_state()` — сериализует `_active_orders` + `_order_history`
- `load_state(state)` — восстанавливает историю; активные ордера помечаются `CANCELLED` (статус неизвестен без брокера)

### `core/capital_manager.py`
- `save_state()` — сохраняет `total_capital`, `max_leverage`, `shares`
- `load_state(state)` — восстанавливает конфигурацию капитала

### `core/strategy_manager.py`
- `_save_component_states()` — вызывается в `stop_all()` и `_auto_save()`
- `load_component_states()` — вызывается из `main.py` при старте

### `main.py`
Последовательность загрузки: `load_component_states()` → `load_initial()` (стратегии)

---

## 3. Реализованное: дорожная карта

### Roadmap 6.2 — Внутренний риск-менеджмент (новые методы в `Strategy`)
```python
strategy.compute_atr(symbol, timeframe, period=14)         # → float | None
strategy.compute_atr_stop(symbol, timeframe, entry_price,  # → float | None
    direction='long', atr_period=14, atr_multiplier=2.0)
strategy.get_position_size_by_risk(symbol, entry_price,    # → float
    stop_price, risk_pct=0.01)
```

### Roadmap 6.1 — Параллельный бэктест (`core/parallel_backtest.py`)
```python
# Запуск нескольких BacktestEngine в параллельных потоках
runner = ParallelBacktestRunner(data, StrategyClass, base_params, ...)
results = runner.run([{'name': 'r1', 'params': {'fast': 5}}, ...])

# Параметрическая оптимизация (grid search)
ranked = ParallelBacktestRunner.grid_search(
    data=data, strategy_class=SMACrossover,
    param_grid={'fast': [5,10,20], 'slow': [30,50,100]},
    rank_by='sharpe_ratio',
)
```

---

## 4. Тесты

| Файл | Кол-во | Покрытие |
|------|--------|---------|
| `test_strategy.py` | 12 | `Strategy`: история, fill, save/load, snapshots, send_order |
| `test_backtest_engine.py` | 14 | `BacktestEngine` + `PortfolioBacktestEngine` end-to-end |
| `test_capital_manager.py` | 9 | `CapitalManager`: allocation, available capital, persistence |
| `test_persistence.py` | 11 | `StateStore`, `OrderManager`, `CapitalManager` round-trip |
| `test_metrics.py` | 13 | `calculate_metrics`: returns, drawdown, Sharpe, win-rate |
| `test_strategy_manager.py` | 17 | `StrategyManager`: add/remove, routing, start/stop, allocation |
| `test_risk_and_parallel.py` | 20 | ATR, risk sizing, `ParallelBacktestRunner`, `grid_search` |
| Итого новых/переписанных | **96** | |
| Уже существовавших | 10 | models, events, time_provider, order_manager |
| **ВСЕГО** | **106 / 106 ✅** | |

---

## 5. Ожидается от вас: QuikGateway

Перед реализацией нужны ваши решения по двум архитектурным вопросам:

**Вопрос 1 — `class_code`** (QUIK требует для всех операций):
- **A**: Добавить в модель `Order` поле `class_code: Optional[str] = None`
- **B**: Хранить маппинг `{symbol → class_code}` в конфиге `QuikGateway`

**Вопрос 2 — торговый счёт** (`account`):
- **A**: Добавить в модель `Order`
- **B**: Задавать один раз в конфиге `QuikGateway`

Рекомендую B/B — не ломает существующие модели и интерфейсы.
