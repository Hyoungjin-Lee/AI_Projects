# {{STOCK_NAME}}({{CODE}}) 종목 심층 분석

**분석일**: {{DATE}}  
**분석 관점**: {{PERSPECTIVE}}  
**데이터 기간**: {{DATA_FROM}} ~ {{DATA_TO}} ({{DATA_DAYS}}일)

---

## 1. 종합 판정

| 항목 | 값 |
|---|---|
| **판정** | **{{VERDICT}}** |
| 확신도 | {{CONFIDENCE}} ({{CONFIDENCE_PCT}}%) |
| 현재가 | {{CURRENT_PRICE}}원 |
| 손절가 | {{STOP_LOSS}}원 (현재가 대비 {{STOP_PCT}}%) |
| 목표가 | {{TARGET_PRICE}}원 (현재가 대비 {{TARGET_PCT}}%) |
| RR 비율 | {{RR_RATIO}}:1 |

{{#if CONFIDENCE_LOW}}
> ⚠️ **확신도 미달**: 시그널이 충돌하거나 데이터가 부족합니다. 참고용으로만 활용하세요.
{{/if}}

---

## 2. 핵심 시그널

| 지표 | 값 | 해석 |
|---|---|---|
{{#each KEY_SIGNALS}}
| {{name}} | {{value}} | {{interpretation}} |
{{/each}}

---

## 3. 스윙 분석 (일봉 기반)

### 추세

{{SWING_TREND_DETAIL}}

### 지지 / 저항

| 구분 | 가격 |
|---|---|
{{#each SUPPORT_LEVELS}}
| 지지 {{@index+1}} | {{this}}원 |
{{/each}}
{{#each RESISTANCE_LEVELS}}
| 저항 {{@index+1}} | {{this}}원 |
{{/each}}

---

## 4. 정량 지표

| 지표 | 값 |
|---|---|
| 20일 모멘텀 | {{MOM_20}}% |
| 60일 모멘텀 | {{MOM_60}}% |
| 연환산 변동성 | {{VOL_ANN}}% |
| 최대 낙폭 (MDD) | {{MDD}}% |
| 샤프 비율 | {{SHARPE}} |

### 백테스트 결과 (SMA 크로스 전략, {{BT_DAYS}}일)

| 항목 | 결과 |
|---|---|
| 총 수익률 | {{BT_TOTAL_RETURN}}% |
| 승률 | {{BT_WIN_RATE}}% |
| 거래 횟수 | {{BT_TRADE_COUNT}}회 |
| 샤프 비율 | {{BT_SHARPE}} |
| 비용 반영 | ✅ (수수료 0.015% + 세금 0.18% + 슬리피지 0.05%) |

---

## 5. 종합 서술

{{NARRATIVE}}

---

## 6. 리스크 요인

{{#each RISKS}}
- {{this}}
{{/each}}

---

## 7. 시장 컨텍스트

{{MARKET_CONTEXT}}

*(분석 시점 코스피/코스닥 흐름, 환율, 섹터 동향 등을 간략히 기술)*

---

## 부록

- **데이터 소스**: 한국투자증권 Open API
- **분석 도구**: stock-analysis 스킬 (analyze_full.py)
- **작성**: Claude AI

> 이 분석은 투자 참고 목적이며, 투자 결과에 대한 책임은 투자자 본인에게 있습니다.  
> 백테스트 과거 성과는 미래 수익을 보장하지 않습니다.
