from __future__ import annotations

import pytest

from risk_analyzer import calculate_cvar, calculate_mdd, calculate_risk_snapshot, calculate_var


def test_calculate_var_cvar_mdd_normal_distribution_case():
    returns = [-2.5, -1.8, -1.2, -0.5, 0.1, 0.5, 1.0, 1.5, 2.0, 3.0] * 6
    equity = [100, 101, 100, 102, 101, 103, 104, 102, 105, 106]

    var_95 = calculate_var(returns, 0.95)
    cvar_95 = calculate_cvar(returns, 0.95)
    mdd = calculate_mdd(equity)

    assert var_95 == pytest.approx(-2.5)
    assert cvar_95 == pytest.approx(-2.5)
    assert mdd == pytest.approx(-1.92)


def test_short_history_boundary_case():
    history = [
        {"date": "2026-05-01", "total_value": 100.0, "total_return_pct": 0.0},
        {"date": "2026-05-02", "total_value": 101.0, "total_return_pct": 1.0},
        {"date": "2026-05-03", "total_value": 99.0, "total_return_pct": -1.0},
    ]

    snapshot = calculate_risk_snapshot(history)

    assert snapshot.var_95 is None
    assert snapshot.cvar_95 is None
    assert snapshot.mdd_60d == pytest.approx(-1.98)
    assert snapshot.portfolio_status == "safe"


def test_calculate_mdd_max_drawdown_case():
    equity = [100, 105, 110, 95, 100, 90, 95, 105, 100]

    assert calculate_mdd(equity) == pytest.approx(-18.18)
