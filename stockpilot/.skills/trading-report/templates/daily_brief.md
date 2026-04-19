# 일일 시황 브리프 — {{DATE}}

> 장 시작 전(08:30~09:00) 확인용. 5분 안에 읽을 수 있도록 요약.

---

## 전일 마감 지표

| 지수 | 종가 | 등락 | 등락률 |
|---|---|---|---|
| 코스피 | {{KOSPI_CLOSE}} | {{KOSPI_CHG}} | {{KOSPI_CHG_PCT}}% |
| 코스닥 | {{KOSDAQ_CLOSE}} | {{KOSDAQ_CHG}} | {{KOSDAQ_CHG_PCT}}% |
| 코스피200선물 | {{FUT_CLOSE}} | {{FUT_CHG}} | — |

## 해외 시장 (전일 야간)

| 시장 | 지수 | 등락률 |
|---|---|---|
| 미국 S&P500 | {{SP500}} | {{SP500_CHG}}% |
| 나스닥 | {{NASDAQ}} | {{NASDAQ_CHG}}% |
| 달러/원 환율 | {{USD_KRW}} | {{FX_CHG}} |
| WTI 유가 | {{WTI}} | {{WTI_CHG}}% |

## 오늘의 시장 컨텍스트

{{MARKET_SUMMARY}}

*(예: 미 연준 FOMC 발언 소화 중. 반도체 섹터 강세 기대. 코스피 외국인 매수세 이어질지 주목.)*

---

## 관심종목 현황

| 종목 | 코드 | 전일 종가 | 판정 | 메모 |
|---|---|---|---|---|
| {{STOCK1_NAME}} | {{STOCK1_CODE}} | {{STOCK1_PRICE}} | {{STOCK1_VERDICT}} | {{STOCK1_MEMO}} |
| {{STOCK2_NAME}} | {{STOCK2_CODE}} | {{STOCK2_PRICE}} | {{STOCK2_VERDICT}} | {{STOCK2_MEMO}} |
| {{STOCK3_NAME}} | {{STOCK3_CODE}} | {{STOCK3_PRICE}} | {{STOCK3_VERDICT}} | {{STOCK3_MEMO}} |

## 보유 포지션 현황

| 종목 | 수량 | 평균단가 | 전일 종가 | 평가손익 | 손절가 | 상태 |
|---|---|---|---|---|---|---|
| {{POS1_NAME}} | {{POS1_QTY}} | {{POS1_AVG}} | {{POS1_CLOSE}} | {{POS1_PNL}} | {{POS1_STOP}} | 보유 |

*(포지션 없으면 "없음" 기재)*

---

## 오늘의 액션 플랜

- **매수 후보**: {{BUY_CANDIDATES}}
- **관찰**: {{WATCH_LIST}}
- **청산 고려**: {{SELL_CANDIDATES}}

## 주의사항 / 오늘의 이벤트

- {{EVENT1}} *(예: 삼성전자 실적 발표 15:00)*
- {{EVENT2}} *(예: 미 CPI 발표 22:30)*
- {{RISK_NOTE}}

---

*작성: Claude AI | 출처: 한국투자증권 API + 시장 데이터*
*이 자료는 투자 참고용이며 투자 결과에 대한 책임은 투자자 본인에게 있습니다.*
