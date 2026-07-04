# core/parallel_backtest.py
"""
Параллельный запуск нескольких независимых бэктестов.

Используется для:
- параметрической оптимизации (grid search по параметрам стратегии)
- сравнения нескольких стратегий на одних данных без разделения капитала

В отличие от PortfolioBacktestEngine, стратегии здесь полностью независимы —
у каждой свой начальный капитал, нет общего CapitalManager.

Использует ThreadPoolExecutor: BacktestEngine.run() — синхронный метод,
вызывающий asyncio.run() внутри. Несколько вызовов в разных потоках
создают независимые event loop-ы, что полностью безопасно.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Type

import pandas as pd

from core.backtest_engine import BacktestEngine
from core.commission import CommissionModel, FixedCommission
from core.strategy import Strategy

logger = logging.getLogger(__name__)


class ParallelBacktestRunner:
    """
    Запускает несколько BacktestEngine параллельно в пуле потоков.

    Пример — оптимизация параметров SMA:

        from core.parallel_backtest import ParallelBacktestRunner
        from strategies.sma_crossover import SMACrossoverStrategy

        configs = [
            {'name': f'sma_{f}_{s}', 'params': {'fast': f, 'slow': s}}
            for f in [5, 10, 20]
            for s in [30, 50, 100]
        ]

        runner = ParallelBacktestRunner(
            data={'AFKS': df},
            strategy_class=SMACrossoverStrategy,
            base_params={'name': 'opt'},
            initial_capital=100_000,
            max_workers=4,
        )
        results = runner.run(configs)
        best = max(results.values(), key=lambda r: r['metrics'].get('sharpe_ratio', -999))
    """

    def __init__(
        self,
        data: Dict[str, pd.DataFrame],
        strategy_class: Type[Strategy],
        base_params: dict,
        initial_capital: float = 100_000.0,
        commission: Optional[CommissionModel] = None,
        execution_model: str = 'next_bar_open',
        max_workers: int = 4,
    ):
        self.data = data
        self.strategy_class = strategy_class
        self.base_params = base_params
        self.initial_capital = initial_capital
        self.commission = commission or FixedCommission(0.0)
        self.execution_model = execution_model
        self.max_workers = max_workers

    def run(
        self,
        run_configs: List[dict],
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> Dict[str, dict]:
        """
        Запускает бэктесты параллельно.

        Args:
            run_configs: список словарей с ключами:
                - 'name'   (str)  — уникальное имя запуска (ключ в результатах)
                - 'params' (dict) — доп. параметры стратегии, мержатся с base_params
            progress_callback: опционально — fn(run_name, i, total) вызывается
                               из рабочих потоков (thread-safe).

        Returns:
            Dict[run_name → result_dict]  где result_dict — то, что возвращает BacktestEngine.run()
        """
        if not run_configs:
            return {}

        results: Dict[str, dict] = {}
        total = len(run_configs)
        completed = 0

        def _run_one(cfg: dict) -> tuple[str, dict]:
            run_name = cfg['name']
            merged_params = {**self.base_params, **cfg.get('params', {}), 'name': run_name}
            engine = BacktestEngine(
                data=self.data,
                strategy_class=self.strategy_class,
                strategy_params=merged_params,
                initial_capital=self.initial_capital,
                commission=self.commission,
                execution_model=self.execution_model,
            )
            try:
                cb = None
                if progress_callback:
                    cb = lambda i, t: progress_callback(run_name, i, t)
                result = engine.run(progress_callback=cb)
            except Exception as exc:
                logger.error(f"Backtest '{run_name}' failed: {exc}")
                result = engine._empty_result(error=str(exc))
            return run_name, result

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_map = {executor.submit(_run_one, cfg): cfg['name']
                          for cfg in run_configs}
            for future in as_completed(future_map):
                run_name, result = future.result()
                results[run_name] = result
                completed += 1
                logger.info(f"[{completed}/{total}] '{run_name}' done: "
                            f"final_equity={result.get('final_equity', 0):.2f}")

        return results

    # ── Convenience: parameter grid search ────────────────────────────────────
    @classmethod
    def grid_search(
        cls,
        data: Dict[str, pd.DataFrame],
        strategy_class: Type[Strategy],
        param_grid: Dict[str, List[Any]],
        base_params: Optional[dict] = None,
        initial_capital: float = 100_000.0,
        commission: Optional[CommissionModel] = None,
        execution_model: str = 'next_bar_open',
        max_workers: int = 4,
        rank_by: str = 'sharpe_ratio',
    ) -> List[dict]:
        """
        Перебирает декартово произведение параметров и ранжирует по метрике.

        Args:
            param_grid: {param_name: [value1, value2, ...]}
            rank_by:    ключ в result['metrics'] для ранжирования (по убыванию)

        Returns:
            Список словарей (params, name, metrics, final_equity, trades),
            отсортированных по rank_by (лучший — первый).

        Example:
            results = ParallelBacktestRunner.grid_search(
                data={'AFKS': df},
                strategy_class=SMACrossoverStrategy,
                param_grid={'fast': [5, 10], 'slow': [30, 50, 100]},
                rank_by='sharpe_ratio',
            )
            print(results[0])  # best params
        """
        import itertools

        keys = list(param_grid.keys())
        values_product = list(itertools.product(*param_grid.values()))
        run_configs = [
            {'name': '_'.join(f"{k}{v}" for k, v in zip(keys, combo)),
             'params': dict(zip(keys, combo))}
            for combo in values_product
        ]

        runner = cls(
            data=data,
            strategy_class=strategy_class,
            base_params=base_params or {},
            initial_capital=initial_capital,
            commission=commission,
            execution_model=execution_model,
            max_workers=max_workers,
        )
        raw_results = runner.run(run_configs)

        ranked = []
        for cfg in run_configs:
            name = cfg['name']
            res = raw_results.get(name, {})
            metrics = res.get('metrics', {})
            ranked.append({
                'name': name,
                'params': cfg['params'],
                'metrics': metrics,
                'final_equity': res.get('final_equity', 0.0),
                'num_trades': len(res.get('trades', [])),
                rank_by: metrics.get(rank_by, float('-inf')),
            })

        ranked.sort(key=lambda x: x[rank_by], reverse=True)
        return ranked
