# 📘 Briefing Enhancement — Stage 4 Plan Final

> 작성일: 2026-05-06
> 단계: Stage 1 (brainstorm 제외) → Stage 2~4 통합 → 형진님 결정 누적 반영
> 입력: 형진님 결정 Q1=C(통합), Q2=A(B 3개 모두), Q3=B(직접), 권고 Plan 2(분리)
> 다음: 직접 5건 즉시 진행 → Codex 위임 3건 brief

---

## 0. 결정 기록

| ID | 결정 | 일자 |
|----|------|------|
| Q1 | 묶음 단위 = 통합 plan (1개) | 2026-05-06 |
| Q2 | 그룹 B 3개 모두 도입 (B1+B2+B3) | 2026-05-06 |
| Q3 | 진행 방식 = 직접 (Plan 2 권고 채택 — 핵심 5건 직접 + 큰 3건 Codex) | 2026-05-06 |
| 보충 | brainstorm Stage 제외 — Stage 2~4 통합 | 2026-05-06 |

**Plan 2 채택 이유:** A1 (cron 18개 등록)은 시각 오류 시 매일 잘못된 알림 발송 위험. B3/C1 신규 모듈은 정확성 검증 부담 → 안전성 우선.

---

## 1. 전체 작업 9건 (그룹 B + A + C 통합)

| # | 작업 | 담당 | 분류 | 분량 | 상태 |
|---|------|------|------|------|------|
| **B1** | 모닝 전날 발굴 성과 요약 | 🟢 직접 | 핫픽스 | 중 | 🔴 진행 |
| **B2** | 모닝 KOSPI 시장 레짐 표시 | 🟢 직접 | 핫픽스 | 작음 | 🔴 진행 |
| **B3** | 클로징 VaR/CVaR/스트레스 | 🔴 Codex | 신규 모듈 | 큼 | 🔴 brief 작성 |
| **A1** | 시간대 확장 (10/11/12/13/15시) | 🔴 Codex | 신규 기능+cron | 매우 큼 | 🔴 brief 작성 |
| **A2** | 시간대별 임계값 차등 | 🟢 직접 | 핫픽스 | 중 | 🔴 진행 |
| **A3** | 12시 신뢰도 표시 | 🟢 직접 | 핫픽스 | 작음 | 🔴 진행 |
| **C1** | pattern_lifecycle 모듈+plist | 🔴 Codex | 신규 모듈+cron | 큼 | 🔴 brief 작성 |
| **C2** | 통계 대시보드 (closing 섹션) | 🟢 직접 | 핫픽스 | 중 | 🟡 C1 후 |
| ※ | (필터 완화 — 이미 적용) | ✅ 완료 | 핫픽스 | - | ✅ v2.8.0 |

---

## 2. 직접 핫픽스 5건 — 상세 명세

### B1 — 모닝 전날 발굴 성과 요약
**파일:** `morning_report/morning_report.py`
**변경:**
- 전날(전일 거래일) `data/discovery_log.json` 레코드 추출
- `close_price` / `return_pct` 가 있는 종목만 통계
- 텔레그램 메시지에 "📊 어제 발굴 성과" 섹션 추가

**메시지 예시:**
```
📊 어제 발굴 성과 (2026-05-05)
- 발굴 3종목 → 평균 +1.8%
- 🥇 카카오뱅크(323410) 5점 → +3.2%
- 🥈 LG디스플레이(034220) 4점 → +1.1%
- 🥉 카카오페이(377300) 4점 → +1.1%
```

**검증:** dry-run + 실제 메시지 형식 확인

### B2 — 모닝 KOSPI 시장 레짐 표시
**파일:** `morning_report/morning_report.py` + (data_fetcher.py 가능)
**변경:**
- KOSPI 5거래일 평균 등락률 계산 (yfinance ^KS11 또는 KIS API daily)
- 분류 기준:
  - 추세장 (5일 평균 ≥ +0.3%)
  - 횡보장 (-0.3% ~ +0.3%)
  - 하락장 (≤ -0.3%)
- 텔레그램에 "📊 시장 레짐" 섹션 추가

**메시지 예시:**
```
📊 시장 레짐: 추세장 (KOSPI 5일 +1.2%)
```

**검증:** dry-run

### A2 — 시간대별 임계값 차등
**파일:** `morning_report/intraday_discovery.py`
**변경:** `_score_candidate()` 호출 시 현재 시각 전달 → 시간대별 임계값 분기

```python
# 현재 시각 기반 임계값
def _get_thresholds(hour: int) -> tuple[float, float]:
    """(pow_2 임계, flc_2 임계)"""
    if hour in (9, 14):  return (110, 2.0)   # 모멘텀 강
    if hour in (10, 13): return (115, 2.0)   # 약간 보수
    if hour in (11, 15): return (115, 2.5)   # 보수
    if hour == 12:       return (125, 3.0)   # 점심 — 가장 보수
    return (110, 2.0)  # 기본값 (안전)
```

**검증:** 단위 테스트 6건 (9/10/11/12/13/14/15시)

### A3 — 12시 신뢰도 표시
**파일:** `morning_report/intraday_discovery.py` (`_build_message_*`)
**변경:** 12시 시간대인 경우 헤더에 신뢰도 표시 추가

```python
# 헤더 변경
if hour == 12:
    header = f"🔍 {_korean_hm(time_str)} 발굴 (점심 신뢰도 ↓)"
else:
    header = f"🔍 {_korean_hm(time_str)} 발굴"
```

**검증:** 단위 테스트

### C2 — 통계 대시보드 (C1 후속, 보류)
C1 완료 + 데이터 누적 후 별도 작업.

---

## 3. Codex 위임 brief 3건 — 작성 예정

| Brief | 파일 | 범위 |
|-------|------|------|
| **Brief 13-A** | `docs/13_briefing_enhancement/06_codex_brief_a1.md` | A1 시간대 확장 (round 9~26 + plist 18) |
| **Brief 13-B** | `docs/13_briefing_enhancement/07_codex_brief_b3.md` | B3 risk_analyzer.py + closing_report 통합 |
| **Brief 13-C** | `docs/13_briefing_enhancement/08_codex_brief_c1.md` | C1 pattern_lifecycle.py + plist 등록 |

---

## 4. 진행 순서

```
[Step 1 — 즉시] 직접 핫픽스 4건
   B1 → B2 → A2 → A3
   (각 변경 후 py_compile + 단위 테스트)

[Step 2 — Codex 위임 준비]
   Brief 13-A / 13-B / 13-C 작성
   형진님 검토 후 Codex 호출

[Step 3 — Codex 구현 후]
   Stage 9 Opus 코드 리뷰 (3 brief 각각)
   Stage 10 Codex 수정 (필요 시)
   Stage 11 최종 검증

[Step 4 — C2]
   C1 완료 + 데이터 누적 1주 후 진행
```

---

## 5. 검증 전략

| 작업 | 단위 테스트 | dry-run | 통합 |
|------|-----------|---------|------|
| B1 | 전날 데이터 추출 함수 | morning_report --dry-run | 내일 08:30 자동 실행 |
| B2 | KOSPI 등락률 함수 | morning_report --dry-run | 내일 08:30 |
| A2 | 시간대 임계값 함수 | intraday_discovery --round 2 --debug | 내일 09:05 |
| A3 | 12시 헤더 분기 | (12시 발굴 도입 후 검증) | A1 도입 시 동시 |

---

## 6. 리스크

| 리스크 | 영향 | 대응 |
|--------|------|------|
| B1 — 어제 발굴 0건 | 빈 섹션 표시 | "어제는 발굴 종목 없었음" 메시지 fallback |
| B2 — yfinance ^KS11 fetch 실패 | 시장 레짐 N/A | 표시 생략 + 로그만 |
| A2 — 시간대 외 호출 | 기본값(110/2.0) 사용 | 안전 fallback |
| A3 — 12시 도입 전 | 표시 분기 자동 무시 | A1 도입 시 동시 활성 |

---

## 7. 변경 이력

| 일자 | 항목 |
|------|------|
| 2026-05-06 | plan_final 작성 (brainstorm 제외, Stage 2~4 통합) |
| TBD | 직접 5건 핫픽스 완료 |
| TBD | Codex 위임 3건 brief 작성 |
| TBD | Codex 구현 + Stage 9 리뷰 |
| TBD | 통합 검증 + HANDOFF v2.8.x 갱신 |

---

*이 문서는 Stage 4 plan_final. brainstorm 제외 + Stage 2/3 통합 + 형진님 권고 채택 누적.*
*문서 위치: `docs/13_briefing_enhancement/04_plan_final.md`*
