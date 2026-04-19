# KIS Open API 엔드포인트 치트시트 (실전)

베이스 URL: `https://openapi.koreainvestment.com:9443`

## 인증

| 작업 | 메서드 | 경로 | 비고 |
|---|---|---|---|
| 토큰 발급 | POST | `/oauth2/tokenP` | 1분당 1회 제한. 24시간 유효 |
| 토큰 폐기 | POST | `/oauth2/revokeP` | 보통 안 씀 |
| Hashkey | POST | `/uapi/hashkey` | POST 주문에 필수 |

## 시세 (TR_ID는 헤더로)

| 작업 | TR_ID | 경로 |
|---|---|---|
| 현재가 | `FHKST01010100` | `/uapi/domestic-stock/v1/quotations/inquire-price` |
| 호가 + 잔량 | `FHKST01010200` | `/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn` |
| 일봉 (최대 100건) | `FHKST03010100` | `/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice` |
| 분봉 (1분, 30봉) | `FHKST03010200` | `/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice` |
| 일자별 체결 | `FHKST01010300` | `/uapi/domestic-stock/v1/quotations/inquire-ccnl` |
| 투자자별 매매동향 | `FHPTJ04400000` | `/uapi/domestic-stock/v1/quotations/inquire-investor` |

시세 호출의 공통 쿼리: `FID_COND_MRKT_DIV_CODE=J` (J=주식), `FID_INPUT_ISCD=<6자리 종목코드>`.

## 거래 (계좌)

| 작업 | TR_ID | 경로 |
|---|---|---|
| 잔고 조회 | `TTTC8434R` | `/uapi/domestic-stock/v1/trading/inquire-balance` |
| 매수 주문 (현금) | `TTTC0802U` | `/uapi/domestic-stock/v1/trading/order-cash` |
| 매도 주문 (현금) | `TTTC0801U` | `/uapi/domestic-stock/v1/trading/order-cash` |
| 정정/취소 | `TTTC0803U` | `/uapi/domestic-stock/v1/trading/order-rvsecncl` |
| 일별 주문체결 조회 | `TTTC8001R` | `/uapi/domestic-stock/v1/trading/inquire-daily-ccld` |
| 매수가능조회 | `TTTC8908R` | `/uapi/domestic-stock/v1/trading/inquire-psbl-order` |

거래 호출의 공통 본문 필드: `CANO`(계좌 8자리), `ACNT_PRDT_CD`(상품코드 2자리, 보통 '01').

## 주문 ORD_DVSN 코드

| 코드 | 의미 |
|---|---|
| `00` | 지정가 |
| `01` | 시장가 |
| `02` | 조건부지정가 |
| `03` | 최유리지정가 |
| `04` | 최우선지정가 |
| `05` | 장전 시간외 |
| `06` | 장후 시간외 |
| `07` | 시간외 단일가 |

## 주요 응답 필드 (시세)

`output` 또는 `output1` 안의 필드:

| 필드 | 의미 |
|---|---|
| `stck_prpr` | 현재가 |
| `prdy_vrss` | 전일 대비 |
| `prdy_ctrt` | 전일 대비율 (%) |
| `acml_vol` | 누적 거래량 |
| `acml_tr_pbmn` | 누적 거래대금 |
| `stck_oprc / hgpr / lwpr / clpr` | 시/고/저/종가 |
| `hts_avls` | 시가총액 (억원 단위) |
| `w52_hgpr / lwpr` | 52주 고가/저가 |
| `per / pbr / eps / bps` | 재무 지표 |
| `askp1..10 / bidp1..10` | 매도/매수 호가 1~10단계 |
| `askp_rsqn1..10 / bidp_rsqn1..10` | 잔량 |

## 주요 응답 필드 (잔고 TTTC8434R)

`output1`의 각 항목 = 보유 종목 1개:

| 필드 | 의미 |
|---|---|
| `pdno` | 종목코드 |
| `prdt_name` | 종목명 |
| `hldg_qty` | 보유수량 |
| `pchs_avg_pric` | 평균단가 |
| `prpr` | 현재가 |
| `evlu_amt` | 평가금액 |
| `evlu_pfls_amt` | 평가손익 |
| `evlu_pfls_rt` | 평가수익률 (%) |

`output2[0]` = 계좌 요약:

| 필드 | 의미 |
|---|---|
| `dnca_tot_amt` | 예수금 총액 |
| `ord_psbl_cash` | 주문가능 현금 |
| `tot_evlu_amt` | 총평가금액 |
| `evlu_pfls_smtl_amt` | 평가손익 합계 |
