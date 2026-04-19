---
name: trading-report
description: stock-analysis 스킬이 생성한 분석 JSON을 받아 Notion DB, Word(.docx), Markdown 리포트로 문서화하는 스킬. "리포트 만들어줘", "Notion에 정리해줘", "일일 시황", "매매 일지", "분석 결과 문서화", "기록해줘", "정리해줘" 같은 표현이 나올 때 반드시 이 스킬을 활용한다. 입력이 분석 JSON이 아닌 경우에는 먼저 stock-analysis 스킬로 데이터를 생성한 뒤 이 스킬로 문서화한다.
---

# trading-report: 분석 결과 문서화 스킬

## 이 스킬이 하는 일

`stock-analysis` 스킬의 표준 JSON 출력을 받아:

1. **Notion DB** — 종목별 분석 기록을 Notion 데이터베이스 페이지로 저장/업데이트
2. **Word(.docx)** — 정식 보고서 형태의 심층 분석 Word 문서 생성
3. **Markdown** — 빠른 확인용 요약 Markdown 파일 생성
4. **매매 일지** — 매매 1건의 사후 기록 및 회고

출력 채널은 사용자 요청에 따라 선택한다 (아래 채널 선택 규칙 참조).

---

## 출력 채널 선택 규칙

| 상황 | 권장 채널 | 이유 |
|---|---|---|
| "지금 이 종목 어때?" → 빠른 확인 | **Markdown** | 즉각 확인, 저장 필요 없음 |
| "리포트 만들어줘" / 정식 보고 | **Word(.docx)** | 포맷 정렬, 인쇄/공유 가능 |
| "Notion에 기록해줘" / 누적 추적 | **Notion DB** | 날짜별 히스토리, 검색 가능 |
| "매매 일지 써줘" | **Markdown + Notion** | 둘 다 저장해 이중 백업 |
| "일일 시황 정리해줘" | **Markdown + Notion** | 매일 자동 기록 적합 |

---

## (a) Notion DB 스키마

Notion에서 "주식 분석 DB" 데이터베이스를 만들 때 다음 속성을 사용한다.

| 속성명 | 유형 | 설명 |
|---|---|---|
| 종목코드 | Title | 예: 005930 삼성전자 |
| 분석일 | Date | 분석 실행 날짜 |
| 관점 | Select | swing / intraday / quant / full |
| 판정 | Select | BUY / HOLD / SELL / WATCH |
| 확신도 | Number | 0~1 |
| 진입가 | Number | 분석 시점 현재가 |
| 손절가 | Number | ATR 기반 손절 |
| 목표가 | Number | RR 2:1 기준 |
| 핵심시그널 | Rich Text | key_signals 요약 |
| 내러티브 | Rich Text | narrative 전문 |
| 리스크 | Rich Text | risks 목록 |
| 결과 | Select | 진행중 / 목표달성 / 손절 / 보류 (매매 후 업데이트) |
| 실현손익(%) | Number | 매매 후 기입 |

### Notion MCP 도구 호출 패턴

**페이지 생성** (`notion-create-pages`):

```json
{
  "parent": { "database_id": "<DB_ID>" },
  "properties": {
    "종목코드": { "title": [{ "text": { "content": "005930 삼성전자" } }] },
    "분석일":  { "date": { "start": "2026-04-17" } },
    "관점":    { "select": { "name": "swing" } },
    "판정":    { "select": { "name": "BUY" } },
    "확신도":  { "number": 0.72 },
    "손절가":  { "number": 68000 },
    "목표가":  { "number": 74000 },
    "핵심시그널": {
      "rich_text": [{ "text": { "content": "SMA20/60 골든크로스, RSI 58, MACD 양전환" } }]
    },
    "내러티브": {
      "rich_text": [{ "text": { "content": "...(narrative 전문)..." } }]
    }
  }
}
```

**페이지 업데이트** (`notion-update-page`) — 매매 결과 기록 시:

```json
{
  "page_id": "<PAGE_ID>",
  "properties": {
    "결과": { "select": { "name": "목표달성" } },
    "실현손익(%)": { "number": 8.3 }
  }
}
```

---

## (b) Word 리포트 구조

`anthropic-skills:docx` 스킬을 활용해 생성. Word 문서 구조는 다음과 같다.

```
[커버]
  종목명 / 코드
  분석일 / 분석 관점
  판정: BUY | HOLD | SELL | WATCH  (색상 강조)
  확신도: xx%

[1. 요약]
  핵심 verdict 1~2줄
  손절가 / 목표가 / RR 비율

[2. 핵심 시그널]
  key_signals 테이블 (지표명 | 값 | 해석)

[3. 기술적 분석]
  스윙 관점 상세
  지지/저항 레벨 테이블

[4. 정량 지표]
  모멘텀, 변동성, MDD, 샤프
  백테스트 결과 테이블

[5. 리스크 요인]
  risks 목록

[6. 시장 컨텍스트]
  분석 시점의 코스피/코스닥 상황 (사용자가 제공하거나 검색)

[부록]
  data_window (분석 데이터 기간)
  면책조항
```

Word 문서는 `reports/<종목코드>_<날짜>_report.docx` 로 저장한다.

---

## (c) Markdown 요약 형식

빠른 확인용. 파일은 `reports/<종목코드>_<날짜>_summary.md`.

```markdown
# [종목코드] 분석 요약 — YYYY-MM-DD

**판정**: BUY | HOLD | SELL | WATCH  (확신도: 0.72)

## 핵심 시그널
- SMA20/60: 골든크로스 유지 (+2.3%)
- RSI(14): 58.3 — 중립~상승
- MACD: 양전환

## 손절 / 목표
- 손절가: 68,000원 (-2.1%)
- 목표가: 74,000원 (+5.7%)
- RR: 2.7:1

## 요약
한 문단 narrative

## 리스크
- 거래대금 감소
- 코스피 약세 흐름

---
*데이터 기간: 2026-02-15 ~ 2026-04-17 (60일)*
```

---

## 매매 일지 템플릿 활용

`templates/trade_journal_entry.md` 를 복사해 `journal/YYYY-MM-DD_<코드>.md`로 저장.
매매가 완료된 뒤 결과를 Notion DB에도 업데이트해 이중 보관한다.

---

## 일일 시황 템플릿 활용

`templates/daily_brief.md` 를 복사해 `journal/daily/YYYY-MM-DD.md`로 저장.
매일 장 시작 전(08:30~09:00) 사용자가 "오늘 시황 정리해줘"라고 말하면 이 템플릿 기반으로 작성한다.

---

## 작업 순서 (공통 흐름)

1. `stock-analysis` 스킬의 분석 JSON이 있는지 확인. 없으면 먼저 분석 실행.
2. 사용자가 원하는 출력 채널 확인 (없으면 기본 Markdown 생성 + Notion 저장 제안).
3. 채널별 작업 수행:
   - Markdown: `reports/` 폴더에 직접 Write
   - Word: `anthropic-skills:docx` 스킬 호출
   - Notion: `mcp__003a854a-...__notion-create-pages` 또는 `notion-update-page` 호출
4. 완료 후 사용자에게 파일 링크(computer://) 또는 Notion 링크 제공.
