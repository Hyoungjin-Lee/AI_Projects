# 📘 Pattern Integration — Stage 4 Plan Final

> 작성일: 2026-05-06
> 단계: Stage 4 (Plan Final — 검토 통합)
> 입력: `02_plan_draft.md` + `03_plan_review.md` (P0 6 / P1 7 / P2 5 / 결정 기록 2)
> 다음: 🔴 **형진님 승인** → Stage 5 (기술 설계)

---

## 0. Executive Summary

기존 추세추종 B+C 정책에 5종 패턴 매매법(바닥/뚜껑/서치/공급/라인) + 4개 외부 레포 차용 룰을 **선택적·단계적**으로 통합:

- **TradingAgents**: Bull/Bear 토론 게이트 (R17, 2-stage)
- **Vibe-Trading**: ADX > 25 트렌드 강도 필터 (R18) + VaR/CVaR/스트레스 시나리오 리스크 분석 (R19)
- **AutoHedge / QuantDinger**: 매매기법 차용 X (정량 룰 부재 / 한국장 부적합)

**핵심 효과 5가지:**
1. 신규 매수 false breakout 진입 -30%↓ (ADX + 서치 필터)
2. 추가매수 평단 개선 (바닥 패턴)
3. 익절 보호 강화 (뚜껑 트레일링 조기)
4. 양면 평가 게이트 (Bull/Bear)
5. 일일 포트폴리오 리스크 가시화 (VaR/스트레스)

---

## 1. 형진님 확정 결정사항 (2026-05-06 누적)

### 1차 결정 (Stage 2 입력)
| ID | 질문 | 결정 |
|----|------|------|
| Q1 | 도입 순서 | **A — 서치 → 공급/라인 → 바닥/뚜껑 → 레짐** |
| Q2 | 약신호 처리 | **B — 절반 사이즈 (Kelly-Lite)** |
| Q3 | 단계적 롤아웃 | **A — Shadow 1~2주 → Live** |

### 2차 결정 (외부 레포 검토 후)
| ID | 질문 | 결정 |
|----|------|------|
| 외부1 | TradingAgents Tier 1 (Bull/Bear) | **A — 채택** |
| 외부2 | Vibe-Trading ADX 필터 | **A — 채택 (R18)** |
| 외부3 | Vibe-Trading 리스크 분석 | **A — 채택 (R19)** |
| 외부4 | Vibe-Trading 4-stage 게이트 | **B — 미채택, 2-stage 유지** |
| 외부5 | QuantDinger 리스크 디폴트 비교 | **C — 운영 데이터 기반 별도 논의** (§9.3) |

---

## 2. 핵심 설계 — 6단 진입 게이트 + 추매/매도 통합

### 2.1 신규 매수 — 6단 게이트

```
[Gate 1] 시장 레짐 필터 (Phase E)
  일봉 기준: 직전 5거래일 KOSPI 평균 등락률 ≥ -1% AND
  일중 기준: 09:30 시점 KOSPI 등락률 ≥ -0.7%
  두 조건 모두 충족 X = 하락장 → 신규 매수 정지
       ↓
[Gate 2] B+C 기본 조건 + ADX 필터 (R18 반영)
  ✅ 주봉 SMA5 > SMA10
  ✅ 현재가 > 일봉 SMA20
  ✅ RSI 40~60
  ✅ ADX(14) ≥ 25  ← NEW (추세 강도)
       ↓
[Gate 3] 공급/라인 패턴 — 진입 신뢰도 (Phase C)
  공급: 수평 지지선 매수 흡수 + 반등
  라인: 상승 추세선 매수 누적
       ↓
[Gate 4] 서치 함정 차단 — 진입 거부권 (Phase B) 🥇 1순위
  검출 시간 단위: 5분봉 5봉 (실시간 차단)
  서치 패턴 검출 → 무조건 진입 거부
       ↓
[Gate 5] 호가/체결강도 확인 (선택)
  매수 호가 누적 + 체결강도 ≥ 100 → 신뢰도 +
       ↓
[Gate 6] Bull/Bear 토론 게이트 (R17 반영, 2-stage)
  bull_score = (b_c_score × 0.4) + (supply × 0.2)
             + (line × 0.2) + (buy_orderbook × 0.2)
  bear_score = (search × 0.4) + (top_early × 0.3)
             + (sell_orderbook × 0.2) + (bear_regime × 0.1)
  decision_score = bull_score - bear_score

  → ≥ 0.5  : 진입 통과 (강신호 검사)
  → 0.0~0.5: 약신호 (절반 사이즈)
  → < 0.0  : 거부 (Bear 우세)
       ↓
[매수 사이즈 결정 — Kelly-Lite × split_weights, R2 반영]
  final_1st_buy = base × split_weights[0] × signal_multiplier
                = base × 0.5 × {0.5/1.0/1.5}
                = base × {0.25 / 0.50 / 0.75}
  2차/3차 매수 = base × split_weights × 1.0 (multiplier 고정)
```

### 2.2 추가 매수 (분할 2차/3차)

```
기본 룰 (Phase 2): 평단 -1~-2% 눌림 + SMA20 위 + 1일 경과
                            ↓
[NEW] 바닥 패턴 추가 트리거 (Phase D):
  평단 -1~-2% 구간 + 바닥 패턴 검출 = 추매 신호
   - 긴 아래꼬리 (lower_wick / candle_total ≥ 0.6)
   - 거래량 다이버전스 (가격↓ + 거래량↑)
   - 직전 저점 -0.5% 이내 흡수 후 반등
                            ↓
[필수] 서치 패턴 재확인 (Phase B):
  검출 시간 단위: 15분봉 3봉 (지연 허용)
  검출 시 → 추매 거부 + 보유 정리 알림
```

### 2.3 매도 (트레일링 조기 발동)

```
기존 트레일링: 평단 +2% 활성화 → 5일 고가 -3% 이탈 청산
                            ↓
[NEW] 뚜껑 패턴 검출 시 (Phase D):
  평단 +1%부터 조기 활성화
   - 1차→2차→3차 상승봉 누적
   - 거래량 다이버전스 (가격↑ + 거래량↓)
                            ↓
[NEW] 서치 패턴 검출 시 (Phase B):
  검출 시간 단위: 15분봉 3봉
  → 즉시 매도 (하드스탑 -3% 도달 전)
```

### 2.4 강제 정지 트리거

| 트리거 | 조건 | 복구 (R7 반영) |
|--------|------|---------------|
| 시장 레짐 = 하락장 | Gate 1 차단 | 매일 09:00 자동 재평가 |
| 일중 누적 손실 -3% | Kill Switch 발동 | **자정 자동 해제** (Phase 2 max_daily_loss와 동일 패턴) |
| false positive 30% 초과 (직전 20건) | 패턴 매매 비활성화 | **수동 `/패턴재시작` 명령 필요** (자동 해제 X) |

---

## 3. 도입 순서 (Phased Rollout)

| Phase | 기간 | 내용 | 진입 영향 | 매도 영향 |
|-------|------|------|----------|----------|
| **A. 인프라** | 2주 | 라인 검출기, HA 캔들, 백테스트 환경, KOSPI 스트레스 시나리오 데이터 | — | — |
| **B. 서치 + ADX** | 2주 | Gate 4 + R18(ADX 필터) + 매도 가속기 | 거부권 + 강도 필터 | 즉시 매도 |
| **C. 공급/라인 + Bull/Bear** | 3주 | Gate 3 + Gate 6(R17) + Kelly-Lite | 신뢰도 + 양면 평가 | — |
| **D. 바닥/뚜껑** | 2주 | 추매 트리거 + 트레일링 조기 발동 | — | 트레일링 + |
| **E. 레짐 + 리스크 분석** | 1주 | Gate 1 + R19(VaR/CVaR/스트레스) + Kill Switch | 시장 정지 | — |

각 Phase는 **Shadow → Alert → Trade-Small → Trade-Full** 4단계로 점진 활성화.

**Trade-Small 사이즈 (R10):** 정상 사이즈 × 0.33 (1차 매수만, 추가매수는 정상 룰), 1주 미만은 1주 고정.

---

## 4. 신규 코드 모듈

| 모듈 | 역할 | Phase |
|------|------|-------|
| `morning_report/line_detector.py` | 수평 지지/저항 + 추세선 자동 검출 | A |
| `morning_report/heiken_ashi.py` | HA 캔들 변환 함수 | A |
| `morning_report/pattern_detector.py` | 5종 패턴 검출 + ADX 계산 | A |
| `morning_report/regime_classifier.py` | KOSPI 일봉/일중 레짐 분류 | E |
| `morning_report/signal_aggregator.py` | Gate 1~6 통합 + Bull/Bear + Kelly-Lite | B/C |
| `morning_report/pattern_lifecycle.py` | 검출 패턴 후속 가격 추적 + 승률 통계 | A |
| `morning_report/risk_analyzer.py` | VaR/CVaR/MDD/스트레스 시나리오 (R19) | E |

### 기존 모듈 수정 (R8 반영 — Hook 지점 명시)

| 모듈 | 수정 내용 |
|------|----------|
| `morning_report/intraday_discovery.py` | round 2/4/6/8 종료 시 → signal_aggregator.evaluate_batch() 호출 → pattern_log.json 기록 |
| `morning_report/validator.py` | preflight() 내부에 Gate 4 (서치 거부권) hook 추가 — `signal_aggregator.check_search_pattern()` 호출, reject 시 거부 사유 반환 |
| `morning_report/position_monitor.py` | monitor_tick() 내부에 tick_pattern_check() 추가 — 보유 종목 매 tick 뚜껑/서치 검출 → 트레일링 조기 활성 or 즉시 매도 |
| `morning_report/closing_report.py` | 신규 섹션 "리스크 분석" 추가 (R19) — VaR/CVaR/스트레스 5종 |
| `data/strategy_config.json` | `pattern_detection`, `bull_bear_gate`, `entry.adx_filter`, `risk_analysis` 섹션 신설 |
| `docs/STRATEGY.md` | 패턴 통합 정책 + ADX 필터 + 리스크 분석 섹션 추가 |

---

## 5. strategy_config.json 통합 스키마

```jsonc
{
  "entry": {
    "_comment": "기존 B+C + R18 ADX 필터",
    "weekly_trend": { /* 기존 */ },
    "sma20_support": { /* 기존 */ },
    "rsi_range": { /* 기존 */ },
    "adx_filter": {                          // R18 NEW
      "_comment": "Vibe-Trading 차용 — 추세 강도 검증",
      "enabled": false,
      "period": 14,
      "threshold": 25.0,
      "rollout_phase": "shadow"
    }
  },

  "pattern_detection": {
    "enabled": false,
    "rollout_phase": "shadow",               // shadow/alert/trade_small/trade_full
    "search_pattern": {                      // Gate 4 — 1순위
      "enabled": false,
      "timeframe_entry": "5m",               // R3 — 진입 차단용
      "timeframe_holding": "15m",            // R3 — 보유 매도용
      "min_drop_pct": 3.0,
      "absorption_volume_ratio": 1.5,
      "false_rebound_max_pct": 2.0,
      "redrop_within_bars": 5,
      "action_on_entry": "reject",
      "action_on_holding": "force_sell"
    },
    "supply_pattern": { /* Gate 3 */ },
    "line_pattern":   { /* Gate 3 */ },
    "bottom_pattern": { /* 추매 — Phase D */ },
    "top_pattern":    { /* 트레일링 조기 — Phase D */ },
    "regime_filter": {                       // Gate 1 — Phase E
      "enabled": false,
      "kospi_bear_daily_threshold_pct": -1.0,    // R5 — 5일 평균
      "kospi_bear_intraday_threshold_pct": -0.7, // R5 — 09:30 시점
      "halt_buys_on_bear": true
    },
    "sizing": {                              // Kelly-Lite × split_weights (R2)
      "weak_signal_multiplier": 0.5,
      "standard_signal_multiplier": 1.0,
      "strong_signal_multiplier": 1.5,
      "apply_to_first_buy_only": true        // 2차/3차는 1.0 고정
    },
    "kill_switch": {
      "daily_loss_pct_limit": -3.0,
      "auto_reset_at_midnight": true,
      "false_positive_window": 20,
      "false_positive_threshold_pct": 30.0,
      "fp_auto_reset": false                 // R7 — 수동 /패턴재시작 필요
    }
  },

  "bull_bear_gate": {                        // R17 NEW — Gate 6
    "_comment": "TradingAgents 차용 — 2-stage 양면 평가 (Vibe 4-stage 미채택)",
    "enabled": false,
    "weights": {
      "bull": {"b_c_score": 0.4, "supply": 0.2, "line": 0.2, "buy_orderbook": 0.2},
      "bear": {"search": 0.4, "top_early": 0.3, "sell_orderbook": 0.2, "bear_regime": 0.1}
    },
    "thresholds": {
      "pass": 0.5,
      "weak_signal": 0.0,
      "reject_below": 0.0
    }
  },

  "risk_analysis": {                         // R19 NEW
    "_comment": "Vibe-Trading 차용 — closing_report 일일 리스크 보고",
    "enabled": false,
    "var_confidence": 0.95,
    "var_lookback_days": 60,
    "portfolio_stop_loss_pct": -15.0,
    "stress_scenarios": {
      "kospi_2008_crisis_pct": -54,
      "kospi_2011_eu_crisis_pct": -22,
      "kospi_2018_trade_war_pct": -25,
      "kospi_2020_covid_pct": -34,
      "kospi_2022_rate_hike_pct": -25
    }
  }
}
```

---

## 6. 데이터 인프라 (R6 반영 — 스키마 예시)

### 6.1 신규 데이터 파일

| 파일 | 용도 | 쓰기 주체 | 스키마 예시 |
|------|------|----------|------------|
| `data/pattern_log.json` | 검출된 모든 패턴 + 후속 추적 | pattern_lifecycle.py | 아래 |
| `data/regime_state.json` | 일별 시장 레짐 분류 | regime_classifier.py (08:30) | `{"date":"2026-05-06","regime":"trend","kospi_5d_avg_pct":1.2}` |
| `data/risk_snapshot.json` | 일별 VaR/CVaR/MDD | risk_analyzer.py (closing_report 시) | `{"date":"...","var_95":-2.3,"cvar_95":-3.1,"mdd_60d":-8.7}` |

### 6.2 pattern_log.json 스키마 예시 (R6 반영)

```jsonc
{
  "code": "005930",
  "pattern": "search",
  "detected_at": "2026-05-06T10:23:00",
  "context": {
    "timeframe": "5m",
    "high": 73000,
    "drop_pct": -3.2,
    "rebound_pct": 1.5,
    "redrop_bars": 4
  },
  "lifecycle": {
    "+24h_close": null,
    "+72h_close": null,
    "outcome": null,                          // "true_positive" / "false_positive" / "neutral"
    "outcome_judged_at": null
  }
}
```

### 6.3 KIS API 권한 사전 점검 (Phase A)

- [ ] 분봉 OHLCV (5분/15분/1시간) — 라인 검출 + 서치 검출용
- [ ] 호가 10단계 — Gate 5
- [x] 체결강도 (FHKST01010300) — v2.3 통합 완료 (kis_client.get_ccnl)

---

## 7. 코드 통합 Hook 다이어그램 (R8)

```
┌─ validator.py (Phase 2) ──────────────────────────────────┐
│  preflight(proposal):                                      │
│    [기존] 시장시간 / 잔고 / 위험한도                        │
│    + [NEW] Gate 4: signal_aggregator.check_search_pattern()│
│      → reject 시 거부 사유 반환 ("search_pattern_detected")│
└────────────────────────────────────────────────────────────┘

┌─ position_monitor.py (Phase 2) ───────────────────────────┐
│  monitor_tick(holding):                                    │
│    [기존] 손절(-3%) / 트레일링 / 익절(+5%) / 보류청산       │
│    + [NEW] tick_pattern_check(holding):                    │
│      - 뚜껑 검출 → trailing_activate_pct = 0.01 임시 적용  │
│      - 서치 검출 → 즉시 시장가 매도 (-3% 대기 X)           │
└────────────────────────────────────────────────────────────┘

┌─ intraday_discovery.py ───────────────────────────────────┐
│  round 2/4/6/8 종료 시:                                    │
│    discovered_codes = [...]                                │
│    + [NEW] signal_aggregator.evaluate_batch(discovered)    │
│      → pattern_log.json 기록                               │
│      → discovery_log.json + pattern_log.json은             │
│         (code, detected_at) 으로 join 가능                 │
└────────────────────────────────────────────────────────────┘

┌─ closing_report.py ───────────────────────────────────────┐
│  generate_report():                                        │
│    [기존] 자산 변화 / 보유 종목 / 매매일지                  │
│    + [NEW] risk_analyzer.snapshot()                        │
│      → "📊 리스크 분석" 섹션 추가                          │
│      → risk_snapshot.json 기록                             │
└────────────────────────────────────────────────────────────┘
```

---

## 8. 테스트/검증 전략

### 8.1 단계별 (R16 반영)

| 종류 | 위치 | 시점 |
|------|------|------|
| **단위 테스트** | `tests/test_pattern_detector.py` 등 | 모듈 작성 시 |
| **백테스트** | `tests/backtest_pattern.py` — 1년 일봉 → 검출 + 후속 5일 수익률 | Phase 종료 전 |
| **dry-run 통합** | 기존 `--dry-run` 모드 + 패턴 검출만 활성화 | Shadow 진입 전 |
| **실거래 시나리오** | Shadow 1주 → Alert 1주 → Trade-Small 5~10건 → Trade-Full | 각 Phase |

### 8.2 Phase별 Exit 기준 (R9 반영)

| Phase | Exit 기준 |
|-------|-----------|
| A. 인프라 | 라인 검출기 PoC: 임의 종목 1년 일봉 → matplotlib 차트 오버레이 PNG → **형진님 시각 확인 70% 이상 일치** |
| B. 서치 + ADX | 진입 거부권 활성 종목 후속 5일 평균 수익률이 미활성 종목 대비 유의미하게 낮음 + ADX 필터 적용 후 false breakout -30% 이상 감소 |
| C. 공급/라인 + Bull/Bear | 표본 50건 이상 + 기존 B+C 단독 대비 승률 또는 R:R 개선 |
| D. 바닥/뚜껑 | 추매 후 평단 개선 효과 + 트레일링 조기 발동 익절률 +5%p |
| E. 레짐 + 리스크 분석 | 하락장 신규 매수 정지 표본 10건 이상 + VaR/스트레스 보고 5거래일 연속 정상 출력 |

### 8.3 백테스트 데이터 소스 (R15)
- 기존 KIS API daily 1년치 캐시로 충분 (Phase A에서 수집)
- 분봉 백테스트는 Phase A 진행 중 KIS rate limit 우려 별도 검토

---

## 9. 리스크 / 미해결 항목

### 9.1 기술 리스크
- 라인 검출 주관성 → Phase A PoC 시각 검증으로 보정
- Phase 2 통합 부담 → §10 선행 조건으로 차단
- 백테스트 overfitting → walk-forward 미사용, 단순 1년 통계만

### 9.2 운영 리스크
- KIS API rate limit (분봉 + 호가 동시 호출)
- 패턴 false positive → kill switch (R7) + Anti-Pattern은 Phase D 이후 별도 검토

### 9.3 미해결 (별도 트랙)
- **D3 (자본 90/10 분할)** — Phase 2 운영 안정화 후 재논의
- **D4 (AI 차트 해석 이중 검증)** — Phase D 이후 별도 검토
- **R21 (리스크 디폴트 재검토)** — Phase 2 Trade-Small 실거래 30~50건 누적 후 별도 stage. 비교 참조:
  | 파라미터 | 현재 | QuantDinger 보수형 |
  |---------|------|-------------------|
  | 손절 | -3% | -2% |
  | 트레일 활성 | +2% | +3% |
  | 트레일 폭 | -3% | -1.5% |

### 9.4 보류 (Phase D 이후 별도 stage)
- Anti-Pattern 라이브러리 자동 학습
- AI 차트 해석 이중 검증 게이트
- 외인/기관 수급 게이트
- Vibe-Trading 4-stage Bull-Bear 확장 (Phase B/C false positive율 검토 후 재논의)

---

## 10. 의존성 / 선행 조건 (R1 반영 — 필수 격상)

| 항목 | 상태 | 비고 |
|------|------|------|
| **Phase 2 Brief A~F 구현 완료 + Trade-Small 실거래 검증 통과** | 🔴 미완료 | **본 Plan Phase A 착수 게이트 — 미통과 시 Stage 5 진입 금지** |
| KIS API 분봉/호가 권한 점검 | 🔴 미점검 | Phase A 사전 작업 |
| 백테스트 환경 (1년 일봉 캐시) | 🔴 미구축 | Phase A |
| KOSPI 스트레스 시나리오 데이터 | 🔴 미수집 | Phase A (R19) |

**시점 권고:** Phase 2가 Trade-Full 안정화된 이후 Phase A 인프라부터 시작.

---

## 11. 정량 성공 기준

| 지표 | 목표 |
|------|------|
| 서치 필터 도입 후 false breakout 진입 비율 | -50% 이상 감소 |
| ADX 필터 도입 후 횡보장 false breakout | -30% 이상 감소 |
| 공급/라인 신호 가중 진입 평균 수익률 | 기존 B+C 단독 대비 +1%p 이상 |
| Bull/Bear 게이트 거부 종목 후속 5일 수익률 | 통과 종목 대비 유의미하게 낮음 |
| 바닥 추매 후 평균 평단 개선 | -0.5% 이상 |
| 뚜껑 트레일링 조기 발동 익절률 | 기존 트레일링 대비 +5%p |
| 레짐 필터 하락장 신규 매수 정지 손실 회피 | 표본 10건 이상 |
| VaR/CVaR/스트레스 보고 정상 출력 | 5거래일 연속 |

---

## 12. launchd 추가 (R13)

| plist | 시각 | 용도 |
|-------|------|------|
| `com.aigeenya.stockreport.pattern_lifecycle.plist` | 23:35 (closing_report 5분 후) | pattern_log.json 후속 가격 추적 |
| 그 외 모듈 | 기존 launchd에 통합 | intraday_discovery, position_monitor, closing_report |

---

## 13. 다음 단계

1. 🔴 **형진님 승인 대기** — 본 plan_final.md 검토 후 명시적 승인 (예: "승인" / "수정 요청")
2. 승인 후 Stage 5 기술 설계 — Phase A부터 단계적 설계
3. Stage 8 Codex 위임 (Phase A 인프라 brief부터)

---

## 14. 변경 이력 (Stage 3 review 반영)

| 항목 | 출처 | 적용 위치 |
|------|------|----------|
| R1 — Phase 2 의존성 필수 격상 | review §2 | §10 |
| R2 — Kelly-Lite × split_weights 산식 | review §2 | §2.1 사이즈 결정 박스 |
| R3 — 서치 검출 시간 단위 | review §2 | §2.1 Gate 4 + §5 strategy_config |
| R4 — Convergence Score 산식 | review §2 | R17로 흡수 (§2.1 Gate 6) |
| R5 — 레짐 분류 기준 구체화 | review §3 | §2.1 Gate 1 + §5 |
| R6 — pattern_log.json 스키마 | review §3 | §6.2 |
| R7 — Kill Switch 복구 절차 | review §3 | §2.4 + §5 |
| R8 — Hook 다이어그램 | review §3 | §7 |
| R9 — Phase A PoC 검증 | review §3 | §8.2 |
| R10 — Trade-Small 사이즈 | review §3 | §3 |
| R11 — discovery_log/pattern_log 관계 | review §3 | §7 |
| R12 — enabled 이중 구조 | review §4 | §5 strategy_config |
| R13 — launchd plist | review §4 | §12 |
| R14 — Phase 1.5 통합 | review §4 | (별도 작업 — HANDOFF) |
| R15 — 백테스트 데이터 소스 | review §4 | §8.3 |
| R16 — 테스트 시나리오 구분 | review §4 | §8.1 |
| **R17 — TradingAgents Bull/Bear 게이트** | review §4 P0 추가 | §2.1 Gate 6 + §5 |
| **R18 — Vibe-Trading ADX 필터** | review §4 P0 추가 | §2.1 Gate 2 + §5 |
| **R19 — Vibe-Trading 리스크 분석** | review §4 P0 추가 | §4 (closing_report) + §5 + §6.1 |
| R20 — 2-stage 유지 결정 | review §4 결정 | §2.1 Gate 6 (2-stage 명시) |
| R21 — 리스크 디폴트 별도 논의 | review §4 결정 | §9.3 |

---

*이 문서는 Stage 4 plan_final. 🔴 형진님 승인 전까지 Stage 5 (기술 설계) 진입 금지.*
*문서 위치: `docs/12_pattern_integration/04_plan_final.md`*
