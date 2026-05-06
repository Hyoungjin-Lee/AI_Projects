# 🛠️ Pattern Integration — Stage 5 Phase A Technical Design

> 작성일: 2026-05-06
> 단계: Stage 5 (Technical Design — Phase A 인프라)
> 입력: `04_plan_final.md` (형진님 승인 2026-05-06)
> 범위: Phase A 인프라 모듈 6종 + 백테스트 환경 + KIS API 권한 점검
> 다음: Stage 8 Codex 위임 (Brief A-1~A-3 분리)

---

## 0. Phase A 목표

| # | 산출물 | 검증 |
|---|--------|------|
| 1 | `indicators.py`에 ADX(14) 함수 추가 | 단위 테스트 + 기존 함수와 동일 시그니처 |
| 2 | `heiken_ashi.py` 신규 — HA 캔들 변환 | 단위 테스트 |
| 3 | `line_detector.py` 신규 — 수평 지지/저항 + 추세선 자동 검출 | matplotlib PoC 차트 형진님 70% 시각 일치 |
| 4 | `pattern_detector.py` 골격 — 5종 패턴 인터페이스 (구현은 Phase B/C/D) | 인터페이스 단위 테스트 |
| 5 | `pattern_lifecycle.py` 신규 — 검출 패턴 후속 가격 추적 | 24h/72h 자동 업데이트 시뮬레이션 |
| 6 | `risk_analyzer.py` 신규 — VaR/CVaR/MDD/스트레스 (R19) | KOSPI 5종 시나리오 수치 검증 |
| 7 | KOSPI 1년 일봉 캐시 + 스트레스 시나리오 데이터 | `data/raw/kospi_*.json` |
| 8 | KIS API 권한 점검 스크립트 | 분봉 5/15분/1H + 호가 10단계 호출 성공 |
| 9 | `data/strategy_config.json`에 신규 섹션 골격 추가 (모두 enabled=false) | py_compile + JSON validate |

**Phase A Exit:** PoC 차트 형진님 시각 검증 + KIS 권한 점검 통과 + 단위 테스트 100% pass.

---

## 1. ADX 함수 (indicators.py 확장)

### 1.1 시그니처

```python
def adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    n: int = 14,
) -> dict:
    """
    Average Directional Index — 추세 강도 지표.

    반환:
        {
            "adx": pd.Series,        # ADX 값 (0~100)
            "plus_di": pd.Series,    # +DI
            "minus_di": pd.Series,   # -DI
        }

    해석:
        ADX < 20 = 추세 없음 (횡보)
        20 ≤ ADX < 25 = 약한 추세
        ADX ≥ 25 = 명확한 추세 (R18 임계값)
        ADX ≥ 40 = 강한 추세
    """
```

### 1.2 산식

```
1. True Range (TR) = max(
     high - low,
     abs(high - prev_close),
     abs(low - prev_close)
   )

2. +DM (Plus Directional Movement) = 
     high - prev_high  if (high - prev_high) > (prev_low - low) and > 0
     else 0

   -DM (Minus Directional Movement) = 
     prev_low - low    if (prev_low - low) > (high - prev_high) and > 0
     else 0

3. Smoothed (Wilder's, n=14):
     ATR_n   = EMA(TR, n) — Wilder smoothing
     +DI_n   = 100 × EMA(+DM, n) / ATR_n
     -DI_n   = 100 × EMA(-DM, n) / ATR_n

4. DX = 100 × abs(+DI - -DI) / (+DI + -DI)
   ADX = EMA(DX, n) — Wilder smoothing
```

**Wilder smoothing = `series.ewm(alpha=1/n, adjust=False).mean()`**

### 1.3 단위 테스트

```python
# tests/test_indicators_adx.py
def test_adx_known_values():
    """알려진 입력에 대한 출력 검증."""
    # Wilder 원본 예제 데이터 (Pine Script ta.adx와 동일 결과 보장)
    df = pd.read_csv("tests/data/adx_reference.csv")
    result = adx(df["high"], df["low"], df["close"], n=14)
    assert abs(result["adx"].iloc[-1] - 32.5) < 0.5  # 허용 오차

def test_adx_trending_market():
    """강한 상승 추세에서 ADX > 25."""
    rising = pd.Series(range(100, 200))
    high = rising * 1.01
    low = rising * 0.99
    result = adx(high, low, rising, n=14)
    assert result["adx"].iloc[-10:].mean() > 25

def test_adx_sideways_market():
    """횡보장에서 ADX < 20."""
    sideways = pd.Series([100 + (i % 5) for i in range(100)])
    result = adx(sideways, sideways - 1, sideways, n=14)
    assert result["adx"].iloc[-10:].mean() < 20
```

---

## 2. heiken_ashi.py — HA 캔들 변환

### 2.1 시그니처

```python
def to_heiken_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """
    OHLC → Heiken Ashi 변환.

    입력 컬럼: open, high, low, close
    출력 컬럼: ha_open, ha_high, ha_low, ha_close
    """
```

### 2.2 산식

```
ha_close = (open + high + low + close) / 4
ha_open  = (prev_ha_open + prev_ha_close) / 2     # 첫 행은 (open + close) / 2
ha_high  = max(high, ha_open, ha_close)
ha_low   = min(low, ha_open, ha_close)
```

### 2.3 사용 패턴

```python
from heiken_ashi import to_heiken_ashi

df_ha = to_heiken_ashi(df)
# pattern_detector가 노이즈 제거된 HA 캔들로 패턴 검출 (선택)
```

---

## 3. line_detector.py — 수평/추세선 자동 검출

### 3.1 핵심 인터페이스

```python
def detect_horizontal_lines(
    df: pd.DataFrame,
    lookback: int = 60,
    min_touch_count: int = 2,
    tolerance_pct: float = 1.0,
) -> list[dict]:
    """
    수평 지지/저항선 검출.

    반환:
        [{"price": 73000, "type": "support", "touch_count": 3,
          "touched_at": ["2026-04-12", "2026-04-25", "2026-05-02"]}, ...]
    """

def detect_trendlines(
    df: pd.DataFrame,
    lookback: int = 30,
    min_touch_points: int = 3,
    max_deviation_pct: float = 1.0,
) -> list[dict]:
    """
    추세선 (상승/하락) 검출 — 선형 회귀 + RANSAC.

    반환:
        [{"slope": 0.012, "intercept": 71500, "type": "uptrend",
          "touch_count": 4, "r2": 0.89, "start_date": "2026-04-15",
          "end_date": "2026-05-06"}, ...]
    """
```

### 3.2 알고리즘

**수평선 검출:**
1. 최근 `lookback` 봉의 swing high/low 추출 (`scipy.signal.find_peaks`, prominence 기준)
2. 가격 클러스터링 — 인접 swing 가격이 `tolerance_pct` 이내면 같은 라인으로 합침
3. `min_touch_count` 이상 터치된 클러스터만 라인으로 인정
4. 가장 최근 종가 위 = 저항, 아래 = 지지

**추세선 검출:**
1. 최근 `lookback` 봉의 swing high (저항선용) / swing low (지지선용) 추출
2. 모든 두 점 조합에 대해 직선 fit → 직선과 다른 swing 점들 거리 계산
3. RANSAC: 거리 `max_deviation_pct` 이내인 점이 가장 많은 직선 선택
4. `min_touch_points` 이상 + R² ≥ 0.7 이면 유효 추세선

### 3.3 PoC 검증 (Phase A Exit 게이트)

**입력:** 임의 종목 5종 × 1년 일봉 데이터 (예: 005930, 000660, 035420, 005380, 051910)

**출력:** matplotlib 차트 5종
- 가격 캔들스틱 + 검출된 수평선 (파란색) + 추세선 (빨강/초록)
- 각 라인에 touch_count 라벨

**검증 절차:**
1. Codex가 차트 5종 PNG 생성 → `docs/12_pattern_integration/poc_lines/`
2. 형진님 시각 확인 — "사람이 그릴 만한 라인과 일치도 70% 이상"
3. 통과 못 할 시 → tolerance/min_touch 파라미터 튜닝 후 재생성

---

## 4. pattern_detector.py — 5종 패턴 골격

### 4.1 인터페이스 (Phase A에서는 시그니처만, 구현은 Phase B/C/D)

```python
@dataclass
class PatternResult:
    code: str
    pattern: str                        # search/supply/line/bottom/top
    detected_at: datetime
    timeframe: str                      # 5m/15m/1h/1d
    confidence: float                   # 0.0~1.0
    context: dict                       # 패턴별 메타데이터

def detect_search_pattern(
    df: pd.DataFrame,
    timeframe: str = "5m",
    min_drop_pct: float = 3.0,
    absorption_volume_ratio: float = 1.5,
    false_rebound_max_pct: float = 2.0,
    redrop_within_bars: int = 5,
) -> PatternResult | None:
    """서치(Bull Trap) 패턴 — Phase B 구현."""

def detect_supply_pattern(
    df: pd.DataFrame,
    horizontal_lines: list[dict],       # line_detector 출력
    absorption_volume_ratio: float = 1.3,
) -> PatternResult | None:
    """공급 패턴 (수평 지지선 흡수) — Phase C 구현."""

def detect_line_pattern(
    df: pd.DataFrame,
    trendlines: list[dict],             # line_detector 출력
) -> PatternResult | None:
    """라인 패턴 (추세선 따라 매수 누적) — Phase C 구현."""

def detect_bottom_pattern(
    df: pd.DataFrame,
    lower_wick_min_ratio: float = 0.6,
    volume_divergence: bool = True,
    prev_low_break_pct: float = 0.5,
) -> PatternResult | None:
    """바닥 패턴 — Phase D 구현."""

def detect_top_pattern(
    df: pd.DataFrame,
    stack_count_min: int = 3,
    volume_divergence: bool = True,
) -> PatternResult | None:
    """뚜껑 패턴 — Phase D 구현."""

# Phase A에서는 모든 detect_*() 함수가 NotImplementedError 발생
# 또는 None 반환 + 로그 "pattern_detector: 구현 대기 (Phase B/C/D)"
```

### 4.2 모듈 책임 경계

| 모듈 | 책임 |
|------|------|
| `line_detector.py` | 라인 검출만 (다른 패턴 무관) |
| `pattern_detector.py` | 5종 패턴 검출 + line_detector 출력 활용 |
| `signal_aggregator.py` | Gate 1~6 통합 (Phase B/C에서 신설) |

---

## 5. pattern_lifecycle.py — 후속 가격 추적

### 5.1 데이터 흐름

```
[검출 시점]
intraday_discovery → signal_aggregator → pattern_detector
                                         ↓
                                   pattern_log.json 기록
                                   (lifecycle 필드는 null)

[+24h, +72h 후 — 23:35 launchd]
pattern_lifecycle.run()
  ↓ pattern_log.json 읽기
  ↓ lifecycle.+24h_close == null 인 항목 추출
  ↓ KIS API 일봉 종가 조회
  ↓ outcome 판정 + lifecycle 필드 업데이트
```

### 5.2 outcome 판정 룰

```python
def judge_outcome(pattern: str, detected_close: float, future_close: float) -> str:
    """
    pattern: 검출된 패턴 종류
    detected_close: 검출 시점 종가
    future_close: +24h or +72h 종가
    
    반환: "true_positive" / "false_positive" / "neutral"
    """
    pct_change = (future_close - detected_close) / detected_close * 100
    
    if pattern in ("search", "top"):
        # 하락 시그널 — future가 하락이면 정답
        if pct_change <= -2.0: return "true_positive"
        if pct_change >= 2.0:  return "false_positive"
        return "neutral"
    
    if pattern in ("supply", "line", "bottom"):
        # 상승 시그널 — future가 상승이면 정답
        if pct_change >= 2.0:  return "true_positive"
        if pct_change <= -2.0: return "false_positive"
        return "neutral"
    
    return "neutral"
```

### 5.3 launchd plist (R13)

```xml
<!-- com.aigeenya.stockreport.pattern_lifecycle.plist -->
<dict>
    <key>Label</key>
    <string>com.aigeenya.stockreport.pattern_lifecycle</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/geenya/projects/AI_Projects/stockpilot/venv/bin/python3</string>
        <string>/Users/geenya/projects/AI_Projects/stockpilot/morning_report/pattern_lifecycle.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>
        <dict>
            <key>Weekday</key><integer>1</integer>
            <key>Hour</key><integer>23</integer>
            <key>Minute</key><integer>35</integer>
        </dict>
        <!-- 화~토 동일 -->
    </array>
    <key>StandardOutPath</key>
    <string>/Users/geenya/projects/AI_Projects/stockpilot/logs/pattern_lifecycle.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/geenya/projects/AI_Projects/stockpilot/logs/pattern_lifecycle_error.log</string>
</dict>
```

23:30 closing_report → 23:35 pattern_lifecycle (5분 간격으로 의존 보장).

---

## 6. risk_analyzer.py — VaR/CVaR/MDD/스트레스 (R19)

### 6.1 핵심 함수

```python
def calculate_var(
    daily_returns: pd.Series,
    confidence: float = 0.95,
    method: str = "historical",  # historical / parametric
) -> float:
    """일별 VaR — 직전 60일 수익률 기준."""

def calculate_cvar(
    daily_returns: pd.Series,
    confidence: float = 0.95,
) -> float:
    """CVaR — VaR 초과 손실 평균."""

def calculate_mdd(
    equity: pd.Series,
    lookback_days: int = 60,
) -> dict:
    """
    Max Drawdown.
    반환: {"mdd_pct": -8.7, "peak_date": "...", "trough_date": "..."}
    """

def stress_test_scenarios(
    holdings: dict[str, dict],         # {code: {qty, avg_price, beta_to_kospi}}
    scenarios: dict[str, float] = None,
) -> dict[str, float]:
    """
    KOSPI 5종 시나리오에 대한 포트폴리오 손실률 추정.
    
    holdings의 beta_to_kospi가 없으면 1.0으로 가정 (Phase A 단순화).
    """
```

### 6.2 KOSPI 스트레스 시나리오 데이터

`data/raw/kospi_stress_scenarios.json`:

```json
{
  "_comment": "KOSPI 일봉 기준 역사적 폭락 시나리오 (Vibe-Trading 차용 + 한국 시장 보정)",
  "_source": "KOSPI 일봉 데이터 (KIS API 또는 yfinance ^KS11)",
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

**수치 재검증:** Codex가 KIS API 또는 yfinance(^KS11)로 실제 KOSPI 일봉 데이터 fetch → 위 수치 자동 검증 + 오차 0.5% 이내 보정.

### 6.3 closing_report 통합 hook

```python
# closing_report.py 신규 섹션 (기존 generate_report() 함수 내부 추가)
from risk_analyzer import calculate_var, calculate_cvar, calculate_mdd, stress_test_scenarios

risk_section = ""
if config["risk_analysis"]["enabled"]:
    daily_returns = _get_portfolio_daily_returns(60)  # 직전 60거래일
    var95 = calculate_var(daily_returns, 0.95)
    cvar95 = calculate_cvar(daily_returns, 0.95)
    mdd = calculate_mdd(_get_portfolio_equity(60), 60)
    stress = stress_test_scenarios(_get_holdings_dict())
    
    risk_section = (
        "📊 *리스크 분석*\n"
        f"- VaR(95%): {var95:.1%}\n"
        f"- CVaR(95%): {cvar95:.1%}\n"
        f"- MDD(60일): {mdd['mdd_pct']:.1%}\n"
        f"- 스트레스 노출 (코로나급): {stress['kospi_2020_covid']:.1%}\n"
        f"- 포트폴리오 손절 임계: -15% (현재 {mdd['mdd_pct']:.1%}, "
        f"{'안전' if mdd['mdd_pct'] > -15 else '⚠️ 임계 초과'})"
    )

# 기존 텔레그램 메시지에 risk_section 추가
```

`data/risk_snapshot.json` 일별 기록:
```json
{"date":"2026-05-06","var_95":-2.3,"cvar_95":-3.1,"mdd_60d":-8.7,
 "stress":{"kospi_2020_covid":-12.1},"portfolio_status":"safe"}
```

---

## 7. KIS API 권한 점검 스크립트

### 7.1 위치

`scripts/check_kis_api_permissions.py`

### 7.2 점검 항목

```python
"""
Phase A 인프라 사전 점검 — KIS API 권한 검증.

체크 항목:
1. 분봉 OHLCV 5분 (FHKST03010200) — 5분봉 30봉 호출 성공
2. 분봉 OHLCV 15분 — 15분봉 30봉 호출 성공
3. 분봉 OHLCV 1시간 — 1시간봉 30봉 호출 성공
4. 호가 10단계 (FHKST01010200) — 매수/매도 호가 10단계 호출 성공
5. 체결강도 (FHKST01010300) — 이미 통합 (검증만)
6. yfinance ^KS11 — KOSPI 1년 일봉 fetch 성공
7. 라인 검출 PoC 차트 5종 생성 가능 여부

출력: scripts/kis_api_check_report.json
"""
```

### 7.3 실행 결과 예시

```json
{
  "checked_at": "2026-05-06T22:00:00",
  "results": {
    "minute_5m": {"status": "ok", "sample_count": 30},
    "minute_15m": {"status": "ok", "sample_count": 30},
    "minute_1h": {"status": "ok", "sample_count": 30},
    "orderbook_10": {"status": "ok", "ask_levels": 10, "bid_levels": 10},
    "ccnl_strength": {"status": "ok", "value": 105.3},
    "kospi_yfinance": {"status": "ok", "rows": 252},
    "matplotlib_poc": {"status": "ok", "files": 5}
  },
  "overall": "pass"
}
```

전 항목 `ok` 시 Phase A → Phase B 게이트 통과.

---

## 8. strategy_config.json 골격 추가 (Phase A 단계)

Phase A에서는 **모두 `enabled: false`** 로 추가만 (실행은 Phase B 이후).

```jsonc
{
  // ... 기존 entry / exit / risk_reward / trading 섹션 ...

  "entry": {
    // ... 기존 weekly_trend, sma20_support, rsi_range ...
    "adx_filter": {                          // R18 — Phase A에서 함수만 추가, false
      "enabled": false,
      "period": 14,
      "threshold": 25.0,
      "rollout_phase": "shadow"
    }
  },

  "pattern_detection": {
    "enabled": false,
    "rollout_phase": "shadow",
    // ... search_pattern / supply_pattern / line_pattern / bottom_pattern / top_pattern ...
    // Phase A에서는 모두 enabled: false
  },

  "bull_bear_gate": {                        // Phase C에서 활성화
    "enabled": false,
    "weights": { /* ... */ },
    "thresholds": { "pass": 0.5, "weak_signal": 0.0, "reject_below": 0.0 }
  },

  "risk_analysis": {                         // Phase A에서 함수만 추가, false
    "enabled": false,
    "var_confidence": 0.95,
    "var_lookback_days": 60,
    "portfolio_stop_loss_pct": -15.0,
    "stress_scenarios_enabled": true
  }
}
```

---

## 9. 단위 테스트 골격

```
tests/
├── test_indicators_adx.py         # §1.3
├── test_heiken_ashi.py            # HA 변환 검증
├── test_line_detector.py          # 가짜 데이터로 라인 검출 검증
├── test_pattern_detector_skel.py  # 인터페이스 시그니처 검증
├── test_pattern_lifecycle.py      # outcome 판정 룰 검증
├── test_risk_analyzer.py          # VaR/CVaR/MDD/스트레스 단위 테스트
├── test_kis_permissions.py        # 권한 점검 (모킹)
└── data/
    ├── adx_reference.csv          # ADX 검증 데이터
    └── line_test_fixtures.json    # 라인 검출 테스트 픽스처
```

---

## 10. Codex 위임 Brief 분리 (Stage 8)

Phase A를 한 brief에 모두 담으면 분량 과다. **3개 brief로 분리:**

| Brief | 범위 | 예상 분량 |
|-------|------|----------|
| **Brief A-1: 지표/캔들 인프라** | indicators.adx + heiken_ashi.py + 단위 테스트 + strategy_config.adx_filter 골격 | ~400줄 |
| **Brief A-2: 라인 검출 + 패턴 골격** | line_detector.py + pattern_detector.py 인터페이스 + matplotlib PoC + strategy_config.pattern_detection 골격 | ~600줄 |
| **Brief A-3: 라이프사이클 + 리스크 + KIS 점검** | pattern_lifecycle.py + risk_analyzer.py + closing_report 통합 + KIS 권한 점검 + KOSPI 스트레스 데이터 + strategy_config.risk_analysis 골격 + launchd plist | ~700줄 |

**구현 순서:** A-1 → A-2 → A-3 (의존성 체인). 각 brief 완료 후 Stage 9 (Opus 코드 리뷰) → Stage 10 (Codex 수정) → Stage 11 (최종 검증) 사이클.

---

## 11. 검증/테스트 시나리오 (Phase A 통합)

### 11.1 단위 테스트 (모듈별)
- 각 함수 입력/출력 검증
- 엣지 케이스 (빈 시리즈, NaN, 0 거래량 등)

### 11.2 통합 시나리오
1. KIS API에서 005930 1년 일봉 fetch
2. ADX(14) 계산 → 마지막 30봉 평균 ≥ 25 인지 시각 확인
3. line_detector → matplotlib 차트 PNG 출력
4. pattern_lifecycle → fake pattern_log.json 입력 → outcome 판정 테스트
5. risk_analyzer → 테스트 holdings + KOSPI 시나리오 → 손실률 추정

### 11.3 KIS API 권한 점검 통합 실행
```bash
cd /Users/geenya/projects/AI_Projects/stockpilot
venv/bin/python3 scripts/check_kis_api_permissions.py
# scripts/kis_api_check_report.json 생성 → overall: "pass" 확인
```

### 11.4 Phase A Exit 게이트 (R9)
- [ ] 단위 테스트 100% pass (`venv/bin/python3 -m pytest tests/`)
- [ ] KIS 권한 점검 overall: pass
- [ ] line_detector PoC 차트 5종 → 형진님 시각 일치 70% 이상 ✅
- [ ] strategy_config.json py_compile + JSON validate 통과
- [ ] launchd pattern_lifecycle plist 등록 + 23:35 1회 dry-run 실행 성공

---

## 12. 리스크 / 미해결

### 12.1 Phase A 자체 리스크
- **라인 검출 알고리즘 주관성** — RANSAC tolerance 튜닝 부담. PoC 검증 미통과 시 파라미터 튜닝 1~2일 소요 예상
- **KIS API rate limit** — 분봉 + 호가 동시 호출 시 제한. Phase A 점검에서 발견 시 분봉 캐시 전략 추가 필요
- **KOSPI 스트레스 시나리오 수치 정확성** — Vibe-Trading 차용 수치(예: 2020 코로나 -34%)와 실제 KOSPI 일봉 차이. Codex가 자동 검증 + 보정

### 12.2 Phase 2와의 동시 진행 부담
- Phase 2 Brief A~F 구현이 아직 진행 중 → 본 Phase A 동시 작업 시 형진님 검토 부담 가중
- **권고:** Phase 2 Brief A~D 구현 + Trade-Small 검증 통과 → 본 Phase A 착수
- 현 시점에서는 본 plan_final + 본 design_A 문서를 **참조 문서로 보관**, 실제 코딩은 Phase 2 안정화 후

---

## 13. 다음 단계

1. **본 design_A 형진님 검토** — 누락/오류 지적 시 수정
2. **Phase 2 진행 상황 점검** — Brief A~F 구현 완료 시점 확인
3. **Phase 2 Trade-Small 검증 통과 시점에 Phase A 착수**
4. **Stage 8 Codex 위임** — Brief A-1 (지표/캔들 인프라)부터 시작
5. **Phase B~E 기술 설계** — Phase A 구현 + 검증 완료 후 후속 stage로 작성

---

*이 문서는 Stage 5 Phase A 기술 설계. Phase B~E는 Phase A 구현/검증 완료 후 후속 stage로 별도 작성 예정.*
*문서 위치: `docs/12_pattern_integration/05_technical_design_A.md`*
