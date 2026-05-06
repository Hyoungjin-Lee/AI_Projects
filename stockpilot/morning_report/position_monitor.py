"""position_monitor.py - Phase 2 단일 writer 데몬."""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
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


_SKILLS_ROOT = Path(__file__).parent.parent / ".skills" / "kis-api" / "scripts"
if str(_SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILLS_ROOT))
from kis_client import KISClient, KISConfigError  # noqa: E402


_ROOT = Path(__file__).parent.parent
_CONFIG_FILE = _ROOT / "data" / "strategy_config.json"
_PIDFILE = _ROOT / "data" / "position_monitor.pid"
_LOG_FILE = _ROOT / "logs" / "trading.log"

_TICK_MARKET = 5.0
_TICK_IDLE = 60.0
_MAX_CONSECUTIVE_FAILURES = 30
_SELL_COOLDOWN_SECONDS = 300
_FORCED_LIQUIDATION_EXPIRE_SECONDS = 180


@dataclass
class MonitorConfig:
    """strategy_config.json 기반 데몬 설정."""

    sell_cooldown_seconds: int = _SELL_COOLDOWN_SECONDS
    max_consecutive_failures: int = _MAX_CONSECUTIVE_FAILURES
    tick_market: float = _TICK_MARKET
    tick_idle: float = _TICK_IDLE
    proposal_expire_seconds: int = _FORCED_LIQUIDATION_EXPIRE_SECONDS

    @classmethod
    def load(cls, path: Path = _CONFIG_FILE) -> "MonitorConfig":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return cls()
        trading = raw.get("trading") or {}
        return cls(
            sell_cooldown_seconds=int(
                trading.get("sell_cooldown_seconds", _SELL_COOLDOWN_SECONDS)
            ),
            max_consecutive_failures=int(
                trading.get(
                    "monitor_max_consecutive_failures", _MAX_CONSECUTIVE_FAILURES
                )
            ),
            tick_market=float(
                trading.get("monitor_tick_market_seconds", _TICK_MARKET)
            ),
            tick_idle=float(trading.get("monitor_tick_idle_seconds", _TICK_IDLE)),
            proposal_expire_seconds=int(
                trading.get(
                    "proposal_expire_seconds",
                    _FORCED_LIQUIDATION_EXPIRE_SECONDS,
                )
            ),
        )


@dataclass
class TickerBalance:
    code: str
    name: str
    qty: int
    avg_price: float
    current_price: float


@dataclass
class BalanceSnapshot:
    fetched_at: datetime
    holdings: dict[str, TickerBalance] = field(default_factory=dict)


class PositionMonitor:
    """Phase 2 데몬 본체."""

    def __init__(
        self,
        *,
        kis_client: KISClient | None = None,
        position_store: PositionStateStore | None = None,
        trading_store: TradingStateStore | None = None,
        proposals_store: PendingProposalsStore | None = None,
        config: MonitorConfig | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config or MonitorConfig.load()
        self.kis = kis_client or KISClient(mode="trading")
        self.positions = position_store or PositionStateStore()
        self.trading = trading_store or TradingStateStore()
        self.proposals = proposals_store or PendingProposalsStore()
        self.logger = logger or _setup_logger()
        self._consecutive_failures = 0
        self._running = False
        self._last_known_date: date | None = None

    def run(self) -> None:
        self._running = True
        for signum in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(signum, self._handle_shutdown)
            except ValueError:
                # 테스트나 비메인 스레드에서는 signal 등록이 불가할 수 있다.
                pass

        self.logger.info("position_monitor 기동")
        self.recover_on_boot()

        while self._running:
            now = datetime.now()
            try:
                self.tick(now)
                self._consecutive_failures = 0
            except Exception as exc:  # pragma: no cover - 예외 경로는 부분 검증만 수행
                self._consecutive_failures += 1
                self.logger.exception(
                    "tick 실패 (%d/%d): %s",
                    self._consecutive_failures,
                    self.config.max_consecutive_failures,
                    exc,
                )
                if self._consecutive_failures >= self.config.max_consecutive_failures:
                    self.logger.error("연속 실패 한도 초과. 10분 휴면.")
                    self._sleep(600)
                    self._consecutive_failures = 0

            interval = (
                self.config.tick_market if is_market_open(now) else self.config.tick_idle
            )
            self._sleep(interval)

        self.logger.info("position_monitor 종료")

    def _handle_shutdown(self, signum: int, frame: Any) -> None:  # noqa: ARG002
        self._running = False

    def _sleep(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while self._running and time.monotonic() < end:
            remaining = end - time.monotonic()
            time.sleep(min(1.0, max(0.0, remaining)))

    def tick(self, now: datetime) -> None:
        self._check_midnight_reset(now)
        self._tick_expire_proposals(now)
        if not is_market_open(now):
            return
        snapshot = self._fetch_kis_snapshot()
        self._diff_and_apply(snapshot, now)
        self._check_loss_limit(now)

    def _fetch_kis_snapshot(self) -> BalanceSnapshot:
        raw = self.kis.get_balance()
        fetched = datetime.now()
        holdings: dict[str, TickerBalance] = {}

        for item in raw.get("output1", []):
            code = str(item.get("pdno") or "").strip()
            qty = _to_int(item.get("hldg_qty"))
            if not code or qty <= 0:
                continue
            holdings[code] = TickerBalance(
                code=code,
                name=str(item.get("prdt_name") or "").strip(),
                qty=qty,
                avg_price=_to_float(item.get("pchs_avg_pric")),
                current_price=_to_float(item.get("prpr")),
            )
        return BalanceSnapshot(fetched_at=fetched, holdings=holdings)

    def _diff_and_apply(self, snapshot: BalanceSnapshot, now: datetime) -> None:  # noqa: ARG002
        changes = False
        local_codes = set(self.positions.holdings.keys())
        remote_codes = set(snapshot.holdings.keys())

        for code in remote_codes:
            remote = snapshot.holdings[code]
            local = self.positions.get(code)

            if local is None:
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
                self.logger.info(
                    "BUY 감지 (신규): %s %d주 @%.0f",
                    code,
                    remote.qty,
                    remote.avg_price,
                )
                changes = True
                continue

            if remote.qty > local.qty:
                added_qty = remote.qty - local.qty
                try:
                    fill_price = (
                        (remote.avg_price * remote.qty)
                        - (local.avg_price * local.qty)
                    ) / added_qty
                except ZeroDivisionError:
                    fill_price = remote.avg_price
                if fill_price <= 0:
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
                    next_stage,
                    code,
                    added_qty,
                    fill_price,
                )
                changes = True
                continue

            if remote.qty < local.qty:
                sold_qty = local.qty - remote.qty
                fill_price = remote.current_price or local.avg_price
                pnl = self.positions.apply_sell(code, sold_qty, fill_price)
                self.trading.inc_sell()
                self.trading.add_realized_pnl(pnl)
                self.trading.clear_in_flight(code)
                self.trading.set_cooldown(
                    code,
                    snapshot.fetched_at
                    + timedelta(seconds=self.config.sell_cooldown_seconds),
                )
                self.logger.info(
                    "SELL 감지 (부분): %s -%d주 @%.0f (실현%+d원)",
                    code,
                    sold_qty,
                    fill_price,
                    pnl,
                )
                changes = True

        for code in local_codes - remote_codes:
            local = self.positions.get(code)
            if local is None:
                continue
            local_qty = local.qty
            fill_price = local.avg_price
            pnl = self.positions.apply_sell(code, local_qty, fill_price)
            self.trading.inc_sell()
            self.trading.add_realized_pnl(pnl)
            self.trading.clear_in_flight(code)
            self.trading.set_cooldown(
                code,
                snapshot.fetched_at + timedelta(seconds=self.config.sell_cooldown_seconds),
            )
            self.logger.warning(
                "SELL 감지 (전량, 체결가 avg_price 추정): %s -%d주 @%.0f",
                code,
                local_qty,
                fill_price,
            )
            changes = True

        for code, remote in snapshot.holdings.items():
            position = self.positions.get(code)
            if position is None or remote.current_price <= 0:
                continue
            before_peak = position.peak_price_since_entry
            self.positions.update_peak(code, remote.current_price)
            if position.peak_price_since_entry != before_peak:
                changes = True

        if changes:
            self.positions.persist()
            self.trading.persist()

    def recover_on_boot(self) -> None:
        self.logger.info("재시작 복구 시작")
        try:
            snapshot = self._fetch_kis_snapshot()
        except Exception as exc:
            self.logger.error("복구: KIS 잔고조회 실패, 로컬 state 유지: %s", exc)
            cutoff = datetime.now() - timedelta(
                seconds=self.config.proposal_expire_seconds
            )
            self.proposals.cleanup_expired_on_boot(cutoff)
            self.proposals.persist()
            return

        divergent: list[str] = []
        for code, remote in snapshot.holdings.items():
            local = self.positions.get(code)
            if local is None:
                divergent.append(code)
                continue
            if local.qty != remote.qty or abs(local.avg_price - remote.avg_price) > 0.5:
                divergent.append(code)

        local_only = sorted(set(self.positions.holdings.keys()) - set(snapshot.holdings.keys()))
        divergent.extend(local_only)

        if divergent:
            self.logger.warning(
                "복구: KIS 불일치 %d종목 — KIS 기준 덮어쓰기: %s",
                len(divergent),
                divergent,
            )
            self._rebuild_positions_from_kis(snapshot)
        else:
            self.logger.info("복구: KIS와 로컬 일치. position_state 유지")

        in_flight_codes = list(self.trading.data.in_flight_orders.keys())
        for code in in_flight_codes:
            self.trading.clear_in_flight(code)
        if in_flight_codes:
            self.logger.info(
                "복구: in_flight %d건 clear (%s)",
                len(in_flight_codes),
                in_flight_codes,
            )

        now = datetime.now()
        self.trading._cleanup_expired_cooldowns(now)

        cutoff = now - timedelta(seconds=self.config.proposal_expire_seconds)
        expired_props = self.proposals.cleanup_expired_on_boot(cutoff)
        if expired_props:
            self.logger.info("복구: 만료 proposal %d건 정리", len(expired_props))

        self.positions.persist()
        self.trading.persist()
        self.proposals.persist()
        self.logger.info("재시작 복구 완료")

    def _rebuild_positions_from_kis(self, snapshot: BalanceSnapshot) -> None:
        self.positions.holdings.clear()
        for code, remote in snapshot.holdings.items():
            self.positions.apply_buy(
                code=code,
                name=remote.name,
                qty=remote.qty,
                price=remote.avg_price,
                stage=1,
                at=snapshot.fetched_at,
            )
            position = self.positions.get(code)
            if position is None:
                continue
            position.peak_price_since_entry = remote.current_price or remote.avg_price
            position.trailing_active = False

    def _check_midnight_reset(self, now: datetime) -> None:
        today = now.date()
        last_reset = _parse_date(self.trading.data.last_reset_date)
        if last_reset == today:
            self._last_known_date = today
            return

        try:
            orderable_cash = self._fetch_orderable_cash()
        except Exception as exc:
            self.logger.error("자정 리셋: orderable_cash 조회 실패, 리셋 연기: %s", exc)
            return

        self.trading.reset_daily(today=today, new_orderable_cash=orderable_cash)
        self.trading.persist()
        self._last_known_date = today
        self.logger.info(
            "자정 리셋 완료. 일일 손실한도=%d원 (trial=%s)",
            orderable_cash,
            self.trading.data.trial_mode,
        )

    def _fetch_orderable_cash(self) -> int:
        raw = self.kis.get_orderable_cash()
        if isinstance(raw, dict):
            output = raw.get("output") or {}
            return int(
                output.get("ord_psbl_cash")
                or output.get("nrcvb_buy_amt")
                or output.get("stck_itgr_cash100_ord_psbl_amt")
                or output.get("stck_cash_ord_psbl_amt")
                or 0
            )
        return int(raw or 0)

    def _check_loss_limit(self, now: datetime) -> None:  # noqa: ARG002
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

    def _tick_expire_proposals(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.config.proposal_expire_seconds)
        expired = self.proposals.cleanup_expired_on_boot(cutoff)
        if not expired:
            return
        self.proposals.persist()
        for proposal in expired:
            self.logger.info("proposal 만료: %s (%s)", proposal.id, proposal.code)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _to_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _acquire_lock() -> bool:
    if _PIDFILE.exists():
        try:
            old_pid = int(_PIDFILE.read_text(encoding="utf-8").strip())
            os.kill(old_pid, 0)
            return False
        except (OSError, ValueError):
            try:
                _PIDFILE.unlink()
            except OSError:
                pass
    _PIDFILE.parent.mkdir(parents=True, exist_ok=True)
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
    has_file_handler = any(
        isinstance(handler, logging.FileHandler)
        and Path(getattr(handler, "baseFilename", "")) == _LOG_FILE
        for handler in logger.handlers
    )
    if not has_file_handler:
        handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
    return logger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 2 position monitor daemon")
    parser.add_argument("--once", action="store_true", help="단일 tick 실행 후 종료")
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
    except KISConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        _release_lock()


if __name__ == "__main__":
    sys.exit(main())
