"""trading_state.py - 일일 트레이딩 상태 관리 (Phase 2)."""
from __future__ import annotations

import copy
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any


_ROOT = Path(__file__).parent.parent
_DEFAULT_FILE = _ROOT / "data" / "trading_state.json"

_EMPTY_STATE = {
    "last_reset_date": "",
    "realized_pnl": 0,
    "daily_start_orderable_cash": 0,
    "buy_count_today": 0,
    "sell_count_today": 0,
    "block_new_orders": False,
    "trial_mode": False,
    "trial_started_at": None,
    "trial_max_buys": 1,
    "cooldown_until": {},
    "in_flight_orders": {},
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _atomic_dump_json(path: Path, data: dict[str, Any]) -> None:
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _backup_corrupt_file(path: Path) -> None:
    backup = path.with_suffix(".json.corrupt")
    try:
        path.replace(backup)
    except OSError:
        pass


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass
class InFlightOrder:
    side: str
    started_at: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InFlightOrder":
        side = str(data["side"]).upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError(f"invalid side: {side}")
        return cls(side=side, started_at=str(data["started_at"]))

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "started_at": self.started_at,
        }


@dataclass
class TradingStateData:
    last_reset_date: str = ""
    realized_pnl: int = 0
    daily_start_orderable_cash: int = 0
    buy_count_today: int = 0
    sell_count_today: int = 0
    block_new_orders: bool = False
    trial_mode: bool = False
    trial_started_at: str | None = None
    trial_max_buys: int = 1
    cooldown_until: dict[str, str] = field(default_factory=dict)
    in_flight_orders: dict[str, InFlightOrder] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TradingStateData":
        merged = copy.deepcopy(_EMPTY_STATE)
        _deep_merge(merged, data)

        orders: dict[str, InFlightOrder] = {}
        for code, payload in (merged.get("in_flight_orders") or {}).items():
            try:
                orders[str(code)] = InFlightOrder.from_dict(payload)
            except (KeyError, TypeError, ValueError):
                continue

        cooldown_until = {
            str(code): str(until)
            for code, until in (merged.get("cooldown_until") or {}).items()
        }

        return cls(
            last_reset_date=str(merged.get("last_reset_date", "")),
            realized_pnl=_coerce_int(merged.get("realized_pnl"), 0),
            daily_start_orderable_cash=_coerce_int(
                merged.get("daily_start_orderable_cash"), 0
            ),
            buy_count_today=_coerce_int(merged.get("buy_count_today"), 0),
            sell_count_today=_coerce_int(merged.get("sell_count_today"), 0),
            block_new_orders=bool(merged.get("block_new_orders", False)),
            trial_mode=bool(merged.get("trial_mode", False)),
            trial_started_at=merged.get("trial_started_at"),
            trial_max_buys=max(1, _coerce_int(merged.get("trial_max_buys"), 1)),
            cooldown_until=cooldown_until,
            in_flight_orders=orders,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_reset_date": self.last_reset_date,
            "realized_pnl": self.realized_pnl,
            "daily_start_orderable_cash": self.daily_start_orderable_cash,
            "buy_count_today": self.buy_count_today,
            "sell_count_today": self.sell_count_today,
            "block_new_orders": self.block_new_orders,
            "trial_mode": self.trial_mode,
            "trial_started_at": self.trial_started_at,
            "trial_max_buys": self.trial_max_buys,
            "cooldown_until": dict(self.cooldown_until),
            "in_flight_orders": {
                code: order.to_dict() for code, order in self.in_flight_orders.items()
            },
        }


class TradingStateStore:
    def __init__(self, path: Path | None = None):
        self._path = Path(path) if path else _DEFAULT_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self.data = TradingStateData()
        self._load()

    @classmethod
    def load(cls, path: Path | None = None) -> "TradingStateStore":
        return cls(path=path)

    def _load(self) -> None:
        if not self._path.exists():
            return

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            _backup_corrupt_file(self._path)
            return

        if isinstance(raw, dict):
            self.data = TradingStateData.from_dict(raw)

    def persist(self) -> None:
        _atomic_dump_json(self._path, self.data.to_dict())

    def reset_daily(self, today: date, new_orderable_cash: int) -> None:
        self.data.realized_pnl = 0
        self.data.daily_start_orderable_cash = int(new_orderable_cash)
        self.data.buy_count_today = 0
        self.data.sell_count_today = 0
        self.data.block_new_orders = False
        self.data.last_reset_date = today.isoformat()
        self.data.trial_mode = False
        self.data.trial_started_at = None
        midnight = datetime.combine(today, time.min)
        self._cleanup_expired_cooldowns(midnight)

    def _cleanup_expired_cooldowns(self, now: datetime) -> None:
        expired = [
            code
            for code, until in self.data.cooldown_until.items()
            if self._parse_iso(until) is not None and self._parse_iso(until) <= now
        ]
        for code in expired:
            del self.data.cooldown_until[code]

    def inc_buy(self) -> None:
        self.data.buy_count_today += 1

    def inc_sell(self) -> None:
        self.data.sell_count_today += 1

    def add_realized_pnl(self, pnl: int) -> None:
        self.data.realized_pnl += int(pnl)

    def should_block(self) -> bool:
        limit = self.data.daily_start_orderable_cash
        if limit <= 0:
            return False
        return self.data.realized_pnl <= -limit

    def set_block(self, value: bool) -> None:
        self.data.block_new_orders = bool(value)

    def set_cooldown(self, code: str, until: datetime) -> None:
        self.data.cooldown_until[code] = until.isoformat(timespec="seconds")

    def is_in_cooldown(self, code: str, now: datetime) -> bool:
        until = self._parse_iso(self.data.cooldown_until.get(code))
        if until is None:
            return False
        return until > now

    def cooldown_remaining_seconds(self, code: str, now: datetime) -> int:
        until = self._parse_iso(self.data.cooldown_until.get(code))
        if until is None:
            return 0
        return max(0, int((until - now).total_seconds()))

    def mark_in_flight(self, code: str, side: str, at: datetime | None = None) -> None:
        side = side.upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        started_at = (at or datetime.now()).isoformat(timespec="seconds")
        self.data.in_flight_orders[code] = InFlightOrder(side=side, started_at=started_at)

    def clear_in_flight(self, code: str) -> None:
        self.data.in_flight_orders.pop(code, None)

    def is_in_flight(self, code: str, side: str | None = None) -> bool:
        order = self.data.in_flight_orders.get(code)
        if order is None:
            return False
        if side is None:
            return True
        return order.side == side.upper()

    def start_trial(self, max_buys: int, at: datetime | None = None) -> None:
        if max_buys <= 0:
            raise ValueError("trial max_buys must be positive")
        self.data.trial_mode = True
        self.data.trial_max_buys = int(max_buys)
        self.data.trial_started_at = (at or datetime.now()).isoformat(timespec="seconds")

    def stop_trial(self) -> None:
        self.data.trial_mode = False
        self.data.trial_started_at = None

    @staticmethod
    def _parse_iso(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
