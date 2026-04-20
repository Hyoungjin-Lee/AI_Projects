# Stage 2 — 계획 초안: intraday_discovery 고도화

> 작성일: 2026-04-21
> 담당: Claude (Sonnet)
> 입력: docs/08_phase1_intraday/brainstorm.md

---

## 1. 문제 진술

intraday_discovery는 매일 종목을 발굴하지만:
1. 발굴 성과 데이터가 없어 필터 기준값 개선 근거가 없다
2. 텔레그램 메시지가 top3만 보여줘 4~5위 후보를 놓친다

---

## 2. 범위

**포함:**
- `intraday_discovery.py` — 발굴 시점 데이터를 `discovery_log.json`에 기록
- `closing_report.py` — 장마감 시 발굴 종목 종가를 `discovery_log.json`에 업데이트
- `intraday_discovery.py` — 텔레그램 메시지에 4~5위 후보 추가

**제외 (Phase 1.5):**
- 모닝 리포트에 전날 발굴 성과 요약 추가
- 발굴 성과 통계 대시보드

---

## 3. 성공 기준

- [ ] 발굴 실행 시마다 `discovery_log.json`에 자동 기록
- [ ] 당일 closing_report 실행 후 발굴 종목의 종가·수익률 자동 업데이트
- [ ] 텔레그램 메시지에 후보 4~5위 "관심 후보" 섹션 표시 (후보 4개 이상일 때)
- [ ] 기존 발굴 로직 동작 변경 없음 (필터·점수 체계 유지)

---

## 4. 구현 대상 파일

| 파일 | 변경 내용 |
|------|-----------|
| `morning_report/intraday_discovery.py` | 발굴 결과 → `discovery_log.json` 기록 + 메시지 개선 |
| `morning_report/closing_report.py` | 발굴 종목 종가 → `discovery_log.json` 업데이트 |
| `data/discovery_log.json` | 신규 생성 (없으면 자동 생성) |

---

## 5. discovery_log.json 스키마 (안)

```json
[
  {
    "date": "2026-04-21",
    "disc_time": "09:05",
    "code": "080010",
    "name": "이수페타시스",
    "disc_price": 45200,
    "score": 6,
    "pow_2": 145.3,
    "flc_2": 4.2,
    "close_price": null,
    "return_pct": null,
    "updated_at": null
  }
]
```

- `close_price`: 장마감 후 closing_report가 채움
- `return_pct`: `(close_price - disc_price) / disc_price * 100`
- 최대 30일치 보관 (30일 초과 시 오래된 항목 자동 삭제)

---

## 6. 리스크

| 리스크 | 대응 |
|--------|------|
| closing_report에서 발굴 종목 가격 조회 실패 | try/except로 감싸고 `close_price: null` 유지 |
| discovery_log.json 파일 손상 | 읽기 실패 시 빈 리스트로 초기화 후 계속 진행 |
| 발굴 종목이 0개일 때 | 기록 없이 정상 종료 |

---

## 7. 다음 단계

Stage 3 (계획 검토) → Stage 4 (계획 통합) → Stage 5 (기술 설계) → Codex 위임
