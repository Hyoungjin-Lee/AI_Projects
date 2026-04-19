# 매매 일지 — {{STOCK_NAME}}({{CODE}}) {{DATE}}

---

## 기본 정보

| 항목 | 값 |
|---|---|
| 종목 | {{STOCK_NAME}} ({{CODE}}) |
| 매매 방향 | {{DIRECTION}} (매수 / 매도) |
| 전략 유형 | {{STRATEGY}} (단타 / 스윙 / 정량) |
| 진입일 | {{ENTRY_DATE}} |
| 청산일 | {{EXIT_DATE}} |
| 보유 기간 | {{HOLD_DAYS}}일 |

---

## 진입 사유

**분석 당시 판정**: {{VERDICT}} (확신도 {{CONFIDENCE}})

**진입 근거**:
1. {{ENTRY_REASON_1}}
2. {{ENTRY_REASON_2}}
3. {{ENTRY_REASON_3}}

**시장 컨텍스트**:
{{MARKET_CONTEXT_AT_ENTRY}}

---

## 손절 / 목표 계획

| 항목 | 가격 | 비율 |
|---|---|---|
| 진입가 | {{ENTRY_PRICE}}원 | — |
| 손절가 | {{STOP_LOSS}}원 | {{STOP_PCT}}% |
| 목표가 | {{TARGET_PRICE}}원 | {{TARGET_PCT}}% |
| RR 비율 | — | {{RR_RATIO}}:1 |
| 포지션 수량 | {{QTY}}주 | — |
| 투자 금액 | {{INVEST_AMT}}원 | 자본의 {{INVEST_PCT}}% |

---

## 매매 결과

| 항목 | 값 |
|---|---|
| 청산가 | {{EXIT_PRICE}}원 |
| 청산 방식 | {{EXIT_TYPE}} (목표 달성 / 손절 / 임의 청산) |
| 수익금 | {{PROFIT_AMT}}원 |
| 수익률 | {{PROFIT_PCT}}% |
| 세금 + 수수료 | 약 {{COST_AMT}}원 |
| 순수익 | {{NET_PROFIT_AMT}}원 |

---

## 회고 (Post-Trade Review)

### 잘 된 점
{{GOOD_POINT}}

### 아쉬운 점 / 실수
{{BAD_POINT}}

### 다음에 개선할 점
{{IMPROVE_POINT}}

### 규칙 준수 여부
- [ ] 2% 룰 지켰는가?
- [ ] 손절 계획 그대로 실행했는가?
- [ ] 감정적 판단 없이 규칙대로 청산했는가?
- [ ] 진입 전 분석 스킬 결과를 확인했는가?

---

*저장 위치: `journal/{{DATE}}_{{CODE}}.md`*  
*Notion 업데이트: 주식 분석 DB → {{CODE}} 페이지 → 결과/실현손익 입력*
