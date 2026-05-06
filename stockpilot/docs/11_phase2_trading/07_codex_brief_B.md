# Codex Brief B — State Helpers + Validator (Phase 2)

> **날짜:** 2026-04-23 | **작성자:** Claude | **근거:** `05_technical_design.md` Section 2.2, 3.1–3.4 + 구현 순서 4·5·6·7
> **의존:** Brief A 완료 (keychain `--reset-trading`, `KISClient(mode="trading")`, `strategy_config.trading` 섹션)
> **산출물:** 3개 상태 헬퍼 모듈 + validator + 단위 테스트
> **실행 전제:** `venv/bin/python3` (Python 3.14), macOS 키체인 기반 `inject_to_env()` 로드 완료 상태

---

## 0. 배경 & 설계 원칙

Phase 2 자동매매의 **상태 계층**을 구현한다. 이 계층은 `position_monitor.py` (Brief C, 아직 미구현) 가 사용할 기반이며, 단독으로도 import 가능한 **순수 라이브러리**여야 한다.

### 불변 원칙 (SoC)
1. **단일 쓰기** — 모든 `*_state.json`은 monitor만이 쓴다. 본 Brief의 헬퍼는 "메모리 위 상태 객체 + persist()" 패턴을 제공. orchestrator 같은 read-only 소비자는 `load()`만 호출.
2. **원자적 저장** — `json.dump → os.replace` 패턴 (Brief A의 `kis_client._save_token` 참고)으로 손상 방지.
3. **하위호환** — 스키마 필드 추가 시 `_deep_merge(default, loaded)` 로 누락분 채움 (`state_manager.py` 패턴 재사용).
4. **type-safe 내부** — 내부 표현은 `@dataclass`, 파일 직렬화는 `asdict()` + `from_dict()`. 외부에 `dict`를 직접 노출하지 않음.
5. **테스트 격리** — 모든 Store는 파일 경로를 생성자 인수로 받을 수 있어 테스트에서 tmp_path로 주입 가능.

### 파일 네이밍
- `morning_report/position_state.py` (신규)
- `morning_report/trading_state.py` (신규)
- `morning_report/pending_proposals.py` (신규)
- `morning_report/validator.py` (신규)
- `tests/test_position_state.py` (신규)
- `tests/test_trading_state.py` (신규)
- `tests/test_pending_proposals.py` (신규)
- `tests/test_validator.py` (신규)

---

## Task 1 — `morning_report/position_state.py` (신규, ≈200줄)

### 책임
- `data/position_state.json` 읽기/쓰기
- 가중평단 재계산 `apply_buy()` / 실현손익 반환 `apply_sell()`
- 트레일링 peak 갱신 `update_peak(ticker, current_price)`
- 트레일링 활성화 플래그 토글 `mark_trailing_active(ticker)`

### 스키마 (05_technical_design.md §3.1)
```json
{
  "updated_at": "2026-04-23T09:05:12",
  "holdings": {
    "005930": {
      "name": "삼성전자",
      "qty": 50,
      "avg_price": 87200.0,
      "stage": 1,
      "first_entry_at": "2026-04-23T09:05:12",
      "last_entry_at":  "2026-04-23T09:05:12",
      "peak_price_since_entry": 87500.0,
      "trailing_active": false,
      "entry_history": [
        {"at": "2026-04-23T09:05:12", "qty": 50, "price": 87200.0, "stage": 1}
      ]
    }
  }
}
```

### 구현

```python
"""position_state.py — 보유 포지션 상태 관리 (Phase 2)."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_DEFAULT_FILE = _ROOT / "data" / "position_state.json"


@dataclass
class EntryRecord:
    at: str                  # ISO datetime
    qty: int
    price: float
    stage: int               # 1|2|3


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
    def from_dict(cls, d: dict) -> "Position":
        history = [EntryRecord(**e) for e in d.get("entry_history", [])]
        return cls(
            name=d["name"],
            qty=int(d["qty"]),
            avg_price=float(d["avg_price"]),
            stage=int(d["stage"]),
            first_entry_at=d["first_entry_at"],
            last_entry_at=d["last_entry_at"],
            peak_price_since_entry=float(d["peak_price_since_entry"]),
            trailing_active=bool(d.get("trailing_active", False)),
            entry_history=history,
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "qty": self.qty,
            "avg_price": self.avg_price,
            "stage": self.stage,
            "first_entry_at": self.first_entry_at,
            "last_entry_at": self.last_entry_at,
            "peak_price_since_entry": self.peak_price_since_entry,
            "trailing_active": self.trailing_active,
            "entry_history": [asdict(e) for e in self.entry_history],
        }


class PositionStateStore:
    """보유 포지션 상태 저장소. monitor 단독 writer."""

    def __init__(self, path: Path | None = None):
        self._path = Path(path) if path else _DEFAULT_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self.holdings: dict[str, Position] = {}
        self.updated_at: str = ""
        self._load()

    # ── 로드/저장 ─────────────────────────────────────────────────────────────
    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # 손상 파일은 백업 후 초기화 (데이터 보존을 위해 삭제 X)
            backup = self._path.with_suffix(".json.corrupt")
            try:
                self._path.replace(backup)
            except OSError:
                pass
            return
        self.updated_at = str(raw.get("updated_at", ""))
        for code, d in (raw.get("holdings") or {}).items():
            try:
                self.holdings[code] = Position.from_dict(d)
            except (KeyError, TypeError, ValueError):
                # 개별 종목 파싱 실패는 스킵 (다른 종목은 살림)
                continue

    def persist(self) -> None:
        """원자적 저장. monitor 외에는 호출 금지."""
        self.updated_at = datetime.now().isoformat(timespec="seconds")
        data = {
            "updated_at": self.updated_at,
            "holdings": {code: p.to_dict() for code, p in self.holdings.items()},
        }
        tmp_fd, tmp_path = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)
        except Exception:
            try: os.unlink(tmp_path)
            except OSError: pass
            raise

    # ── 변경 연산 ─────────────────────────────────────────────────────────────
    def apply_buy(
        self, code: str, name: str, qty: int, price: float,
        stage: int, at: datetime | None = None,
    ) -> Position:
        """매수 체결 반영. 가중평단 재계산. 반환: 갱신된 Position."""
        if qty <= 0: raise ValueError("qty must be positive")
        if price <= 0: raise ValueError("price must be positive")
        if stage not in (1, 2, 3): raise ValueError("stage must be 1/2/3")
        at = at or datetime.now()
        iso = at.isoformat(timespec="seconds")

        pos = self.holdings.get(code)
        if pos is None:
            pos = Position(
                name=name, qty=qty, avg_price=float(price), stage=stage,
                first_entry_at=iso, last_entry_at=iso,
                peak_price_since_entry=float(price),
                trailing_active=False, entry_history=[],
            )
            self.holdings[code] = pos
        else:
            # 가중평단: (old_avg * old_qty + new_price * new_qty) / (old_qty + new_qty)
            new_total = pos.qty + qty
            pos.avg_price = (pos.avg_price * pos.qty + price * qty) / new_total
            pos.qty = new_total
            pos.stage = max(pos.stage, stage)
            pos.last_entry_at = iso
            # 추가 매수 시 peak 재설정 (평단이 바뀌었으므로 새 기준)
            pos.peak_price_since_entry = max(pos.peak_price_since_entry, price)
            pos.trailing_active = False  # 평단 바뀌면 재활성 필요

        pos.entry_history.append(EntryRecord(at=iso, qty=qty, price=float(price), stage=stage))
        return pos

    def apply_sell(self, code: str, qty: int, price: float) -> int:
        """
        매도 체결 반영. 부분/전량 처리. 반환: 실현손익 (원, 정수 반올림).
        전량 매도 시 holdings에서 제거.
        """
        if qty <= 0: raise ValueError("qty must be positive")
        if price <= 0: raise ValueError("price must be positive")
        pos = self.holdings.get(code)
        if pos is None:
            raise KeyError(f"{code} 보유 없음")
        if qty > pos.qty:
            raise ValueError(f"보유 수량 초과: {qty} > {pos.qty}")

        pnl = int(round((price - pos.avg_price) * qty))
        if qty == pos.qty:
            del self.holdings[code]
        else:
            pos.qty -= qty
            # 일부 매도 시 avg_price는 유지 (남은 단가 불변)
        return pnl

    def update_peak(self, code: str, current_price: float) -> None:
        pos = self.holdings.get(code)
        if pos is None: return
        if current_price > pos.peak_price_since_entry:
            pos.peak_price_since_entry = float(current_price)

    def mark_trailing_active(self, code: str) -> None:
        pos = self.holdings.get(code)
        if pos is not None:
            pos.trailing_active = True

    # ── 조회 (read-only 헬퍼) ─────────────────────────────────────────────────
    def has(self, code: str) -> bool:
        return code in self.holdings

    def get(self, code: str) -> Position | None:
        return self.holdings.get(code)

    def all_codes(self) -> list[str]:
        return list(self.holdings.keys())
```

### 수용 기준
- [ ] `Position.from_dict(Position.to_dict())` 라운드트립 ok
- [ ] `apply_buy` 신규 종목: holdings 추가, entry_history 1건
- [ ] `apply_buy` 추가매수: 가중평단 공식 정확 (예: 87200×50 + 88000×30 = 평단 87500.0)
- [ ] `apply_sell` 일부 매도: qty 감소, avg_price 유지, pnl 계산 정확
- [ ] `apply_sell` 전량 매도: holdings에서 제거, pnl 반환
- [ ] qty/price ≤ 0, stage ∉ {1,2,3} → ValueError
- [ ] 손상 파일은 `.corrupt` 백업 후 빈 상태로 시작 (데이터 보존)
- [ ] persist() 후 다시 load 하면 상태 동일

---

## Task 2 — `morning_report/trading_state.py` (신규, ≈200줄)

### 책임
- 일일 카운터 / 손실한도 / 블록 / 쿨다운 / in_flight / 시범모드 관리
- `kis_client.get_orderable_cash()` 호출은 monitor가 담당, 본 모듈은 **숫자만 저장**
- 자정 리셋 로직은 monitor가 호출하되 원자 연산으로 `reset_daily()` 제공

### 스키마 (05_technical_design.md §3.2)
```json
{
  "last_reset_date": "2026-04-23",
  "realized_pnl": 0,
  "daily_start_orderable_cash": 3000000,
  "buy_count_today": 0,
  "sell_count_today": 0,
  "block_new_orders": false,
  "trial_mode": false,
  "trial_started_at": null,
  "trial_max_buys": 1,
  "cooldown_until": {"005930": "2026-04-23T10:35:00"},
  "in_flight_orders": {"005930": {"side": "SELL", "started_at": "..."}}
}
```

### 구현 요점

```python
"""trading_state.py — 일일 트레이딩 상태 관리 (Phase 2)."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, date, timedelta
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_DEFAULT_FILE = _ROOT / "data" / "trading_state.json"


@dataclass
class InFlightOrder:
    side: str          # "BUY" | "SELL"
    started_at: str    # ISO


@dataclass
class TradingStateData:
    last_reset_date: str = ""                      # "YYYY-MM-DD"
    realized_pnl: int = 0                          # 원
    daily_start_orderable_cash: int = 0            # 원 — 자정 스냅샷
    buy_count_today: int = 0
    sell_count_today: int = 0
    block_new_orders: bool = False
    trial_mode: bool = False
    trial_started_at: str | None = None
    trial_max_buys: int = 1
    cooldown_until: dict[str, str] = field(default_factory=dict)
    in_flight_orders: dict[str, dict] = field(default_factory=dict)


class TradingStateStore:
    def __init__(self, path: Path | None = None):
        self._path = Path(path) if path else _DEFAULT_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self.data = TradingStateData()
        self._load()

    def _load(self) -> None:
        if not self._path.exists(): return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            backup = self._path.with_suffix(".json.corrupt")
            try: self._path.replace(backup)
            except OSError: pass
            return
        # 필드별로 안전하게 채움 (누락 필드는 기본값 유지)
        d = self.data
        d.last_reset_date = str(raw.get("last_reset_date", ""))
        d.realized_pnl = int(raw.get("realized_pnl", 0) or 0)
        d.daily_start_orderable_cash = int(raw.get("daily_start_orderable_cash", 0) or 0)
        d.buy_count_today = int(raw.get("buy_count_today", 0) or 0)
        d.sell_count_today = int(raw.get("sell_count_today", 0) or 0)
        d.block_new_orders = bool(raw.get("block_new_orders", False))
        d.trial_mode = bool(raw.get("trial_mode", False))
        d.trial_started_at = raw.get("trial_started_at")
        d.trial_max_buys = int(raw.get("trial_max_buys", 1) or 1)
        d.cooldown_until = dict(raw.get("cooldown_until") or {})
        d.in_flight_orders = dict(raw.get("in_flight_orders") or {})

    def persist(self) -> None:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(asdict(self.data), f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)
        except Exception:
            try: os.unlink(tmp_path)
            except OSError: pass
            raise

    # ── 자정 리셋 ─────────────────────────────────────────────────────────────
    def reset_daily(self, today: date, new_orderable_cash: int) -> None:
        """monitor가 자정 감지 시 호출. trial_mode는 false로 리셋 (설계 §2.6)."""
        d = self.data
        d.realized_pnl = 0
        d.buy_count_today = 0
        d.sell_count_today = 0
        d.block_new_orders = False
        d.daily_start_orderable_cash = int(new_orderable_cash)
        d.last_reset_date = today.isoformat()
        d.trial_mode = False
        d.trial_started_at = None
        # cooldown_until은 유지 (만료된 것만 cleanup)
        self._cleanup_expired_cooldowns(datetime.combine(today, datetime.min.time()))

    def _cleanup_expired_cooldowns(self, now: datetime) -> None:
        expired = [
            c for c, t in self.data.cooldown_until.items()
            if datetime.fromisoformat(t) <= now
        ]
        for c in expired:
            del self.data.cooldown_until[c]

    # ── 카운터 / 블록 ─────────────────────────────────────────────────────────
    def inc_buy(self) -> None:
        self.data.buy_count_today += 1

    def inc_sell(self) -> None:
        self.data.sell_count_today += 1

    def add_realized_pnl(self, pnl: int) -> None:
        self.data.realized_pnl += int(pnl)

    def should_block(self) -> bool:
        """daily_start_orderable_cash만큼 손실 시 block."""
        limit = self.data.daily_start_orderable_cash
        if limit <= 0: return False  # 미설정 시 block 하지 않음
        return self.data.realized_pnl <= -limit

    def set_block(self, value: bool) -> None:
        self.data.block_new_orders = value

    # ── 쿨다운 ────────────────────────────────────────────────────────────────
    def set_cooldown(self, code: str, until: datetime) -> None:
        self.data.cooldown_until[code] = until.isoformat(timespec="seconds")

    def is_in_cooldown(self, code: str, now: datetime) -> bool:
        t = self.data.cooldown_until.get(code)
        if not t: return False
        try:
            return datetime.fromisoformat(t) > now
        except ValueError:
            return False

    def cooldown_remaining_seconds(self, code: str, now: datetime) -> int:
        t = self.data.cooldown_until.get(code)
        if not t: return 0
        try:
            until = datetime.fromisoformat(t)
        except ValueError:
            return 0
        return max(0, int((until - now).total_seconds()))

    # ── in_flight ─────────────────────────────────────────────────────────────
    def mark_in_flight(self, code: str, side: str, at: datetime | None = None) -> None:
        self.data.in_flight_orders[code] = {
            "side": side, "started_at": (at or datetime.now()).isoformat(timespec="seconds"),
        }

    def clear_in_flight(self, code: str) -> None:
        self.data.in_flight_orders.pop(code, None)

    def is_in_flight(self, code: str, side: str | None = None) -> bool:
        o = self.data.in_flight_orders.get(code)
        if not o: return False
        if side is None: return True
        return o.get("side") == side

    # ── 시범 모드 ─────────────────────────────────────────────────────────────
    def start_trial(self, max_buys: int, at: datetime | None = None) -> None:
        if max_buys <= 0: raise ValueError("trial max_buys must be positive")
        self.data.trial_mode = True
        self.data.trial_max_buys = max_buys
        self.data.trial_started_at = (at or datetime.now()).isoformat(timespec="seconds")

    def stop_trial(self) -> None:
        self.data.trial_mode = False
        self.data.trial_started_at = None
```

### 수용 기준
- [ ] `reset_daily()` 호출 후 모든 카운터 0, block false, trial_mode false, orderable_cash 갱신
- [ ] `should_block()` 은 `realized_pnl ≤ -daily_start_orderable_cash` 일 때 True, `daily_start_orderable_cash==0` 이면 False
- [ ] `is_in_cooldown()` 은 정확한 만료 기준 (동일 시각은 False = 만료됨)
- [ ] `mark_in_flight / clear_in_flight / is_in_flight(code, side)` 동작 확인
- [ ] `start_trial(2)` → `trial_mode=True, trial_max_buys=2, trial_started_at` set
- [ ] `stop_trial()` → `trial_mode=False, trial_started_at=None`, `trial_max_buys` 유지 (다음 /시범시작 인수 없을 때 기본값 참조는 monitor가 처리)
- [ ] 손상 파일은 `.corrupt` 백업 후 빈 상태 시작
- [ ] persist → 재로드 라운드트립 무손실

---

## Task 3 — `morning_report/pending_proposals.py` (신규, ≈200줄)

### 책임
- `data/pending_proposals.json` 5상태 전이 관리
- `enqueue(proposal)` / `peek_oldest_pending()` / `transition(id, new_status)` / `increment_count(id)` / `cleanup_on_boot(cutoff)`
- 분할 단계별 독립 id (같은 종목이라도 `최초진입`/`1차_추가매수`는 별개 proposal)

### 스키마 (05_technical_design.md §3.3)
```json
{
  "proposals": [
    {
      "id": "2-005930-1745200000",
      "code": "005930", "name": "삼성전자",
      "round": 2, "rank": 1, "stage": "최초진입",
      "score": 85, "tday_rltv": 125, "chg": 3.2,
      "price_ref": 87200,
      "top5": [ ... ],
      "status": "pending",
      "count": 0,
      "created_at": "...",
      "last_sent": "...",
      "resolved_at": null
    }
  ]
}
```

### 구현 요점

```python
"""pending_proposals.py — 매수 제안 5상태 전이 관리."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_DEFAULT_FILE = _ROOT / "data" / "pending_proposals.json"

_VALID_STATUSES = {"pending", "accepted", "declined", "exhausted", "expired"}
_TERMINAL_STATUSES = {"accepted", "declined", "exhausted", "expired"}


@dataclass
class Proposal:
    id: str
    code: str
    name: str
    round: int
    rank: int
    stage: str                  # "최초진입" | "1차_추가매수" | "2차_추가매수"
    score: float
    tday_rltv: float
    chg: float
    price_ref: float
    top5: list[dict] = field(default_factory=list)
    status: str = "pending"
    count: int = 0              # 0~resuggest_max_count
    created_at: str = ""
    last_sent: str = ""
    resolved_at: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "Proposal":
        return cls(
            id=str(d["id"]),
            code=str(d["code"]),
            name=str(d["name"]),
            round=int(d["round"]),
            rank=int(d["rank"]),
            stage=str(d["stage"]),
            score=float(d.get("score", 0)),
            tday_rltv=float(d.get("tday_rltv", 0)),
            chg=float(d.get("chg", 0)),
            price_ref=float(d["price_ref"]),
            top5=list(d.get("top5") or []),
            status=str(d.get("status", "pending")),
            count=int(d.get("count", 0)),
            created_at=str(d.get("created_at", "")),
            last_sent=str(d.get("last_sent", "")),
            resolved_at=d.get("resolved_at"),
        )


class PendingProposalsStore:
    def __init__(self, path: Path | None = None):
        self._path = Path(path) if path else _DEFAULT_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self.proposals: list[Proposal] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists(): return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            backup = self._path.with_suffix(".json.corrupt")
            try: self._path.replace(backup)
            except OSError: pass
            return
        for d in (raw.get("proposals") or []):
            try:
                self.proposals.append(Proposal.from_dict(d))
            except (KeyError, TypeError, ValueError):
                continue

    def persist(self) -> None:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(
                    {"proposals": [asdict(p) for p in self.proposals]},
                    f, ensure_ascii=False, indent=2,
                )
            os.replace(tmp_path, self._path)
        except Exception:
            try: os.unlink(tmp_path)
            except OSError: pass
            raise

    # ── 조회 ──────────────────────────────────────────────────────────────────
    def get(self, proposal_id: str) -> Proposal | None:
        for p in self.proposals:
            if p.id == proposal_id: return p
        return None

    def peek_oldest_pending(self) -> Proposal | None:
        """아직 pending 상태 중 created_at이 가장 오래된 것."""
        candidates = [p for p in self.proposals if p.status == "pending"]
        if not candidates: return None
        return min(candidates, key=lambda p: p.created_at)

    def pending_ids(self) -> list[str]:
        return [p.id for p in self.proposals if p.status == "pending"]

    # ── 전이 ──────────────────────────────────────────────────────────────────
    def enqueue(self, proposal: Proposal) -> None:
        """신규 제안 추가. 동일 id 존재 시 중복 거부."""
        if self.get(proposal.id) is not None:
            raise ValueError(f"duplicate proposal id: {proposal.id}")
        if proposal.status not in _VALID_STATUSES:
            raise ValueError(f"invalid status: {proposal.status}")
        self.proposals.append(proposal)

    def transition(self, proposal_id: str, new_status: str,
                   at: datetime | None = None) -> Proposal:
        """상태 전이. 종결 상태에서는 다시 전이 불가."""
        if new_status not in _VALID_STATUSES:
            raise ValueError(f"invalid status: {new_status}")
        p = self.get(proposal_id)
        if p is None:
            raise KeyError(f"proposal not found: {proposal_id}")
        if p.status in _TERMINAL_STATUSES:
            raise ValueError(f"{proposal_id} already in terminal state: {p.status}")
        p.status = new_status
        if new_status in _TERMINAL_STATUSES:
            p.resolved_at = (at or datetime.now()).isoformat(timespec="seconds")
        return p

    def increment_count(self, proposal_id: str, at: datetime | None = None) -> int:
        """재권유 카운트 증가 + last_sent 갱신. 반환: 갱신된 count."""
        p = self.get(proposal_id)
        if p is None:
            raise KeyError(f"proposal not found: {proposal_id}")
        if p.status != "pending":
            raise ValueError(f"cannot increment count on status={p.status}")
        p.count += 1
        p.last_sent = (at or datetime.now()).isoformat(timespec="seconds")
        return p.count

    def cleanup_expired_on_boot(self, cutoff: datetime) -> list[Proposal]:
        """
        부팅 시 호출. pending + last_sent < cutoff → expired 전이.
        반환: 전이된 proposal 리스트.
        """
        out: list[Proposal] = []
        for p in self.proposals:
            if p.status != "pending": continue
            if not p.last_sent: continue
            try:
                sent = datetime.fromisoformat(p.last_sent)
            except ValueError:
                continue
            if sent < cutoff:
                p.status = "expired"
                p.resolved_at = datetime.now().isoformat(timespec="seconds")
                out.append(p)
        return out
```

### 수용 기준
- [ ] `enqueue` 후 `get(id)` / `peek_oldest_pending()` 반환
- [ ] 동일 id 재enqueue → ValueError
- [ ] `transition("accepted")` 후 다시 `transition("declined")` → ValueError (종결 불변)
- [ ] `increment_count` — pending 에서만 가능, count 증가 + last_sent 갱신
- [ ] `cleanup_expired_on_boot(now-5min)` — 5분 초과 pending만 expired로, 다른 상태 무영향
- [ ] 같은 code 다른 stage 제안 2건 enqueue 가능 (id가 다르므로)
- [ ] 손상 파일은 `.corrupt` 백업

---

## Task 4 — `morning_report/validator.py` (신규, ≈180줄)

### 책임
9체크 단일 진입점 `validate_order(action, ticker, qty, price_ref)`. 구조적·한도성 체크만 담당. 실시간 시세 비교는 호출자 (monitor `_execute_buy`).

### 9체크 순서 (05_technical_design.md §2.2)

| # | 체크 | 실패 문구 |
|---|---|---|
| 1 | `KIS_ALLOW_LIVE_ORDER == "1"` (환경변수) | "실전 가드 미설정 (KIS_ALLOW_LIVE_ORDER)" |
| 2 | `is_market_open(now)` | "장 시간 외 주문 불가" |
| 3 | `qty > 0` | "수량 0 이하" |
| 4 | BUY: `trading_state.block_new_orders == False` | "일일 손실한도 초과 — 소액계좌 시작금액 전액 손실. 00:00 자동 해제" |
| 5 | BUY: `buy_count_today < _effective_max_buys()` | "일일 매수 횟수 초과 (N/M건)" |
| 6 | BUY: `ticker` 쿨다운 만료 | "종목 COOLDOWN 중 (남은 Xs)" |
| 7 | BUY: `orderable_cash >= qty * price_ref` | "주문가능금액 부족" |
| 8 | SELL: `holdings[ticker].qty >= qty` | "보유 수량 부족" |
| 9 | SELL: `in_flight_orders[ticker].side != "SELL"` | "매도 주문 진행 중 (중복 차단)" |

### `_effective_max_buys()` 헬퍼
```python
def _effective_max_buys(trading_state: TradingStateData, config: dict) -> int:
    if trading_state.trial_mode:
        return trading_state.trial_max_buys
    return int(config.get("max_buy_trades_per_day", 10))
```

### 구현 요점

```python
"""validator.py — 모든 주문 preflight 단일 진입점."""
from __future__ import annotations

import json
import os
from datetime import datetime, time
from pathlib import Path

from position_state import PositionStateStore
from trading_state import TradingStateStore, TradingStateData

_ROOT = Path(__file__).parent.parent
_CONFIG_FILE = _ROOT / "data" / "strategy_config.json"


# ── 장 시간 게이트 ────────────────────────────────────────────────────────────

_KRX_OPEN = time(9, 0)
_KRX_CLOSE = time(15, 30)


def is_market_open(now: datetime | None = None) -> bool:
    """한국 증시 정규장 시간 체크 (주말·공휴일은 별도)."""
    now = now or datetime.now()
    if now.weekday() >= 5:  # 토(5), 일(6)
        return False
    t = now.time()
    return _KRX_OPEN <= t <= _KRX_CLOSE


def _load_trading_config() -> dict:
    try:
        cfg = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return cfg.get("trading") or {}


def _effective_max_buys(state: TradingStateData, cfg: dict) -> int:
    if state.trial_mode:
        return max(1, int(state.trial_max_buys))
    return int(cfg.get("max_buy_trades_per_day", 10))


# ── 단일 진입점 ───────────────────────────────────────────────────────────────

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
    주문 preflight. 모든 체크 통과 시 (True, "").
    Store / orderable_cash / config 는 테스트용으로 주입 가능.
    BUY 시 orderable_cash 인수 필요 (monitor가 kis_client.get_orderable_cash() 로 전달).
    """
    action = action.upper()
    if action not in ("BUY", "SELL"):
        return False, f"지원하지 않는 action: {action}"

    now = now or datetime.now()
    cfg = config if config is not None else _load_trading_config()
    position_store = position_store or PositionStateStore()
    trading_store = trading_store or TradingStateStore()
    tstate = trading_store.data

    # 1. 실전 가드
    if os.getenv("KIS_ALLOW_LIVE_ORDER") != "1":
        return False, "실전 가드 미설정 (KIS_ALLOW_LIVE_ORDER)"

    # 2. 장 시간
    if not is_market_open(now):
        return False, "장 시간 외 주문 불가"

    # 3. 수량
    if qty is None or qty <= 0:
        return False, "수량 0 이하"

    if action == "BUY":
        # 4. 블록
        if tstate.block_new_orders:
            return False, "일일 손실한도 초과 — 소액계좌 시작금액 전액 손실. 00:00 자동 해제"
        # 5. 매수 횟수
        limit = _effective_max_buys(tstate, cfg)
        if tstate.buy_count_today >= limit:
            return False, f"일일 매수 횟수 초과 ({tstate.buy_count_today}/{limit}건)"
        # 6. 쿨다운
        if trading_store.is_in_cooldown(ticker, now):
            remaining = trading_store.cooldown_remaining_seconds(ticker, now)
            return False, f"종목 COOLDOWN 중 (남은 {remaining}s)"
        # 7. 주문가능금액
        if price_ref is None:
            return False, "BUY 검증에 price_ref 필수"
        if orderable_cash is None:
            return False, "BUY 검증에 orderable_cash 필수"
        required = int(qty * price_ref)
        if orderable_cash < required:
            return False, f"주문가능금액 부족 ({orderable_cash:,} < {required:,}원)"

    else:  # SELL
        # 8. 보유 수량
        pos = position_store.get(ticker)
        if pos is None or pos.qty < qty:
            held = 0 if pos is None else pos.qty
            return False, f"보유 수량 부족 (보유 {held}주 < 요청 {qty}주)"
        # 9. 중복 SELL 차단
        if trading_store.is_in_flight(ticker, side="SELL"):
            return False, "매도 주문 진행 중 (중복 차단)"

    return True, ""
```

### 수용 기준 (단위테스트 필수 케이스)
- [ ] KIS_ALLOW_LIVE_ORDER 미설정 → 체크 1 실패
- [ ] 주말 or 08:59 / 15:31 → 체크 2 실패
- [ ] qty=0 또는 -1 → 체크 3 실패
- [ ] BUY + block_new_orders=true → 체크 4 실패
- [ ] BUY + buy_count_today == limit (정상/시범모드 각각) → 체크 5 실패
- [ ] BUY + cooldown_until[ticker] > now → 체크 6 실패, 문구에 남은 초 포함
- [ ] BUY + orderable_cash < qty*price_ref → 체크 7 실패
- [ ] BUY + price_ref None → 체크 7 실패 (명시 문구)
- [ ] SELL + 미보유 → 체크 8 실패
- [ ] SELL + pos.qty < qty → 체크 8 실패
- [ ] SELL + in_flight SELL 진행 중 → 체크 9 실패
- [ ] SELL + in_flight BUY 진행 중 → 체크 9 **통과** (다른 side)
- [ ] 모든 조건 충족 시 → `(True, "")`
- [ ] 체크 순서 테스트: qty=0 + 장 외 + KIS_ALLOW 미설정 → 문구에 "실전 가드 미설정" 포함 (1번이 먼저)

---

## Task 5 — 단위 테스트

### 파일별 테스트 항목

#### `tests/test_position_state.py`
- `test_weighted_avg_on_add_buy` — 87200×50 + 88000×30 = 평단 87500.0 검증
- `test_apply_buy_new_position` — holdings 1건 추가, entry_history 1건
- `test_apply_sell_partial` — qty 감소, avg_price 유지, pnl = (price - avg) * qty
- `test_apply_sell_full` — holdings 제거, pnl 반환
- `test_invalid_qty_price_stage` — 각각 ValueError
- `test_persist_roundtrip` — persist → 새 Store 로드 → 동일 상태
- `test_corrupt_file_backup` — 손상 JSON 주입 시 `.corrupt` 백업 생성 + 빈 상태 시작

#### `tests/test_trading_state.py`
- `test_reset_daily` — 모든 카운터/block/trial 리셋, orderable_cash 갱신
- `test_should_block_logic` — realized_pnl = -3_000_000, limit = 3_000_000 → True. limit=0 → 항상 False
- `test_cooldown` — set_cooldown 후 is_in_cooldown True, 만료 시각 정확 + remaining_seconds
- `test_in_flight_by_side` — side="BUY" 저장 후 `is_in_flight(code, "SELL")` False
- `test_start_stop_trial` — start(2) → trial_mode True, max_buys=2. stop() → trial_mode False, started_at None
- `test_persist_roundtrip`
- `test_corrupt_file_backup`

#### `tests/test_pending_proposals.py`
- `test_enqueue_and_peek` — 3건 enqueue, peek_oldest_pending이 가장 오래된 것 반환
- `test_duplicate_id_rejected` — ValueError
- `test_transition_to_terminal` — pending → accepted, 재전이 시 ValueError
- `test_increment_count` — pending에서만 가능, count 증가 + last_sent 갱신
- `test_increment_on_non_pending_rejected` — accepted에 increment → ValueError
- `test_cleanup_expired_on_boot` — 5분 초과 pending만 expired, accepted/declined 무영향
- `test_same_code_different_stage` — 삼성전자 최초진입 + 1차추가 2건 공존
- `test_persist_roundtrip`
- `test_corrupt_file_backup`

#### `tests/test_validator.py`
- 9체크 각각 실패 케이스 1개씩 (총 9개)
- `test_all_checks_pass_buy` — 모든 조건 충족 시 (True, "")
- `test_all_checks_pass_sell`
- `test_check_order_kis_guard_first` — 여러 실패 조건 동시 존재 시 KIS_ALLOW 문구 우선
- `test_effective_max_buys_in_trial_mode` — trial 활성 시 trial_max_buys 사용
- `test_in_flight_buy_does_not_block_sell` — BUY in-flight 중 SELL 가능

**공통 픽스처:**
```python
@pytest.fixture
def tmp_position_store(tmp_path):
    from position_state import PositionStateStore
    return PositionStateStore(path=tmp_path / "position_state.json")

@pytest.fixture
def tmp_trading_store(tmp_path):
    from trading_state import TradingStateStore
    return TradingStateStore(path=tmp_path / "trading_state.json")

@pytest.fixture
def tmp_proposals_store(tmp_path):
    from pending_proposals import PendingProposalsStore
    return PendingProposalsStore(path=tmp_path / "pending_proposals.json")

@pytest.fixture
def fake_market_open(monkeypatch):
    """화요일 10시로 고정."""
    import validator
    fake_now = datetime(2026, 4, 21, 10, 30, 0)  # 화요일 10:30
    monkeypatch.setattr(validator, "datetime", _FrozenDatetime(fake_now))
    return fake_now
```

---

## 0. 구현 순서 (병렬 가능)

Task 1, 2, 3은 서로 독립 → 병렬 작성 가능.
Task 4 (validator)는 1, 2에 의존 (position_store, trading_store 사용).

권장 순서:
1. Task 1 + 2 + 3 동시 작성 (각자 독립)
2. 단위 테스트 1 + 2 + 3 (스토어별 검증)
3. Task 4 validator
4. 단위 테스트 4

---

## 자체 검증 (완료 후 Codex가 직접 실행)

```bash
cd /Users/geenya/projects/AI_Projects/stockpilot

# 1. 문법 검사
venv/bin/python3 -m py_compile morning_report/position_state.py
venv/bin/python3 -m py_compile morning_report/trading_state.py
venv/bin/python3 -m py_compile morning_report/pending_proposals.py
venv/bin/python3 -m py_compile morning_report/validator.py

# 2. 테스트 실행
venv/bin/python3 -m pytest tests/test_position_state.py tests/test_trading_state.py tests/test_pending_proposals.py tests/test_validator.py -v

# 3. 기존 관측 스크립트 회귀 확인 (Brief A 회귀 방지)
venv/bin/python3 morning_report/morning_report.py --dry-run
```

**수용 기준 요약:**
- [ ] 4개 모듈 모두 py_compile 통과
- [ ] 단위 테스트 전수 통과 (30+ 케이스)
- [ ] morning_report --dry-run 정상 실행 (기존 관측 경로 무영향)
- [ ] 생성된 모든 파일 경로 보고: `morning_report/*.py`, `tests/test_*.py`
- [ ] 각 모듈의 public API는 본 문서와 일치 (메서드 추가는 OK, 제거·시그니처 변경은 금지)

---

## 주의 / 하지 말 것

- ❌ `position_monitor.py` 작성 금지 (Brief C 범위)
- ❌ `orchestrator.py` 또는 `telegram_bot.py` 수정 금지 (Brief D 범위)
- ❌ `KISClient` 추가 수정 금지 (Brief A에서 완결, validator는 kis_client를 직접 호출 안 함 — orderable_cash 인수로 주입받음)
- ❌ 스케줄러 / launchd plist 수정 금지
- ❌ 전역 state (module-level singleton) 생성 금지 — 반드시 Store 클래스 인스턴스 통해 접근
- ❌ 동기화 primitive (threading.Lock 등) 추가 금지 — Phase 2는 단일 writer(monitor)이므로 불필요

---

## Brief B 완료 후 Claude 작업 (Stage 9)

- [ ] Opus high effort 코드 리뷰 (단일 writer 원칙 준수, 원자적 저장, 타입 안전, 테스트 커버리지)
- [ ] validator 체크 순서 재검증 (설계 문서와 1:1 매칭)
- [ ] Brief C 작성 진입 (position_monitor 골격 + 재시작 복구 + 자정 리셋)

*자동 생성 | stockpilot Phase 2 Brief B*
