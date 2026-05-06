# Codex Brief 13-B — B3 risk_analyzer.py + closing_report 통합

> **입력 문서:** `docs/13_briefing_enhancement/04_plan_final.md` §3 + Pattern Integration `04_plan_final.md` R19
> **담당자:** Codex
> **작업 범위:** 신규 risk_analyzer.py + closing_report.py 섹션 통합 + strategy_config.json risk_analysis 섹션 + KOSPI 스트레스 시나리오 데이터

---

## 0. 작업 개요

`closing_report.py` 텔레그램 메시지에 **일일 포트폴리오 리스크 분석** 섹션 추가:

- VaR(95%) — 직전 60일 일별 수익률 5% percentile
- CVaR(95%) — VaR 초과 손실 평균
- MDD(60일) — 직전 60거래일 peak-to-trough
- KOSPI 5종 스트레스 시나리오 노출 추정
- 포트폴리오 손절 임계 -15%

**예시 출력:**
```
📊 리스크 분석 (2026-05-06)
- VaR(95%): -2.3% (당일 95% 확률 최대 손실)
- CVaR(95%): -3.1% (꼬리 위험)
- MDD(60일): -8.7%
- 스트레스 노출 (코로나급 -34%): -12.1% ✅
- 포트폴리오 손절 임계: -15% (현재 -8.7%, 안전)
```

---

## 1. 공통 원칙

1. **신규 모듈만** — 기존 closing_report 로직은 변경 최소화 (섹션 추가만)
2. **enabled=false 기본** — strategy_config 에서 명시적 활성화해야 동작
3. **외부 의존성:** numpy (이미 venv에 있음 가정 — 확인 필요)
4. **데이터 소스:** state_manager 의 보유 종목 + 일별 자산 기록 + KIS 일봉
5. **하위 호환성** — closing_report 기존 섹션/메시지 형식 유지

---

## 2. 신규 파일 1: `morning_report/risk_analyzer.py`

### 2.1 시그니처

```python
"""
risk_analyzer.py — 일일 포트폴리오 리스크 분석 (B3)

산출물:
  - VaR(95%) / CVaR(95%) / MDD(60일)
  - KOSPI 5종 스트레스 시나리오 노출 추정
  - 포트폴리오 손절 임계 비교

사용 패턴:
  from risk_analyzer import calculate_risk_snapshot
  snapshot = calculate_risk_snapshot(holdings, daily_returns_60d)
  # snapshot: {"var_95": -2.3, "cvar_95": -3.1, "mdd_60d": -8.7,
  #            "stress": {"kospi_2020_covid": -12.1, ...},
  #            "portfolio_status": "safe"|"warning"|"critical"}
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

_ROOT = Path(__file__).parent.parent
_STRESS_FILE = _ROOT / "data" / "raw" / "kospi_stress_scenarios.json"


@dataclass
class RiskSnapshot:
    var_95: float | None = None        # 일별 VaR (%, 음수)
    cvar_95: float | None = None       # 일별 CVaR (%, 음수)
    mdd_60d: float | None = None       # 60일 MDD (%, 음수)
    stress: dict[str, float] = field(default_factory=dict)  # 시나리오별 손실 추정
    portfolio_status: str = "unknown"  # safe / warning / critical / unknown
    threshold_pct: float = -15.0       # 임계
    

def calculate_var(daily_returns: list[float], confidence: float = 0.95) -> float | None:
    """일별 VaR (역사적 방법) — 직전 60일 중 (1-confidence) percentile."""
    if not daily_returns or len(daily_returns) < 10:
        return None
    arr = np.array([r for r in daily_returns if r is not None])
    if len(arr) < 10:
        return None
    return float(np.percentile(arr, (1 - confidence) * 100))


def calculate_cvar(daily_returns: list[float], confidence: float = 0.95) -> float | None:
    """CVaR — VaR 이하 수익률의 평균."""
    var = calculate_var(daily_returns, confidence)
    if var is None:
        return None
    arr = np.array([r for r in daily_returns if r is not None])
    tail = arr[arr <= var]
    if len(tail) == 0:
        return var
    return float(np.mean(tail))


def calculate_mdd(equity: list[float]) -> float | None:
    """Max Drawdown — peak-to-trough 최대 낙폭 (%, 음수)."""
    if not equity or len(equity) < 2:
        return None
    arr = np.array(equity)
    peak = np.maximum.accumulate(arr)
    dd = (arr - peak) / peak * 100
    return float(np.min(dd))


def load_stress_scenarios() -> dict[str, dict]:
    """data/raw/kospi_stress_scenarios.json 로드. 파일 부재 시 빈 dict."""
    if not _STRESS_FILE.exists():
        return {}
    try:
        return json.loads(_STRESS_FILE.read_text(encoding="utf-8")).get("scenarios", {})
    except Exception as e:
        print(f"[리스크] 스트레스 시나리오 로드 실패: {e}", file=sys.stderr)
        return {}


def estimate_stress_exposure(
    portfolio_value: float,
    scenario_kospi_drop_pct: float,
    portfolio_beta: float = 1.0,
) -> float:
    """
    KOSPI 시나리오 발생 시 포트폴리오 손실률 추정.
    portfolio_beta 미지정 시 1.0 (KOSPI 동행 가정 — Phase A 단순화)
    반환: 예상 손실률 (%, 음수)
    """
    return scenario_kospi_drop_pct * portfolio_beta


def calculate_risk_snapshot(
    daily_returns_60d: list[float],
    portfolio_equity_60d: list[float],
    threshold_pct: float = -15.0,
) -> RiskSnapshot:
    """
    핵심 함수 — 일일 리스크 스냅샷 생성.

    Parameters
    ----------
    daily_returns_60d : list[float]
        직전 60거래일의 일별 수익률 (%, 양수=수익)
    portfolio_equity_60d : list[float]
        직전 60거래일의 포트폴리오 평가금액 (peak-to-trough 계산용)
    threshold_pct : float
        포트폴리오 손절 임계 (%, 음수, 기본 -15)
    """
    snapshot = RiskSnapshot(threshold_pct=threshold_pct)
    snapshot.var_95 = calculate_var(daily_returns_60d, 0.95)
    snapshot.cvar_95 = calculate_cvar(daily_returns_60d, 0.95)
    snapshot.mdd_60d = calculate_mdd(portfolio_equity_60d)

    # 스트레스 시나리오
    scenarios = load_stress_scenarios()
    for key, info in scenarios.items():
        kospi_drop = info.get("kospi_drop_pct", 0)
        snapshot.stress[key] = estimate_stress_exposure(
            portfolio_value=1.0,
            scenario_kospi_drop_pct=kospi_drop,
            portfolio_beta=1.0,
        )

    # 상태 판정
    if snapshot.mdd_60d is None:
        snapshot.portfolio_status = "unknown"
    elif snapshot.mdd_60d <= threshold_pct:
        snapshot.portfolio_status = "critical"
    elif snapshot.mdd_60d <= threshold_pct * 0.8:  # 임계의 80% 도달
        snapshot.portfolio_status = "warning"
    else:
        snapshot.portfolio_status = "safe"

    return snapshot


def format_risk_section(snapshot: RiskSnapshot, today_str: str) -> list[str]:
    """텔레그램 메시지 섹션 생성. closing_report 에서 호출."""
    lines = [f"\n📊 리스크 분석 ({today_str})"]

    if snapshot.var_95 is not None:
        lines.append(f"  VaR(95%): {snapshot.var_95:+.1f}% (당일 95% 확률 최대 손실)")
    if snapshot.cvar_95 is not None:
        lines.append(f"  CVaR(95%): {snapshot.cvar_95:+.1f}% (꼬리 위험)")
    if snapshot.mdd_60d is not None:
        lines.append(f"  MDD(60일): {snapshot.mdd_60d:+.1f}%")

    # 스트레스 시나리오 — 가장 가혹한 1개만 표시 (메시지 간결)
    if snapshot.stress:
        worst_key = min(snapshot.stress, key=lambda k: snapshot.stress[k])
        scenarios = load_stress_scenarios()
        worst_label = scenarios.get(worst_key, {}).get("label", worst_key)
        worst_pct = snapshot.stress[worst_key]
        emoji = "✅" if worst_pct > snapshot.threshold_pct else "⚠️"
        lines.append(f"  스트레스 노출 ({worst_label} 시): {worst_pct:+.1f}% {emoji}")

    # 포트폴리오 임계
    status_emoji = {"safe": "🟢", "warning": "🟡", "critical": "🔴", "unknown": "⚪"}[snapshot.portfolio_status]
    if snapshot.mdd_60d is not None:
        lines.append(
            f"  포트폴리오 손절 임계: {snapshot.threshold_pct:.0f}% "
            f"(현재 {snapshot.mdd_60d:+.1f}%, {status_emoji} {snapshot.portfolio_status})"
        )
    return lines


def save_snapshot(snapshot: RiskSnapshot, today_str: str) -> None:
    """data/risk_snapshot.json 일별 기록 (append)."""
    out_file = _ROOT / "data" / "risk_snapshot.json"
    record = {
        "date": today_str,
        "var_95": snapshot.var_95,
        "cvar_95": snapshot.cvar_95,
        "mdd_60d": snapshot.mdd_60d,
        "stress": snapshot.stress,
        "portfolio_status": snapshot.portfolio_status,
        "threshold_pct": snapshot.threshold_pct,
        "saved_at": datetime.now().isoformat(),
    }
    try:
        if out_file.exists():
            data = json.loads(out_file.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                data = []
        else:
            data = []
        # 같은 날짜 레코드 있으면 갱신, 없으면 append
        data = [r for r in data if r.get("date") != today_str]
        data.append(record)
        out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[리스크] snapshot 저장 실패 (무시): {e}", file=sys.stderr)
```

---

## 3. 신규 파일 2: `data/raw/kospi_stress_scenarios.json`

```json
{
  "_comment": "KOSPI 일봉 기준 역사적 폭락 시나리오 (Vibe-Trading 차용 + 한국 시장 보정)",
  "_source": "KOSPI 일봉 데이터 검증 후 재보정 권장",
  "_updated": "2026-05-06",
  "scenarios": {
    "kospi_2008_crisis": {
      "label": "2008 글로벌 금융위기",
      "period": "2008-05-01 ~ 2008-10-24",
      "kospi_drop_pct": -54.0,
      "duration_days": 176
    },
    "kospi_2011_eu_crisis": {
      "label": "2011 유럽 재정위기",
      "period": "2011-08-01 ~ 2011-09-26",
      "kospi_drop_pct": -22.0,
      "duration_days": 56
    },
    "kospi_2018_trade_war": {
      "label": "2018 미중 무역전쟁",
      "period": "2018-01-29 ~ 2018-10-29",
      "kospi_drop_pct": -25.0,
      "duration_days": 273
    },
    "kospi_2020_covid": {
      "label": "2020 코로나 쇼크",
      "period": "2020-02-17 ~ 2020-03-19",
      "kospi_drop_pct": -34.0,
      "duration_days": 31
    },
    "kospi_2022_rate_hike": {
      "label": "2022 미 연준 금리인상",
      "period": "2022-01-01 ~ 2022-09-30",
      "kospi_drop_pct": -25.0,
      "duration_days": 272
    }
  }
}
```

**선택적 검증:** Codex가 yfinance ^KS11 으로 위 5종 기간 실 데이터 fetch → 오차 ±2% 이내 확인 후 보정 (없으면 위 수치 그대로 사용 OK).

---

## 4. closing_report.py 통합

### 4.1 import 추가

```python
# closing_report.py 상단 import 영역에 추가
try:
    from risk_analyzer import calculate_risk_snapshot, format_risk_section, save_snapshot
    _RISK_AVAILABLE = True
except ImportError:
    _RISK_AVAILABLE = False
```

### 4.2 강력 통합 — 일별 수익률 시계열 확보

closing_report 내부에 보유 종목 + 일별 자산 60일치 시계열이 이미 있는지 확인. 없으면 신규 헬퍼 작성:

```python
def _load_portfolio_history_60d() -> tuple[list[float], list[float]]:
    """
    state_manager 또는 risk_snapshot.json 등에서 60일 시계열 로드.

    반환: (daily_returns_60d, portfolio_equity_60d)
    각각 60개 (또는 가용한 만큼). 부족하면 짧은 시계열로 그대로 진행.
    """
    # TODO: state_manager 의 financials.net_asset 일별 기록 활용
    # 현재 state 가 1일치만 보존한다면, 별도 history 파일 필요 (data/portfolio_history.json)
    # 60일 시계열이 없으면 빈 list 반환 → calculate_risk_snapshot 이 None 반환
    history_file = _ROOT / "data" / "portfolio_history.json"
    if not history_file.exists():
        return [], []
    try:
        data = json.loads(history_file.read_text(encoding="utf-8"))
        equity = [r["net_asset"] for r in data[-60:] if r.get("net_asset")]
        if len(equity) < 2:
            return [], equity
        returns = [
            (equity[i] - equity[i-1]) / equity[i-1] * 100
            for i in range(1, len(equity))
            if equity[i-1]
        ]
        return returns, equity
    except Exception as e:
        print(f"[리스크] portfolio_history 로드 실패: {e}", file=sys.stderr)
        return [], []
```

### 4.3 텔레그램 메시지 섹션 추가

closing_report 의 보고서 빌더 내부 — 기존 섹션 끝부분에 추가 (푸터 직전):

```python
# strategy_config 의 risk_analysis.enabled 체크
risk_cfg = config.get("risk_analysis") or {}
if _RISK_AVAILABLE and risk_cfg.get("enabled"):
    returns, equity = _load_portfolio_history_60d()
    if returns and equity:
        snapshot = calculate_risk_snapshot(
            returns,
            equity,
            threshold_pct=risk_cfg.get("portfolio_stop_loss_pct", -15.0),
        )
        risk_section = format_risk_section(snapshot, today_str)
        lines.extend(risk_section)
        save_snapshot(snapshot, today_str)
```

### 4.4 일별 portfolio_history 누적

closing_report 종료 직전 또는 별도 헬퍼:
```python
def _append_portfolio_history(today_str: str, net_asset: int, daily_pnl: int) -> None:
    """data/portfolio_history.json 에 오늘 포트폴리오 기록 추가."""
    history_file = _ROOT / "data" / "portfolio_history.json"
    try:
        if history_file.exists():
            data = json.loads(history_file.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                data = []
        else:
            data = []
        # 같은 날짜 있으면 갱신
        data = [r for r in data if r.get("date") != today_str]
        data.append({
            "date": today_str,
            "net_asset": net_asset,
            "daily_pnl": daily_pnl,
            "saved_at": datetime.now().isoformat(),
        })
        # 90일 이상 누적분 자동 제거 (롤링)
        data = sorted(data, key=lambda r: r["date"])[-90:]
        history_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[리스크] portfolio_history 저장 실패: {e}", file=sys.stderr)
```

closing_report 내 기존 net_asset 계산 후 호출.

---

## 5. strategy_config.json 추가

기존 trading 섹션과 별개로 risk_analysis 섹션 신설:

```jsonc
{
  // ... 기존 entry / exit / risk_reward / trading ...

  "risk_analysis": {
    "_comment": "B3 — 일일 포트폴리오 리스크 보고 (Vibe-Trading 차용)",
    "enabled": false,
    "var_confidence": 0.95,
    "var_lookback_days": 60,
    "portfolio_stop_loss_pct": -15.0,
    "stress_scenarios_enabled": true,
    "history_max_days": 90
  }
}
```

---

## 6. 검증 시나리오

### 6.1 단위 테스트

```bash
venv/bin/python3 -c "
import sys
sys.path.insert(0, 'morning_report')
from risk_analyzer import calculate_var, calculate_cvar, calculate_mdd

# 케이스 1: 정상 분포
returns = [-2.5, -1.8, -1.2, -0.5, 0.1, 0.5, 1.0, 1.5, 2.0, 3.0] * 6  # 60개
print(f'VaR(95%): {calculate_var(returns, 0.95):.2f}%')   # 음수 출력 기대
print(f'CVaR(95%): {calculate_cvar(returns, 0.95):.2f}%') # VaR 이하

# 케이스 2: MDD
equity = [100, 105, 110, 95, 100, 90, 95, 105, 100]
print(f'MDD: {calculate_mdd(equity):.2f}%')  # peak 110 → trough 90 = -18.18%

# 케이스 3: 짧은 시계열
print(f'VaR(짧음): {calculate_var([1.0, 2.0, 3.0], 0.95)}')  # None 기대
"
```

### 6.2 통합 dry-run

```bash
# strategy_config.json 에 risk_analysis.enabled=true 일시 활성화
venv/bin/python3 morning_report/closing_report.py --dry-run
# 출력에 "📊 리스크 분석" 섹션이 있는지 확인
# 60일 시계열 데이터 없으면 섹션 출력 안 됨 (정상)
```

### 6.3 일별 누적 확인

```bash
ls -la data/portfolio_history.json data/risk_snapshot.json 2>&1
# 최소 1일 운영 후 파일 생성 확인
```

---

## 7. 산출물 체크리스트

- [ ] `morning_report/risk_analyzer.py` 신규 작성
- [ ] `data/raw/kospi_stress_scenarios.json` 신규 작성
- [ ] `morning_report/closing_report.py` — import + _load_portfolio_history_60d + _append_portfolio_history + 텔레그램 섹션 추가
- [ ] `data/strategy_config.json` — risk_analysis 섹션 추가 (enabled=false)
- [ ] py_compile 통과 (risk_analyzer + closing_report)
- [ ] JSON validate 통과 (strategy_config + kospi_stress_scenarios)
- [ ] numpy 의존성 확인 (`venv/bin/python3 -c "import numpy"` 통과)
- [ ] 단위 테스트 3 케이스 통과

---

## 8. 보고 형식

```
status: Brief 13-B 완료
completion_reason:
- risk_analyzer.py 신규 (~150줄)
- kospi_stress_scenarios.json 신규
- closing_report.py 통합 (3 헬퍼 + 섹션 1개)
- strategy_config risk_analysis 섹션 추가
- numpy 의존성 OK
- 단위 테스트 3건 통과
files_changed:
- morning_report/risk_analyzer.py (신규)
- data/raw/kospi_stress_scenarios.json (신규)
- morning_report/closing_report.py (수정)
- data/strategy_config.json (수정)
warnings:
- portfolio_history.json 누적 시작 — 60일 후 풀 분석 가능
- Phase A 의 R19 일부이지만 매매 무관 (Phase 2 Trade-Small 검증 무관하게 진행 가능)
next_recommended_action:
- strategy_config risk_analysis.enabled = true 로 활성화 후 closing_report 1주일 운영
- 1주일 후 portfolio_history.json 확인 + risk_snapshot.json 일별 기록 검증
```

---

*Brief 13-B: 일일 리스크 분석 (Vibe-Trading R19 차용)*
*매매 모듈과 독립 — Phase 2 Trade-Small 게이트 무관하게 도입 가능*
