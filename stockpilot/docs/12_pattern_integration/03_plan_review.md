# 🔍 Pattern Integration — Stage 3 Plan Review

> 작성일: 2026-05-06
> 단계: Stage 3 (Plan Review — 자체 검토)
> 입력: `02_plan_draft.md`
> 검토 노력: High
> 다음: Stage 4 plan_final.md (피드백 통합) → 🔴 형진님 승인

---

## 1. 종합 평가

**plan_draft 강점:**
- 5단 진입 게이트 / 추매 / 매도 통합 로직이 명료하게 분리됨
- Q1/Q2/Q3 형진님 결정사항이 plan 전반에 일관 반영
- Phase별 Exit 기준이 정량적으로 정의됨
- Phase 2 의존성이 명시됨 (선행 조건 9.1)

**plan_draft 약점:**
- Phase 2와의 통합 지점(코드 레벨) 구체성 부족
- Kelly-Lite × split_weights 조합 방식 미정의
- 서치/공급/라인 패턴의 검출 시간 단위(분봉 vs 일봉) 불명확
- Convergence Score 산식 누락 (PATTERN_INTEGRATION.md A2 참조 항목)
- 데이터 스키마 예시(pattern_log.json) 누락

→ **수정 제안 19건** (P0 6건 / P1 7건 / P2 5건 / 결정 기록 2건)
    - P0 차단: R1~R4 + R17(TradingAgents) + R18~R19(Vibe-Trading)
    - P1 보완: R5~R11
    - P2 개선: R12~R16
    - 결정 기록: R20(Bull-Bear 2-stage 유지), R21(리스크 디폴트 별도 논의)

---

## 2. P0 차단 — Stage 4 진입 전 반드시 해결

### R1. Phase 2 운영 안정화 의존성 — "권고"가 아니라 "필수"로 격상
**문제:** plan §10에서 "Phase 2 Trade-Full 안정화 이후 시작 권고" 표현. 하지만 실제로는 validator/position_monitor에 Gate 4·뚜껑 검출을 끼워넣어야 함 → Phase 2 미안정 시 본 작업이 Phase 2 코드를 깨뜨릴 위험.

**조치:** plan_final §10에서 **선행 조건**으로 격상.
- "Phase 2 Brief A~F 구현 완료 + Trade-Small 실거래 검증 통과 = 본 Plan Phase A 착수 게이트"
- 게이트 미통과 시 Stage 5 (기술 설계) 진입 금지

### R2. Kelly-Lite × split_weights 조합 방식 명시
**문제:** plan §3.1에서 신호 강도별 사이즈 multiplier 0.5/1.0/1.5 정의했으나, Phase 2의 분할매수 `split_weights: [0.5, 0.3, 0.2]`와 결합 방식 미정의.

**조치:** plan_final §6 strategy_config.json에 명시:
```
final_1st_buy_ratio = base × split_weights[0] × signal_multiplier
                    = base × 0.5 × {0.5/1.0/1.5}
                    = base × {0.25 / 0.50 / 0.75}
```
2차/3차 매수에는 multiplier 1.0 고정 (분할 의미 보존).

### R3. 서치 패턴 검출 시간 단위 명시
**문제:** plan §6 strategy_config.json `search_pattern.redrop_within_bars: 5`만 있고 "5봉이 분봉인지 일봉인지" 불명확.

**조치:** plan_final §3.1에 명시:
- 신규 진입 차단: **5분봉 5봉** (장중 실시간 차단)
- 보유 중 매도: **15분봉 3봉** (지연 허용)
- Shadow 통계: 일봉 5봉 (백테스트용)

### R4. Convergence Score 산식 정의
**문제:** PATTERN_INTEGRATION.md A2에서 "B+C 점수 + 패턴 점수 0~1 정규화 가중 합산"이라고만 표현. plan_draft는 이를 미반영.

**조치:** plan_final §3.1 [매수 사이즈 결정] 박스에 산식 추가:
```
b_c_score = (주봉우상향 ? 0.34 : 0) + (SMA20 위 ? 0.33 : 0) + (RSI 적정 ? 0.33 : 0)
pattern_score = 0.5 × supply_match + 0.5 × line_match  (각 0/1)
convergence = 0.6 × b_c_score + 0.4 × pattern_score   (가중치 튜너블)

강신호 = convergence ≥ 0.85
표준   = 0.65 ≤ convergence < 0.85
약신호 = 0.45 ≤ convergence < 0.65
거부   = convergence < 0.45
```

---

## 3. P1 보완 — Stage 4에 반영

### R5. 시장 레짐 분류 기준 구체화
**문제:** plan §6에서 `kospi_bear_threshold_pct: -1.0`만 있고 "어느 시점 -1%"인지 모호.

**조치:** plan_final 명시:
- 일봉 기준: 직전 5거래일 평균 등락률 -1% 이상 = 하락장
- 일중 기준: 09:30 시점 KOSPI -0.7% 이상 약세 = 당일 매수 제한
- 두 기준 모두 충족 = 신규 매수 정지

### R6. pattern_log.json 스키마 예시 추가
**문제:** plan §7.1에서 파일명만 명시, 스키마 부재.

**조치:** plan_final §7.1에 한 줄 예시 추가:
```jsonc
{
  "code": "005930",
  "pattern": "search",
  "detected_at": "2026-05-06T10:23:00",
  "context": {"timeframe": "5m", "high": 73000, "drop_pct": -3.2, "rebound_pct": 1.5, "redrop_bars": 4},
  "lifecycle": {
    "+24h_close": null, "+72h_close": null,
    "outcome": null,           // "true_positive" / "false_positive" / "neutral"
    "outcome_judged_at": null
  }
}
```

### R7. Kill Switch 복구 절차 명시
**문제:** plan §3.4 Kill Switch 발동 후 자동 해제 vs 수동 명령 미정의.

**조치:** plan_final 명시:
- 일중 누적 손실 -3% → 패턴 매매 중단 → **자정 자동 해제** (Phase 2 max_daily_loss와 동일 패턴)
- false positive 30% 초과 → 패턴 매매 중단 → **수동 `/패턴재시작` 명령 필요** (자동 해제 X — 검토 필수)

### R8. 코드 통합 지점 — validator.py / position_monitor.py 끼워넣기 위치
**문제:** plan §5에서 "Phase 2 validator/position_monitor 수정"만 표현, 구체적 hook 지점 미명시.

**조치:** plan_final에 hook 다이어그램 추가:
```
validator.py:
  preflight() →
    [기존] 시장시간 / 잔고 / 위험한도 검사
    + [NEW] Gate 4: signal_aggregator.check_search_pattern() → reject 시 거부 사유 반환

position_monitor.py:
  monitor_tick() →
    [기존] 손절/트레일링/익절/보류청산 검사
    + [NEW] tick_pattern_check(): 보유 종목 매 tick에서 뚜껑/서치 검출 → 트레일링 조기 활성 or 즉시 매도
```

### R9. 라인 검출기 PoC 출력 정의
**문제:** plan §8.5 Phase A Exit 기준 "라인 검출기 시각 검증"만 명시, "통과/실패" 정의 부재.

**조치:** plan_final 명시:
- PoC 입력: 임의 종목 1년 일봉 데이터
- PoC 출력: matplotlib 차트에 자동 검출된 지지/저항/추세선 오버레이 PNG
- 검증: 형진님 시각 확인 — "사람이 그릴 만한 라인과 일치도 70% 이상" → 통과

### R10. Trade-Small 실제 사이즈 정의
**문제:** plan §8.3 "정상 사이즈의 1/3 또는 1주 단위" 모호.

**조치:** plan_final 명시:
- 패턴 검출 종목 진입 시: 정상 사이즈 × **0.33** (1차 매수만, 추가 매수는 정상 룰)
- 1주 미만 종목은 1주 고정

### R11. discovery_log.json 와 pattern_log.json 관계
**문제:** intraday_discovery에서 검출된 종목 → 패턴 검출도 같은 파이프라인? 별도?

**조치:** plan_final 명시:
- intraday_discovery round 2/4/6/8 종료 시 → 발굴 종목 list → signal_aggregator.evaluate_batch() 호출
- evaluate_batch 내부에서 pattern_detector 실행 → 결과 pattern_log.json 기록
- discovery_log.json과 pattern_log.json은 `code + detected_at` 으로 join 가능

---

## 4. P0 추가 — TradingAgents Tier 1 차용 (2026-05-06 형진님 결정)

### R17. Bull/Bear 토론 게이트 도입 (TradingAgents 부분 차용)
**근거:** TauricResearch/TradingAgents 레포 조사(★69k Apache 2.0) 결과 풀스택 도입은 데이터·비용·철학 3중 충돌로 비추천. 단 **Bull/Bear 토론 구조**는 LLM 없이 결정론적 룰로 구현 가능하며 stockpilot의 양면 평가 부재 문제를 해결.

**문제:** plan_draft 5단 게이트는 단방향 평가(매수 신호 강도만 측정). 매수/매도 시그널이 동시에 발생할 때(예: B+C 충족 + 공급 검출 + 동시에 뚜껑 초기 형성) 충돌 처리 불명확.

**조치:** plan_final에 **Gate 6 — Bull/Bear 토론 게이트** 추가 (Gate 5 다음, 매수 사이즈 결정 직전):

```
[Gate 6] Bull/Bear 토론 게이트 (NEW — 결정론적 룰)

bull_score = (b_c_score × 0.4)
           + (supply_match × 0.2)
           + (line_match × 0.2)
           + (buy_orderbook_strength × 0.2)

bear_score = (search_match × 0.4)
           + (top_pattern_early × 0.3)
           + (sell_orderbook_strength × 0.2)
           + (bear_regime × 0.1)

decision_score = bull_score - bear_score

→ decision_score ≥ 0.5  : 진입 통과
→ 0.0 ≤ score < 0.5     : 약신호 (절반 사이즈)
→ score < 0.0            : 진입 거부 (Bear 우세)
```

**LLM 미사용 — 비용 0, 결정론적, 회귀 테스트 가능.** 향후 Phase 2 안정화 + 비용 모델링 후 LLM 토론으로 업그레이드 옵션 열어둠.

**strategy_config.json 추가:**
```jsonc
"bull_bear_gate": {
  "_comment": "TradingAgents Tier 1 차용 — 양면 평가 게이트",
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
}
```

**도입 시점:** Phase C (공급/라인) 도입 시 동시 활성화. Phase B 단독 진입은 부담스러움.

**Convergence Score(R4)와의 관계:** Gate 6 = R4 Convergence Score의 확장판 (bull-only → bull-vs-bear). plan_final §3.1 사이즈 결정 박스에서 R4 산식을 본 R17으로 대체.

### R18. ADX > 25 트렌드 강도 필터 추가 (Vibe-Trading 차용)
**근거:** HKUDS/Vibe-Trading의 `technical-basic` skill에서 추세 검증 표준 — EMA 크로스 + **ADX > 25** AND OBV > OBV_MA20. 횡보장에서 SMA/RSI 시그널이 빈번하게 거짓 양성을 만드는 문제를 ADX가 제거.

**문제:** 현재 B+C 정책은 추세 방향(주봉 SMA, 일봉 SMA20)만 판단하고 추세 **강도**를 측정하지 않음. 횡보장에서 SMA20을 살짝 돌파했다가 다시 빠지는 false breakout이 진입을 유도.

**조치:** plan_final §3.1 [Gate 2] B+C에 **4번째 조건** 추가:
```
[Gate 2] B+C 기본 조건 + ADX 필터 (수정)
  ✅ 주봉 SMA5 > SMA10
  ✅ 현재가 > 일봉 SMA20
  ✅ RSI 40~60
  ✅ ADX(14) ≥ 25  ← NEW (추세 강도)
```

**strategy_config.json 추가:**
```jsonc
"entry": {
  "adx_filter": {
    "_comment": "Vibe-Trading 차용 — 추세 강도 검증",
    "enabled": false,            // 단계적 활성화
    "period": 14,
    "threshold": 25.0,
    "rollout_phase": "shadow"
  }
}
```

**도입 시점:** Phase B (서치 필터) 동시 활성화. Phase A 인프라 단계에서 ADX 함수 추가 검증 완료 후.

**예상 효과:** 횡보장 false breakout 진입 -30% 이상 감소 (V1 차용 출처 통계 기반 추정).

### R19. VaR/CVaR/스트레스 시나리오 closing_report 통합 (Vibe-Trading 차용)
**근거:** Vibe-Trading의 `risk-analysis` skill 정량 룰 — VaR(95%/99%) + CVaR + MDD + 5종 역사적 스트레스 시나리오 + 4종 가설 시나리오. stockpilot 현재 closing_report는 일별 자산 변화만 표시, 시나리오 기반 리스크 노출 평가 없음.

**문제:** 보유 종목이 많아질수록 포트폴리오 차원의 스트레스 노출 측정 부재. 단일 종목 -3% 손절은 잘 작동하지만, 시장 폭락 시 포트폴리오 전체 노출은 추적 불가.

**조치:** plan_final §5에 closing_report.py 수정 항목 추가:

```python
# closing_report.py 신규 섹션 — "리스크 분석"
- VaR(95%, 1일): 역사적 방법 (직전 60일 일별 수익률 5% percentile)
- CVaR(95%): VaR 초과 손실 평균 (꼬리 위험)
- MDD: 직전 60일 peak-to-trough
- 스트레스 시나리오 5종 (한국 시장 데이터로 swap):
  · 2008 글로벌 금융위기: KOSPI -54%
  · 2011 유럽 재정위기: KOSPI -22%
  · 2018 미중 무역전쟁: KOSPI -25%
  · 2020 코로나 쇼크: KOSPI -34%
  · 2022 금리인상: KOSPI -25%
- 포트폴리오 손절 임계값: -15% (스트레스 테스트 통과 기준)
```

**텔레그램 메시지 추가 섹션 (예시):**
```
📊 리스크 분석 (2026-05-06)
- VaR(95%): -2.3% (당일 95% 확률 최대 손실)
- CVaR(95%): -3.1% (꼬리 위험)
- MDD(60일): -8.7%
- 스트레스 노출 (코로나급 -34% 시): -12.1% ✅
- 포트폴리오 손절 임계: -15% (현재 -8.7%, 안전)
```

**strategy_config.json 추가:**
```jsonc
"risk_analysis": {
  "_comment": "Vibe-Trading 차용 — 일일 포트폴리오 리스크 보고",
  "enabled": false,
  "var_confidence": 0.95,
  "var_lookback_days": 60,
  "portfolio_stop_loss_pct": -15.0,
  "stress_scenarios_enabled": true
}
```

**도입 시점:** Phase A 인프라 (백테스트 환경 구축 시 KOSPI 시나리오 데이터 수집 동시 진행).

**비고:** 한국 시장 스트레스 시나리오 수치는 KOSPI 일봉 데이터로 백테스트해서 보정 필요 (Phase A 작업).

### R20-결정. Bull-Bear 게이트 — 2-stage 유지 (Vibe-Trading 4-stage 미채택)
**형진님 결정 (2026-05-06):** Q3 = B — TradingAgents 원안 2-stage(Bull/Bear) 유지. Vibe-Trading의 4-stage(Bull → Bear → CRO → PM) 미채택.

**근거:** 단순성 우선. CRO 단계 추가 시 게이트 복잡도 ↑ + 정량 룰 정의 부담. 단, R17 Bear 측 weights에 `bear_regime` (시장 레짐 약세 가산점) 포함되어 있어 CRO의 핵심 기능(거시 리스크 검토) 일부 흡수.

**향후 옵션:** Phase B/C 운영 결과 false positive율 검토 후 4-stage 확장 재논의.

### R21-결정. 리스크 디폴트 재검토 — 별도 논의 트랙
**형진님 결정 (2026-05-06):** Q4 = C — 형진님 운영 데이터 기반 재결정. plan_final 본문에 반영 X.

**현 정책 vs QuantDinger 보수형 비교 (참조용):**
| 파라미터 | stockpilot 현재 | QuantDinger 보수형 |
|---------|----------------|-------------------|
| 손절 | -3.0% | -2.0% |
| 익절 | +5.0% | +5.0% |
| 트레일 활성 | +2.0% | +3.0% |
| 트레일 폭 | -3.0% | -1.5% |

**조치:** plan_final §9.3 (미해결) 항목으로 명시. Phase 2 Trade-Small 실거래 데이터 30~50건 누적 후 별도 stage로 재논의.

---

## 5. P2 개선 — 여유 있을 때 반영

### R12. enabled 이중 구조 명시
- `pattern_detection.enabled` = 마스터 스위치 (전체 ON/OFF)
- `pattern_detection.<each>.enabled` = 개별 패턴 스위치
- 평가 순서: 마스터 OFF → 모든 패턴 무시 / 마스터 ON → 개별 enabled 평가

### R13. launchd plist 추가 검토
- pattern_lifecycle.py 후속 가격 추적 = 일별 1회 실행 필요 → 신규 plist `com.aigeenya.stockreport.pattern_lifecycle.plist` 23:35 실행 (closing_report 5분 후)
- 그 외 모듈은 기존 launchd에 통합 (intraday_discovery, position_monitor 등)

### R14. Phase 1.5 (전날 발굴 성과 요약) 와 통합
- HANDOFF.md Phase 1.5 = "모닝 리포트에 전날 발굴 성과 요약 추가"
- 패턴 검출 통계도 같은 섹션에 — 일별 검출 수, 24h/72h 승률 누적값
- 따로 Phase 만들 필요 없음

### R15. 백테스트 데이터 소스
- 기존 KIS API daily 데이터로 충분 (1년치)
- 분봉 백테스트는 Phase A에서 별도 검토 (KIS rate limit 우려)

### R16. 단위 테스트 / 백테스트 / 실거래 시나리오 구분
- 단위 테스트: 각 패턴 검출 함수 input/output (`tests/test_pattern_detector.py`)
- 백테스트: 1년 일봉 → 패턴 검출 + 후속 5일 수익률 통계
- 실거래 시나리오: dry-run 모드 + Shadow 1주

---

## 5. 검토자 결론

**plan_draft 통과 가능 여부:** 🟡 조건부 통과 — P0 6건 반영 후 Stage 4 진입 가능.

**Stage 4 작업 지시:**
1. P0 6건 (R1~R4 + R17~R19) 본문 반영 필수
2. P1 7건 (R5~R11) 가능한 한 반영 (시간 부족 시 일부 Stage 5로 이월 가능)
3. P2 5건 (R12~R16) Stage 5에서 반영해도 무방
4. 결정 기록 2건 (R20, R21) — R20은 plan_final §3.1에 2-stage 명시, R21은 §9.3 미해결 항목

**형진님 승인 요청 시점:** Stage 4 plan_final.md 완료 후, 본 review.md와 함께 제출.

---

*이 문서는 Stage 3 자체 검토. Claude Sonnet High effort 시뮬레이션 결과.*
