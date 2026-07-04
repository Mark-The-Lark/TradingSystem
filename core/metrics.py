import numpy as np
import pandas as pd

def calculate_metrics(equity_curve: pd.DataFrame, trades=None) -> dict:
    if equity_curve.empty or len(equity_curve) < 2:
        return {}
    returns = equity_curve['equity'].pct_change().dropna()
    if returns.empty:
        return {}

    total_return = (equity_curve['equity'].iloc[-1] / equity_curve['equity'].iloc[0]) - 1

    # Шарп с учётом минутной частоты (252 торговых дня * 24*60 минут)
    minutes_per_year = 252 * 24 * 60
    sharpe = returns.mean() / returns.std() * np.sqrt(minutes_per_year) if returns.std() != 0 else 0

    # Максимальная просадка
    cumulative = (1 + returns).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max
    max_drawdown = drawdown.min()

    # Метрики на основе сделок
    if trades:
        profits = [t.pnl for t in trades]
        win_rate = sum(1 for p in profits if p > 0) / len(profits) * 100 if profits else 0
        avg_profit = np.mean(profits) if profits else 0
        profit_sum = sum(p for p in profits if p > 0)
        loss_sum = abs(sum(p for p in profits if p < 0))
        profit_factor = profit_sum / loss_sum if loss_sum != 0 else float('inf')
    else:
        num_trades = 0
        win_rate = 0.0
        avg_profit = 0.0
        profit_factor = 0.0

    return {
        'total_return_pct': total_return * 100,
        'sharpe_ratio': sharpe,
        'max_drawdown_pct': max_drawdown * 100,
        'num_trades': len(trades) if trades else 0,
        'win_rate_pct': win_rate,
        'avg_profit': avg_profit,
        'profit_factor': profit_factor,
    }
