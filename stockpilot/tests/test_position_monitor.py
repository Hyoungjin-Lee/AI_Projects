from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MORNING_REPORT_DIR = PROJECT_ROOT / "morning_report"
if str(MORNING_REPORT_DIR) not in sys.path:
    sys.path.insert(0, str(MORNING_REPORT_DIR))

from pending_proposals import PendingProposalsStore, Proposal
from position_monitor import (
    BalanceSnapshot,
    MonitorConfig,
    PositionMonitor,
    TickerBalance,
)
from position_state import PositionStateStore
from trading_state import TradingStateStore


_MARKET_HOUR = datetime(2026, 4, 23, 10, 0, 0)
_BEFORE_MARKET = datetime(2026, 4, 23, 8, 0, 0)
_MIDNIGHT = datetime(2026, 4, 24, 0, 0, 30)


def _test_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = True
    return logger


def _build_monitor(tmp_path: Path, kis_stub: MagicMock, *, name: str = "position_monitor.test") -> PositionMonitor:
    return PositionMonitor(
        kis_client=kis_stub,
        position_store=PositionStateStore(path=tmp_path / "position_state.json"),
        trading_store=TradingStateStore(path=tmp_path / "trading_state.json"),
        proposals_store=PendingProposalsStore(path=tmp_path / "pending_proposals.json"),
        config=MonitorConfig(
            sell_cooldown_seconds=300,
            proposal_expire_seconds=180,
            tick_market=5.0,
            tick_idle=60.0,
        ),
        logger=_test_logger(name),
    )


def _kis_balance_response(rows: list[dict]) -> dict:
    return {"output1": rows, "output2": []}


def _proposal(proposal_id: str, last_sent: str) -> Proposal:
    return Proposal(
        id=proposal_id,
        code="005930",
        name="삼성전자",
        round=1,
        rank=1,
        stage="S1",
        score=0.9,
        tday_rltv=1.5,
        chg=2.0,
        price_ref=70000.0,
        status="pending",
        count=1,
        created_at=last_sent,
        last_sent=last_sent,
    )


def test_run_exits_on_shutdown_signal(tmp_path, monkeypatch):
    kis = MagicMock()
    kis.get_balance.return_value = _kis_balance_response([])
    kis.get_orderable_cash.return_value = 1000000
    monitor = _build_monitor(tmp_path, kis, name="position_monitor.test.run")

    calls = {"count": 0}

    def fake_sleep(seconds: float) -> None:
        calls["count"] += 1
        monitor._running = False

    monkeypatch.setattr(monitor, "_sleep", fake_sleep)
    monitor.run()

    assert calls["count"] >= 1
    assert monitor._running is False
    assert monitor._consecutive_failures == 0


def test_acquire_lock_prevents_double_run_and_releases(tmp_path, monkeypatch):
    import position_monitor as pm

    lock_path = tmp_path / "position_monitor.pid"
    monkeypatch.setattr(pm, "_PIDFILE", lock_path)

    assert pm._acquire_lock() is True
    assert pm._acquire_lock() is False
    pm._release_lock()
    assert not lock_path.exists()


def test_acquire_lock_cleans_stale_pidfile(tmp_path, monkeypatch):
    import position_monitor as pm

    lock_path = tmp_path / "position_monitor.pid"
    lock_path.write_text("999999", encoding="utf-8")
    monkeypatch.setattr(pm, "_PIDFILE", lock_path)

    def fake_kill(pid: int, sig: int) -> None:
        raise OSError("stale")

    monkeypatch.setattr(pm.os, "kill", fake_kill)
    assert pm._acquire_lock() is True
    assert lock_path.read_text(encoding="utf-8").strip().isdigit()


def test_diff_detects_new_buy(tmp_path):
    monitor = _build_monitor(tmp_path, MagicMock(), name="position_monitor.test.new_buy")
    snapshot = BalanceSnapshot(
        fetched_at=_MARKET_HOUR,
        holdings={
            "005930": TickerBalance(
                "005930", "삼성전자", qty=10, avg_price=70000.0, current_price=71000.0
            )
        },
    )

    monitor._diff_and_apply(snapshot, _MARKET_HOUR)

    pos = monitor.positions.get("005930")
    assert pos is not None
    assert pos.qty == 10
    assert pos.avg_price == pytest.approx(70000.0)
    assert pos.stage == 1
    assert monitor.trading.data.buy_count_today == 1


def test_diff_detects_additional_buy_with_fill_price_backsolve(tmp_path):
    monitor = _build_monitor(tmp_path, MagicMock(), name="position_monitor.test.add_buy")
    monitor.positions.apply_buy(
        "005930", "삼성전자", qty=10, price=70000.0, stage=1, at=_MARKET_HOUR
    )
    snapshot = BalanceSnapshot(
        fetched_at=_MARKET_HOUR,
        holdings={
            "005930": TickerBalance(
                "005930", "삼성전자", qty=30, avg_price=73000.0, current_price=74000.0
            )
        },
    )

    monitor._diff_and_apply(snapshot, _MARKET_HOUR)

    pos = monitor.positions.get("005930")
    assert pos is not None
    assert pos.qty == 30
    assert pos.avg_price == pytest.approx(73000.0, abs=1.0)
    assert pos.stage == 2
    assert monitor.trading.data.buy_count_today == 1


def test_diff_detects_partial_sell_with_cooldown(tmp_path):
    monitor = _build_monitor(tmp_path, MagicMock(), name="position_monitor.test.partial_sell")
    monitor.positions.apply_buy(
        "005930", "삼성전자", qty=10, price=70000.0, stage=1, at=_MARKET_HOUR
    )
    snapshot = BalanceSnapshot(
        fetched_at=_MARKET_HOUR,
        holdings={
            "005930": TickerBalance(
                "005930", "삼성전자", qty=3, avg_price=70000.0, current_price=75000.0
            )
        },
    )

    monitor._diff_and_apply(snapshot, _MARKET_HOUR)

    pos = monitor.positions.get("005930")
    assert pos is not None
    assert pos.qty == 3
    assert monitor.trading.data.sell_count_today == 1
    assert monitor.trading.data.realized_pnl == 35000
    assert monitor.trading.is_in_cooldown("005930", _MARKET_HOUR) is True


def test_diff_detects_full_exit(tmp_path):
    monitor = _build_monitor(tmp_path, MagicMock(), name="position_monitor.test.full_exit")
    monitor.positions.apply_buy(
        "005930", "삼성전자", qty=5, price=70000.0, stage=1, at=_MARKET_HOUR
    )
    snapshot = BalanceSnapshot(fetched_at=_MARKET_HOUR, holdings={})

    monitor._diff_and_apply(snapshot, _MARKET_HOUR)

    assert monitor.positions.get("005930") is None
    assert monitor.trading.data.sell_count_today == 1
    assert monitor.trading.data.realized_pnl == 0


def test_diff_without_changes_does_not_persist(tmp_path, monkeypatch):
    monitor = _build_monitor(tmp_path, MagicMock(), name="position_monitor.test.no_change")
    monitor.positions.apply_buy(
        "005930", "삼성전자", qty=5, price=70000.0, stage=1, at=_MARKET_HOUR
    )
    monitor.positions.persist()
    before_position = monitor.positions._path.read_text(encoding="utf-8")
    before_trading = (
        monitor.trading._path.read_text(encoding="utf-8")
        if monitor.trading._path.exists()
        else None
    )

    persist_calls = {"positions": 0, "trading": 0}

    original_positions_persist = monitor.positions.persist
    original_trading_persist = monitor.trading.persist

    def wrapped_positions_persist() -> None:
        persist_calls["positions"] += 1
        original_positions_persist()

    def wrapped_trading_persist() -> None:
        persist_calls["trading"] += 1
        original_trading_persist()

    monkeypatch.setattr(monitor.positions, "persist", wrapped_positions_persist)
    monkeypatch.setattr(monitor.trading, "persist", wrapped_trading_persist)

    snapshot = BalanceSnapshot(
        fetched_at=_MARKET_HOUR,
        holdings={
            "005930": TickerBalance(
                "005930", "삼성전자", qty=5, avg_price=70000.0, current_price=70000.0
            )
        },
    )
    monitor._diff_and_apply(snapshot, _MARKET_HOUR)

    assert persist_calls == {"positions": 0, "trading": 0}
    assert monitor.positions._path.read_text(encoding="utf-8") == before_position
    if before_trading is None:
        assert not monitor.trading._path.exists()
    else:
        assert monitor.trading._path.read_text(encoding="utf-8") == before_trading


def test_diff_updates_peak_and_persists(tmp_path):
    monitor = _build_monitor(tmp_path, MagicMock(), name="position_monitor.test.peak")
    monitor.positions.apply_buy(
        "005930", "삼성전자", qty=5, price=70000.0, stage=1, at=_MARKET_HOUR
    )
    snapshot = BalanceSnapshot(
        fetched_at=_MARKET_HOUR,
        holdings={
            "005930": TickerBalance(
                "005930", "삼성전자", qty=5, avg_price=70000.0, current_price=72000.0
            )
        },
    )

    monitor._diff_and_apply(snapshot, _MARKET_HOUR)

    pos = monitor.positions.get("005930")
    assert pos is not None
    assert pos.peak_price_since_entry == 72000.0


def test_recover_no_divergence(tmp_path):
    kis = MagicMock()
    kis.get_balance.return_value = _kis_balance_response(
        [
            {
                "pdno": "005930",
                "prdt_name": "삼성전자",
                "hldg_qty": "10",
                "pchs_avg_pric": "70000",
                "prpr": "71000",
            }
        ]
    )
    monitor = _build_monitor(tmp_path, kis, name="position_monitor.test.recover_same")
    monitor.positions.apply_buy(
        "005930", "삼성전자", qty=10, price=70000.0, stage=1, at=_MARKET_HOUR
    )

    monitor.recover_on_boot()

    pos = monitor.positions.get("005930")
    assert pos is not None
    assert pos.qty == 10
    assert pos.stage == 1


def test_recover_overwrites_local_on_divergence(tmp_path):
    kis = MagicMock()
    kis.get_balance.return_value = _kis_balance_response(
        [
            {
                "pdno": "005930",
                "prdt_name": "삼성전자",
                "hldg_qty": "15",
                "pchs_avg_pric": "72000",
                "prpr": "73000",
            }
        ]
    )
    monitor = _build_monitor(tmp_path, kis, name="position_monitor.test.recover_overwrite")
    monitor.positions.apply_buy(
        "005930", "삼성전자", qty=10, price=70000.0, stage=2, at=_MARKET_HOUR
    )

    monitor.recover_on_boot()

    pos = monitor.positions.get("005930")
    assert pos is not None
    assert pos.qty == 15
    assert pos.avg_price == pytest.approx(72000.0)
    assert pos.stage == 1
    assert pos.peak_price_since_entry == 73000.0


def test_recover_clears_in_flight_and_expires_proposals(tmp_path):
    kis = MagicMock()
    kis.get_balance.return_value = _kis_balance_response([])
    monitor = _build_monitor(tmp_path, kis, name="position_monitor.test.recover_cleanup")
    monitor.trading.mark_in_flight("005930", "BUY", _MARKET_HOUR)
    monitor.trading.mark_in_flight("000660", "SELL", _MARKET_HOUR)
    old_sent = (datetime.now() - timedelta(minutes=5)).isoformat(timespec="seconds")
    monitor.proposals.enqueue(_proposal("P1", old_sent))

    monitor.recover_on_boot()

    assert monitor.trading.is_in_flight("005930") is False
    assert monitor.trading.is_in_flight("000660") is False
    assert monitor.proposals.get("P1").status == "expired"


def test_recover_keeps_local_state_when_kis_fetch_fails(tmp_path):
    kis = MagicMock()
    kis.get_balance.side_effect = RuntimeError("balance failed")
    monitor = _build_monitor(tmp_path, kis, name="position_monitor.test.recover_fail")
    monitor.positions.apply_buy(
        "005930", "삼성전자", qty=3, price=70000.0, stage=1, at=_MARKET_HOUR
    )
    old_sent = (datetime.now() - timedelta(minutes=5)).isoformat(timespec="seconds")
    monitor.proposals.enqueue(_proposal("P1", old_sent))

    monitor.recover_on_boot()

    pos = monitor.positions.get("005930")
    assert pos is not None
    assert pos.qty == 3
    assert monitor.proposals.get("P1").status == "expired"


def test_midnight_reset_triggers_with_fresh_orderable_cash(tmp_path):
    kis = MagicMock()
    kis.get_orderable_cash.return_value = 2000000
    monitor = _build_monitor(tmp_path, kis, name="position_monitor.test.midnight")
    monitor.trading.data.last_reset_date = "2026-04-22"
    monitor.trading.data.realized_pnl = -500000
    monitor.trading.data.buy_count_today = 3

    monitor._check_midnight_reset(_MIDNIGHT)

    assert monitor.trading.data.last_reset_date == "2026-04-24"
    assert monitor.trading.data.realized_pnl == 0
    assert monitor.trading.data.buy_count_today == 0
    assert monitor.trading.data.daily_start_orderable_cash == 2000000


def test_midnight_reset_delays_on_orderable_cash_failure(tmp_path, caplog):
    kis = MagicMock()
    kis.get_orderable_cash.side_effect = RuntimeError("cash failed")
    monitor = _build_monitor(tmp_path, kis, name="position_monitor.test.midnight_fail")
    monitor.trading.data.last_reset_date = "2026-04-22"

    with caplog.at_level(logging.ERROR, logger=monitor.logger.name):
        monitor._check_midnight_reset(_MIDNIGHT)

    assert monitor.trading.data.last_reset_date == "2026-04-22"
    assert "orderable_cash 조회 실패" in caplog.text


def test_loss_limit_flips_block_flag(tmp_path, caplog):
    monitor = _build_monitor(tmp_path, MagicMock(), name="position_monitor.test.loss_limit")
    monitor.trading.data.daily_start_orderable_cash = 100000
    monitor.trading.data.realized_pnl = -100000
    monitor.positions.apply_buy(
        "005930", "삼성전자", qty=5, price=70000.0, stage=1, at=_MARKET_HOUR
    )

    with caplog.at_level(logging.WARNING, logger=monitor.logger.name):
        monitor._check_loss_limit(_MARKET_HOUR)

    assert monitor.trading.data.block_new_orders is True
    reloaded = TradingStateStore(path=monitor.trading._path)
    assert reloaded.data.block_new_orders is True
    assert "일일 손실한도 초과" in caplog.text


def test_loss_limit_noop_when_already_blocked(tmp_path, caplog):
    monitor = _build_monitor(tmp_path, MagicMock(), name="position_monitor.test.loss_limit_noop")
    monitor.trading.data.block_new_orders = True
    monitor.trading.data.daily_start_orderable_cash = 100000
    monitor.trading.data.realized_pnl = -200000

    with caplog.at_level(logging.ERROR, logger=monitor.logger.name):
        monitor._check_loss_limit(_MARKET_HOUR)

    assert monitor.trading.data.block_new_orders is True
    assert "일일 손실한도 초과" not in caplog.text


def test_tick_expire_proposals_marks_expired(tmp_path):
    monitor = _build_monitor(tmp_path, MagicMock(), name="position_monitor.test.expire")
    old_sent = (_MARKET_HOUR - timedelta(minutes=5)).isoformat(timespec="seconds")
    monitor.proposals.enqueue(_proposal("P1", old_sent))

    monitor._tick_expire_proposals(_MARKET_HOUR)

    assert monitor.proposals.get("P1").status == "expired"


def test_tick_skips_diff_when_market_closed(tmp_path):
    kis = MagicMock()
    kis.get_balance.return_value = _kis_balance_response([])
    kis.get_orderable_cash.return_value = 1000000
    monitor = _build_monitor(tmp_path, kis, name="position_monitor.test.market_closed")
    monitor.trading.data.last_reset_date = _BEFORE_MARKET.date().isoformat()

    monitor.tick(_BEFORE_MARKET)

    kis.get_balance.assert_not_called()


def test_tick_fetches_balance_and_applies_changes_when_market_open(tmp_path):
    kis = MagicMock()
    kis.get_balance.return_value = _kis_balance_response(
        [
            {
                "pdno": "005930",
                "prdt_name": "삼성전자",
                "hldg_qty": "2",
                "pchs_avg_pric": "70000",
                "prpr": "71000",
            }
        ]
    )
    monitor = _build_monitor(tmp_path, kis, name="position_monitor.test.market_open")
    monitor.trading.data.last_reset_date = _MARKET_HOUR.date().isoformat()

    monitor.tick(_MARKET_HOUR)

    pos = monitor.positions.get("005930")
    assert pos is not None
    assert pos.qty == 2
    kis.get_balance.assert_called_once()
