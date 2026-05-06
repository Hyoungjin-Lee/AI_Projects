"""validator.py - 모든 주문 preflight 단일 진입점."""
from __future__ import annotations

import json
import os
from datetime import datetime, time
from pathlib import Path

try:
    from .position_state import PositionStateStore
    from .trading_state import TradingStateData, TradingStateStore
except ImportError:
    from position_state import PositionStateStore
    from trading_state import TradingStateData, TradingStateStore


_ROOT = Path(__file__).parent.parent
_CONFIG_FILE = _ROOT / "data" / "strategy_config.json"
_KRX_OPEN = time(9, 0)
_KRX_CLOSE = time(15, 30)


def is_market_open(now: datetime | None = None) -> bool:
    """한국 증시 정규장 시간 체크. 주말만 배제하고 공휴일은 launchd 스케줄에서 제외."""
    now = now or datetime.now()
    if now.weekday() >= 5:  # Sat(5), Sun(6) 배제. 공휴일은 launchd 평일 스케줄로 처리
        return False
    return _KRX_OPEN <= now.time() <= _KRX_CLOSE


def _load_trading_config() -> dict:
    try:
        raw = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return raw.get("trading") or {}


def _effective_max_buys(state: TradingStateData, config: dict) -> int:
    if state.trial_mode:
        return state.trial_max_buys
    return int(config.get("max_buy_trades_per_day", 10))


def validate_order(
    action: str,
    ticker: str,
    qty: int,
    price_ref: float | None,
    *,
    position_store: PositionStateStore | None = None,
    trading_store: TradingStateStore | None = None,
    orderable_cash: int | None = None,
    config: dict | None = None,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """
    주문 preflight. 모든 체크 통과 시 (True, "") 반환.
    BUY 시 orderable_cash 는 호출자가 별도 조회 후 주입한다.
    """
    action = action.upper()
    if action not in {"BUY", "SELL"}:
        return False, f"지원하지 않는 action: {action}"

    now = now or datetime.now()
    config = config if config is not None else _load_trading_config()
    position_store = position_store or PositionStateStore()
    trading_store = trading_store or TradingStateStore()
    trading_state = trading_store.data

    if os.getenv("KIS_ALLOW_LIVE_ORDER") != "1":
        return False, "실전 가드 미설정 (KIS_ALLOW_LIVE_ORDER)"

    if not is_market_open(now):
        return False, "장 시간 외 주문 불가"

    if qty is None or qty <= 0:
        return False, "수량 0 이하"

    if action == "BUY":
        if trading_state.block_new_orders:
            return False, "일일 손실한도 초과 — 소액계좌 시작금액 전액 손실. 00:00 자동 해제"

        limit = _effective_max_buys(trading_state, config)
        if trading_state.buy_count_today >= limit:
            return False, f"일일 매수 횟수 초과 ({trading_state.buy_count_today}/{limit}건)"

        if trading_store.is_in_cooldown(ticker, now):
            remaining = trading_store.cooldown_remaining_seconds(ticker, now)
            return False, f"종목 COOLDOWN 중 (남은 {remaining}s)"

        if price_ref is None:
            return False, "BUY 검증에 price_ref 필수"
        if orderable_cash is None:
            return False, "BUY 검증에 orderable_cash 필수"

        required = int(qty * price_ref)
        if orderable_cash < required:
            return False, f"주문가능금액 부족 ({orderable_cash:,} < {required:,}원)"

    else:
        position = position_store.get(ticker)
        held_qty = 0 if position is None else position.qty
        if held_qty < qty:
            return False, f"보유 수량 부족 (보유 {held_qty}주 < 요청 {qty}주)"

        if trading_store.is_in_flight(ticker, side="SELL"):
            return False, "매도 주문 진행 중 (중복 차단)"

    return True, ""
