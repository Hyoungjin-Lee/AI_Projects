from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MORNING_REPORT_DIR = PROJECT_ROOT / "morning_report"
if str(MORNING_REPORT_DIR) not in sys.path:
    sys.path.insert(0, str(MORNING_REPORT_DIR))

from trading_state import TradingStateStore


def test_reset_daily(tmp_path):
    store = TradingStateStore(path=tmp_path / "trading_state.json")
    store.data.realized_pnl = -100000
    store.data.buy_count_today = 3
    store.data.sell_count_today = 2
    store.data.block_new_orders = True
    store.start_trial(2, at=datetime(2026, 4, 23, 9, 0, 0))
    store.data.cooldown_until = {
        "005930": "2026-04-23T00:00:00",
        "000660": "2026-04-23T10:35:00",
    }

    store.reset_daily(date(2026, 4, 23), 3000000)

    assert store.data.realized_pnl == 0
    assert store.data.daily_start_orderable_cash == 3000000
    assert store.data.buy_count_today == 0
    assert store.data.sell_count_today == 0
    assert store.data.block_new_orders is False
    assert store.data.last_reset_date == "2026-04-23"
    assert store.data.trial_mode is False
    assert store.data.trial_started_at is None
    assert "005930" not in store.data.cooldown_until
    assert "000660" in store.data.cooldown_until


def test_should_block_logic(tmp_path):
    store = TradingStateStore(path=tmp_path / "trading_state.json")
    store.data.daily_start_orderable_cash = 0
    store.data.realized_pnl = -100
    assert store.should_block() is False

    store.data.daily_start_orderable_cash = 3000000
    store.data.realized_pnl = -2999999
    assert store.should_block() is False

    store.data.realized_pnl = -3000000
    assert store.should_block() is True


def test_cooldown(tmp_path):
    store = TradingStateStore(path=tmp_path / "trading_state.json")
    now = datetime(2026, 4, 23, 10, 30, 0)
    until = datetime(2026, 4, 23, 10, 35, 0)

    store.set_cooldown("005930", until)

    assert store.is_in_cooldown("005930", now) is True
    assert store.cooldown_remaining_seconds("005930", now) == 300
    assert store.is_in_cooldown("005930", until) is False
    assert store.cooldown_remaining_seconds("005930", until) == 0


def test_in_flight_by_side(tmp_path):
    store = TradingStateStore(path=tmp_path / "trading_state.json")

    store.mark_in_flight("005930", "BUY", at=datetime(2026, 4, 23, 9, 1, 2))

    assert store.is_in_flight("005930") is True
    assert store.is_in_flight("005930", side="BUY") is True
    assert store.is_in_flight("005930", side="SELL") is False

    store.clear_in_flight("005930")
    assert store.is_in_flight("005930") is False


def test_start_stop_trial(tmp_path):
    store = TradingStateStore(path=tmp_path / "trading_state.json")
    at = datetime(2026, 4, 23, 9, 1, 2)

    store.start_trial(2, at=at)

    assert store.data.trial_mode is True
    assert store.data.trial_max_buys == 2
    assert store.data.trial_started_at == "2026-04-23T09:01:02"

    store.stop_trial()

    assert store.data.trial_mode is False
    assert store.data.trial_started_at is None
    assert store.data.trial_max_buys == 2


def test_persist_roundtrip(tmp_path):
    path = tmp_path / "trading_state.json"
    store = TradingStateStore(path=path)
    store.reset_daily(date(2026, 4, 23), 3000000)
    store.inc_buy()
    store.inc_sell()
    store.add_realized_pnl(-25000)
    store.set_cooldown("005930", datetime(2026, 4, 23, 10, 35, 0))
    store.mark_in_flight("005930", "SELL", at=datetime(2026, 4, 23, 9, 5, 0))
    store.start_trial(3, at=datetime(2026, 4, 23, 9, 10, 0))
    store.persist()

    restored = TradingStateStore(path=path)

    assert restored.data.last_reset_date == "2026-04-23"
    assert restored.data.realized_pnl == -25000
    assert restored.data.buy_count_today == 1
    assert restored.data.sell_count_today == 1
    assert restored.data.cooldown_until["005930"] == "2026-04-23T10:35:00"
    assert restored.data.in_flight_orders["005930"].side == "SELL"
    assert restored.data.trial_mode is True
    assert restored.data.trial_max_buys == 3


def test_corrupt_file_backup(tmp_path):
    path = tmp_path / "trading_state.json"
    path.write_text("{broken", encoding="utf-8")

    store = TradingStateStore(path=path)

    assert store.data.buy_count_today == 0
    assert not path.exists()
    assert path.with_suffix(".json.corrupt").exists()


def test_start_trial_rejects_non_positive_limit(tmp_path):
    store = TradingStateStore(path=tmp_path / "trading_state.json")

    with pytest.raises(ValueError, match="trial max_buys must be positive"):
        store.start_trial(0)
