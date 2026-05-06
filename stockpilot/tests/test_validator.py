from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MORNING_REPORT_DIR = PROJECT_ROOT / "morning_report"
if str(MORNING_REPORT_DIR) not in sys.path:
    sys.path.insert(0, str(MORNING_REPORT_DIR))

from position_state import PositionStateStore
from trading_state import TradingStateStore
from validator import validate_order


MARKET_NOW = datetime(2026, 4, 23, 10, 0, 0)
WEEKEND_NOW = datetime(2026, 4, 25, 10, 0, 0)


@pytest.fixture
def tmp_position_store(tmp_path):
    return PositionStateStore(path=tmp_path / "position_state.json")


@pytest.fixture
def tmp_trading_store(tmp_path):
    return TradingStateStore(path=tmp_path / "trading_state.json")


def _base_buy_kwargs(position_store, trading_store, *, now=MARKET_NOW, cash=1000000):
    return {
        "position_store": position_store,
        "trading_store": trading_store,
        "orderable_cash": cash,
        "config": {"max_buy_trades_per_day": 10},
        "now": now,
    }


def _base_sell_kwargs(position_store, trading_store, *, now=MARKET_NOW):
    return {
        "position_store": position_store,
        "trading_store": trading_store,
        "config": {"max_buy_trades_per_day": 10},
        "now": now,
    }


def test_check_1_kis_guard(tmp_position_store, tmp_trading_store, monkeypatch):
    monkeypatch.delenv("KIS_ALLOW_LIVE_ORDER", raising=False)

    ok, reason = validate_order(
        "BUY",
        "005930",
        1,
        87200.0,
        **_base_buy_kwargs(tmp_position_store, tmp_trading_store),
    )

    assert ok is False
    assert reason == "실전 가드 미설정 (KIS_ALLOW_LIVE_ORDER)"


def test_check_2_market_open(tmp_position_store, tmp_trading_store, monkeypatch):
    monkeypatch.setenv("KIS_ALLOW_LIVE_ORDER", "1")

    ok, reason = validate_order(
        "BUY",
        "005930",
        1,
        87200.0,
        **_base_buy_kwargs(
            tmp_position_store,
            tmp_trading_store,
            now=datetime(2026, 4, 23, 15, 31, 0),
        ),
    )

    assert ok is False
    assert reason == "장 시간 외 주문 불가"


def test_check_3_qty_positive(tmp_position_store, tmp_trading_store, monkeypatch):
    monkeypatch.setenv("KIS_ALLOW_LIVE_ORDER", "1")

    ok, reason = validate_order(
        "BUY",
        "005930",
        0,
        87200.0,
        **_base_buy_kwargs(tmp_position_store, tmp_trading_store),
    )

    assert ok is False
    assert reason == "수량 0 이하"


def test_check_4_buy_block_new_orders(tmp_position_store, tmp_trading_store, monkeypatch):
    monkeypatch.setenv("KIS_ALLOW_LIVE_ORDER", "1")
    tmp_trading_store.set_block(True)

    ok, reason = validate_order(
        "BUY",
        "005930",
        1,
        87200.0,
        **_base_buy_kwargs(tmp_position_store, tmp_trading_store),
    )

    assert ok is False
    assert reason == "일일 손실한도 초과 — 소액계좌 시작금액 전액 손실. 00:00 자동 해제"


def test_check_5_buy_count_limit(tmp_position_store, tmp_trading_store, monkeypatch):
    monkeypatch.setenv("KIS_ALLOW_LIVE_ORDER", "1")
    tmp_trading_store.data.buy_count_today = 10

    ok, reason = validate_order(
        "BUY",
        "005930",
        1,
        87200.0,
        **_base_buy_kwargs(tmp_position_store, tmp_trading_store),
    )

    assert ok is False
    assert reason == "일일 매수 횟수 초과 (10/10건)"


def test_check_6_buy_cooldown(tmp_position_store, tmp_trading_store, monkeypatch):
    monkeypatch.setenv("KIS_ALLOW_LIVE_ORDER", "1")
    tmp_trading_store.set_cooldown("005930", datetime(2026, 4, 23, 10, 1, 30))

    ok, reason = validate_order(
        "BUY",
        "005930",
        1,
        87200.0,
        **_base_buy_kwargs(tmp_position_store, tmp_trading_store),
    )

    assert ok is False
    assert reason == "종목 COOLDOWN 중 (남은 90s)"


def test_check_7_buy_orderable_cash(tmp_position_store, tmp_trading_store, monkeypatch):
    monkeypatch.setenv("KIS_ALLOW_LIVE_ORDER", "1")

    ok, reason = validate_order(
        "BUY",
        "005930",
        2,
        87200.0,
        **_base_buy_kwargs(tmp_position_store, tmp_trading_store, cash=100000),
    )

    assert ok is False
    assert reason == "주문가능금액 부족 (100,000 < 174,400원)"


def test_check_8_sell_holding_qty(tmp_position_store, tmp_trading_store, monkeypatch):
    monkeypatch.setenv("KIS_ALLOW_LIVE_ORDER", "1")
    tmp_position_store.apply_buy("005930", "삼성전자", 3, 87200.0, 1, at=MARKET_NOW)

    ok, reason = validate_order(
        "SELL",
        "005930",
        4,
        None,
        **_base_sell_kwargs(tmp_position_store, tmp_trading_store),
    )

    assert ok is False
    assert reason == "보유 수량 부족 (보유 3주 < 요청 4주)"


def test_check_9_sell_in_flight_sell(tmp_position_store, tmp_trading_store, monkeypatch):
    monkeypatch.setenv("KIS_ALLOW_LIVE_ORDER", "1")
    tmp_position_store.apply_buy("005930", "삼성전자", 3, 87200.0, 1, at=MARKET_NOW)
    tmp_trading_store.mark_in_flight("005930", "SELL", at=MARKET_NOW)

    ok, reason = validate_order(
        "SELL",
        "005930",
        1,
        None,
        **_base_sell_kwargs(tmp_position_store, tmp_trading_store),
    )

    assert ok is False
    assert reason == "매도 주문 진행 중 (중복 차단)"


def test_all_checks_pass_buy(tmp_position_store, tmp_trading_store, monkeypatch):
    monkeypatch.setenv("KIS_ALLOW_LIVE_ORDER", "1")

    ok, reason = validate_order(
        "BUY",
        "005930",
        1,
        87200.0,
        **_base_buy_kwargs(tmp_position_store, tmp_trading_store),
    )

    assert ok is True
    assert reason == ""


def test_all_checks_pass_sell(tmp_position_store, tmp_trading_store, monkeypatch):
    monkeypatch.setenv("KIS_ALLOW_LIVE_ORDER", "1")
    tmp_position_store.apply_buy("005930", "삼성전자", 3, 87200.0, 1, at=MARKET_NOW)

    ok, reason = validate_order(
        "SELL",
        "005930",
        1,
        None,
        **_base_sell_kwargs(tmp_position_store, tmp_trading_store),
    )

    assert ok is True
    assert reason == ""


def test_check_order_kis_guard_first(tmp_position_store, tmp_trading_store, monkeypatch):
    monkeypatch.delenv("KIS_ALLOW_LIVE_ORDER", raising=False)

    ok, reason = validate_order(
        "BUY",
        "005930",
        0,
        87200.0,
        **_base_buy_kwargs(
            tmp_position_store,
            tmp_trading_store,
            now=WEEKEND_NOW,
        ),
    )

    assert ok is False
    assert "실전 가드 미설정" in reason


def test_effective_max_buys_in_trial_mode(
    tmp_position_store, tmp_trading_store, monkeypatch
):
    monkeypatch.setenv("KIS_ALLOW_LIVE_ORDER", "1")
    tmp_trading_store.start_trial(1, at=MARKET_NOW)
    tmp_trading_store.data.buy_count_today = 1

    ok, reason = validate_order(
        "BUY",
        "005930",
        1,
        87200.0,
        **_base_buy_kwargs(tmp_position_store, tmp_trading_store),
    )

    assert ok is False
    assert reason == "일일 매수 횟수 초과 (1/1건)"


def test_in_flight_buy_does_not_block_sell(
    tmp_position_store, tmp_trading_store, monkeypatch
):
    monkeypatch.setenv("KIS_ALLOW_LIVE_ORDER", "1")
    tmp_position_store.apply_buy("005930", "삼성전자", 3, 87200.0, 1, at=MARKET_NOW)
    tmp_trading_store.mark_in_flight("005930", "BUY", at=MARKET_NOW)

    ok, reason = validate_order(
        "SELL",
        "005930",
        1,
        None,
        **_base_sell_kwargs(tmp_position_store, tmp_trading_store),
    )

    assert ok is True
    assert reason == ""


def test_buy_requires_price_ref(tmp_position_store, tmp_trading_store, monkeypatch):
    monkeypatch.setenv("KIS_ALLOW_LIVE_ORDER", "1")

    ok, reason = validate_order(
        "BUY",
        "005930",
        1,
        None,
        **_base_buy_kwargs(tmp_position_store, tmp_trading_store),
    )

    assert ok is False
    assert reason == "BUY 검증에 price_ref 필수"


def test_sell_requires_holding_even_when_none(
    tmp_position_store, tmp_trading_store, monkeypatch
):
    monkeypatch.setenv("KIS_ALLOW_LIVE_ORDER", "1")

    ok, reason = validate_order(
        "SELL",
        "005930",
        1,
        None,
        **_base_sell_kwargs(tmp_position_store, tmp_trading_store),
    )

    assert ok is False
    assert reason == "보유 수량 부족 (보유 0주 < 요청 1주)"
