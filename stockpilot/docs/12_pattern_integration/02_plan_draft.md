# 📋 Pattern Integration — Stage 2 Plan Draft

> 작성일: 2026-05-06
> 단계: Stage 2 (Plan Draft)
> 입력: `docs/01_brainstorm/PATTERN_INTEGRATION.md`, `docs/STRATEGY_GUIDE_EASY.md`, 형진님 권고안 채택
> 다음: Stage 3 (자체 검토) → Stage 4 (plan_final + 형진님 승인)

---

## 1. 목적 (Why)

기존 추세추종 B+C 정책에 5종 패턴 매매법(바닥/뚜껑/서치/공급/라인)을 **선택적·단계적**으로 통합하여:

1. 신규 매수 진입 게이트 강화 (서치 함정 차단 + 공급/라인 신뢰도 확정)
2. 추가 매수 정확도 향상 (바닥 패턴으로 평단 낮추기)
3. 익절 보호 강화 (뚜껑 패턴으로 트레일링 조기 발동)
4. 시장 상황별 자동 보수화 (레짐 필터)

---

## 2. 형진님 확정 결정사항 (2026-05-06)

| ID | 질문 | 결정 |
|----|------|------|
| Q1 | 도입 순서 | **A — 서치 → 공급/라인 → 바닥/뚜껑 → 레짐** |
| Q2 | 약신호 처리 | **B — 절반 사이즈 진입 (Kelly-Lite)** |
| Q3 | 단계적 롤아웃 | **A — Shadow 1~2주 → 통계 후 Live** |

PATTERN_INTEGRATION.md의 D1~D4 (정책 결정) 중 본 plan에서 추가로 정리:

| ID | 질문 | 본 Plan의 답변 |
|----|------|---------------|
| D1 | 패턴 매매 도입 정책 | A안 — B+C 보조로 통합 (별트랙 X) |
| D2 | 바닥 패턴 사용 여부 | 보조적 사용 — **추가매수 트리거에만** (신규 진입 X) |
| D3 | 자본 분할 정책 | 보류 (Phase 2 운영 안정화 후 재논의) |
| D4 | AI 차트 해석 비용 | 보류 (Phase D에서 별도 검토) |

---

## 3. 핵심 설계 — 5단 진입 게이트 + 추매/매도 통합

### 3.1 신규 매수 — 5단 게이트

```
[Gate 1] 시장 레짐 필터
  추세장/횡보장 → 통과
  하락장 (KOSPI -1% 이상 약세) → 신규 매수 정지
       ↓
[Gate 2] B+C 기본 조건 (변경 없음)
  주봉 SMA5 > SMA10
  현재가 > 일봉 SMA20
  RSI 40~60
       ↓
[Gate 3] 공급/라인 패턴 — 진입 신뢰도 확정 (NEW)
  공급: 수평 지지선에서 매수 흡수 + 반등
  라인: 상승 추세선 따라 매수 누적
  → 둘 다 검출 = 강신호 (1.5배)
  → 하나 검출 = 표준 신호 (1.0배)
  → 둘 다 없음 = 약신호 (0.5배 — Kelly-Lite)
       ↓
[Gate 4] 서치 함정 차단 — 진입 거부권 (NEW) 🥇 1순위
  서치 패턴 검출 → 무조건 진입 거부
  검출 안 됨 → 통과
       ↓
[Gate 5] 호가/체결강도 확인 (선택)
  매수 호가 누적 + 체결강도 ≥ 100 → 신뢰도 +
       ↓
[매수 사이즈 결정]
  강신호 = base × 1.5
  표준   = base × 1.0
  약신호 = base × 0.5
```

### 3.2 추가 매수 (분할 2차/3차)

```
기본 룰 (Phase 2): 평단 -1~-2% 눌림 + SMA20 위 + 1일 경과
                            ↓
[NEW] 바닥 패턴 추가 트리거:
  평단 -1~-2% 구간에서 바닥 패턴 검출 시 추매 신호
   - 긴 아래꼬리 (매수 흡수)
   - 거래량 다이버전스
   - 직전 저점 흡수 후 반등
                            ↓
[필수] 서치 패턴 재확인:
  보유 중에도 서치 검출 시 추매 거부 + 보유 정리 알림
```

### 3.3 매도 (트레일링 조기 발동)

```
기존 트레일링: 평단 +2% 활성화 → 5일 고가 -3% 이탈 청산
                            ↓
[NEW] 뚜껑 패턴 검출 시: 평단 +1%부터 조기 활성화
   - 1차→2차→3차 상승봉 누적
   - 거래량 다이버전스 (가격↑ + 거래량↓)
                            ↓
[NEW] 서치 패턴 검출 시: 즉시 매도 (하드스탑 -3% 도달 전)
```

### 3.4 강제 정지 트리거

```
시장 레짐 = 하락장:
  - 신규 매수 전면 정지 (Gate 1에서 차단)
  - 추가 매수 정지
  - 보유 종목은 일반 매도 룰 그대로

Kill Switch (PATTERN_INTEGRATION.md E2):
  - 일중 누적 손실 -3% → 패턴 매매 전면 정지
  - 직전 20건 false positive 30% 초과 → 자동 비활성화
```

---

## 4. 도입 순서 (Phased Rollout)

| Phase | 기간 | 내용 | 진입 영향 | 매도 영향 |
|-------|------|------|----------|----------|
| **A. 인프라** | 2주 | 라인 검출기, HA 캔들, 백테스트 환경 | — | — |
| **B. 서치 필터** | 2주 | Gate 4 + 매도 가속기 | 거부권 | 즉시 매도 |
| **C. 공급/라인** | 3주 | Gate 3 + Kelly-Lite 사이징 | 신뢰도 + 사이즈 | — |
| **D. 바닥/뚜껑** | 2주 | 추매 트리거 + 트레일링 조기 발동 | — | 트레일링 + |
| **E. 레짐 필터** | 1주 | Gate 1 + Kill Switch | 시장 정지 | — |

각 Phase는 **Shadow → Alert → Trade-Small → Trade-Full** 4단계로 점진 활성화.

---

## 5. 신규 코드 모듈

| 모듈 | 역할 | 의존성 |
|------|------|--------|
| `morning_report/line_detector.py` | 수평 지지/저항 + 추세선 자동 검출 (모든 패턴 기반) | numpy, pandas |
| `morning_report/heiken_ashi.py` | HA 캔들 변환 함수 | pandas |
| `morning_report/pattern_detector.py` | 5종 패턴 검출 메인 (바닥/뚜껑/서치/공급/라인) | line_detector, heiken_ashi |
| `morning_report/regime_classifier.py` | 시장 레짐 분류 (KOSPI 일봉 기반 ADX/변동성) | indicators.py |
| `morning_report/signal_aggregator.py` | Gate 1~5 통합 + Convergence Score + Kelly-Lite 사이징 | pattern_detector, regime_classifier |
| `morning_report/pattern_lifecycle.py` | 검출된 모든 패턴 후속 가격 추적 + 승률 통계 | data/pattern_log.json |

### 기존 모듈 수정

| 모듈 | 수정 내용 |
|------|----------|
| `morning_report/intraday_discovery.py` | round 2/4/6/8 종목 발굴 시 signal_aggregator 호출 |
| `morning_report/validator.py` (Phase 2) | Gate 4 (서치 거부권) 통합 |
| `morning_report/position_monitor.py` (Phase 2) | 보유 종목 매 tick 뚜껑/서치 검출 → 매도 트리거 |
| `data/strategy_config.json` | `pattern_detection` 섹션 신설 |
| `docs/STRATEGY.md` | 패턴 통합 정책 섹션 추가 |

---

## 6. strategy_config.json 확장 스키마 (초안)

```jsonc
{
  "pattern_detection": {
    "_comment": "5종 패턴 검출 + Kelly-Lite 사이징 + 단계적 롤아웃",
    "enabled": false,                      // Phase A 인프라 완료 후 true
    "rollout_phase": "shadow",             // shadow / alert / trade_small / trade_full

    "search_pattern": {
      "_comment": "Gate 4 — 진입 거부권 + 매도 가속기 (1순위 도입)",
      "enabled": false,
      "min_drop_pct": 3.0,                 // 고점에서 -3% 이상 급락
      "absorption_volume_ratio": 1.5,      // 흡수 거래량 > 평균 1.5배
      "false_rebound_max_pct": 2.0,        // 가짜 반등 +2% 이내
      "redrop_within_bars": 5,             // 5봉 이내 재급락
      "action_on_entry": "reject",         // reject / warn
      "action_on_holding": "force_sell"    // force_sell / alert
    },

    "supply_pattern": {
      "_comment": "Gate 3 — 공급(수평 지지) 진입 신뢰도",
      "enabled": false,
      "support_lookback_days": 60,
      "support_touch_count_min": 2,
      "absorption_volume_ratio": 1.3
    },

    "line_pattern": {
      "_comment": "Gate 3 — 라인(추세선) 진입 신뢰도",
      "enabled": false,
      "trendline_lookback_days": 30,
      "min_touch_points": 3,
      "max_deviation_pct": 1.0
    },

    "bottom_pattern": {
      "_comment": "추가매수 트리거 (Phase D 도입)",
      "enabled": false,
      "lower_wick_min_ratio": 0.6,         // 아래꼬리 / 캔들 전체
      "volume_divergence": true,           // 거래량 다이버전스 필수
      "prev_low_break_pct": 0.5            // 직전 저점 -0.5% 이내 흡수
    },

    "top_pattern": {
      "_comment": "트레일링 조기 발동 트리거 (Phase D 도입)",
      "enabled": false,
      "stack_count_min": 3,                // 1차→2차→3차 상승봉
      "volume_divergence": true,
      "trailing_early_activate_pct": 1.0   // 평단 +1%부터 트레일링
    },

    "regime_filter": {
      "_comment": "Gate 1 — 시장 레짐 필터 (Phase E)",
      "enabled": false,
      "kospi_bear_threshold_pct": -1.0,    // KOSPI -1% 이상 = 하락장
      "adx_trend_min": 25,                 // ADX ≥ 25 = 추세장
      "halt_buys_on_bear": true
    },

    "sizing": {
      "_comment": "Kelly-Lite 신호 강도별 사이징",
      "weak_signal_multiplier": 0.5,
      "standard_signal_multiplier": 1.0,
      "strong_signal_multiplier": 1.5
    },

    "kill_switch": {
      "_comment": "Pattern E2 — 긴급 정지",
      "daily_loss_pct_limit": -3.0,
      "false_positive_window": 20,
      "false_positive_threshold_pct": 30.0
    }
  }
}
```

---

## 7. 데이터 인프라

### 7.1 신규 데이터 파일

| 파일 | 용도 | 쓰기 주체 |
|------|------|----------|
| `data/pattern_log.json` | 검출된 모든 패턴 + 후속 가격 추적 | pattern_lifecycle.py |
| `data/regime_state.json` | 일별 시장 레짐 분류 결과 | regime_classifier.py (08:30 morning_report 시) |

### 7.2 KIS API 권한 점검 (사전 확인)

- [ ] 분봉 OHLCV (5분/15분/1시간) — 라인 검출용
- [ ] 호가 10단계 — Gate 5
- [ ] 체결강도 (FHKST01010300) — 이미 v2.3에서 통합 (kis_client.get_ccnl)

---

## 8. 테스트/검증 전략

### 8.1 Shadow 모드 (각 Phase 시작 시 1~2주)

- 패턴 검출 실행 + 검출 결과만 로그 (`data/pattern_log.json`)
- 실제 매수/매도 의사결정에는 영향 없음
- 1주~2주 후 통계:
  - 검출 빈도 (일평균)
  - 후속 24시간/72시간 승률
  - false positive 비율

### 8.2 Alert 모드 (Shadow 통과 후)

- 텔레그램에 패턴 검출 알림만 전송
- 형진님 수동 매매 의사결정에 참고
- 1주 후 통계 재확인

### 8.3 Trade-Small (Alert 통과 후)

- 정상 사이즈의 1/3 또는 1주 단위 자동 매매
- 5건~10건 표본 누적

### 8.4 Trade-Full

- 정상 사이즈 자동 매매

### 8.5 Exit 기준 (Phase별)

| Phase | Exit 기준 |
|-------|-----------|
| A. 인프라 | 라인 검출기 시각 검증 — 임의 종목 1년 데이터 |
| B. 서치 | 진입 거부권 활성화 종목 후속 5일 평균 수익률이 미활성 종목 대비 유의미하게 낮음 |
| C. 공급/라인 | 표본 50건 이상 + 기존 B+C 단독 대비 승률 또는 R:R 개선 |
| D. 바닥/뚜껑 | 추매 후 평단 개선 효과 통계 + 트레일링 조기 발동 익절률 향상 |
| E. 레짐 | 하락장 신규 매수 정지가 손실 회피에 기여한 표본 |

---

## 9. 리스크 / 미해결 항목

### 9.1 기술 리스크
- **라인 검출의 주관성** — 동일 차트에서 사람마다 다른 라인. 알고리즘 합의 기준 필요 (PoC에서 검증)
- **Phase 2 통합 부담** — Phase 2 (승인형 매수) 운영 안정화 전 도입 시 복잡도 ↑. **Phase 2 Trade-Full 진입 후 시작 권장**
- **백테스트 overfitting** — 과거 데이터 최적화 결과가 실거래와 괴리될 가능성

### 9.2 운영 리스크
- KIS API rate limit — 분봉 + 호가 동시 호출 빈도 제한
- 패턴 검출 false positive — Anti-Pattern 라이브러리(D2) 없이 시작 시 누적 통계로만 보정

### 9.3 미해결 (D3/D4 — 본 Plan 범위 외)
- 자본 90/10 분할 (메인/실험) → Phase 2 운영 안정화 후 별도 논의
- AI 차트 해석 이중 검증 → Phase D 이후 별도 검토

---

## 10. 의존성 / 선행 조건

| 항목 | 상태 |
|------|------|
| Phase 2 (승인형 매수 + 자동 매도) Trade-Small 이상 진입 | 🔴 미완료 — Brief A~D 설계 단계 |
| KIS API 분봉/호가 권한 점검 | 🔴 미점검 |
| 백테스트 환경 | 🔴 미구축 |
| `data/pattern_log.json` 스키마 | 🟡 본 Plan에서 초안 |

**권고:** 본 Pattern Integration은 **Phase 2가 Trade-Full 안정화된 이후** Phase A 인프라부터 시작.

---

## 11. 정량 성공 기준

| 지표 | 목표 |
|------|------|
| 서치 필터 도입 후 false breakout 진입 비율 | -50% 이상 감소 |
| 공급/라인 신호 가중 진입 평균 수익률 | 기존 B+C 단독 대비 +1%p 이상 |
| 바닥 추매 후 평균 평단 개선 | -0.5% 이상 |
| 뚜껑 트레일링 조기 발동 익절률 | 기존 트레일링 대비 +5%p |
| 레짐 필터 하락장 신규 매수 정지 손실 회피 | 표본 10건 이상 |

---

## 12. 다음 단계

1. **Stage 3 자체 검토** (Claude Sonnet High effort) — 본 plan_draft 검토 + 16건 이내 수정 제안
2. **Stage 4 plan_final** — 검토 피드백 통합 → **🔴 형진님 승인 대기**
3. **Stage 5 기술 설계** — Phase A (인프라) 부터 단계적 설계
4. **Stage 8 Codex 위임** — Phase A 인프라 brief 작성

---

*이 문서는 Stage 2 plan_draft. Stage 4 plan_final.md 형진님 승인 전까지는 Stage 5 (기술 설계) 진입 금지.*
