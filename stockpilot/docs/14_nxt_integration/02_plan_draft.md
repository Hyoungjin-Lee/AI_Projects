# NXT 거래 통합 — Stage 2 계획 초안

> 작성: 2026-05-07 (Claude · WORKFLOW Stage 2)
> 입력: `01_brainstorm.md`
> 다음: Stage 3 (plan_review)

---

## 1. 문제 진술

`closing_report.py`(20:30 자동 발송)와 `morning_report.py`(08:30) 모두 KIS `주식잔고조회`(`TTTC8434R`)를 호출할 때 `AFHR_FLPR_YN="N"` 하드코딩으로 정규장 잔고만 가져온다. NXT 시간대(프리마켓 08:00~08:50, 메인 09:00~15:30 NXT 체결분, 애프터마켓 15:30~20:00) 매매분이 누락되어 평가손익·총자산이 실제와 어긋난다.

### 코드 위치 (확정)
- `.skills/kis-api/scripts/kis_client.py` line 288~307 — `def get_balance()`
- line 293에 `"AFHR_FLPR_YN": "N"` 하드코딩

---

## 2. 범위

### 포함
- `kis_client.get_balance()` 시그니처에 모드 파라미터 추가
- `closing_report.py`에서 N+X 듀얼 호출 + NXT 차이 섹션 표시 (옵션 2 권고)
- `morning_report.py`에서도 X 모드 적용 (08:30은 NXT 프리마켓 08:00~08:50 끝난 후라 영향 있음)
- v2.8.4 핫픽스 안내문 (`※ NXT 정규외 거래는 정규장 데이터에 미반영`) 제거

### 제외
- WebSocket 실시간 NXT 데이터 (당장 불필요)
- NXT 시간외 호가/체결 분석 (별도 기능)
- 매매(주문) 시 NXT 모드 분기 (Phase 2 trading 영역)

---

## 3. 성공 기준

1. NXT 거래 발생일에도 `closing_report` 평가손익 = 실제 보유 자산 (오차 ±100원 이내)
2. NXT 거래가 없는 날도 정상 동작 (정규장 잔고와 동일 표시)
3. 옵션 2 채택 시 NXT 차이가 있을 때만 추가 섹션 표시 (없으면 기존 메시지 그대로)
4. 단위 테스트: `kis_client.get_balance(mode="...")` 시그니처 검증
5. 통합 테스트(dry-run): N/X 모드 응답 데이터 형식 일치 확인

---

## 4. 옵션 비교 (Stage 1 권고 검증)

| 옵션 | 호출 | 표시 | 작업량 | 정확도 | 권고 |
|---|---|---|---|---|---|
| 1. X 단일 | 1회 | NXT 통합 잔고만 | 1h | 가장 정확 | △ (정규장만 검토하던 사용자에게 데이터 형식 변경) |
| **2. N+X 듀얼** | 2회 | 정규장 + NXT 차이 | 2~3h | 정확 + 차이 명시 | **✅** |
| 3. 시간대 분기 | 1회 (분기) | 분기별 | 3~4h | 동일 | ✗ (분기 로직 복잡, 검증 어려움) |

### 권고: 옵션 2

**이유:**
- 정확성 + 가시성 동시 확보. NXT 거래가 있을 때 사용자가 즉시 인지
- 정규장 N 응답이 기존과 동일 → 기존 메시지 형식 보존, "NXT 차이" 섹션만 추가
- 추후 NXT 거래가 일상화되어 "차이가 매번 큼"이 확인되면 옵션 1로 단순화 가능

---

## 5. 작업 분해 (옵션 2 채택 가정)

### Task A — kis_client 시그니처 확장 (S, ~30분)
파일: `.skills/kis-api/scripts/kis_client.py`

```python
def get_balance(self, *, afhr_mode: str = "N") -> dict:
    """
    계좌 보유 종목 + 평가손익 + 예수금.

    Args:
        afhr_mode:
            "N" — 기본 (정규장 KRX 잔고)
            "Y" — 시간외단일가
            "X" — NXT 정규장 (프리마켓 + 메인 + 애프터마켓 통합)
    """
    if afhr_mode not in ("N", "Y", "X"):
        raise ValueError(f"afhr_mode must be N/Y/X, got: {afhr_mode}")
    params = {
        ...
        "AFHR_FLPR_YN": afhr_mode,
        ...
    }
    return self._get(...)
```

**검증:** 단위 테스트 + 라이브 호출 (X 모드 응답 형식 확인)

### Task B — closing_report 듀얼 호출 + NXT 차이 섹션 (M, ~1.5h)
파일: `morning_report/closing_report.py`

추가:
```python
# 정규장 잔고 (기존)
balance_n = client.get_balance(afhr_mode="N")
# NXT 통합 잔고 (신규)
try:
    balance_x = client.get_balance(afhr_mode="X")
except Exception as e:
    print(f"[NXT조회 실패] {e}", file=sys.stderr)
    balance_x = None

# 차이 분석
nxt_diff = _compute_nxt_diff(balance_n, balance_x) if balance_x else None
```

신규 함수: `_compute_nxt_diff(n_data, x_data) -> dict`
- 보유 종목별 수량/평가금액 차이
- 총평가금액 차이
- 차이가 0이면 None 반환 (섹션 생략)

신규 메시지 섹션 (차이 있을 때만):
```
🌙 NXT 정규외 거래 반영 (X 모드)
  종목 추가/변경:
    - SK하이닉스(000660) +5주 (NXT 매수)
    - LG디스플레이(034220) -10주 (NXT 매도)
  총평가금액 NXT 보정: +1,234,567원

🟢 NXT 통합 평가손익: +XXX,XXX원 (+X.XX%)
```

기존 v2.8.4 NXT 안내문 제거 (line 565~567).

### Task C — morning_report 동일 적용 (M, ~30분)
파일: `morning_report/morning_report.py`

08:30 모닝 리포트도 X 모드로 호출하여 NXT 프리마켓(08:00~08:50) 거래분 반영. 단순 적용 (보유 종목 표시 정확도 ↑).

### Task D — 단위 테스트 (S, ~30분)
신규 파일: `tests/test_get_balance.py`
- `afhr_mode` 파라미터 검증 (N/Y/X 허용, 기타 ValueError)
- 호출 파라미터 동봉 검증 (mocking)

### Task E — 통합 검증 (M, ~30분)
- dry-run 또는 라이브 호출로 N/X 응답 형식 비교
- NXT 거래가 없는 날 정상 동작 확인
- NXT 거래 임의 1건 후 다음 클로징 검증

---

## 6. 검증 계획

### 단위 테스트
- `tests/test_get_balance.py` 신규 (Task D)
- 기존 `tests/test_kis_client_phase2.py` 회귀 검증

### 통합 테스트 (수동)
1. 다음 영업일 일과 후 (예: 5/8 금) 라이브 호출:
   ```bash
   venv/bin/python3 -c "
   from .skills.kis-api.scripts.kis_client import KISClient
   c = KISClient()
   bn = c.get_balance(afhr_mode='N')
   bx = c.get_balance(afhr_mode='X')
   # output1/output2 키 비교 + 종목 수 비교
   "
   ```
2. NXT 거래 1건 의도적 실행 (소액 1주) → 다음 클로징에서 차이 섹션 표시 확인

### 자동 검증
- `closing_report.py` `--dry-run` 모드 실행 → 메시지 출력에 "NXT 정규외 거래 반영" 섹션 정상 빌드 확인

---

## 7. 위험 / 보완

| 위험 | 완화 |
|---|---|
| KIS API rate limit (호출 2배) | TTTC8434R는 일반 조회. rate limit 여유. 그래도 X 호출 실패 시 N만으로 graceful degradation |
| X 모드 응답 형식 차이 | Task E 통합 검증 우선. 형식 다르면 매핑 로직 추가 |
| NXT 거래 없을 때 차이 섹션 노이즈 | `_compute_nxt_diff`에서 차이 0이면 None 반환 → 섹션 생략 |
| 모의투자 미지원 위험 | TTTC8434R는 모의투자 지원. AFHR_FLPR_YN=X도 지원 가능 (검증 필요) |

---

## 8. 작업량 합계

| Task | 노력 | 시간 |
|---|---|---|
| A. kis_client | S | 30분 |
| B. closing_report | M | 1.5h |
| C. morning_report | M | 30분 |
| D. 단위 테스트 | S | 30분 |
| E. 통합 검증 | M | 30분 |
| **합계** | | **3.5h** |

---

## 9. 결정 필요 (형진님)

1. **옵션 2 (N+X 듀얼) 채택 여부**
2. **morning_report도 X 모드 적용 여부** (보수적이면 closing만)
3. **검증용 NXT 거래 의도 실행 가능 여부** (소액 1주, 5/8 또는 5/9)
4. **v2.8.4 NXT 안내문 제거 시점** (Task B 완료와 동시 vs 별도)
