"""
pattern_lifecycle.py - Track follow-up closes for discovered stocks.

Usage:
  venv/bin/python3 morning_report/pattern_lifecycle.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / ".skills" / "kis-api" / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))

from keychain_manager import inject_to_env

_INJECT_ERROR: Exception | None = None
try:
    inject_to_env()
except Exception as exc:
    _INJECT_ERROR = exc
from kis_client import KISClient

_LOG_FILE = _ROOT / "data" / "discovery_log.json"
_OUTCOMES = {"true_positive", "false_positive", "neutral", "pending"}


def _previous_trading_day(d: date, n: int = 1) -> date:
    """Return the previous n-th trading day, skipping weekends only."""
    cur = d
    for _ in range(n):
        cur -= timedelta(days=1)
        while cur.weekday() >= 5:
            cur -= timedelta(days=1)
    return cur


def _next_trading_day(d: date, n: int = 1) -> date:
    """Return the next n-th trading day, skipping weekends only."""
    cur = d
    for _ in range(n):
        cur += timedelta(days=1)
        while cur.weekday() >= 5:
            cur += timedelta(days=1)
    return cur


def _judge_outcome(return_pct: float | int | None) -> str:
    """Classify a return percentage into the lifecycle outcome enum."""
    if return_pct is None:
        return "pending"
    try:
        pct = float(return_pct)
    except (TypeError, ValueError):
        return "pending"
    if pct > 3.0:
        return "true_positive"
    if pct < -1.0:
        return "false_positive"
    return "neutral"


def _parse_log_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _normalize_date_str(value: str | date) -> str:
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    text = str(value).strip()
    if "-" in text:
        try:
            return date.fromisoformat(text).strftime("%Y%m%d")
        except ValueError:
            return text.replace("-", "")
    return text


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _return_pct(base_price: Any, future_close: Any) -> float | None:
    base = _safe_float(base_price)
    close = _safe_float(future_close)
    if base is None or close is None or base <= 0:
        return None
    return round((close - base) / base * 100.0, 2)


def _fetch_close_price(ticker: str, date_str: str, kis_client: KISClient) -> float | None:
    """Fetch a ticker close price for a specific YYYY-MM-DD or YYYYMMDD date."""
    target_yyyymmdd = _normalize_date_str(date_str)
    try:
        target_date = datetime.strptime(target_yyyymmdd, "%Y%m%d").date()
    except ValueError:
        print(f"[lifecycle] invalid target date: {date_str}", file=sys.stderr)
        return None

    if target_date > date.today():
        return None

    days = min(max((date.today() - target_date).days + 10, 5), 100)
    try:
        rows = kis_client.get_daily_chart(str(ticker), days=days)
    except Exception as exc:
        print(f"[lifecycle] {ticker} {target_yyyymmdd} close fetch failed: {exc}", file=sys.stderr)
        return None

    if not isinstance(rows, list):
        return None

    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("stck_bsop_date", "")).strip() != target_yyyymmdd:
            continue
        close = _safe_float(row.get("stck_clpr"))
        return close if close and close > 0 else None
    return None


def _ensure_lifecycle_keys(entry: dict[str, Any]) -> None:
    entry.setdefault("lifecycle_24h_close", None)
    entry.setdefault("lifecycle_72h_close", None)
    entry.setdefault("outcome_24h", None)
    entry.setdefault("outcome_72h", None)
    entry.setdefault("lifecycle_updated_at", None)


def _set_outcome_if_open(entry: dict[str, Any], key: str, outcome: str) -> None:
    if entry.get(key) in (None, "pending"):
        entry[key] = outcome


def _process_entry(entry: dict[str, Any], kis_client: KISClient, today: date) -> tuple[int, int, bool]:
    disc_date = _parse_log_date(entry.get("date"))
    ticker = entry.get("code")
    if disc_date is None or not ticker:
        return 0, 0, False

    updated_24h = 0
    updated_72h = 0
    touched = False
    base_price = entry.get("close_price")

    if entry.get("lifecycle_24h_close") is None:
        target_24h = _next_trading_day(disc_date, n=1)
        if target_24h <= today:
            close_24h = _fetch_close_price(str(ticker), target_24h.isoformat(), kis_client)
            if close_24h is not None:
                entry["lifecycle_24h_close"] = close_24h
                _set_outcome_if_open(entry, "outcome_24h", _judge_outcome(_return_pct(base_price, close_24h)))
                updated_24h = 1
                touched = True
            elif entry.get("outcome_24h") is None:
                entry["outcome_24h"] = "pending"
                touched = True

    if entry.get("lifecycle_72h_close") is None:
        target_72h = _next_trading_day(disc_date, n=3)
        if target_72h <= today:
            close_72h = _fetch_close_price(str(ticker), target_72h.isoformat(), kis_client)
            if close_72h is not None:
                entry["lifecycle_72h_close"] = close_72h
                _set_outcome_if_open(entry, "outcome_72h", _judge_outcome(_return_pct(base_price, close_72h)))
                updated_72h = 1
                touched = True
            elif entry.get("outcome_72h") is None:
                entry["outcome_72h"] = "pending"
                touched = True

    if touched:
        entry["lifecycle_updated_at"] = datetime.now().isoformat(timespec="seconds")
    return updated_24h, updated_72h, touched


def _make_kis_client() -> KISClient:
    if _INJECT_ERROR is not None:
        try:
            inject_to_env()
        except Exception as exc:
            print(f"[lifecycle] keychain inject failed: {exc}", file=sys.stderr)
    return KISClient()


def _count_dry_run_candidates(entries: list[dict[str, Any]], today: date) -> tuple[int, int]:
    count_24h = 0
    count_72h = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        disc_date = _parse_log_date(entry.get("date"))
        if disc_date is None or not entry.get("code"):
            continue
        if entry.get("lifecycle_24h_close") is None and _next_trading_day(disc_date, n=1) <= today:
            count_24h += 1
        if entry.get("lifecycle_72h_close") is None and _next_trading_day(disc_date, n=3) <= today:
            count_72h += 1
    return count_24h, count_72h


def update_lifecycle(log_path: str | Path = _LOG_FILE, dry_run: bool = False) -> int:
    """Update discovery_log.json lifecycle fields without touching intraday fields."""
    path = Path(log_path)
    if not path.exists():
        print(f"[lifecycle] log not found: {path}", file=sys.stderr)
        return 1

    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[lifecycle] discovery log load failed: {exc}", file=sys.stderr)
        return 1

    if not isinstance(entries, list):
        print("[lifecycle] discovery log must be a JSON list", file=sys.stderr)
        return 1

    work_entries = deepcopy(entries) if dry_run else entries
    for entry in work_entries:
        if isinstance(entry, dict):
            _ensure_lifecycle_keys(entry)

    if dry_run:
        updated_24h, updated_72h = _count_dry_run_candidates(work_entries, date.today())
        total_updates = updated_24h + updated_72h
        print(
            f"[dry-run] {total_updates} 건 업데이트 가능 "
            f"(+24h {updated_24h}건 / +72h {updated_72h}건)",
            file=sys.stderr,
        )
        _print_statistics(work_entries)
        return 0

    try:
        kis_client = _make_kis_client()
    except Exception as exc:
        print(f"[lifecycle] KIS client init failed: {exc}", file=sys.stderr)
        return 1

    updated_24h = 0
    updated_72h = 0
    touched_count = 0
    today = date.today()

    for entry in work_entries:
        if not isinstance(entry, dict):
            continue
        before_close = entry.get("close_price")
        before_return = entry.get("return_pct")
        try:
            count_24h, count_72h, touched = _process_entry(entry, kis_client, today)
        except Exception as exc:
            print(f"[lifecycle] record failed ({entry.get('code', '?')}): {exc}", file=sys.stderr)
            continue
        entry["close_price"] = before_close
        entry["return_pct"] = before_return
        updated_24h += count_24h
        updated_72h += count_72h
        touched_count += int(touched)

    total_updates = updated_24h + updated_72h
    if touched_count:
        path.write_text(json.dumps(work_entries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"[lifecycle] 업데이트 완료: {total_updates}건 "
        f"(+24h {updated_24h}건 / +72h {updated_72h}건)",
        file=sys.stderr,
    )
    _print_statistics(work_entries)
    return 0


def _score_band(score: Any) -> str:
    value = _safe_float(score)
    if value is None:
        return "unknown"
    if value >= 5:
        return "5+"
    if value >= 4:
        return "4"
    return "<4"


def _print_group_stats(title: str, groups: dict[str, dict[str, int]]) -> None:
    print(f"\n  {title}", file=sys.stderr)
    for name in sorted(groups):
        stats = groups[name]
        total = stats["total"]
        tp = stats["true_positive"]
        fp = stats["false_positive"]
        win_rate = (tp / total * 100.0) if total else 0.0
        print(
            f"    {name}: {total}건 / 승률 {win_rate:.1f}% "
            f"(TP {tp}, FP {fp})",
            file=sys.stderr,
        )


def _print_statistics(entries: list[dict[str, Any]]) -> None:
    """Print 24h win-rate statistics by discovery hour and score band."""
    completed = [
        row for row in entries
        if isinstance(row, dict) and row.get("outcome_24h") in _OUTCOMES - {"pending"}
    ]
    if not completed:
        print("[lifecycle] 통계: 완료 표본 0건", file=sys.stderr)
        return

    total = len(completed)
    tp = sum(1 for row in completed if row.get("outcome_24h") == "true_positive")
    fp = sum(1 for row in completed if row.get("outcome_24h") == "false_positive")
    neutral = sum(1 for row in completed if row.get("outcome_24h") == "neutral")
    print(
        f"[lifecycle 통계] +24h 표본 {total}건: "
        f"TP {tp}건, FP {fp}건, neutral {neutral}건, 승률 {tp / total * 100.0:.1f}%",
        file=sys.stderr,
    )

    by_hour: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "true_positive": 0, "false_positive": 0}
    )
    by_score: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "true_positive": 0, "false_positive": 0}
    )

    for row in completed:
        outcome = row.get("outcome_24h")
        disc_time = str(row.get("disc_time", "unknown"))
        hour = disc_time.split(":", 1)[0] if ":" in disc_time else "unknown"
        score_band = _score_band(row.get("score"))

        for groups, key in ((by_hour, hour), (by_score, score_band)):
            groups[key]["total"] += 1
            if outcome == "true_positive":
                groups[key]["true_positive"] += 1
            elif outcome == "false_positive":
                groups[key]["false_positive"] += 1

    _print_group_stats("시간대별 승률 (+24h)", by_hour)
    _print_group_stats("점수 구간별 승률 (+24h)", by_score)


def main() -> int:
    parser = argparse.ArgumentParser(description="Track discovery lifecycle outcomes.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write discovery_log.json")
    parser.add_argument("--force", action="store_true", help="Run even on holidays/weekends")
    parser.add_argument(
        "--log-path",
        default=str(_LOG_FILE),
        help="Path to discovery_log.json",
    )
    args = parser.parse_args()

    # 휴장일(주말+한국 공휴일) 가드 — --force / --dry-run 우회 가능
    if not args.force and not args.dry_run:
        from market_calendar import exit_if_holiday  # sys.path는 line 20에서 이미 설정됨
        exit_if_holiday("pattern_lifecycle")

    return update_lifecycle(args.log_path, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
