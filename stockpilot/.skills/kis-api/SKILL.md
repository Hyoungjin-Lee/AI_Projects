---
name: kis-api
description: 한국투자증권(KIS) Open API를 사용해 국내주식 시세·차트·잔고를 조회하고 주문 초안을 생성하는 스킬. 사용자가 "한투 API", "KIS", "한국투자증권", "현재가 조회", "일봉/분봉", "잔고 조회", "주식 시세", "매수/매도 주문 초안", "종목코드 005930", "관심종목 가격" 같은 표현을 쓰거나, 국내 상장 종목의 실시간/과거 가격 데이터가 필요한 모든 상황에서 반드시 이 스킬을 사용한다. 분석/리포트 스킬이 데이터를 요청할 때도 이 스킬이 데이터 공급원 역할을 한다.
---

# kis-api: 한국투자증권 Open API 데이터 수집 스킬

## 이 스킬이 하는 일

한국투자증권(KIS) Open Trading API를 호출해서 다음 작업을 수행한다.

1. OAuth 액세스 토큰 발급/캐싱/재사용
2. 국내주식 현재가, 일봉, 분봉, 호가, 체결 데이터 조회
3. 계좌 잔고 및 보유 종목 조회
4. 매수/매도 주문 **초안(JSON payload)** 생성 — 실제 전송은 사용자가 명시적으로 허가한 경우에만

이 스킬은 **데이터 공급자** 역할이다. 분석이나 리포트 작성은 `stock-analysis`, `trading-report` 스킬이 담당한다. 둘 중 하나가 호출됐을 때 데이터가 필요하면 이 스킬의 스크립트를 사용한다.

## 환경 변수 (필수)

이 스킬은 사용자의 실전 계좌를 다루므로 자격증명을 코드/리포지토리에 절대 하드코딩하지 않는다. 항상 환경변수에서 읽는다. 사용자가 `.env` 파일을 프로젝트 루트(`stockpilot/.env`)에 두는 것을 가정한다.

```
KIS_APP_KEY=...
KIS_APP_SECRET=...
KIS_ACCOUNT_NO=12345678-01     # 8자리-2자리 (CANO-ACNT_PRDT_CD)
KIS_ENV=real                    # real 고정 (사용자 결정)
```

스크립트는 `python-dotenv`로 자동 로드한다. 자격증명이 없으면 즉시 명확한 에러 메시지를 띄우고 사용자에게 `.env`를 만들도록 안내한다.

## 핵심 라이브러리

모든 API 호출은 `scripts/kis_client.py`의 `KISClient` 클래스를 통해 한다. 이 클래스는 토큰 캐싱, 레이트 리밋(초당 ≤20건 보수적 적용), 에러 처리, hashkey 생성을 모두 처리한다. 같은 작업을 여러 번 인라인으로 다시 짜지 말고 항상 이 클라이언트를 import해서 쓴다.

```python
from kis_client import KISClient

client = KISClient()                 # 환경변수에서 자동 설정
price = client.get_price("005930")    # 삼성전자 현재가
daily = client.get_daily_chart("005930", days=60)
```

토큰은 `data/cache/kis_token.json`에 만료시각과 함께 저장된다. 클라이언트가 자동으로 만료 5분 전에 재발급한다. 사용자가 한 세션에서 여러 번 API를 호출해도 토큰을 매번 새로 받지 않는다 — KIS는 1분당 1회 발급 제한이 있어 이걸 어기면 다음 1분간 다른 호출도 막힌다.

## 사용 가능한 스크립트

`scripts/` 디렉터리에 있는 실행 가능한 도구들. 모든 스크립트는 `--help`를 지원한다.

| 스크립트 | 용도 | 예시 |
|---|---|---|
| `get_quote.py` | 현재가/등락률/거래량 (단일 종목) | `python get_quote.py 005930` |
| `get_daily_chart.py` | 일봉 OHLCV (최대 100일) | `python get_daily_chart.py 005930 --days 60` |
| `get_minute_chart.py` | 분봉 OHLCV (당일/특정일, 1분 기준) | `python get_minute_chart.py 005930 --time 1430` |
| `get_orderbook.py` | 10단계 호가 + 잔량 | `python get_orderbook.py 005930` |
| `get_balance.py` | 계좌 보유 종목 + 평가손익 | `python get_balance.py` |
| `draft_order.py` | 주문 JSON 초안 생성 (전송 X) | `python draft_order.py BUY 005930 10 --price 70000` |

스크립트는 결과를 stdout에 JSON으로 찍고, 동시에 `data/raw/<종목코드>_<지표>_<YYYYMMDD-HHMM>.json`에 저장한다. 이렇게 하면 같은 데이터를 분석 스킬에서 다시 호출하지 않고 캐시에서 읽을 수 있다.

## 주문에 대한 안전 원칙 (중요)

사용자가 "이번에는 주문 초안까지만 하고 향후 자동 주문 확장"이라고 명시했다. 이 원칙을 지킨다.

- `draft_order.py`는 **절대로** 실제 주문을 전송하지 않는다. JSON payload, 예상 hashkey, 호출할 endpoint, 사용자가 직접 실행할 수 있는 `curl` 명령을 출력한다.
- 실제 전송 함수(`KISClient.place_order`)는 클라이언트에 정의는 되어 있지만, 호출 시 환경변수 `KIS_ALLOW_LIVE_ORDER=1`이 명시적으로 설정되어 있어야만 작동한다. 이 환경변수가 없으면 함수는 즉시 `RuntimeError`를 던진다.
- 사용자가 "주문 실행해줘" 같은 말을 해도 먼저 (a) 주문 초안을 보여주고 (b) 명시적으로 "이대로 전송해" 같은 추가 확인을 받기 전엔 전송하지 않는다.

## 자주 쓰는 종목코드 메모

- 005930 삼성전자 / 000660 SK하이닉스 / 035720 카카오 / 035420 NAVER
- 207940 삼성바이오로직스 / 005380 현대차 / 068270 셀트리온
- 233740 KODEX 코스닥150 레버리지 / 122630 KODEX 레버리지 / 252670 KODEX 200선물인버스2X

ETF/선물인버스 종목은 `--market ETF` 등 별도 플래그 없이도 `get_*` 스크립트가 동일하게 동작한다 (KIS는 보통주와 ETF를 같은 엔드포인트로 처리).

## 자료 참조

추가 정보가 필요하면 다음 파일을 읽는다:

- `references/endpoints.md` — TR_ID, 엔드포인트, 요청/응답 필드 매핑 (한 페이지짜리 치트시트)
- `references/error_codes.md` — KIS API가 자주 뱉는 에러코드 해석과 대처

KIS 공식 문서는 https://apiportal.koreainvestment.com 에 있지만, 위 두 파일에 일상 작업에 필요한 90%가 정리돼 있다. 거기서 못 찾을 때만 공식 문서를 검색한다.

## 호출 순서 가이드

새 작업이 시작되면 보통 이 순서로 진행한다:

1. `client = KISClient()` — 환경 확인 (자격증명 누락 시 사용자에게 알림)
2. 분석 대상 종목코드 확정 (사용자가 종목명으로 말했으면 코드 확인)
3. 필요한 데이터 종류 결정: 단타면 분봉+호가, 스윙이면 일봉 60~120일, 정량이면 일봉 + 거래량
4. 적절한 스크립트 호출 → JSON 결과 받음 → `data/raw/`에 자동 저장
5. 결과를 분석 스킬에 넘기거나, 사용자에게 핵심 수치만 요약해서 보고
