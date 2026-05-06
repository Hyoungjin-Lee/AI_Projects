"""
risk_analyzer.py — 일일 포트폴리오 리스크 분석 (Brief 13-B).
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_STRESS_FILE = _ROOT / "data" / "raw" / "kospi_stress_scenarios.json"
_DEFAULT_SNAPSHOT_FILE = _ROOT / "data" / "risk_snapshot.json"
_STOP_LOSS_THRESHOLD_PCT = -15.0
_MIN_RETURNS = 4


@dataclass
class RiskSnapshot:
    as_of: str = field(default_factory=lambda: date.today().isoformat())
    var_95: float | None = None
    cvar_95: float | None = None
    mdd_60d: float | None = None
    stress_exposures: list[dict[str, Any]] = field(default_factory=list)
    portfolio_value: float = 0.0
    portfolio_status: str = "unknown"
    threshold_pct: float = _STOP_LOSS_THRESHOLD_PCT
    confidence: float = 0.95


def calculate_var(returns: list[float], confidence: float = 0.95) -> float | None:
    clean = _clean_numbers(returns)
    if len(clean) < _MIN_RETURNS:
        return None
    return round(float(np.percentile(clean, (1.0 - confidence) * 100)), 2)


def calculate_cvar(returns: list[float], confidence: float = 0.95) -> float | None:
    var_value = calculate_var(returns, confidence)
    if var_value is None:
        return None
    clean = np.array(_clean_numbers(returns), dtype=float)
    tail = clean[clean <= var_value]
    if len(tail) == 0:
        return var_value
    return round(float(np.mean(tail)), 2)


def calculate_mdd(equity_curve: list[float]) -> float | None:
    clean = _clean_numbers(equity_curve)
    if len(clean) < 2:
        return None
    equity = np.array(clean, dtype=float)
    peaks = np.maximum.accumulate(equity)
    valid = peaks > 0
    if not np.any(valid):
        return None
    drawdowns = np.zeros_like(equity, dtype=float)
    drawdowns[valid] = (equity[valid] - peaks[valid]) / peaks[valid] * 100.0
    return round(float(np.min(drawdowns)), 2)


def load_stress_scenarios(path: str = "data/raw/kospi_stress_scenarios.json") -> list[dict]:
    scenario_path = Path(path)
    if not scenario_path.is_absolute():
        scenario_path = _ROOT / scenario_path
    if not scenario_path.exists():
        return []
    try:
        data = json.loads(scenario_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[리스크] 스트레스 시나리오 로드 실패: {exc}", file=sys.stderr)
        return []
    if isinstance(data, list):
        return [s for s in data if isinstance(s, dict)]
    if isinstance(data, dict) and isinstance(data.get("scenarios"), list):
        return [s for s in data["scenarios"] if isinstance(s, dict)]
    return []


def estimate_stress_exposure(portfolio_value, scenarios) -> list[dict]:
    value = _to_float(portfolio_value)
    exposures = []
    for scenario in scenarios or []:
        kospi_return = _to_float(scenario.get("kospi_return"))
        exposures.append({
            "name": scenario.get("name", "unknown"),
            "year": scenario.get("year"),
            "kospi_return": kospi_return,
            "estimated_loss_pct": round(kospi_return, 2),
            "estimated_loss_value": round(value * kospi_return / 100.0, 0),
            "description": scenario.get("description", ""),
        })
    return exposures


def calculate_risk_snapshot(
    portfolio_history: list[dict],
    confidence: float = 0.95,
    threshold_pct: float = _STOP_LOSS_THRESHOLD_PCT,
) -> RiskSnapshot:
    history = _normalize_history(portfolio_history)[-60:]
    equity = [row["total_value"] for row in history if row.get("total_value", 0) > 0]
    returns = _daily_returns_from_equity(equity)

    portfolio_value = equity[-1] if equity else 0.0
    snapshot = RiskSnapshot(
        as_of=history[-1].get("date", date.today().isoformat()) if history else date.today().isoformat(),
        var_95=calculate_var(returns, confidence),
        cvar_95=calculate_cvar(returns, confidence),
        mdd_60d=calculate_mdd(equity),
        stress_exposures=estimate_stress_exposure(portfolio_value, load_stress_scenarios()),
        portfolio_value=portfolio_value,
        threshold_pct=threshold_pct,
        confidence=confidence,
    )
    snapshot.portfolio_status = _status_from_mdd(snapshot.mdd_60d, threshold_pct)
    return snapshot


def format_risk_section(snapshot: RiskSnapshot) -> str:
    lines = [f"\n📊 리스크 분석 ({snapshot.as_of})"]
    lines.append(f"- VaR({snapshot.confidence:.0%}): {_fmt_pct(snapshot.var_95)} (당일 최대 손실 추정)")
    lines.append(f"- CVaR({snapshot.confidence:.0%}): {_fmt_pct(snapshot.cvar_95)} (꼬리 위험)")
    lines.append(f"- MDD(60일): {_fmt_pct(snapshot.mdd_60d)}")

    if snapshot.stress_exposures:
        worst = min(snapshot.stress_exposures, key=lambda item: item.get("estimated_loss_pct", 0))
        mark = "✅" if worst["estimated_loss_pct"] > snapshot.threshold_pct else "⚠️"
        lines.append(
            f"- 스트레스 노출 ({worst['name']} {worst['kospi_return']:+.0f}%): "
            f"{worst['estimated_loss_pct']:+.1f}% {mark}"
        )

    status_text = {"safe": "안전", "warning": "주의", "critical": "위험", "unknown": "판단불가"}
    current = _fmt_pct(snapshot.mdd_60d)
    lines.append(
        f"- 포트폴리오 손절 임계: {snapshot.threshold_pct:.0f}% "
        f"(현재 {current}, {status_text.get(snapshot.portfolio_status, '판단불가')})"
    )
    return "\n".join(lines)


def save_snapshot(snapshot: RiskSnapshot, path: str = "data/risk_snapshot.json") -> None:
    out_path = Path(path)
    if not out_path.is_absolute():
        out_path = _ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    record = asdict(snapshot)
    record["saved_at"] = datetime.now().isoformat()

    try:
        if out_path.exists():
            data = json.loads(out_path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                data = []
        else:
            data = []
        data = [row for row in data if row.get("as_of") != snapshot.as_of]
        data.append(record)
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"[리스크] snapshot 저장 실패: {exc}", file=sys.stderr)


def _clean_numbers(values) -> list[float]:
    return [num for num in (_to_optional_float(v) for v in values or []) if num is not None]


def _to_optional_float(value) -> float | None:
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return number


def _to_float(value, default: float = 0.0) -> float:
    number = _to_optional_float(value)
    return default if number is None else number


def _normalize_history(portfolio_history: list[dict]) -> list[dict]:
    rows = []
    for row in portfolio_history or []:
        if not isinstance(row, dict):
            continue
        total_value = _to_float(row.get("total_value", row.get("net_asset", 0)))
        if total_value <= 0:
            continue
        rows.append({"date": str(row.get("date") or ""), "total_value": total_value})
    return sorted(rows, key=lambda row: row["date"])


def _daily_returns_from_equity(equity: list[float]) -> list[float]:
    returns = []
    for previous, current in zip(equity, equity[1:]):
        if previous > 0:
            returns.append(round((current - previous) / previous * 100.0, 4))
    return returns


def _status_from_mdd(mdd: float | None, threshold_pct: float) -> str:
    if mdd is None:
        return "unknown"
    if mdd <= threshold_pct:
        return "critical"
    if mdd <= threshold_pct * 0.8:
        return "warning"
    return "safe"


def _fmt_pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value:+.1f}%"
