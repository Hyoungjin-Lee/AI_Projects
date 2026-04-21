# Stage 5 기술 설계 — intraday_discovery round 5~8 (오후장)

> 작성일: 2026-04-21
> Stage 1 브레인스토밍 → Stage 4 계획 통합 → **Stage 5 기술 설계**

---

## 1. 목표

오후장 전용 발굴 사이클 추가. 오전장(round 1~4)과 완전 분리.

---

## 2. 실행 스케줄

| round | 시각  | 동작 |
|-------|-------|------|
| 1     | 09:03 | 수집만 (기존) |
| 2     | 09:05 | 교집합 분석 + 전송 (기존) |
| 3     | 09:30 | 수집만 (기존) |
| 4     | 09:33 | 교집합 분석 + round 2 추적 + 전송 (기존) |
| **5** | **14:03** | **수집만 (신규)** |
| **6** | **14:05** | **교집합 분석 + 전송 (신규)** |
| **7** | **14:30** | **수집만 (신규)** |
| **8** | **14:33** | **교집합 분석 + round 6 추적 + 전송 (신규)** |

---

## 3. 변경 범위

### 3-1. `intraday_discovery.py` 수정

#### (1) `main()` argparse 수정
```python
# 변경 전
parser.add_argument("--round", dest="round_no", type=int, choices=[1, 2, 3, 4], required=True)

# 변경 후
parser.add_argument("--round", dest="round_no", type=int, choices=[1, 2, 3, 4, 5, 6, 7, 8], required=True)
```

#### (2) `run()` 함수 분기 추가
```python
elif round_no == 5:
    return _run_round5(client, state)
elif round_no == 6:
    return _run_round6(client, state, dry_run=dry_run, debug=debug)
elif round_no == 7:
    return _run_round7(client, state)
elif round_no == 8:
    return _run_round8(client, state, dry_run=dry_run, debug=debug)
```

#### (3) `_run_round5()` 신규 함수
`_run_round1()`과 완전 동일 구조. state key만 `round5`로 저장.

```python
def _run_round5(client, state: StateManager) -> int:
    volume_rows = _fetch_volume_rank(client)
    power_rows  = _fetch_power_rank(client)
    fluct_rows  = _fetch_fluctuation_rank(client)

    round5 = {
        "time":     datetime.now().strftime("%H:%M"),
        "vol":      _extract_codes(volume_rows),
        "pow":      _extract_metric_map(power_rows, "tday_rltv"),
        "flc":      _extract_metric_map(fluct_rows, "prdy_ctrt"),
        "acml_vol": _extract_metric_map(volume_rows, "acml_vol"),
        "names":    _extract_name_map(volume_rows, power_rows, fluct_rows),
    }
    state.update("intraday_discovery", {"round5": round5}, caller="intraday_discovery")
    print(f"[완료] round5 저장 완료 ...", file=sys.stderr)
    return 0
```

#### (4) `_run_round6()` 신규 함수
`_run_round2()`와 동일 구조. 단:
- round1 대신 **round5** state 참조
- 메시지 헤더: `"🔍 오후장 종목 발굴"`
- `_build_message()` 대신 `_build_message_afternoon()` 사용
- `_save_discovery_log()` 호출 시 `session="afternoon"` 파라미터 추가 (기존 오전 로그와 구분)

```python
def _run_round6(client, state: StateManager, dry_run: bool = False, debug: bool = False) -> int:
    round5 = state.get("intraday_discovery.round5")
    if not isinstance(round5, dict):
        print("[오류] round5 데이터가 없습니다. 먼저 --round 5 를 실행하세요.", file=sys.stderr)
        return 1
    # ... round2와 동일한 교집합 로직 (vol_5, vol_6, pow_5, pow_6, flc_5, flc_6) ...
    # state key: round6
    # message: _build_message_afternoon()
```

#### (5) `_run_round7()` 신규 함수
`_run_round3()`과 완전 동일 구조. state key만 `round7`로 저장.

#### (6) `_run_round8()` 신규 함수
`_run_round4()`와 동일 구조. 단:
- round3 대신 **round7** state 참조
- 오전 추적: round2 대신 **round6** state 참조
- 메시지 헤더: `"🔍 오후장 종목 재발굴"`
- `_build_message_round8()` 사용 (round4의 `_build_message_round4()`와 동일 구조, 헤더만 다름)

```python
def _run_round8(client, state: StateManager, dry_run: bool = False, debug: bool = False) -> int:
    round7 = state.get("intraday_discovery.round7")
    if not isinstance(round7, dict):
        print("[오류] round7 데이터가 없습니다. 먼저 --round 7 을 실행하세요.", file=sys.stderr)
        return 1
    # round6 추적 (오전 round2 아님)
    round6 = state.get("intraday_discovery.round6") or {}
    # ... round4와 동일한 교집합 로직 ...
    # _fetch_afternoon_tracking(client, state) — round6 기준
```

#### (7) `_fetch_afternoon_tracking()` 신규 함수
`_fetch_morning_tracking()`과 동일 구조. round2 대신 **round6** 참조.

```python
def _fetch_afternoon_tracking(client, state: StateManager) -> list[dict[str, Any]]:
    """오후 round6 발굴 종목 상위 5개 현재가 추적."""
    round6 = state.get("intraday_discovery.round6") or {}
    if not isinstance(round6, dict) or not round6:
        print("[경고] round6 데이터 없음 — 오후 발굴 추적 생략", file=sys.stderr)
        return []
    # ... _fetch_morning_tracking()과 동일 로직 ...
```

#### (8) `_build_message_afternoon()` 신규 함수
`_build_message()`와 동일 구조. 헤더만 변경:
```python
f"🔍 오후장 종목 발굴 ({time_str})"
"코스피200 14:03분대 분석"
```

#### (9) `_build_message_round8()` 신규 함수
`_build_message_round4()`와 동일 구조. 헤더만 변경:
```python
f"🔍 오후장 종목 재발굴 ({time_str})"
"코스피200 14:30분대 분석"
# 추적 섹션 레이블: "📊 오후 발굴 종목 추적 (발굴 HH:MM 기준)"
```

#### (10) `_save_discovery_log()` 수정
오전/오후 구분을 위해 `session` 파라미터 추가:
```python
def _save_discovery_log(scored: list[dict], volume_rows: list[dict], session: str = "morning") -> None:
    # 기존 로직 동일
    # 각 항목에 "session": session 필드 추가
    existing.append({
        "date": today,
        "session": session,   # "morning" | "afternoon"
        "disc_time": disc_time,
        ...
    })
```

---

## 4. launchd plist 추가 (4개)

### `com.aigeenya.stockreport.discovery5.plist` (14:03)
### `com.aigeenya.stockreport.discovery6.plist` (14:05)
### `com.aigeenya.stockreport.discovery7.plist` (14:30)
### `com.aigeenya.stockreport.discovery8.plist` (14:33)

기존 discovery1~4 plist와 동일 구조. 시각과 round 번호만 변경.
`StandardErrorPath`: `intraday_discovery_error.log` (기존과 동일 파일에 append)

---

## 5. 영향 범위

| 파일 | 변경 내용 |
|------|-----------|
| `morning_report/intraday_discovery.py` | round 5~8 함수 추가, argparse choices 확장, `_save_discovery_log()` session 파라미터 추가 |
| `~/Library/LaunchAgents/com.aigeenya.stockreport.discovery5~8.plist` | 신규 생성 4개 |
| `CLAUDE.md` / `HANDOFF.md` | 스케줄 테이블 round 5~8 추가 |

기존 round 1~4 로직 변경 없음. 완전 후방 호환.

---

## 6. 예외 처리

- round5 없이 round6 실행 → 에러 메시지 + exit 1
- round7 없이 round8 실행 → 에러 메시지 + exit 1
- round6 없이 round8 실행 → 경고 로그 + 추적 섹션 생략, 신규 발굴만 전송
- `_fetch_current_price()` 실패 → cur_price=0, 수익률 N/A

---

## 7. 오전/오후 완전 분리 원칙

- round 5~8은 round 1~4 state를 **절대 참조하지 않음**
- `_save_discovery_log()`의 `session` 필드로 오전/오후 구분
- 추후 Phase 1.5 (전날 발굴 성과 요약) 시 session 필드로 필터링 가능
