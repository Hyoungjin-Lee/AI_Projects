# Codex 구현 지시서 — intraday_discovery 고도화 (Phase 1)

> 이 문서를 Codex에게 전달하여 구현을 요청하세요.

---

## 역할

당신은 Python 백엔드 개발자입니다.
아래 명세에 따라 기존 파일 2개를 수정해주세요.

---

## 프로젝트 환경

- Python 3.14, macOS
- 프로젝트 루트: `/Users/geenya/projects/AI_Projects/stockpilot`
- 인증정보: `from keychain_manager import inject_to_env; inject_to_env()` (이미 각 파일 상단에 있음)
- 공유 상태: `from state_manager import StateManager` (이미 각 파일에 있음)

---

## 수정할 파일 1: `morning_report/intraday_discovery.py`

### 변경 1 — `_save_discovery_log()` 함수 추가

파일 끝 (`if __name__ == "__main__":` 위)에 아래 함수를 추가하세요:

```python
def _save_discovery_log(scored: list[dict], volume_rows: list[dict]) -> None:
    """발굴 결과를 data/discovery_log.json에 기록. 실패해도 예외 없이 경고만 출력."""
    try:
        from datetime import date as _date
        import json as _json

        log_file = _ROOT / "data" / "discovery_log.json"

        # 기존 로그 읽기
        if log_file.exists():
            try:
                existing = _json.loads(log_file.read_text(encoding="utf-8"))
                if not isinstance(existing, list):
                    existing = []
            except Exception:
                existing = []
        else:
            existing = []

        # disc_price 매핑: volume_rows의 stck_prpr 필드
        price_map = _extract_metric_map(volume_rows, "stck_prpr")

        today = _date.today().isoformat()
        disc_time = datetime.now().strftime("%H:%M")

        # 오늘 날짜 기존 항목 제거 (재실행 시 덮어쓰기)
        existing = [e for e in existing if e.get("date") != today]

        # 새 항목 추가
        for item in scored:
            existing.append({
                "date": today,
                "disc_time": disc_time,
                "code": item["code"],
                "name": item["name"],
                "disc_price": int(price_map.get(item["code"], 0)),
                "score": item["score"],
                "pow_2": round(item["pow_2"], 1),
                "flc_2": round(item["flc_2"], 2),
                "close_price": None,
                "return_pct": None,
                "updated_at": None,
            })

        # 30일 이전 항목 삭제
        from datetime import timedelta
        cutoff = (_date.today() - timedelta(days=30)).isoformat()
        existing = [e for e in existing if e.get("date", "") >= cutoff]

        # 저장
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text(
            _json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"[발굴로그] {len(scored)}개 종목 기록 완료 → {log_file.name}", file=sys.stderr)
    except Exception as e:
        print(f"[발굴로그] 저장 실패 (무시): {e}", file=sys.stderr)
```

### 변경 2 — `_run_round2()` 수정

`message = _build_message(...)` 호출 **직전**에 아래 한 줄 추가:

```python
_save_discovery_log(scored, volume_rows)
```

`volume_rows`는 `_run_round2()` 내에 이미 선언되어 있습니다.

### 변경 3 — `_build_message()` 수정

함수 시그니처 변경:
```python
# 기존
def _build_message(time_str: str, top_picks: list[dict[str, Any]], candidate_count: int) -> str:

# 변경 후
def _build_message(time_str: str, top_picks: list[dict[str, Any]], candidate_count: int, all_scored: list[dict[str, Any]] | None = None) -> str:
```

기존 출력 마지막 `lines.extend([...후보 N종목...])` **앞에** 아래 블록 추가:

```python
    # 추가 관심 후보 (4위 이상인 경우)
    if all_scored and len(all_scored) >= 4:
        extra = all_scored[3:5]  # 4위, 5위 (최대 2개)
        lines.append("―――――――――――――――")
        lines.append("📋 추가 관심 후보")
        for rank, item in enumerate(extra, start=4):
            lines.append(
                f"  {rank}위 {item['name']} ({item['code']}) "
                f"— 체결강도: {item['pow_2']:.0f} | {item['flc_2']:+.1f}%"
            )
```

`_run_round2()`에서 `_build_message()` 호출 부분도 수정:
```python
# 기존
message = _build_message(round2["time"], top_picks, len(scored))

# 변경 후
message = _build_message(round2["time"], top_picks, len(scored), all_scored=scored)
```

---

## 수정할 파일 2: `morning_report/closing_report.py`

### 변경 1 — `_update_discovery_log()` 함수 추가

파일 끝 (`if __name__ == "__main__":` 위)에 아래 함수를 추가하세요:

```python
def _update_discovery_log(client) -> None:
    """오늘 발굴 종목의 종가를 discovery_log.json에 업데이트. 실패해도 경고만 출력."""
    try:
        import json as _json
        from datetime import datetime as _dt, date as _date

        log_file = _ROOT / "data" / "discovery_log.json"
        if not log_file.exists():
            return

        log = _json.loads(log_file.read_text(encoding="utf-8"))
        if not isinstance(log, list):
            return

        today = _date.today().isoformat()
        updated = 0

        for entry in log:
            if entry.get("date") != today:
                continue
            if entry.get("close_price") is not None:
                continue

            code = entry.get("code")
            if not code:
                continue

            try:
                # 장마감 후 현재가 = 종가
                price_info = client.get_current_price(code)
                close_price = int(price_info.get("stck_prpr", 0)) if isinstance(price_info, dict) else 0

                # get_current_price 없으면 get_stock_info 시도
                if close_price == 0:
                    info = client.get_stock_info(code)
                    close_price = int(_safe_float(info.get("stck_prpr", 0)) or 0)

                if close_price > 0:
                    disc_price = entry.get("disc_price", 0)
                    entry["close_price"] = close_price
                    entry["return_pct"] = round((close_price - disc_price) / disc_price * 100, 2) if disc_price > 0 else None
                    entry["updated_at"] = _dt.now().strftime("%Y-%m-%dT%H:%M:%S")
                    updated += 1
            except Exception as e:
                print(f"[발굴로그] {code} 종가 조회 실패: {e}", file=sys.stderr)

        log_file.write_text(
            _json.dumps(log, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"[발굴로그] 종가 업데이트 완료: {updated}개", file=sys.stderr)
    except Exception as e:
        print(f"[발굴로그] 업데이트 실패 (무시): {e}", file=sys.stderr)
```

### 변경 2 — `_build_closing_report()` 내 호출 추가

`_build_closing_report()` 함수 내부, `client` 초기화 직후에 아래 블록 추가:

```python
    # 발굴 성과 업데이트 (장마감 종가 기록)
    _update_discovery_log(client)
```

`client`가 초기화되는 위치는 함수 상단부에 있습니다. `client`가 `None`일 수 있으므로:
```python
    if client:
        _update_discovery_log(client)
```

---

## 주의사항

1. 기존 함수 동작 변경 금지 — 추가만 할 것
2. `_update_discovery_log()`에서 `client.get_current_price()` 메서드가 없으면
   `client.get_stock_info()` 또는 `client.get_daily_chart(code, days=1)`로 대체하되,
   반드시 `stck_prpr` (현재가) 필드를 사용할 것
3. 파일 수정 후 반드시 문법 검사 실행:
   ```bash
   venv/bin/python3 -m py_compile morning_report/intraday_discovery.py
   venv/bin/python3 -m py_compile morning_report/closing_report.py
   ```
4. 테스트:
   ```bash
   venv/bin/python3 morning_report/intraday_discovery.py --round 2 --dry-run
   cat data/discovery_log.json
   venv/bin/python3 morning_report/closing_report.py --dry-run
   cat data/discovery_log.json
   ```
