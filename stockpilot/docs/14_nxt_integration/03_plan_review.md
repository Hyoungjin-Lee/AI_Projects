# NXT 거래 통합 — Stage 3 계획 검토

> 작성: 2026-05-07 (Claude · WORKFLOW Stage 3 — High effort 자체 검토)
> 입력: `02_plan_draft.md`
> 다음: Stage 4 (plan_final, 형진님 옵션 결정 후)

---

## 검토 결론 한 줄

**옵션 2(N+X 듀얼) 권고는 타당. 단 8건의 보완점 + 2건의 결정 추가 필요.**

---

## R1 — `_compute_nxt_diff` 종목 매핑 키 (보완 필수)

**문제:** 동일 종목코드라도 KIS 응답에서 N과 X 모드 사이 행 순서가 다를 수 있음. 단순 zip으로 비교하면 미스매치.

**보완:** 매핑 키는 `pdno`(종목코드)로 dict 변환 후 set 차집합 + 교집합으로 비교.

```python
def _compute_nxt_diff(n_data, x_data):
    n_map = {row["pdno"]: row for row in n_data["output1"]}
    x_map = {row["pdno"]: row for row in x_data["output1"]}
    only_in_x = set(x_map) - set(n_map)
    only_in_n = set(n_map) - set(x_map)
    qty_diff = {pdno: int(x_map[pdno]["hldg_qty"]) - int(n_map[pdno]["hldg_qty"])
                for pdno in set(n_map) & set(x_map)
                if int(x_map[pdno]["hldg_qty"]) != int(n_map[pdno]["hldg_qty"])}
    ...
```

---

## R2 — 모의투자(VTS) 지원 여부 미확정 (검증 필요)

**문제:** AFHR_FLPR_YN=X 가 모의투자(VTS) 환경에서도 동작하는지 KIS 문서 미명시.

**보완:** Task E에 다음 추가:
- 모의투자 도메인 (`https://openapivts...`)에서 X 호출 시 응답 코드 확인
- 미지원이면 `kis_client.get_balance(afhr_mode="X")`가 mode="vts"일 때 자동 N 폴백

---

## R3 — `output2` (예수금/총자산) 데이터의 N vs X 차이 (보완 필수)

**문제:** Stage 2 plan에서 `output1`(보유 종목)만 비교 언급. 그러나 평가손익·총자산은 `output2`에서 옴. X 모드에서 `output2`도 NXT 보정값으로 변경되는지 확인 필요.

**보완:**
- Task E에 `output2` N vs X 비교 추가
- `_compute_nxt_diff`에서 `tot_evlu_amt`, `evlu_pfls_smtl_amt` 등 핵심 필드도 비교
- 메시지의 "총평가금액", "평가손익합계" 항목에 `(NXT 통합)` 표기 또는 별도 행 추가

---

## R4 — closing_report 기존 `change_pct` 핫픽스(v2.7.4)와 충돌 가능성 (영향도 검토)

**문제:** v2.7.4에서 `change_pct`를 `today_close vs prev_close` 수동 계산으로 전환. X 모드 응답에서 `today_close`가 NXT 종가일 가능성. 그러면 prev_close(전일 KRX 종가)와 시점 mismatch.

**보완:** Task B에서 X 모드의 `prpr` 또는 일봉 응답을 그대로 쓰지 않고, 별도 분기:
- 종목별 `change_pct`는 N 모드 데이터로 계산 (기존 로직 유지)
- NXT 차이는 별도 섹션에서만 표시

이렇게 하면 v2.7.4 핫픽스와 충돌 없음.

---

## R5 — 모닝 리포트 X 모드 적용 시 "어제 종가" 영향 (Task C 위험)

**문제:** 08:30 모닝 리포트는 NXT 프리마켓(08:00~08:50) 도중에 실행. X 모드로 잔고 조회 시 "현재가"가 NXT 호가일 가능성. 그러면 모닝 리포트의 "현재가 vs 평단" 표시가 NXT 시세 기반.

**보완 옵션:**
- (a) Task C 보류 — closing_report만 X 모드 적용 (보수적)
- (b) Task C 진행 + 메시지에 `(NXT 프리마켓 시세)` 표기

권고: (a). 모닝은 정규장 시작 전 브리핑이 본질이라 정규장 시세 기반이 자연스러움. NXT 거래분의 "보유 수량" 변경만 반영하고 시세는 정규장 그대로 유지하려면 추가 분기 필요 — 복잡도 상승. 단순 보류가 안전.

---

## R6 — `holiday_skipped` 마커와의 정합성 (영향도 검토)

**문제:** v2.8.8에서 5/5 휴장 데이터에 `holiday_skipped: true` 추가. closing_report `_save_discovery_log` 또는 `update_lifecycle`이 이 마커를 의식하는지 미확인.

**보완:** Task B 진행 시 마커 보존 확인 — closing_report가 `holiday_skipped=True` 레코드를 만나면 종가 갱신 시도 자체를 스킵하도록 (v2.8.5 보호 로직과 일관).

코드 (이미 v2.8.5에서 line 797 `if entry.get("close_price") is not None: continue` 가드 있음 → `holiday_skipped` 케이스도 close_price 없으니 갱신 시도 들어감 → disc==close 시 다시 휴장 의심 처리 → OK). 단 `holiday_skipped` 명시 가드 추가가 더 안전.

```python
if entry.get("holiday_skipped"):
    continue
```

---

## R7 — 신규 함수 `_compute_nxt_diff` 위치 (코드 구조)

**문제:** Stage 2 plan에 `_compute_nxt_diff`를 closing_report.py 내부 함수로 시사. 그러나 morning_report에도 X 모드 적용 시 (Task C 또는 향후) 함수 재사용 필요.

**보완:** `morning_report/balance_diff.py` 별도 모듈로 분리. 단순 closing_report 내부 함수 시작 → 향후 분리 어려움.

---

## R8 — 단위 테스트 mocking 전략 (Task D)

**문제:** Stage 2 plan에서 단위 테스트 언급만. 실제 KIS API mocking 없이 시그니처 검증만 가능.

**보완:**
- `tests/test_get_balance.py`: `afhr_mode` 파라미터 검증 (ValueError, default)
- `tests/test_balance_diff.py` (Task R7 모듈 분리 시): mock N/X 응답으로 `_compute_nxt_diff` 결과 검증
- 통합 테스트는 별도 (Task E)

---

## R9 — 에러 핸들링 시 사용자 가시성 (UX)

**문제:** Stage 2에서 X 호출 실패 시 stderr 출력만. 사용자(텔레그램)는 알 수 없음.

**보완:** X 호출 실패 시 텔레그램 메시지 끝에 안내문:
```
⚠️ NXT 잔고 조회 실패 — 정규장 기준만 표시 (체결내역 직접 확인 권고)
```

---

## R10 — v2.8.4 안내문 제거 시점 (결정 필요)

**문제:** Stage 2 결정 항목 4번 미해결. 옵션:
- (a) Task B 완료 + 1주 안정 운영 후 제거 (보수적)
- (b) Task B 완료와 동시 제거 (단순)
- (c) Task B 완료 + Task E 검증 통과 후 제거 (균형)

권고: **(c)** — 5/8(금) 라이브 검증 통과 시점에 제거.

---

## 보완 후 작업량 재추정

| Task | Stage 2 | Stage 3 보완 후 | 변경 |
|---|---|---|---|
| A. kis_client | 30분 | 30분 | - |
| B. closing_report | 1.5h | 2h | +30분 (R1, R3, R6, R9) |
| C. morning_report | 30분 | **0** (R5 보류) | -30분 |
| D. 단위 테스트 | 30분 | 1h | +30분 (R8 분리) |
| E. 통합 검증 | 30분 | 1h | +30분 (R2 VTS, R3 output2) |
| F. balance_diff 모듈 분리 (R7) | - | 30분 | 신규 |
| **합계** | 3.5h | **5h** | +1.5h |

---

## 추가 결정 필요 (Stage 4 입력)

1. ~~옵션 2 채택 여부~~ → 권고 유지
2. **R5 결과**: morning_report X 모드 적용 → **보류 (보수적)**
3. **R7**: `balance_diff` 별도 모듈 분리 → **권고**
4. **R10**: v2.8.4 안내문 제거 시점 → **(c) Task E 검증 통과 후**
5. **검증용 NXT 거래 의도 실행** (5/8 금 또는 5/9 토 NXT 매매 1건)
6. **모의투자 환경 X 모드 지원 여부** — Task E에서 1차 확인

---

## 다음 단계

- 형진님 검토: 위 보완 + 결정 5개
- Stage 4 (plan_final) 작성 — 결정 반영 후 확정 계획
- Stage 5 (technical_design) — Codex Brief 작성 입력
