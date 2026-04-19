# Codex 구현 지시서 — 장초기 실시간 종목 발굴

> 이 문서를 Codex에게 전달하여 구현을 요청하세요.

---

## 역할

당신은 Python 백엔드 개발자입니다.
아래 명세에 따라 `morning_report/intraday_discovery.py` 를 새로 작성해주세요.

---

## 프로젝트 환경

- Python 3.14, macOS
- 프로젝트 루트: `/Users/geenya/projects/AI_Projects/stockpilot`
- KIS API 클라이언트: `.skills/kis-api/scripts/kis_client.py` (기존 파일)
- 텔레그램 전송: `morning_report/telegram_sender.py` → `send_text(msg)` 사용
- 인증정보: `from keychain_manager import inject_to_env; inject_to_env()` 반드시 첫 줄 호출
- 공유 상태: `from state_manager import StateManager` 사용

---

## 구현할 파일

**`morning_report/intraday_discovery.py`**

---

## 실행 방식

```bash
# 1차 조회 (09:03) — 데이터 수집만, 전송 없음
venv/bin/python3 morning_report/intraday_discovery.py --round 1

# 2차 조회 (09:05) — 교집합 분석 후 텔레그램 전송
venv/bin/python3 morning_report/intraday_discovery.py --round 2

# 테스트 (전송 없이 출력만)
venv/bin/python3 morning_report/intraday_discovery.py --round 2 --dry-run
```

---

## 사용 API (KIS REST API)

모든 API는 GET 방식, 실전 도메인: `https://openapi.koreainvestment.com:9443`

### 1. 거래량순위
- TR_ID: `FHPST01710000`
- URL: `/uapi/domestic-stock/v1/quotations/volume-rank`
- 파라미터:
```
FID_COND_MRKT_DIV_CODE: "J"
FID_COND_SCR_DIV_CODE:  "20171"
FID_INPUT_ISCD:         "2001"   # 코스피200 (안 되면 "0000" 후 소프트웨어 필터)
FID_DIV_CLS_CODE:       "1"      # 보통주
FID_BLNG_CLS_CODE:      "0"      # 평균거래량 순
FID_TRGT_CLS_CODE:      "111111111"
FID_TRGT_EXLS_CLS_CODE: "0000001100"  # ETF, ETN 제외
FID_INPUT_PRICE_1:      ""
FID_INPUT_PRICE_2:      ""
FID_VOL_CNT:            ""
FID_INPUT_DATE_1:       ""
```
- 응답 필드: `output` 리스트, 종목코드 `mksc_shrn_iscd`, 종목명 `hts_kor_isnm`, 거래량 `acml_vol`

### 2. 체결강도 상위
- TR_ID: `FHPST01680000`
- URL: `/uapi/domestic-stock/v1/ranking/volume-power`
- 파라미터:
```
fid_trgt_exls_cls_code: "0000001100"  # ETF, ETN 제외
fid_cond_mrkt_div_code: "J"
fid_cond_scr_div_code:  "20168"
fid_input_iscd:         "2001"   # 코스피200
fid_div_cls_code:       "1"      # 보통주
fid_input_price_1:      ""
fid_input_price_2:      ""
fid_vol_cnt:            ""
fid_trgt_cls_code:      "0"
```
- 응답 필드: `output` 리스트, 종목코드 `mksc_shrn_iscd`, 체결강도 `cttr`

### 3. 등락률 순위
- TR_ID: `FHPST01700000`
- URL: `/uapi/domestic-stock/v1/ranking/fluctuation`
- 파라미터:
```
fid_cond_mrkt_div_code: "J"
fid_cond_scr_div_code:  "20170"
fid_input_iscd:         "2001"   # 코스피200
fid_rank_sort_cls_code: "0"      # 상승율 순
fid_input_cnt_1:        "0"
fid_prc_cls_code:       "1"      # 종가대비
fid_input_price_1:      ""
fid_input_price_2:      ""
fid_vol_cnt:            ""
fid_trgt_cls_code:      "0"
fid_trgt_exls_cls_code: "0000001100"  # ETF, ETN 제외
fid_div_cls_code:       "0"
fid_rsfl_rate1:         ""
fid_rsfl_rate2:         ""
```
- 응답 필드: `output` 리스트, 종목코드 `mksc_shrn_iscd`, 등락률 `prdy_ctrt`

### 4. 이격도 순위 (과열 필터용)
- TR_ID: `FHPST01780000`
- URL: `/uapi/domestic-stock/v1/ranking/disparity`
- 파라미터:
```
fid_cond_mrkt_div_code: "J"
fid_cond_scr_div_code:  "20178"
fid_input_iscd:         "2001"   # 코스피200
fid_rank_sort_cls_code: "0"      # 이격도 상위순
fid_hour_cls_code:      "20"     # 20일 이격도
fid_div_cls_code:       "0"
fid_trgt_cls_code:      "0"
fid_trgt_exls_cls_code: "0"
fid_input_price_1:      ""
fid_input_price_2:      ""
fid_vol_cnt:            ""
```
- 응답 필드: `output` 리스트, 종목코드 `mksc_shrn_iscd`, 이격도 `d20_dsrt` (20일 이격도)

### 5. HTS조회상위 (온라인 관심 가산점용)
- TR_ID: `FHPST01830000` (문서 미확인 — 실패 시 이 기능만 건너뜀)
- URL: `/uapi/domestic-stock/v1/quotations/capture-uplmt`
- 파라미터: 없음
- 응답 필드: `output` 리스트, 종목코드 `mksc_shrn_iscd`
- **실패해도 전체 로직에 영향 없도록 try/except로 감싸기**

---

## 로직 상세

### --round 1 (09:03 실행)
1. 거래량/체결강도/등락률 API 각각 호출
2. 각 API 응답에서 상위 30개 종목코드 추출
3. 체결강도 값(`cttr`), 등락률 값(`prdy_ctrt`), 거래량 값(`acml_vol`) 저장
4. StateManager에 저장:
```python
state.update("intraday_discovery", {
    "round1": {
        "time": "HH:MM",
        "vol": [코드 리스트],
        "pow": {코드: 체결강도값, ...},
        "flc": {코드: 등락률값, ...},
        "acml_vol": {코드: 거래량값, ...}
    }
})
```
5. 텔레그램 전송 없이 종료

### --round 2 (09:05 실행)
1. 거래량/체결강도/등락률 API 각각 호출 (2차)
2. 이격도 API 호출 → 이격도 120 이상 종목코드 추출 (과열 목록)
3. HTS조회상위 API 호출 → 상위 10개 종목코드 추출
4. StateManager에서 round1 데이터 로드
5. **교집합 계산:**
   ```
   candidates = vol_1 ∩ vol_2 ∩ pow_1 ∩ pow_2 ∩ flc_1 ∩ flc_2
   ```
6. **과열 종목 제거:** 이격도 120 이상 종목 제외
7. **점수 산정 (종목별):**
   - 체결강도(2차 기준):
     - 130 이상: +3
     - 110~129: +2
     - 100~109: +1
     - 100 미만 + 1차→2차 상승: +1
     - 100 미만 + 하락/유지: 후보 제외
   - 등락률 1차→2차 상승: +1
   - 거래량 1차→2차 증가: +1
   - HTS조회 상위 10위 이내: +1
8. 점수 높은 순 정렬
9. StateManager에 결과 저장
10. 텔레그램 전송

---

## 텔레그램 출력 형식

```
🔍 장초기 종목 발굴 (09:05)
―――――――――――――――
코스피200 실시간 분석

🥇 삼성전자 (005930)  7점
   체결강도: 135 (+5↑) | 등락률: +2.3%↑ | 거래량↑
   🌐 온라인 관심 3위

🥈 SK하이닉스 (000660)  5점
   체결강도: 112 | 등락률: +1.8%↑ | 거래량↑

🥉 LG에너지솔루션 (373220)  4점
   체결강도: 108 | 등락률: +1.2% | 거래량↑
―――――――――――――――
후보 8종목 → 상위 3종목 선정
```

후보가 0개인 경우:
```
🔍 장초기 종목 발굴 (09:05)
―――――――――――――――
교집합 종목 없음 — 오늘은 뚜렷한 신호 없음
```

---

## 주의사항

1. `inject_to_env()` 반드시 첫 줄 호출
2. API 호출은 `kis_client.py`의 `_get()` 또는 직접 `urllib.request` 사용 (requests 미사용)
3. 모든 API 호출은 try/except로 감싸고, 실패 시 stderr에 로그 후 계속 진행
4. `--dry-run` 시 텔레그램 전송 대신 print 출력
5. 파일 작성 후 반드시 `python3 -m py_compile` 문법 검사 실행
6. round1 데이터가 없는 상태에서 round2 실행 시 에러 메시지 출력 후 종료

---

## KIS API 호출 패턴 참고

기존 `kis_client.py` 또는 아래 패턴 사용:

```python
import urllib.request, urllib.parse, json, os

def _kis_get(tr_id: str, url_path: str, params: dict) -> dict:
    token = os.environ.get("KIS_ACCESS_TOKEN", "")
    app_key = os.environ.get("KIS_APP_KEY", "")
    app_secret = os.environ.get("KIS_APP_SECRET", "")
    base = "https://openapi.koreainvestment.com:9443"
    url = base + url_path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": tr_id,
        "custtype": "P",
    })
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())
```
