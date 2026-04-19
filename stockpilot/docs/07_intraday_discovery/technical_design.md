# 장초기 실시간 종목 발굴 — 기술 설계

> 작성일: 2026-04-19
> 목적: KIS 종목순위 API 기반 장초기 실시간 종목 발굴 시스템

---

## 1. 개요

기존 `stock_discovery.py` (야간 23:30 실행) 와 별도로,
장 시작 직후 09:03 / 09:05 두 시점의 순위 데이터를 교차 분석해
단기 급등 가능성이 높은 종목을 발굴한다.

---

## 2. 신규 스크립트

**파일명:** `morning_report/intraday_discovery.py`

기존 스크립트와의 관계:
- `intraday_report.py` — 보유 종목 현황 브리핑 (유지)
- `intraday_discovery.py` — 코스피200 실시간 발굴 (신규)

---

## 3. 사용 API

| API명 | TR_ID | URL | 용도 |
|-------|-------|-----|------|
| 거래량순위 | `FHPST01710000` | `/uapi/domestic-stock/v1/quotations/volume-rank` | 교집합 필터 |
| 체결강도 상위 | `FHPST01680000` | `/uapi/domestic-stock/v1/ranking/volume-power` | 교집합 필터 + 점수 |
| 등락률 순위 | `FHPST01700000` | `/uapi/domestic-stock/v1/ranking/fluctuation` | 교집합 필터 + 점수 |
| 이격도 순위 | `FHPST01780000` | `/uapi/domestic-stock/v1/ranking/disparity` | 과열 필터 |
| HTS조회상위 | (TR_ID 확인 필요) | `/uapi/domestic-stock/v1/quotations/capture-uplmt` | 가산점 |

---

## 4. API 파라미터 상세

### 4-1. 거래량순위 (FHPST01710000)
```
FID_COND_MRKT_DIV_CODE: J       # KRX
FID_COND_SCR_DIV_CODE:  20171
FID_INPUT_ISCD:         0000    # ⚠️ 코스피200 코드 확인 필요 (업종코드 방식)
FID_DIV_CLS_CODE:       1       # 보통주만
FID_BLNG_CLS_CODE:      0       # 평균거래량 순
FID_TRGT_CLS_CODE:      111111111
FID_TRGT_EXLS_CLS_CODE: 0000010100  # ETF(6번째), ETN(8번째) 제외
FID_INPUT_PRICE_1:      ""      # 가격 제한 없음
FID_INPUT_PRICE_2:      ""
FID_VOL_CNT:            ""
FID_INPUT_DATE_1:       ""
```

### 4-2. 체결강도 상위 (FHPST01680000)
```
fid_trgt_exls_cls_code: 0000010100  # ETF, ETN 제외
fid_cond_mrkt_div_code: J
fid_cond_scr_div_code:  20168
fid_input_iscd:         2001    # ✅ 코스피200
fid_div_cls_code:       1       # 보통주
fid_input_price_1:      ""
fid_input_price_2:      ""
fid_vol_cnt:            ""
fid_trgt_cls_code:      0
```

### 4-3. 등락률 순위 (FHPST01700000)
```
fid_cond_mrkt_div_code: J
fid_cond_scr_div_code:  20170
fid_input_iscd:         2001    # ✅ 코스피200
fid_rank_sort_cls_code: 0       # 상승율 순
fid_input_cnt_1:        0       # 전체
fid_prc_cls_code:       1       # 종가대비
fid_input_price_1:      ""
fid_input_price_2:      ""
fid_vol_cnt:            ""
fid_trgt_cls_code:      0
fid_trgt_exls_cls_code: 0000010100  # ETF, ETN 제외
fid_div_cls_code:       0
fid_rsfl_rate1:         ""
fid_rsfl_rate2:         ""
```

### 4-4. 이격도 순위 (FHPST01780000)
```
fid_cond_mrkt_div_code: J
fid_cond_scr_div_code:  20178
fid_input_iscd:         2001    # ✅ 코스피200
fid_rank_sort_cls_code: 0       # 이격도 상위순
fid_hour_cls_code:      20      # 20일 이격도 사용
fid_div_cls_code:       0
fid_trgt_cls_code:      0
fid_trgt_exls_cls_code: 0
fid_input_price_1:      ""
fid_input_price_2:      ""
fid_vol_cnt:            ""
```

---

## 5. 실행 흐름

```
09:03 실행
  ├── 거래량 상위 30 조회   → set_vol_1
  ├── 체결강도 상위 30 조회 → set_pow_1  (체결강도 값 저장)
  ├── 등락률 상위 30 조회   → set_flc_1  (등락률 값 저장)
  └── 결과를 daily_state에 임시 저장

09:05 실행
  ├── 거래량 상위 30 조회   → set_vol_2
  ├── 체결강도 상위 30 조회 → set_pow_2  (체결강도 값 저장)
  ├── 등락률 상위 30 조회   → set_flc_2  (등락률 값 저장)
  ├── 이격도 상위 30 조회   → 과열 종목 코드 추출
  ├── HTS조회상위 조회      → 온라인 관심 종목 코드 추출
  │
  ├── 교집합 계산
  │   candidates = set_vol_1 ∩ set_vol_2
  │               ∩ set_pow_1 ∩ set_pow_2
  │               ∩ set_flc_1 ∩ set_flc_2
  │
  ├── 이격도 과열 제거 (이격도 120 이상)
  │
  ├── 점수 산정 (종목별)
  │   +3/2/1  체결강도 구간
  │   +1      체결강도 09:03→09:05 상승
  │   +1      등락률 09:03→09:05 상승
  │   +1      거래량 09:03→09:05 증가
  │   +1      HTS조회 상위 10위 이내
  │
  ├── 점수 높은 순 정렬
  └── 텔레그램 전송
```

---

## 6. launchd 스케줄

| 시각 | Label | 스크립트 | 인수 |
|------|-------|---------|------|
| 09:03 | `com.aigeenya.stockreport.discovery1` | `intraday_discovery.py` | `--round 1` |
| 09:05 | `com.aigeenya.stockreport.discovery2` | `intraday_discovery.py` | `--round 2` |

`--round 1`: 1차 조회 후 daily_state 저장만 (전송 없음)
`--round 2`: 2차 조회 후 교집합/점수 계산 → 텔레그램 전송

---

## 7. 텔레그램 출력 형식

```
🔍 장초기 종목 발굴 (09:05)
―――――――――――――――
코스피200 교집합 분석 결과

🥇 삼성전자 (005930)  7점
   체결강도: 135 (+5↑) | 등락률: +2.3%↑ | 거래량↑
   🌐 온라인 관심 3위

🥈 SK하이닉스 (000660)  5점
   체결강도: 112 (+3↑) | 등락률: +1.8%↑ | 거래량→

🥉 LG에너지솔루션 (373220)  4점
   체결강도: 108 | 등락률: +1.2%↑ | 거래량↑
―――――――――――――――
총 후보: 8종목 → 상위 3종목
```

---

## 8. 미확인 사항 (구현 전 확인 필요)

1. **거래량순위 코스피200 필터** — `FID_INPUT_ISCD`에 `2001` 적용 가능 여부 실제 테스트 필요
2. **HTS조회상위 TR_ID** — 문서상 파라미터 없음, 실제 TR_ID 및 응답 필드명 확인 필요
3. **이격도 기준값** — 120으로 시작하되 테스트 후 조정

---

## 9. daily_state 스키마 추가

```json
"intraday_discovery": {
  "round1": {
    "time": "09:03",
    "vol": ["005930", "000660", ...],
    "pow": {"005930": 135.2, ...},
    "flc": {"005930": 2.3, ...}
  },
  "round2_result": [
    {"code": "005930", "name": "삼성전자", "score": 7, ...}
  ]
}
```
