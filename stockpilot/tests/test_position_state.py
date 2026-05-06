from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MORNING_REPORT_DIR = PROJECT_ROOT / "morning_report"
if str(MORNING_REPORT_DIR) not in sys.path:
    sys.path.insert(0, str(MORNING_REPORT_DIR))

from position_state import EntryRecord, Position, PositionStateStore


def test_position_roundtrip():
    position = Position(
        name="삼성전자",
        qty=50,
        avg_price=87200.0,
        stage=1,
        first_entry_at="2026-04-23T09:05:12",
        last_entry_at="2026-04-23T09:05:12",
        peak_price_since_entry=87500.0,
        trailing_active=True,
        entry_history=[
            EntryRecord(
                at="2026-04-23T09:05:12",
                qty=50,
                price=87200.0,
                stage=1,
            )
        ],
    )

    restored = Position.from_dict(position.to_dict())

    assert restored == position


def test_weighted_avg_on_add_buy(tmp_path):
    store = PositionStateStore(path=tmp_path / "position_state.json")
    store.apply_buy(
        "005930",
        "삼성전자",
        50,
        87200.0,
        1,
        at=datetime(2026, 4, 23, 9, 5, 12),
    )

    position = store.apply_buy(
        "005930",
        "삼성전자",
        30,
        88000.0,
        2,
        at=datetime(2026, 4, 23, 9, 30, 0),
    )

    assert position.qty == 80
    assert position.avg_price == 87500.0
    assert position.stage == 2
    assert position.trailing_active is False
    assert len(position.entry_history) == 2


def test_apply_buy_new_position(tmp_path):
    store = PositionStateStore(path=tmp_path / "position_state.json")

    position = store.apply_buy(
        "005930",
        "삼성전자",
        50,
        87200.0,
        1,
        at=datetime(2026, 4, 23, 9, 5, 12),
    )

    assert store.has("005930") is True
    assert position.qty == 50
    assert position.avg_price == 87200.0
    assert position.first_entry_at == "2026-04-23T09:05:12"
    assert position.last_entry_at == "2026-04-23T09:05:12"
    assert position.peak_price_since_entry == 87200.0
    assert len(position.entry_history) == 1


def test_apply_sell_partial(tmp_path):
    store = PositionStateStore(path=tmp_path / "position_state.json")
    store.apply_buy("005930", "삼성전자", 50, 87200.0, 1)
    store.apply_buy("005930", "삼성전자", 30, 88000.0, 2)

    pnl = store.apply_sell("005930", 20, 90000.0)
    position = store.get("005930")

    assert pnl == 50000
    assert position is not None
    assert position.qty == 60
    assert position.avg_price == 87500.0


def test_apply_sell_full(tmp_path):
    store = PositionStateStore(path=tmp_path / "position_state.json")
    store.apply_buy("005930", "삼성전자", 50, 87200.0, 1)

    pnl = store.apply_sell("005930", 50, 86000.0)

    assert pnl == -60000
    assert store.get("005930") is None
    assert store.has("005930") is False


@pytest.mark.parametrize(
    ("qty", "price", "stage", "message"),
    [
        (0, 87200.0, 1, "qty must be positive"),
        (1, 0.0, 1, "price must be positive"),
        (1, 87200.0, 4, "stage must be 1/2/3"),
    ],
)
def test_invalid_qty_price_stage(tmp_path, qty, price, stage, message):
    store = PositionStateStore(path=tmp_path / "position_state.json")

    with pytest.raises(ValueError, match=message):
        store.apply_buy("005930", "삼성전자", qty, price, stage)


def test_persist_roundtrip(tmp_path):
    path = tmp_path / "position_state.json"
    store = PositionStateStore(path=path)
    store.apply_buy(
        "005930",
        "삼성전자",
        50,
        87200.0,
        1,
        at=datetime(2026, 4, 23, 9, 5, 12),
    )
    store.update_peak("005930", 87500.0)
    store.mark_trailing_active("005930")
    store.persist()

    restored = PositionStateStore(path=path)
    position = restored.get("005930")

    assert position is not None
    assert position.name == "삼성전자"
    assert position.qty == 50
    assert position.avg_price == 87200.0
    assert position.peak_price_since_entry == 87500.0
    assert position.trailing_active is True
    assert restored.updated_at


def test_corrupt_file_backup(tmp_path):
    path = tmp_path / "position_state.json"
    path.write_text("{broken", encoding="utf-8")

    store = PositionStateStore(path=path)

    assert store.holdings == {}
    assert not path.exists()
    assert path.with_suffix(".json.corrupt").exists()
