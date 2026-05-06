"""position_state.py - 보유 포지션 상태 관리 (Phase 2)."""
from __future__ import annotations

import copy
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


_ROOT = Path(__file__).parent.parent
_DEFAULT_FILE = _ROOT / "data" / "position_state.json"

_EMPTY_STATE = {
    "updated_at": "",
    "holdings": {},
}

_POSITION_DEFAULTS = {
    "name": "",
    "qty": 0,
    "avg_price": 0.0,
    "stage": 1,
    "first_entry_at": "",
    "last_entry_at": "",
    "peak_price_since_entry": 0.0,
    "trailing_active": False,
    "entry_history": [],
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


@dataclass
class EntryRecord:
    at: str
    qty: int
    price: float
    stage: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EntryRecord":
        return cls(
            at=str(data["at"]),
            qty=int(data["qty"]),
            price=float(data["price"]),
            stage=int(data["stage"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "at": self.at,
            "qty": self.qty,
            "price": self.price,
            "stage": self.stage,
        }


@dataclass
class Position:
    name: str
    qty: int
    avg_price: float
    stage: int
    first_entry_at: str
    last_entry_at: str
    peak_price_since_entry: float
    trailing_active: bool = False
    entry_history: list[EntryRecord] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Position":
        merged = copy.deepcopy(_POSITION_DEFAULTS)
        _deep_merge(merged, data)
        history = [EntryRecord.from_dict(item) for item in merged["entry_history"]]
        return cls(
            name=str(merged["name"]),
            qty=int(merged["qty"]),
            avg_price=float(merged["avg_price"]),
            stage=int(merged["stage"]),
            first_entry_at=str(merged["first_entry_at"]),
            last_entry_at=str(merged["last_entry_at"]),
            peak_price_since_entry=float(merged["peak_price_since_entry"]),
            trailing_active=bool(merged["trailing_active"]),
            entry_history=history,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "qty": self.qty,
            "avg_price": self.avg_price,
            "stage": self.stage,
            "first_entry_at": self.first_entry_at,
            "last_entry_at": self.last_entry_at,
            "peak_price_since_entry": self.peak_price_since_entry,
            "trailing_active": self.trailing_active,
            "entry_history": [entry.to_dict() for entry in self.entry_history],
        }


class PositionStateStore:
    """보유 포지션 상태 저장소. position_monitor 단독 writer."""

    def __init__(self, path: Path | None = None):
        self._path = Path(path) if path else _DEFAULT_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = ""
        self.holdings: dict[str, Position] = {}
        self._load()

    @classmethod
    def load(cls, path: Path | None = None) -> "PositionStateStore":
        return cls(path=path)

    def _load(self) -> None:
        if not self._path.exists():
            return

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            _backup_corrupt_file(self._path)
            return

        merged = copy.deepcopy(_EMPTY_STATE)
        if isinstance(raw, dict):
            _deep_merge(merged, raw)

        self.updated_at = str(merged.get("updated_at", ""))
        for code, payload in (merged.get("holdings") or {}).items():
            try:
                self.holdings[str(code)] = Position.from_dict(payload)
            except (KeyError, TypeError, ValueError):
                continue

    def persist(self) -> None:
        self.updated_at = datetime.now().isoformat(timespec="seconds")
        data = {
            "updated_at": self.updated_at,
            "holdings": {code: position.to_dict() for code, position in self.holdings.items()},
        }
        _atomic_dump_json(self._path, data)

    def apply_buy(
        self,
        code: str,
        name: str,
        qty: int,
        price: float,
        stage: int,
        at: datetime | None = None,
    ) -> Position:
        if qty <= 0:
            raise ValueError("qty must be positive")
        if price <= 0:
            raise ValueError("price must be positive")
        if stage not in (1, 2, 3):
            raise ValueError("stage must be 1/2/3")

        at = at or datetime.now()
        iso = at.isoformat(timespec="seconds")
        position = self.holdings.get(code)

        if position is None:
            position = Position(
                name=name,
                qty=qty,
                avg_price=float(price),
                stage=stage,
                first_entry_at=iso,
                last_entry_at=iso,
                peak_price_since_entry=float(price),
                trailing_active=False,
                entry_history=[],
            )
            self.holdings[code] = position
        else:
            new_total_qty = position.qty + qty
            position.avg_price = (
                (position.avg_price * position.qty) + (float(price) * qty)
            ) / new_total_qty
            position.qty = new_total_qty
            position.stage = max(position.stage, stage)
            position.name = name
            position.last_entry_at = iso
            position.peak_price_since_entry = max(position.peak_price_since_entry, float(price))
            position.trailing_active = False

        position.entry_history.append(
            EntryRecord(at=iso, qty=qty, price=float(price), stage=stage)
        )
        return position

    def apply_sell(self, code: str, qty: int, price: float) -> int:
        if qty <= 0:
            raise ValueError("qty must be positive")
        if price <= 0:
            raise ValueError("price must be positive")

        position = self.holdings.get(code)
        if position is None:
            raise KeyError(f"{code} 보유 없음")
        if qty > position.qty:
            raise ValueError(f"보유 수량 초과: {qty} > {position.qty}")

        pnl = int(round((float(price) - position.avg_price) * qty))
        if qty == position.qty:
            del self.holdings[code]
        else:
            position.qty -= qty
        return pnl

    def update_peak(self, code: str, current_price: float) -> None:
        position = self.holdings.get(code)
        if position is None:
            return
        if current_price > position.peak_price_since_entry:
            position.peak_price_since_entry = float(current_price)

    def mark_trailing_active(self, code: str) -> None:
        position = self.holdings.get(code)
        if position is not None:
            position.trailing_active = True

    def has(self, code: str) -> bool:
        return code in self.holdings

    def get(self, code: str) -> Position | None:
        return self.holdings.get(code)

    def all_codes(self) -> list[str]:
        return list(self.holdings.keys())
