"""Tests for core/metrics.py."""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from core.metrics import calculate_metrics
from core.models import Trade


def make_equity_curve(values, start=datetime(2024, 1, 1)):
    """Helper: creates an equity DataFrame from a list of values."""
    ts = [start + timedelta(minutes=i) for i in range(len(values))]
    return pd.DataFrame({'timestamp': ts, 'equity': values})


def make_trade(pnl, symbol='AAPL'):
    now = datetime(2024, 1, 1)
    return Trade(
        entry_time=now, exit_time=now,
        symbol=symbol,
        direction='long',
        entry_price=100.0, exit_price=100.0 + pnl,
        volume=1.0, commission=0.0, slippage=0.0,
        pnl=pnl, exit_reason='signal',
    )


def test_empty_curve_returns_empty():
    df = pd.DataFrame(columns=['timestamp', 'equity'])
    result = calculate_metrics(df)
    assert result == {}


def test_single_point_returns_empty():
    df = make_equity_curve([10_000])
    result = calculate_metrics(df)
    assert result == {}


def test_flat_equity_zero_return():
    df = make_equity_curve([10_000] * 10)
    result = calculate_metrics(df)
    assert result.get('total_return_pct', 0.0) == pytest.approx(0.0, abs=1e-9)


def test_positive_return():
    df = make_equity_curve([10_000, 11_000])
    result = calculate_metrics(df)
    assert result['total_return_pct'] == pytest.approx(10.0)


def test_negative_return():
    df = make_equity_curve([10_000, 9_000])
    result = calculate_metrics(df)
    assert result['total_return_pct'] == pytest.approx(-10.0)


def test_max_drawdown_negative():
    # Equity goes up then down
    df = make_equity_curve([10_000, 12_000, 11_000, 9_000, 10_500])
    result = calculate_metrics(df)
    assert result['max_drawdown_pct'] < 0


def test_no_drawdown_when_monotone_increasing():
    df = make_equity_curve([10_000, 10_100, 10_200, 10_300])
    result = calculate_metrics(df)
    assert result['max_drawdown_pct'] == pytest.approx(0.0, abs=1e-6)


def test_win_rate_all_wins():
    df = make_equity_curve([10_000, 10_500])
    trades = [make_trade(pnl=100) for _ in range(5)]
    result = calculate_metrics(df, trades)
    assert result['win_rate_pct'] == pytest.approx(100.0)
    assert result['num_trades'] == 5


def test_win_rate_all_losses():
    df = make_equity_curve([10_000, 9_500])
    trades = [make_trade(pnl=-50) for _ in range(4)]
    result = calculate_metrics(df, trades)
    assert result['win_rate_pct'] == pytest.approx(0.0)


def test_profit_factor_with_mixed_trades():
    df = make_equity_curve([10_000, 10_200])
    trades = [make_trade(pnl=200), make_trade(pnl=100), make_trade(pnl=-100)]
    result = calculate_metrics(df, trades)
    # profit_sum = 300, loss_sum = 100 → PF = 3
    assert result['profit_factor'] == pytest.approx(3.0)


def test_profit_factor_no_losses():
    df = make_equity_curve([10_000, 10_500])
    trades = [make_trade(pnl=100), make_trade(pnl=200)]
    result = calculate_metrics(df, trades)
    assert result['profit_factor'] == float('inf')


def test_sharpe_nonzero_for_trending_equity():
    # Monotone increase → positive Sharpe
    df = make_equity_curve(list(range(10_000, 10_200, 10)))
    result = calculate_metrics(df)
    assert result.get('sharpe_ratio', 0) > 0


def test_metrics_keys_present():
    df = make_equity_curve([10_000, 11_000, 10_500, 11_500])
    trades = [make_trade(pnl=500), make_trade(pnl=-200)]
    result = calculate_metrics(df, trades)
    expected_keys = {
        'total_return_pct', 'sharpe_ratio', 'max_drawdown_pct',
        'num_trades', 'win_rate_pct', 'avg_profit', 'profit_factor',
    }
    assert expected_keys.issubset(result.keys())
