# Codex Brief C — position_monitor.py 골격 (Phase 2)

> **날짜:** 2026-04-23 | **작성자:** Claude | **근거:** `05_technical_design.md` §2.1, §3 + Stage 1~4 승인 (`CLAUDE.md` 워크플로우)
> **의존:** Brief A (keychain 매매 키 그룹, `KISClient(mode="trading")`), Brief B (position_state, trading_state, pending_proposals, validator)
> **산출물:** `morning_report/position_monitor.py` 1개 + `tests/test_position_monitor.py` 1개
> **실행 전제:** `venv/bin/python3` (Python 3.14), macOS 키체인 기반 `inject_to_env()` 로드 완료 상태

---

## 0. 배경 & 범위

Phase 2의 **상시 데몬**을 구현한다. 이 데몬은 Brief B의 state 계층 위에서 다음을 수행한다:

1. **단일 writer**: `position_state.json` + `trading_state.json` 쓰기 권한을 이 프로세스에만 귀속
2. **5초 폴링 체결 감지**: KIS 잔고조회 → 직전 스냅샷과 diff → BUY/SELL 체결 사실을 수동 감지 → 상태 반영
3. **재시작 복구**: 기동 시 KIS 잔고를 권위 소스로 수용, 로컬 state와 불일치 시 KIS 기준 덮어쓰기
4. **자정 리셋**: 날짜 경계 감지 시 `reset_daily()` 자체 호출
5. **일일 손실한도 감시**: `realized_pnl ≤ -daily_start_orderable_cash` 전환 시 `block_new_orders=True` + ERROR 로그 (실제 텔레그램 질의/강제청산 실행은 Brief D)

### Brief C 명시적 **제외 범위**

| 기능 | 이관처 |
|------|--------|
| 매수/매도 request queue 소비 (실제 `place_order` 호출) | Brief D (orchestrator와 통합 설계) |
| 매수 승인 플로우 (intraday_discovery → telegram → orchestrator) | Brief D |
| 능동 매도 결정 엔진 (손절/익절/트레일링) | 별도 Brief (C2 또는 E) |
| 실제 텔레그램 send/receive | Brief D |
| 장마감 강제청산 | Brief E |
| launchd plist 파일 | Brief E |
| 재권유 상태머신 | Brief D |

### 불변 원칙 (SoC)

1. **단일 쓰기** — `position_state.json` + `trading_state.json`은 이 데몬만이 쓴다. Brief D/E가 이후 쓰기 요청을 보낼 경우 queue 기반 IPC를 통해서만 반영 (Brief C는 queue consumer 구현 **제외**, 이후 확장).
2. **KIS = 권위 소스** — 체결 여부 판단은 항상 KIS 잔고 응답 기준. 로컬 state와 KIS 불일치 시 KIS 승리.
3. **장애 내성** — 단일 폴링 실패는 로그만 남기고 다음 폴링 계속. 연속 30회(약 2.5분) 실패 시 텔레그램 경고 예정(Brief D 훅).
4. **테스트 격리** — `PositionMonitor` 클래스 기반, `tick(now, kis_snapshot)` 단위로 분해해서 KIS 호출/시간 의존성을 외부 주입.
5. **원자적 영속화** — 모든 state 쓰기는 Brief B의 `_atomic_dump_json` 경로 활용 (`persist()` 호출).

---

## Task 1 — 데몬 골격 & 메인 루프

### 책임
- 시그널 핸들링(SIGTERM/SIGINT) 후 우아한 종료
- 단일 인스턴스 보장 (pidfile 기반 락)
- 적응형 폴링 주기: 장중 5초 / 장외 60초
- 표준 로깅 채널(`logs/trading.log`) 설정

### 파일: `morning_report/position_monitor.py` (신규)

#### Import 구조
```python
"""position_monitor.py — Phase 2 단일 writer 데몬."""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any

try:
    from .keychain_manager import inject_to_env
    from .pending_proposals import PendingProposalsStore
    from .position_state import PositionStateStore
    from .trading_state import TradingStateStore
    from .validator import is_market_open
except ImportError:
    from keychain_manager import inject_to_env
    from pending_proposals import PendingProposalsStore
    from position_state import PositionStateStore
    from trading_state import TradingStateStore
    from validator import is_market_open

# KIS 클라이언트 import (경로는 strategy_config / kis_client 패키지 구조 따라)
_SKILLS_ROOT = Path(__file__).parent.parent / ".skills" / "kis-api" / "scripts"
if str(_SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILLS_ROOT))
from kis_client import KISClient, KISConfigError  # noqa: E402
```

#### 상수 & 설정

```python
_ROOT = Path(__file__).parent.parent
_CONFIG_FILE = _ROOT / "data" / "strategy_config.json"
_PIDFILE = _ROOT / "data" / "position_monitor.pid"
_LOG_FILE = _ROOT / "logs" / "trading.log"

# 폴링 주기
_TICK_MARKET = 5.0        # 장 중
_TICK_IDLE = 60.0         # 장 외

# 실패 허용치
_MAX_CONSECUTIVE_FAILURES = 30     # 연속 실패 한도 (5s × 30 = 2.5분)

# Cooldown 기본값 (매도 직후 재매수 방지)
_SELL_COOLDOWN_SECONDS = 300       # 5분, strategy_config로 override 가능

# Proposal 만료 기간 (BUY 제안 공통, 강제청산 시 Brief D 에서도 동일 값 참조 예정)
_FORCED_LIQUIDATION_EXPIRE_SECONDS = 180  # 3분
```

#### 클래스 골격

```python
@dataclass
class MonitorConfig:
    """strategy_config.json + 환경변수 기반 정적 설정."""
    sell_cooldown_seconds: int = _SELL_COOLDOWN_SECONDS
    max_consecutive_failures: int = _MAX_CONSECUTIVE_FAILURES
    tick_market: float = _TICK_MARKET
    tick_idle: float = _TICK_IDLE
    proposal_expire_seconds: int = _FORCED_LIQUIDATION_EXPIRE_SECONDS  # BUY 제안 + 강제청산 공통 3분

    @classmethod
    def load(cls, path: Path = _CONFIG_FILE) -> "MonitorConfig":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return cls()
        trading = raw.get("trading") or {}
        return cls(
            sell_cooldown_seconds=int(trading.get("sell_cooldown_seconds", _SELL_COOLDOWN_SECONDS)),
            max_consecutive_failures=int(trading.get("monitor_max_consecutive_failures", _MAX_CONSECUTIVE_FAILURES)),
            tick_market=float(trading.get("monitor_tick_market_seconds", _TICK_MARKET)),
            tick_idle=float(trading.get("monitor_tick_idle_seconds", _TICK_IDLE)),
            proposal_expire_seconds=int(trading.get("proposal_expire_seconds", _FORCED_LIQUIDATION_EXPIRE_SECONDS)),
        )


class PositionMonitor:
    """Phase 2 데몬 본체 — state writer + 체결 감지 + 자정 리셋."""

    def __init__(
        self,
        *,
        kis_client: KISClient | None = None,
        position_store: PositionStateStore | None = None,
        trading_store: TradingStateStore | None = None,
        proposals_store: PendingProposalsStore | None = None,
        config: MonitorConfig | None = None,
        logger: logging.Logger | None = None,
    ):
        self.config = config or MonitorConfig.load()
        self.kis = kis_client or KISClient(mode="trading")
        self.positions = position_store or PositionStateStore()
        self.trading = trading_store or TradingStateStore()
        self.proposals = proposals_store or PendingProposalsStore()
        self.logger = logger or _setup_logger()
        self._consecutive_failures = 0
        self._running = False
        self._last_known_date: date | None = None

    # ── 라이프사이클 ─────────────────────────────────────────────────────────
    def run(self) -> None:
        """메인 진입점. SIGTERM/SIGINT 수신 시 우아한 종료."""
        self._running = True
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

        self.logger.info("position_monitor 기동")
        self.recover_on_boot()

        while self._running:
            now = datetime.now()
            try:
                self.tick(now)
                self._consecutive_failures = 0
            except Exception as exc:
                self._consecutive_failures += 1
                self.logger.exception("tick 실패 (%d/%d): %s",
                                      self._consecutive_failures,
                                      self.config.max_consecutive_failures,
                                      exc)
                if self._consecutive_failures >= self.config.max_consecutive_failures:
                    self.logger.error("연속 실패 한도 초과. 10분 휴면.")
                    self._sleep(600)
                    self._consecutive_failures = 0

            interval = self.config.tick_market if is_market_open(now) else self.config.tick_idle
            self._sleep(interval)

        self.logger.info("position_monitor 종료")

    def _handle_shutdown(self, signum, frame) -> None:  # noqa: ARG002
        self._running = False

    def _sleep(self, seconds: float) -> None:
        """종료 시그널에 반응할 수 있는 짧은 슬립 루프."""
        end = time.monotonic() + seconds
        while self._running and time.monotonic() < end:
            time.sleep(min(1.0, end - time.monotonic()))

    # ── 단위 Tick (테스트 대상) ─────────────────────────────────────────────
    def tick(self, now: datetime) -> None:
        """단일 폴링 사이클. 테스트에서 독립 호출 가능."""
        self._check_midnight_reset(now)
        if not is_market_open(now):
            return
        snapshot = self._fetch_kis_snapshot()
        self._diff_and_apply(snapshot, now)
        self._check_loss_limit(now)
```

### 단일 인스턴스 락 (pidfile)

```python
def _acquire_lock() -> bool:
    """pidfile 기반 단일 인스턴스 보장. 이미 실행 중이면 False."""
    if _PIDFILE.exists():
        try:
            old_pid = int(_PIDFILE.read_text(encoding="utf-8").strip())
            os.kill(old_pid, 0)  # 프로세스 존재 여부만 확인
            return False
        except (OSError, ValueError):
            # stale pidfile
            try:
                _PIDFILE.unlink()
            except OSError:
                pass
    _PIDFILE.write_text(str(os.getpid()), encoding="utf-8")
    return True


def _release_lock() -> None:
    try:
        _PIDFILE.unlink()
    except OSError:
        pass


def _setup_logger() -> logging.Logger:
    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("position_monitor")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        )
        logger.addHandler(handler)
    return logger


# ── CLI 진입점 ──────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 2 position monitor daemon")
    parser.add_argument("--once", action="store_true", help="단일 tick 실행 후 종료 (디버그용)")
    args = parser.parse_args(argv)

    inject_to_env()
    if not _acquire_lock():
        print("position_monitor 이미 실행 중", file=sys.stderr)
        return 1

    try:
        monitor = PositionMonitor()
        if args.once:
            monitor.recover_on_boot()
            monitor.tick(datetime.now())
            return 0
        monitor.run()
        return 0
    finally:
        _release_lock()


if __name__ == "__main__":
    sys.exit(main())
```

### Acceptance
- [ ] `PositionMonitor.run()` 호출 시 SIGTERM 수신 후 1초 내 종료
- [ ] 동일 프로세스 2개 기동 시 두 번째는 exit code 1 + "이미 실행 중" 메시지
- [ ] stale pidfile(존재하지만 프로세스 죽은 상태) 자동 정리
- [ ] `tick()` 공개 메서드로 테스트에서 직접 호출 가능
- [ ] 연속 실패 30회 시 10분 휴면 로그 기록
- [ ] `logs/trading.log`에 INFO 이상 기록

---

## Task 2 — KIS 잔고 스냅샷 & 체결 감지 (Diff 알고리즘)

### 책임
- KIS 잔고조회 TR 호출 (trading mode, `inquire_balance_by_ticker` 또는 `get_balance` 활용)
- 직전 스냅샷과 종목별 diff 계산
- BUY 증가 → `apply_buy()` + `inc_buy()` + `clear_in_flight(ticker)`
- SELL 감소 → `apply_sell()` + `inc_sell()` + `add_realized_pnl()` + `clear_in_flight()` + cooldown 설정

### 데이터 모델

```python
@dataclass
class BalanceSnapshot:
    """KIS 잔고조회 응답 정규화 결과. 종목코드 키."""
    fetched_at: datetime
    holdings: dict[str, "TickerBalance"] = field(default_factory=dict)


@dataclass
class TickerBalance:
    code: str
    name: str
    qty: int             # 보유수량 (주)
    avg_price: float     # 매입평균
    current_price: float # 현재가 (참고용, diff 계산에 직접 사용하지 않음)
```

### 구현

```python
    def _fetch_kis_snapshot(self) -> BalanceSnapshot:
        """KIS 잔고조회 → BalanceSnapshot."""
        raw = self.kis.get_balance()  # 기존 KISClient 메서드 활용
        fetched = datetime.now()
        holdings: dict[str, TickerBalance] = {}

        # KIS 응답 구조는 "output1": [...종목..], "output2": [...현금..]
        for item in raw.get("output1", []):
            qty = int(item.get("hldg_qty") or 0)
            if qty <= 0:
                continue
            code = str(item.get("pdno") or "").strip()
            if not code:
                continue
            holdings[code] = TickerBalance(
                code=code,
                name=str(item.get("prdt_name") or "").strip(),
                qty=qty,
                avg_price=float(item.get("pchs_avg_pric") or 0.0),
                current_price=float(item.get("prpr") or 0.0),
            )
        return BalanceSnapshot(fetched_at=fetched, holdings=holdings)

    def _diff_and_apply(self, snapshot: BalanceSnapshot, now: datetime) -> None:
        """
        직전 저장 상태(self.positions)와 snapshot 비교.
        - KIS에는 있는데 로컬에 없음 → 신규 BUY 체결
        - KIS 수량 > 로컬 수량 → 추가 BUY 체결 (분할매수)
        - KIS 수량 < 로컬 수량 → SELL 체결
        - KIS에 없는데 로컬에 있음 → 전량 매도
        """
        changes = False
        local_codes = set(self.positions.holdings.keys())
        remote_codes = set(snapshot.holdings.keys())

        # ── 신규/추가 BUY ────────────────────────────────────────────────
        for code in remote_codes:
            remote = snapshot.holdings[code]
            local = self.positions.get(code)

            if local is None:
                # 신규 진입
                self.positions.apply_buy(
                    code=code,
                    name=remote.name,
                    qty=remote.qty,
                    price=remote.avg_price,
                    stage=1,
                    at=snapshot.fetched_at,
                )
                self.trading.inc_buy()
                self.trading.clear_in_flight(code)
                self.logger.info("BUY 감지 (신규): %s %d주 @%.0f", code, remote.qty, remote.avg_price)
                changes = True

            elif remote.qty > local.qty:
                # 추가 분할매수
                added_qty = remote.qty - local.qty
                # KIS avg_price는 이미 누적 가중평단이므로 역산해서 이번 체결가 추출
                # (price_of_this_fill * added_qty + local.avg_price * local.qty) / remote.qty = remote.avg_price
                try:
                    fill_price = (
                        (remote.avg_price * remote.qty) - (local.avg_price * local.qty)
                    ) / added_qty
                except ZeroDivisionError:
                    fill_price = remote.avg_price
                if fill_price <= 0:
                    # 이상치 방어: 음수/0 → KIS 가중평단 그대로 사용
                    fill_price = remote.avg_price
                next_stage = min(3, (local.stage or 1) + 1)
                self.positions.apply_buy(
                    code=code,
                    name=remote.name,
                    qty=added_qty,
                    price=fill_price,
                    stage=next_stage,
                    at=snapshot.fetched_at,
                )
                self.trading.inc_buy()
                self.trading.clear_in_flight(code)
                self.logger.info(
                    "BUY 감지 (추가 stage%d): %s +%d주 @%.0f",
                    next_stage, code, added_qty, fill_price,
                )
                changes = True

            elif remote.qty < local.qty:
                # 부분 매도
                sold_qty = local.qty - remote.qty
                # apply_sell 은 qty, price 인수 받음. KIS 현재가를 체결가로 간주
                fill_price = remote.current_price or local.avg_price
                pnl = self.positions.apply_sell(code, sold_qty, fill_price)
                self.trading.inc_sell()
                self.trading.add_realized_pnl(pnl)
                self.trading.clear_in_flight(code)
                self.trading.set_cooldown(
                    code, snapshot.fetched_at + timedelta(seconds=self.config.sell_cooldown_seconds)
                )
                self.logger.info(
                    "SELL 감지 (부분): %s -%d주 @%.0f (실현%+d원)",
                    code, sold_qty, fill_price, pnl,
                )
                changes = True

        # ── 전량 매도 ────────────────────────────────────────────────────
        for code in local_codes - remote_codes:
            local = self.positions.get(code)
            if local is None:
                continue
            # 전량 청산: 현재가를 얻을 수 없으므로 KIS 체결내역 조회 또는 avg_price 보수적 사용
            # Brief C에서는 보수적으로 avg_price 가정 (pnl=0). Brief C2에서 체결내역 TR 도입 예정.
            fill_price = local.avg_price
            pnl = self.positions.apply_sell(code, local.qty, fill_price)
            self.trading.inc_sell()
            self.trading.add_realized_pnl(pnl)
            self.trading.clear_in_flight(code)
            self.trading.set_cooldown(
                code, snapshot.fetched_at + timedelta(seconds=self.config.sell_cooldown_seconds)
            )
            self.logger.warning(
                "SELL 감지 (전량, 체결가 avg_price 추정): %s -%d주 @%.0f",
                code, local.qty, fill_price,
            )
            changes = True

        # ── trailing peak 갱신 ───────────────────────────────────────────
        for code, remote in snapshot.holdings.items():
            if remote.current_price > 0:
                self.positions.update_peak(code, remote.current_price)
                changes = True  # peak 변경도 persist 필요

        if changes:
            self.positions.persist()
            self.trading.persist()
```

### 중요 설계 주석
1. **추가 매수 시 `fill_price` 역산**: KIS `pchs_avg_pric`는 전체 누적 가중평단이므로, 이번 체결가는 `(remote_total - local_total) / added_qty`로 추출. 음수·0 방어.
2. **전량 매도 체결가 추정**: KIS 잔고에서 사라진 순간에는 체결가를 알 수 없어 `avg_price` 보수적 사용 → **pnl=0 기록**. Brief C2에서 KIS 주문체결내역 TR(`CTSC9215R` 등) 도입 예정.
3. **stage 자동 증가**: 추가 분할매수 감지 시 `stage = min(3, local.stage+1)`. 수동 매수(오프라인 HTS)로도 정상 기록.
4. **단일 persist**: 한 tick 내 여러 종목 변동이 있어도 `positions.persist()` / `trading.persist()`는 tick 끝에서 1회씩.

### Acceptance
- [ ] KIS 잔고 응답에 **없던** 종목 등장 → `apply_buy(stage=1)` + `inc_buy()` + `clear_in_flight`
- [ ] 기존 종목 수량 증가 → `apply_buy(stage=local.stage+1)` + 가중평단 역산으로 `fill_price` 계산
- [ ] 기존 종목 수량 감소 → `apply_sell` + `inc_sell` + `add_realized_pnl(pnl)` + cooldown 설정
- [ ] 기존 종목 완전 소멸 → `apply_sell(all qty, fill_price=avg_price)` + warning 로그
- [ ] 변경 없는 tick에서는 `positions.persist()` / `trading.persist()` 호출 **안 함** (io 절약)
- [ ] `trailing peak` 현재가 초과 시 `update_peak()` 호출
- [ ] 모든 변경에 INFO/WARNING 로그 기록

---

## Task 3 — 재시작 복구 (Boot Recovery)

### 책임
- 기동 시 KIS 잔고 1회 조회 → 권위 소스로 수용
- 로컬 `position_state.json` 과 불일치 시 **KIS 기준으로 overwrite**
- cooldown/in_flight 정리:
  - `pending_proposals`의 만료 항목 정리 (`cleanup_expired_on_boot`)
  - `trading_state.in_flight_orders` 전체 clear (재시작 후에는 어떤 주문도 in_flight가 아님)

### 구현

```python
    def recover_on_boot(self) -> None:
        """기동 시 1회 호출. KIS 잔고 권위 적용 + 만료 정리."""
        self.logger.info("재시작 복구 시작")
        try:
            snapshot = self._fetch_kis_snapshot()
        except Exception as exc:
            self.logger.error("복구: KIS 잔고조회 실패, 로컬 state 유지: %s", exc)
            # 스냅샷 실패해도 pending 만료는 처리
            cutoff = datetime.now() - timedelta(seconds=self.config.proposal_expire_seconds)
            self.proposals.cleanup_expired_on_boot(cutoff)
            self.proposals.persist()
            return

        # ── 1. position_state 재구성 ──────────────────────────────────────
        divergent: list[str] = []
        for code, remote in snapshot.holdings.items():
            local = self.positions.get(code)
            if local is None or local.qty != remote.qty or abs(local.avg_price - remote.avg_price) > 0.5:
                divergent.append(code)

        local_only = set(self.positions.holdings.keys()) - set(snapshot.holdings.keys())
        if local_only:
            divergent.extend(sorted(local_only))

        if divergent:
            self.logger.warning("복구: KIS 불일치 %d종목 — KIS 기준 덮어쓰기: %s",
                                len(divergent), divergent)
            self._rebuild_positions_from_kis(snapshot)
        else:
            self.logger.info("복구: KIS와 로컬 일치. position_state 유지")

        # ── 2. trading_state 정리: in_flight 전체 clear ────────────────
        in_flight_codes = list(self.trading.data.in_flight_orders.keys())
        for code in in_flight_codes:
            self.trading.clear_in_flight(code)
        if in_flight_codes:
            self.logger.info("복구: in_flight %d건 clear (%s)", len(in_flight_codes), in_flight_codes)

        # ── 3. cooldown 만료 청소 (reset_daily 내부 로직 재활용) ───────
        now = datetime.now()
        self.trading._cleanup_expired_cooldowns(now)  # 접근 허용 (동일 패키지)

        # ── 4. pending proposals 만료 정리 ───────────────────────────────
        cutoff = now - timedelta(seconds=self.config.proposal_expire_seconds)
        expired_props = self.proposals.cleanup_expired_on_boot(cutoff)
        if expired_props:
            self.logger.info("복구: 만료 proposal %d건 정리", len(expired_props))

        # ── 5. persist all ────────────────────────────────────────────────
        self.positions.persist()
        self.trading.persist()
        self.proposals.persist()
        self.logger.info("재시작 복구 완료")

    def _rebuild_positions_from_kis(self, snapshot: BalanceSnapshot) -> None:
        """로컬 position_state 를 KIS 잔고로 덮어쓴다."""
        # 모든 로컬 holdings 제거
        self.positions.holdings.clear()
        # KIS 기준 재구성: avg_price, qty만 권위. peak_price_since_entry는 avg_price로 초기화
        for code, remote in snapshot.holdings.items():
            self.positions.apply_buy(
                code=code,
                name=remote.name,
                qty=remote.qty,
                price=remote.avg_price,
                stage=1,                 # 재구성 후에는 stage 정보 없음 → 1로 시작
                at=snapshot.fetched_at,
            )
            # entry_history 는 "[recovery]" 마커 1건만 남도록 정리
            pos = self.positions.get(code)
            if pos and pos.entry_history:
                pos.entry_history[-1].stage = 1
            # trailing 관련 리셋
            if pos:
                pos.peak_price_since_entry = remote.current_price or remote.avg_price
                pos.trailing_active = False
```

### 중요 설계 주석
1. **덮어쓰기 조건**: 수량 불일치 OR `avg_price` 차이 > 0.5원. 부동소수 미세차이는 허용.
2. **stage 손실 수용**: 재시작 후 분할매수 stage 정보는 복원 불가 → stage=1로 시작, Brief D에서 `entry_history`에 `"[recovery]"` 마커 추가 고려.
3. **in_flight 전체 clear**: 재시작 시점에 진행중이던 주문의 실제 상태는 KIS 기준으로 이미 잔고에 반영됨. in_flight 플래그는 "이 프로세스에서 보냈고 아직 체결 확인 못함"의 의미이므로 재시작 후에는 무조건 false.
4. **KIS 조회 실패 시**: 로컬 state 유지 + proposals만 정리. 다음 tick에서 복구 재시도 (단, recover_on_boot은 run() 시작 시 한 번만 호출).
5. **텔레그램 통지**: Brief C에서는 logger.warning 까지만. 실제 텔레그램 send는 Brief D에서 hook 추가.

### Acceptance
- [ ] KIS 잔고와 로컬 state 일치 시 덮어쓰기 **안 함**, INFO 로그만
- [ ] 수량 불일치 종목 1건 이상 → KIS 기준 덮어쓰기 + WARNING 로그
- [ ] `in_flight_orders` 전체 clear
- [ ] 만료 cooldown 정리
- [ ] `pending_proposals` 만료 정리 (`cleanup_expired_on_boot`)
- [ ] KIS 조회 실패 시 로컬 state 유지 + ERROR 로그 + proposals만 정리
- [ ] 복구 완료 후 `positions.persist()` / `trading.persist()` / `proposals.persist()` 모두 호출

---

## Task 4 — 자정 리셋 & 일일 손실한도 감시

### 책임
- 날짜 경계 감지 시 `reset_daily()` 호출 + 새 `daily_start_orderable_cash` 스냅샷
- 매 tick마다 `should_block()` 체크 → True 전환 시 `block_new_orders=True` + 강제청산 proposal enqueue

### 구현

```python
    def _check_midnight_reset(self, now: datetime) -> None:
        """
        날짜 경계 감지 시 reset_daily + orderable_cash 스냅샷.
        last_reset_date 가 오늘 date()와 다르면 리셋.
        """
        today = now.date()
        last_reset_iso = self.trading.data.last_reset_date
        try:
            last_reset = date.fromisoformat(last_reset_iso) if last_reset_iso else None
        except ValueError:
            last_reset = None

        if last_reset == today:
            return

        # 새 orderable_cash 스냅샷
        try:
            orderable_cash = self._fetch_orderable_cash()
        except Exception as exc:
            self.logger.error("자정 리셋: orderable_cash 조회 실패, 리셋 연기: %s", exc)
            return

        self.trading.reset_daily(today=today, new_orderable_cash=orderable_cash)
        self.trading.persist()
        self.logger.info(
            "자정 리셋 완료. 일일 손실한도=%d원 (trial=%s)",
            orderable_cash,
            self.trading.data.trial_mode,
        )
        self._last_known_date = today

    def _fetch_orderable_cash(self) -> int:
        """KIS get_orderable_cash 호출 → int 반환."""
        raw = self.kis.get_orderable_cash()
        # KIS 응답 구조: {"output": {"ord_psbl_cash": "12345678"}}
        if isinstance(raw, dict):
            output = raw.get("output") or {}
            return int(output.get("ord_psbl_cash") or output.get("nrcvb_buy_amt") or 0)
        return int(raw or 0)

    def _check_loss_limit(self, now: datetime) -> None:  # noqa: ARG002
        """
        realized_pnl <= -daily_start_orderable_cash 전환 감지.
        전환 순간 block_new_orders=True 플립 + ERROR 로그.
        이미 block 상태면 no-op.

        주의: Brief C 범위에서는 **상태 전환만** 담당.
        실제 텔레그램 질의 + 사용자 응답 대기 + sell_request.jsonl 발행은 Brief D 책임.
        Brief D 텔레그램봇이 주기적으로 trading_state.block_new_orders를 감시하다가
        False → True 전환을 감지하면 텔레그램 질의를 시작한다.
        """
        if self.trading.data.block_new_orders:
            return
        if not self.trading.should_block():
            return

        self.trading.set_block(True)
        self.trading.persist()
        self.logger.error(
            "일일 손실한도 초과: realized=%d, limit=%d. 신규 주문 차단 (block_new_orders=True).",
            self.trading.data.realized_pnl,
            self.trading.data.daily_start_orderable_cash,
        )
        self.logger.warning(
            "보유 종목 %d건 — Brief D 텔레그램봇이 3분 질의 후 사용자 승인 시 청산 실행 예정",
            len(self.positions.all_codes()),
        )
```

### 중요 설계 주석
1. **자정 리셋 조건**: `last_reset_date != today`. 데몬이 멈춰 있다가 다음날 장 개시 전 재기동되어도 첫 tick에서 리셋.
2. **orderable_cash 조회 실패**: 리셋 연기 (다음 tick에서 재시도). 리셋이 누락되면 block 판정이 오작동할 수 있으므로 반드시 성공해야 함.
3. **손실한도 전환 edge-trigger**: `block_new_orders` 이미 True면 proposal 중복 enqueue 금지. `should_block()`는 매 tick 저비용 호출.
4. **FORCED_LIQUIDATION proposal 스키마**:
   - `ticker`는 보유 전체 콤마 구분 (운영 시에는 더 구조화된 payload 권장 — Brief D에서 개선)
   - `qty=0`, `price_ref=0.0` — 의미 없는 필드지만 Proposal dataclass가 요구
   - `kind="FORCED_LIQUIDATION"`으로 구분 (기본 `"BUY"`와 별도 분기)
5. **3분 타임아웃 관리**: `cleanup_expired_on_boot` 대신 매 tick `_tick_expire_proposals(now)` 호출 필요 (아래 Task 4b).

### Task 4b — Pending Proposals 만료 tick (BUY 제안 정리)

intraday_discovery → pending_proposals 에 enqueue 된 매수 제안 중 `last_sent` 후 3분 경과한 pending 건을 `expired`로 전환. Brief B의 `cleanup_expired_on_boot(cutoff)` API 재활용 (런타임에서도 동작).

```python
    def tick(self, now: datetime) -> None:
        """단일 폴링 사이클. 수정판."""
        self._check_midnight_reset(now)
        self._tick_expire_proposals(now)    # ← 추가
        if not is_market_open(now):
            return
        snapshot = self._fetch_kis_snapshot()
        self._diff_and_apply(snapshot, now)
        self._check_loss_limit(now)

    def _tick_expire_proposals(self, now: datetime) -> None:
        """pending 중 last_sent < (now - 3분) 인 항목을 expired로 전환."""
        cutoff = now - timedelta(seconds=self.config.proposal_expire_seconds)
        expired = self.proposals.cleanup_expired_on_boot(cutoff)
        if expired:
            self.proposals.persist()
            for proposal in expired:
                self.logger.info("proposal 만료: %s (%s)", proposal.id, proposal.code)
```

**실제 API 참조 (Brief B 구현):**
- `PendingProposalsStore.proposals` 는 `list[Proposal]` (dict 아님)
- `cleanup_expired_on_boot(cutoff: datetime) -> list[Proposal]` 이 pending 중 `last_sent < cutoff` 인 것을 `expired`로 마킹하고 리스트 반환 (내부에서 persist 안 함, caller가 persist)
- 개별 종료 시 `transition(proposal_id, new_status, at=None)` 사용 가능

### Acceptance
- [ ] `last_reset_date`가 오늘과 다르면 `reset_daily()` 호출 + INFO 로그
- [ ] orderable_cash 조회 실패 시 리셋 연기 + ERROR 로그
- [ ] `realized_pnl ≤ -daily_start_orderable_cash` 전환 순간 `block_new_orders=True` + ERROR 로그 + 보유 종목 수 WARNING 로그
- [ ] 이미 block 상태면 `_check_loss_limit` no-op (로그 출력 안 함)
- [ ] `_tick_expire_proposals` 가 `last_sent < now - 3분` 인 pending proposal을 expired로 전환 + persist

---

## Task 5 — 단위 테스트 (`tests/test_position_monitor.py`)

### 테스트 원칙
- `KISClient` 를 `unittest.mock.MagicMock`으로 주입
- 시간은 `datetime(2026, 4, 23, 10, 0)` 같은 고정값 주입 (파라미터로)
- `tmp_path` 기반 state 파일 격리 (Brief B 패턴)
- `tick()` 및 개별 helper를 직접 호출해서 검증

### 테스트 케이스 (최소 12건)

```python
"""test_position_monitor.py — Phase 2 데몬 단위 테스트."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from morning_report.pending_proposals import PendingProposalsStore, Proposal
from morning_report.position_monitor import BalanceSnapshot, MonitorConfig, PositionMonitor, TickerBalance
from morning_report.position_state import PositionStateStore
from morning_report.trading_state import TradingStateStore


_MARKET_HOUR = datetime(2026, 4, 23, 10, 0)  # 목요일 10시 정각
_BEFORE_MARKET = datetime(2026, 4, 23, 8, 0)
_MIDNIGHT = datetime(2026, 4, 24, 0, 0, 30)  # 익일 00:00:30


def _build_monitor(tmp_path: Path, kis_stub: MagicMock) -> PositionMonitor:
    position_store = PositionStateStore(path=tmp_path / "position_state.json")
    trading_store = TradingStateStore(path=tmp_path / "trading_state.json")
    proposals_store = PendingProposalsStore(path=tmp_path / "pending_proposals.json")
    config = MonitorConfig(sell_cooldown_seconds=300, forced_liquidation_expire=180)
    return PositionMonitor(
        kis_client=kis_stub,
        position_store=position_store,
        trading_store=trading_store,
        proposals_store=proposals_store,
        config=config,
    )


def _kis_balance_response(rows: list[dict]) -> dict:
    return {"output1": rows, "output2": []}


# Test 1. Skeleton — signal handling (mock)
def test_run_exits_on_shutdown_flag(tmp_path):
    kis = MagicMock()
    kis.get_balance.return_value = _kis_balance_response([])
    kis.get_orderable_cash.return_value = {"output": {"ord_psbl_cash": "1000000"}}
    monitor = _build_monitor(tmp_path, kis)
    monitor._running = False  # 즉시 종료
    monitor.run()  # 무한루프 안 걸림
    assert monitor._consecutive_failures == 0


# Test 2. 단일 인스턴스 락
def test_acquire_lock_prevents_double_run(tmp_path, monkeypatch):
    from morning_report import position_monitor as pm
    lock_path = tmp_path / "position_monitor.pid"
    monkeypatch.setattr(pm, "_PIDFILE", lock_path)
    assert pm._acquire_lock() is True
    assert pm._acquire_lock() is False  # 이미 실행 중
    pm._release_lock()
    assert not lock_path.exists()


# Test 3. Balance diff — 신규 BUY
def test_diff_detects_new_buy(tmp_path):
    kis = MagicMock()
    monitor = _build_monitor(tmp_path, kis)
    snapshot = BalanceSnapshot(
        fetched_at=_MARKET_HOUR,
        holdings={
            "005930": TickerBalance("005930", "삼성전자", qty=10, avg_price=70000.0, current_price=71000.0)
        },
    )
    monitor._diff_and_apply(snapshot, _MARKET_HOUR)
    pos = monitor.positions.get("005930")
    assert pos is not None
    assert pos.qty == 10
    assert pos.avg_price == pytest.approx(70000.0)
    assert monitor.trading.data.buy_count_today == 1


# Test 4. Balance diff — 추가 분할매수 (가중평단 역산)
def test_diff_detects_additional_buy_with_fill_price_backsolve(tmp_path):
    kis = MagicMock()
    monitor = _build_monitor(tmp_path, kis)
    monitor.positions.apply_buy("005930", "삼성전자", qty=10, price=70000.0, stage=1, at=_MARKET_HOUR)
    # 10주 @70000 보유 중 → KIS가 30주 @ avg 73000 리턴 (20주 추가 @ 74500 가정)
    # (73000*30 - 70000*10) / 20 = (2190000 - 700000)/20 = 74500
    snapshot = BalanceSnapshot(
        fetched_at=_MARKET_HOUR,
        holdings={
            "005930": TickerBalance("005930", "삼성전자", qty=30, avg_price=73000.0, current_price=74000.0)
        },
    )
    monitor._diff_and_apply(snapshot, _MARKET_HOUR)
    pos = monitor.positions.get("005930")
    assert pos.qty == 30
    # 가중평단이 KIS 값과 거의 일치 (역산 → apply_buy 재계산 경로)
    assert pos.avg_price == pytest.approx(73000.0, abs=1.0)
    assert pos.stage == 2


# Test 5. Balance diff — 부분 매도 → pnl + cooldown
def test_diff_detects_partial_sell_with_cooldown(tmp_path):
    kis = MagicMock()
    monitor = _build_monitor(tmp_path, kis)
    monitor.positions.apply_buy("005930", "삼성전자", qty=10, price=70000.0, stage=1, at=_MARKET_HOUR)
    snapshot = BalanceSnapshot(
        fetched_at=_MARKET_HOUR,
        holdings={
            "005930": TickerBalance("005930", "삼성전자", qty=3, avg_price=70000.0, current_price=75000.0)
        },
    )
    monitor._diff_and_apply(snapshot, _MARKET_HOUR)
    pos = monitor.positions.get("005930")
    assert pos.qty == 3
    assert monitor.trading.data.sell_count_today == 1
    # 실현손익 = (75000 - 70000) * 7 = 35000
    assert monitor.trading.data.realized_pnl == 35000
    # cooldown 설정 확인
    assert monitor.trading.is_in_cooldown("005930", _MARKET_HOUR)


# Test 6. Balance diff — 전량 매도
def test_diff_detects_full_exit(tmp_path):
    kis = MagicMock()
    monitor = _build_monitor(tmp_path, kis)
    monitor.positions.apply_buy("005930", "삼성전자", qty=5, price=70000.0, stage=1, at=_MARKET_HOUR)
    snapshot = BalanceSnapshot(fetched_at=_MARKET_HOUR, holdings={})
    monitor._diff_and_apply(snapshot, _MARKET_HOUR)
    assert monitor.positions.get("005930") is None
    assert monitor.trading.data.sell_count_today == 1
    # avg_price 체결 가정 → pnl = 0
    assert monitor.trading.data.realized_pnl == 0


# Test 7. Boot recovery — KIS/로컬 일치 시 no-op
def test_recover_no_divergence(tmp_path):
    kis = MagicMock()
    kis.get_balance.return_value = _kis_balance_response([
        {"pdno": "005930", "prdt_name": "삼성전자", "hldg_qty": "10",
         "pchs_avg_pric": "70000", "prpr": "71000"}
    ])
    monitor = _build_monitor(tmp_path, kis)
    monitor.positions.apply_buy("005930", "삼성전자", qty=10, price=70000.0, stage=1, at=_MARKET_HOUR)
    monitor.recover_on_boot()
    # 덮어쓰기 없이 유지
    pos = monitor.positions.get("005930")
    assert pos.qty == 10


# Test 8. Boot recovery — 불일치 시 KIS 덮어쓰기
def test_recover_overwrites_local_on_divergence(tmp_path):
    kis = MagicMock()
    kis.get_balance.return_value = _kis_balance_response([
        {"pdno": "005930", "prdt_name": "삼성전자", "hldg_qty": "15",
         "pchs_avg_pric": "72000", "prpr": "73000"}
    ])
    monitor = _build_monitor(tmp_path, kis)
    monitor.positions.apply_buy("005930", "삼성전자", qty=10, price=70000.0, stage=2, at=_MARKET_HOUR)
    monitor.recover_on_boot()
    pos = monitor.positions.get("005930")
    assert pos.qty == 15
    assert pos.avg_price == pytest.approx(72000.0)
    # stage 리셋
    assert pos.stage == 1


# Test 9. Boot recovery — in_flight 전체 clear
def test_recover_clears_in_flight(tmp_path):
    kis = MagicMock()
    kis.get_balance.return_value = _kis_balance_response([])
    monitor = _build_monitor(tmp_path, kis)
    monitor.trading.mark_in_flight("005930", "BUY", _MARKET_HOUR)
    monitor.trading.mark_in_flight("000660", "SELL", _MARKET_HOUR)
    monitor.recover_on_boot()
    assert not monitor.trading.is_in_flight("005930")
    assert not monitor.trading.is_in_flight("000660")


# Test 10. 자정 리셋
def test_midnight_reset_triggers_with_fresh_orderable_cash(tmp_path):
    kis = MagicMock()
    kis.get_orderable_cash.return_value = {"output": {"ord_psbl_cash": "2000000"}}
    monitor = _build_monitor(tmp_path, kis)
    # 어제 리셋 상태로 설정
    monitor.trading.data.last_reset_date = "2026-04-22"
    monitor.trading.data.realized_pnl = -500000
    monitor.trading.data.buy_count_today = 3
    monitor._check_midnight_reset(_MIDNIGHT)
    assert monitor.trading.data.last_reset_date == "2026-04-24"
    assert monitor.trading.data.realized_pnl == 0
    assert monitor.trading.data.buy_count_today == 0
    assert monitor.trading.data.daily_start_orderable_cash == 2000000


# Test 11. 일일 손실한도 초과 → block + ERROR 로그
def test_loss_limit_flips_block_flag(tmp_path, caplog):
    kis = MagicMock()
    monitor = _build_monitor(tmp_path, kis)
    monitor.trading.data.daily_start_orderable_cash = 100000
    monitor.trading.data.realized_pnl = -100000
    monitor.positions.apply_buy("005930", "삼성전자", qty=5, price=70000.0, stage=1, at=_MARKET_HOUR)
    with caplog.at_level("WARNING", logger="position_monitor"):
        monitor._check_loss_limit(_MARKET_HOUR)
    assert monitor.trading.data.block_new_orders is True
    # persist 까지 확인
    reloaded = monitor.trading.__class__(path=monitor.trading._path)
    assert reloaded.data.block_new_orders is True


# Test 12. 손실한도 이미 block 상태면 no-op
def test_loss_limit_noop_when_already_blocked(tmp_path, caplog):
    kis = MagicMock()
    monitor = _build_monitor(tmp_path, kis)
    monitor.trading.data.block_new_orders = True
    monitor.trading.data.daily_start_orderable_cash = 100000
    monitor.trading.data.realized_pnl = -200000
    with caplog.at_level("ERROR", logger="position_monitor"):
        monitor._check_loss_limit(_MARKET_HOUR)
    # 추가 로그 없이 block 유지
    assert monitor.trading.data.block_new_orders is True
    assert "초과" not in caplog.text


# Test 13. Proposal 만료 tick
def test_tick_expire_proposals_marks_expired(tmp_path):
    from morning_report.pending_proposals import Proposal as BuyProposal
    kis = MagicMock()
    monitor = _build_monitor(tmp_path, kis)
    old_sent = (_MARKET_HOUR - timedelta(minutes=5)).isoformat(timespec="seconds")
    monitor.proposals.enqueue(BuyProposal(
        id="P1", code="005930", name="삼성전자", round=1, rank=1, stage="S1",
        score=0.9, tday_rltv=1.5, chg=2.0, price_ref=70000.0,
        status="pending", count=1,
        created_at=old_sent, last_sent=old_sent,
    ))
    monitor._tick_expire_proposals(_MARKET_HOUR)
    p = monitor.proposals.get("P1")
    assert p.status == "expired"


# Test 14. 장외 tick → diff 호출 안 함
def test_tick_skips_diff_when_market_closed(tmp_path):
    kis = MagicMock()
    kis.get_balance.return_value = _kis_balance_response([])
    kis.get_orderable_cash.return_value = {"output": {"ord_psbl_cash": "1000000"}}
    monitor = _build_monitor(tmp_path, kis)
    monitor.trading.data.last_reset_date = _BEFORE_MARKET.date().isoformat()
    monitor.tick(_BEFORE_MARKET)
    kis.get_balance.assert_not_called()  # 장외면 잔고조회 스킵
```

### Acceptance (테스트 건수)
- [ ] 최소 14건 이상 통과 (Test 1 ~ Test 14)
- [ ] KIS API mock으로 외부 호출 0건
- [ ] `tmp_path` 기반 격리 (실제 `data/*.json` 미영향)
- [ ] 테스트 실행: `python3 -m pytest tests/test_position_monitor.py -v` 모두 PASS

---

## 구현 순서 권장

1. **Task 1 (skeleton)** 먼저 → `python3 -m py_compile morning_report/position_monitor.py` 통과 + `--once` 실행 가능
2. **Task 2 (diff)** → `_fetch_kis_snapshot` + `_diff_and_apply` 단독 테스트 3건 (신규/추가/부분매도) 먼저 통과
3. **Task 3 (recovery)** → 단일 종목 불일치 케이스 테스트
4. **Task 4 (midnight + loss limit)** → `_check_midnight_reset` + `_check_loss_limit` 테스트
5. **Task 4b (proposal 만료)** → `_tick_expire_proposals` 테스트
6. **Task 5 전체 12+건** 테스트 통과 확인

---

## 통합 검증 체크리스트 (Codex 구현 완료 후 Claude가 실행)

```bash
cd /Users/geenya/projects/AI_Projects/stockpilot

# 1. 문법 검사
venv/bin/python3 -m py_compile morning_report/position_monitor.py

# 2. 단위 테스트 (Brief B 기존 테스트와 함께 regression)
venv/bin/python3 -m pytest tests/test_position_monitor.py \
    tests/test_position_state.py \
    tests/test_trading_state.py \
    tests/test_pending_proposals.py \
    tests/test_validator.py \
    -v

# 3. 데몬 dry-run (1 tick)
DRY_RUN=1 KIS_ALLOW_LIVE_ORDER=0 \
    venv/bin/python3 morning_report/position_monitor.py --once

# 4. pidfile 정리 확인
ls data/position_monitor.pid 2>/dev/null && echo "WARN: pidfile 잔존"

# 5. 로그 확인
tail -20 logs/trading.log
```

### 예상 로그 (dry-run --once)
```
2026-04-23 10:00:00 INFO position_monitor 기동
2026-04-23 10:00:00 INFO 재시작 복구 시작
2026-04-23 10:00:01 INFO 복구: KIS와 로컬 일치. position_state 유지
2026-04-23 10:00:01 INFO 복구: in_flight 0건 clear
2026-04-23 10:00:01 INFO 재시작 복구 완료
```

---

## 경계 체크 (Brief C 범위 외 기능 금지)

### Brief C에서 **구현하지 말 것**
- ❌ `_execute_buy` / `_execute_sell` 능동 호출 (`kis_client.place_order`)
- ❌ `buy_request.jsonl` / `sell_request.jsonl` consumer
- ❌ 손절/익절/트레일링 exit 결정 로직 (`_evaluate_exit`)
- ❌ 장마감 강제청산
- ❌ 실제 텔레그램 전송 (`telegram_sender.send(...)`)
- ❌ 재권유 상태머신 (`_send_resuggestion`, `count += 1`)
- ❌ launchd plist 배포

위 항목은 모두 로깅/훅까지만 구현하고 실제 동작은 Brief D/E에서 추가한다.

### Brief C에서 **반드시 구현할 것**
- ✅ 단일 writer 강제 (pidfile 락)
- ✅ 적응형 폴링 (5초 / 60초)
- ✅ Balance diff passive detection (BUY/SELL 모두)
- ✅ 재시작 복구 (KIS 권위, in_flight clear, proposals 만료 정리)
- ✅ 자정 리셋 (self-triggered, orderable_cash 스냅샷)
- ✅ 손실한도 감시 → `block_new_orders=True` 플립 + ERROR 로그
- ✅ Proposal 만료 tick (`_tick_expire_proposals`)
- ✅ 14+건 단위 테스트 (KIS mock, tmp_path 격리)

---

## 완료 보고 포맷 (Codex → Claude)

작업 완료 후 다음 형식으로 보고 부탁드립니다:

```
=== Brief C 구현 완료 ===
신규 파일:
  - morning_report/position_monitor.py (XXX줄)
  - tests/test_position_monitor.py (YY테스트)

테스트 결과:
  tests/test_position_monitor.py: N/N PASS
  tests/test_position_state.py: 8/8 PASS (regression)
  tests/test_trading_state.py: 6/6 PASS (regression)
  tests/test_pending_proposals.py: 5/5 PASS (regression)
  tests/test_validator.py: 9/9 PASS (regression)
  합계: XX/XX PASS

dry-run --once 결과:
  - [recover_on_boot OK / FAIL: 사유]
  - [tick OK / FAIL: 사유]

설계 결정 변경사항 (있는 경우):
  - ...
  - ...

알려진 한계:
  - 전량 매도 체결가를 avg_price로 가정 → pnl=0 (Brief C2에서 체결내역 TR 도입 예정)
  - ...
```
