# Stage 5 — 기술 설계: intraday_discovery 고도화

> 작성일: 2026-04-21
> 담당: Claude (Opus → Sonnet 대체)
> 입력: docs/08_phase1_intraday/plan_final.md

---

## 1. 변경 대상 파일

| 파일 | 변경 종류 |
|------|-----------|
| `morning_report/intraday_discovery.py` | 함수 2개 추가 + `_build_message()` 수정 |
| `morning_report/closing_report.py` | 함수 1개 추가 + `_build_closing_report()` 호출 추가 |
| `data/discovery_log.json` | 신규 생성 (없으면 자동 생성) |

---

## 2. intraday_discovery.py 변경 상세

### 2-1. `_run_round2()` 수정

발굴 결과 저장 호출 추가. 텔레그램 전송 직전에 삽입:

```python
# 기존: message = _build_message(...)
# 변경 후: 저장 먼저, 그 다음 메시지 빌드

_save_discovery_log(scored, metrics)   # ← 추가
message = _build_message(round2["time"], top_picks, len(scored))
```

`scored`에는 이미 `code`, `name`, `score`, `pow_2`, `flc_2`가 있음.
`disc_price`는 `metrics`에서 가져오거나 별도 파라미터로 전달 — `volume_rows`에서 `stck_prpr` 추출.

→ `_run_round2()` 시그니처 변경 없음. 내부에서 `volume_rows`를 이미 보유하고 있으므로 그대로 활용.

### 2-2. `_save_discovery_log(scored, volume_rows)` 신규 함수

```python
def _save_discovery_log(scored: list[dict], volume_rows: list[dict]) -> None:
    """
    발굴 결과를 data/discovery_log.json에 기록.
    실패해도 예외 발생 없이 stderr 경고만 출력.
    """
```

**동작:**
1. `data/discovery_log.json` 읽기 (없으면 빈 리스트)
2. 오늘 날짜(`date.today().isoformat()`) 기준 기존 항목 중복 체크
   - 같은 날짜·종목코드가 이미 있으면 덮어쓰기 (재실행 대비)
3. `volume_rows`에서 `stck_prpr` 추출해 `disc_price` 매핑
4. 새 항목 구성 후 리스트에 추가
5. 30일 이전 항목 삭제 (`date` 필드 기준)
6. 파일 저장

**신규 항목 구조:**
```python
{
    "date": "2026-04-21",
    "disc_time": datetime.now().strftime("%H:%M"),
    "code": item["code"],
    "name": item["name"],
    "disc_price": price_map.get(item["code"], 0),
    "score": item["score"],
    "pow_2": round(item["pow_2"], 1),
    "flc_2": round(item["flc_2"], 2),
    "close_price": None,
    "return_pct": None,
    "updated_at": None,
}
```

**파일 경로:** `_ROOT / "data" / "discovery_log.json"`

### 2-3. `_build_message()` 수정

```python
def _build_message(time_str: str, top_picks: list, candidate_count: int, all_scored: list = None) -> str:
```

- `all_scored` 파라미터 추가 (기본값 None — 하위 호환 유지)
- 기존 top3 출력 후, `all_scored`가 있고 4개 이상이면 추가 섹션 출력:

```
―――――――――――――――
📋 추가 관심 후보
  4위 종목명 (코드) — 체결강도: XXX | +X.X%
  5위 종목명 (코드) — 체결강도: XXX | +X.X%
```

- `all_scored[3:5]` (인덱스 3, 4) 사용 (최대 2개)
- `_run_round2()`에서 호출 시 `all_scored=scored` 전달

---

## 3. closing_report.py 변경 상세

### 3-1. `_update_discovery_log()` 신규 함수

```python
def _update_discovery_log(client) -> None:
    """
    오늘 발굴된 종목의 종가를 discovery_log.json에 업데이트.
    closing_report 실행 시 호출 (장마감 후 종가 = 현재가).
    실패해도 예외 발생 없이 stderr 경고만 출력.
    """
```

**동작:**
1. `data/discovery_log.json` 읽기 (없거나 실패 시 종료)
2. 오늘 날짜 항목 중 `close_price is None`인 것만 처리
3. 각 종목에 대해 `client.get_current_price(code)` 호출
4. `close_price`, `return_pct`, `updated_at` 채우기
5. 파일 저장

**`return_pct` 계산:**
```python
if disc_price > 0 and close_price > 0:
    return_pct = round((close_price - disc_price) / disc_price * 100, 2)
```

### 3-2. `_build_closing_report()` 호출 추가

기존 `_build_closing_report()` 함수 초반부 (KIS 클라이언트 초기화 직후):
```python
# 발굴 성과 업데이트 (장마감 종가 기록)
try:
    _update_discovery_log(client)
except Exception as e:
    print(f"[발굴로그] 업데이트 실패 (무시): {e}", file=sys.stderr)
```

---

## 4. kis_client.get_current_price() 확인 사항

기존 `kis_client.py`에 `get_current_price(code)` 메서드 존재 여부 확인 필요.
- 있으면 그대로 사용
- 없으면 `get_stock_info(code)` 또는 `get_daily_chart(code, days=1)`로 대체
- **Codex가 구현 전 확인 후 적절한 메서드 사용**

---

## 5. 예외 처리 원칙

- 발굴 로그 관련 모든 함수는 `try/except Exception`으로 감싸기
- 실패 시 `print(f"[발굴로그] ...", file=sys.stderr)` 경고만 출력
- 메인 발굴·전송 로직에 절대 영향 주지 않음

---

## 6. 테스트 방법

```bash
# 1. round2 dry-run 실행 후 discovery_log.json 생성 확인
venv/bin/python3 morning_report/intraday_discovery.py --round 2 --dry-run

# 2. 파일 내용 확인
cat data/discovery_log.json

# 3. closing_report dry-run 후 close_price 업데이트 확인
venv/bin/python3 morning_report/closing_report.py --dry-run

# 4. 파일 내용 재확인 (close_price, return_pct 채워졌는지)
cat data/discovery_log.json
```

---

## 7. 다음 단계

→ 이 문서를 기반으로 Codex 구현 지시서 작성 (implementation_prompt.md)
