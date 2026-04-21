# Stage 5 기술 설계 — intraday_discovery round 3/4

> 작성일: 2026-04-21  
> Stage 1 브레인스토밍 → Stage 4 계획 통합 → **Stage 5 기술 설계**

---

## 1. 목표

`intraday_discovery.py`에 round 3 (09:30 수집) + round 4 (09:33 분석·전송) 추가.

- round 3/4: 09:30분대 신규 교집합 종목 발굴 + 오전(round 2) 발굴 종목 추적

---

## 2. 실행 스케줄

| round | 시각  | 동작 |
|-------|-------|------|
| 1     | 09:03 | 수집만 (기존) |
| 2     | 09:05 | 교집합 분석 + 전송 (기존) |
| 3     | 09:30 | 수집만 (신규) |
| 4     | 09:33 | 교집합 분석 + 추적 + 전송 (신규) |

---

## 3. 변경 범위

### 3-1. `intraday_discovery.py` 수정

#### (1) `main()` argparse 수정
```python
# 변경 전
parser.add_argument("--round", dest="round_no", type=int, choices=[1, 2], required=True)

# 변경 후
parser.add_argument("--round", dest="round_no", type=int, choices=[1, 2, 3, 4], required=True)
```

#### (2) `run()` 함수 분기 추가
```python
if round_no == 1:
    return _run_round1(client, state)
elif round_no == 2:
    return _run_round2(client, state, dry_run=dry_run, debug=debug)
elif round_no == 3:
    return _run_round3(client, state)          # 신규
elif round_no == 4:
    return _run_round4(client, state, dry_run=dry_run, debug=debug)  # 신규
```

#### (3) `_run_round3()` 신규 함수
round 1과 동일한 구조. state key만 `round3`으로 저장.

```python
def _run_round3(client, state: StateManager) -> int:
    volume_rows = _fetch_volume_rank(client)
    power_rows  = _fetch_power_rank(client)
    fluct_rows  = _fetch_fluctuation_rank(client)

    round3 = {
        "time":     datetime.now().strftime("%H:%M"),
        "vol":      _extract_codes(volume_rows),
        "pow":      _extract_metric_map(power_rows, "tday_rltv"),
        "flc":      _extract_metric_map(fluct_rows, "prdy_ctrt"),
        "acml_vol": _extract_metric_map(volume_rows, "acml_vol"),
        "names":    _extract_name_map(volume_rows, power_rows, fluct_rows),
    }
    state.update("intraday_discovery", {"round3": round3}, caller="intraday_discovery")
    print(f"[완료] round3 저장 완료 ...", file=sys.stderr)
    return 0
```

#### (4) `_run_round4()` 신규 함수
round 2와 동일한 교집합 로직. 단, 아래 두 가지 추가:

**A. 오전 발굴 종목 추적**
- `state.get("intraday_discovery.round2")` 에서 `candidates` 목록 읽기
- `candidates` 중 상위 5개(score 기준)에 대해 현재가 조회 → `client.get_current_price(code)`
- `disc_price` 대비 수익률 계산: `(cur - disc) / disc * 100`

```python
def _fetch_morning_tracking(client, state) -> list[dict]:
    """오전 round2 발굴 종목 상위 5개 현재가 추적."""
    round2 = state.get("intraday_discovery.round2") or {}
    candidates = round2.get("candidates", [])
    # score 기준 내림차순 정렬 후 상위 5개
    top5 = sorted(candidates, key=lambda x: -x.get("score", 0))[:5]
    results = []
    for item in top5:
        code = item["code"]
        disc_price = item.get("disc_price", 0)
        try:
            price_info = client.get_current_price(code)
            cur_price = int(_safe_float(price_info.get("stck_prpr", 0)) or 0)
        except Exception:
            cur_price = 0
        ret_pct = (cur_price - disc_price) / disc_price * 100 if disc_price else 0
        results.append({
            "code":       code,
            "name":       item.get("name", code),
            "disc_price": disc_price,
            "cur_price":  cur_price,
            "ret_pct":    round(ret_pct, 2),
            "disc_time":  round2.get("time", ""),
        })
    return results
```

**B. 재확인 신호 판별**
- round 4 최종 후보(`scored`) 중 오전 발굴 종목(`round2.candidates`의 code 집합)과 겹치는 종목 → `is_reconfirmed = True`

```python
morning_codes = {c["code"] for c in round2.get("candidates", [])}
for item in scored:
    item["is_reconfirmed"] = item["code"] in morning_codes
```

#### (5) `_build_message_round4()` 신규 함수
round 2의 `_build_message()`와 별도로 round 4 전용 메시지 빌더 작성.

**메시지 구조:**
```
🔍 장중 종목 재발굴 (HH:MM)
―――――――――――――――
코스피200 09:30분대 분석

🥇 종목명 (코드)  N점  ⭐재확인  ← is_reconfirmed=True 일 때만 ⭐재확인 표시
   체결강도: 125(+12↑) | 등락률: +4.2%↑ | 거래량↑

🥈 종목명 (코드)  N점
   체결강도: 118(-3↓) | 등락률: +3.1%→ | 거래량↑

...

―――――――――――――――
📊 오전 발굴 종목 추적 (발굴 HH:MM 기준)
  ① 종목명  발굴가 38,500 → 현재 39,800  (+3.4%)
  ② 종목명  발굴가 12,300 → 현재 12,100  (-1.6%)
  ...최대 5개

―――――――――――――――
후보 N종목 → 상위 3종목 선정
```

- `⭐재확인` 태그: `is_reconfirmed=True` 종목에만 표시
- 오전 추적 섹션: `tracking` 리스트가 비어있으면 섹션 전체 생략
- 추가 관심 후보(4~5위): 기존 round 2와 동일하게 표시

---

## 4. launchd plist 추가

### `~/Library/LaunchAgents/aigeenya.stockpilot.round3.plist`
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>aigeenya.stockpilot.round3</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/geenya/projects/AI_Projects/stockpilot/venv/bin/python3</string>
        <string>/Users/geenya/projects/AI_Projects/stockpilot/morning_report/intraday_discovery.py</string>
        <string>--round</string>
        <string>3</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>30</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/geenya/projects/AI_Projects/stockpilot/logs/intraday_discovery.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/geenya/projects/AI_Projects/stockpilot/logs/intraday_discovery.log</string>
    <key>WorkingDirectory</key>
    <string>/Users/geenya/projects/AI_Projects/stockpilot</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
```

### `~/Library/LaunchAgents/aigeenya.stockpilot.round4.plist`
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>aigeenya.stockpilot.round4</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/geenya/projects/AI_Projects/stockpilot/venv/bin/python3</string>
        <string>/Users/geenya/projects/AI_Projects/stockpilot/morning_report/intraday_discovery.py</string>
        <string>--round</string>
        <string>4</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>33</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/geenya/projects/AI_Projects/stockpilot/logs/intraday_discovery.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/geenya/projects/AI_Projects/stockpilot/logs/intraday_discovery.log</string>
    <key>WorkingDirectory</key>
    <string>/Users/geenya/projects/AI_Projects/stockpilot</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
```

---

## 5. 영향 범위

| 파일 | 변경 내용 |
|------|-----------|
| `morning_report/intraday_discovery.py` | `_run_round3()`, `_run_round4()`, `_fetch_morning_tracking()`, `_build_message_round4()` 추가, `main()` choices 확장 |
| `~/Library/LaunchAgents/aigeenya.stockpilot.round3.plist` | 신규 생성 |
| `~/Library/LaunchAgents/aigeenya.stockpilot.round4.plist` | 신규 생성 |
| `CLAUDE.md` / `HANDOFF.md` | 스케줄 테이블 round 3/4 추가 |

기존 round 1/2 로직 변경 없음. 완전 후방 호환.

---

## 6. 예외 처리

- `round3` state 없이 `round4` 실행 시 → round 2와 동일하게 에러 메시지 + exit 1
- `round2` state 없이 `round4` 실행 시 (오전 추적 불가) → 추적 섹션 생략, 신규 발굴만 전송
- `get_current_price()` 실패 시 → `cur_price=0`, 수익률 `N/A` 표시
