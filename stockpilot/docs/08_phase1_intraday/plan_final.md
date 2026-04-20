# Stage 4 — 확정 계획: intraday_discovery 고도화

> 작성일: 2026-04-21
> 담당: Claude (Sonnet)
> 입력: plan_draft.md + plan_review.md

---

## 1. 최종 범위

### 포함
1. **발굴 성과 추적 DB** — `data/discovery_log.json`
   - `intraday_discovery.py`: 발굴 시 기록
   - `closing_report.py`: 장마감 시 종가·수익률 업데이트
2. **텔레그램 메시지 개선**
   - 후보 4개 이상 시 하단에 "관심 후보" 섹션 추가

### 제외 (Phase 1.5)
- 모닝 리포트 발굴 성과 요약
- 성과 통계 대시보드

---

## 2. 확정 스키마 — discovery_log.json

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

- `disc_price`: 거래량 API 응답의 `stck_prpr` (발굴 시점 현재가)
- `close_price`: closing_report 실행 시 `kis_client.get_current_price(code)` 로 채움
- `return_pct`: `round((close_price - disc_price) / disc_price * 100, 2)`
- `updated_at`: 종가 업데이트 시각 (ISO 형식)
- **30일 보관**: 기록 시 `date` 기준 30일 이전 항목 자동 삭제

---

## 3. 확정 텔레그램 메시지 포맷

```
🔍 장초기 종목 발굴 (09:05)
―――――――――――――――
코스피200 실시간 분석

🥇 이수페타시스 (080010)  6점
   체결강도: 145 (+12↑) | 등락률: +4.2%↑ | 거래량↑
   🌐 온라인 관심 2위

🥈 삼성전자 (005930)  5점
   체결강도: 128 (+3↑) | 등락률: +3.1%↑ | 거래량↑

🥉 SK하이닉스 (000660)  4점
   체결강도: 115 | 등락률: +2.8%↑ | 거래량→

―――――――――――――――
📋 추가 관심 후보
  4위 LG에너지솔루션 (373220) — 체결강도: 112 | +2.3%
  5위 카카오 (035720) — 체결강도: 111 | +2.1%
―――――――――――――――
후보 8종목 → 상위 3종목 선정
```

- 후보 3개 이하: 기존과 동일 (추가 섹션 없음)
- 후보 4개: 4위만 표시
- 후보 5개 이상: 4~5위 표시 (최대 2개)

---

## 4. 파일별 변경 상세

### intraday_discovery.py
- `_run_round2()` 마지막에 `_save_discovery_log(scored, volume_rows)` 호출 추가
- `_save_discovery_log()` 신규 함수: discovery_log.json에 오늘 발굴 결과 append
- `_build_message()` 수정: 후보 4개 이상 시 "추가 관심 후보" 섹션 추가

### closing_report.py
- `_build_closing_report()` 내부에 `_update_discovery_log()` 호출 추가
- `_update_discovery_log()` 신규 함수: 오늘 날짜 발굴 항목에 종가·수익률 업데이트

---

## 5. 성공 기준

- [ ] 발굴 실행 시 `data/discovery_log.json` 자동 생성·기록
- [ ] closing_report 실행 후 당일 발굴 항목에 `close_price`, `return_pct` 채워짐
- [ ] 후보 4개 이상 시 텔레그램에 "추가 관심 후보" 섹션 표시
- [ ] 기존 발굴·전송 로직 동작 변경 없음
- [ ] 로그 저장 실패 시 예외 발생하지 않고 경고만 출력

---

## 6. 다음 단계

→ Stage 5 (기술 설계) 작성 후 Codex 구현 지시서 작성
