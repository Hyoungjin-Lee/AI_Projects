# Codex Brief 13-A — A1 시간대 확장

> **입력 문서:** `docs/13_briefing_enhancement/04_plan_final.md`
> **담당자:** Codex
> **작업 범위:** intraday_discovery.py round 9~26 추가 + launchd plist 18개 등록
> **사전 작업 완료:**
> - `_korean_hm()` / `_time_header()` 헬퍼 (헤더 자동 처리)
> - `_get_time_thresholds(hour)` 헬퍼 (시간대별 임계값 자동 적용)
> - `_DISPARITY_OVERHEATED_THRESHOLD = 130` 상수
> - `_TOP_N = 50`

---

## 0. 작업 개요

기존 round 1~8 (9시/14시 발굴+재발굴 사이클) 에 시간대 확장:

```
[기존]                      [신규 추가]
9시  → round 1~4           10시 → round 9~12
14시 → round 5~8           11시 → round 13~16
                           12시 → round 17~20
                           13시 → round 21~24
                           15시 → round 25~26 (재발굴 없음)
```

**총 신규: round 함수 18개 + launchd plist 18개**

---

## 1. 공통 원칙

1. **기존 패턴 100% 재사용** — 새 로직 만들지 말 것
   - 홀수 round (수집): `_run_round1` 그대로 복제
   - 짝수 round (발굴 1차): `_run_round2` 그대로 복제
   - 짝수 round (재발굴): `_run_round4` 그대로 복제

2. **자동 처리되는 것 (수정 X):**
   - 메시지 헤더: `_time_header(time_str, "발굴"|"재발굴")` — 12시 신뢰도 자동 추가
   - 한국어 시간 변환: `_korean_hm(time_str)` — "10:05" → "10시 5분"
   - 임계값: `_score_candidate()` 내부에서 `_get_time_thresholds(datetime.now().hour)` 자동 호출

3. **dry-run 가드 필수** — `[v2.7.3 핫픽스]` 패턴 준수
   - state.update / _save_discovery_log 모두 가드

4. **하위 호환성 유지** — 기존 _run_round1~8 시그니처 변경 금지

5. **문법 검사 필수** — `venv/bin/python3 -m py_compile morning_report/intraday_discovery.py`

---

## 2. Round 매핑 표 (전체)

| Round | 시각 | 역할 | 패턴 복제 대상 | 텔레그램 |
|-------|------|------|--------------|---------|
| 1 | 09:03 | 9시 발굴 1차 수집 | (기존) | ❌ |
| 2 | 09:05 | 9시 발굴 2차 + 텔레그램 | (기존) | ✅ |
| 3 | 09:30 | 9시 재발굴 1차 수집 | (기존) | ❌ |
| 4 | 09:33 | 9시 재발굴 2차 + 추적 | (기존) | ✅ |
| 5 | 14:03 | 14시 발굴 1차 수집 | (기존) | ❌ |
| 6 | 14:05 | 14시 발굴 2차 + 텔레그램 | (기존) | ✅ |
| 7 | 14:30 | 14시 재발굴 1차 수집 | (기존) | ❌ |
| 8 | 14:33 | 14시 재발굴 2차 + 추적 | (기존) | ✅ |
| **9** | **10:03** | **10시 발굴 1차** | round1 | ❌ |
| **10** | **10:05** | **10시 발굴 2차** | round2 | ✅ |
| **11** | **10:30** | **10시 재발굴 1차** | round3 | ❌ |
| **12** | **10:33** | **10시 재발굴 2차 + 추적** | round4 (round10 추적) | ✅ |
| **13** | **11:03** | **11시 발굴 1차** | round1 | ❌ |
| **14** | **11:05** | **11시 발굴 2차** | round2 | ✅ |
| **15** | **11:30** | **11시 재발굴 1차** | round3 | ❌ |
| **16** | **11:33** | **11시 재발굴 2차 + 추적** | round4 (round14 추적) | ✅ |
| **17** | **12:03** | **12시 발굴 1차** | round1 | ❌ |
| **18** | **12:05** | **12시 발굴 2차** | round2 | ✅ |
| **19** | **12:30** | **12시 재발굴 1차** | round3 | ❌ |
| **20** | **12:33** | **12시 재발굴 2차 + 추적** | round4 (round18 추적) | ✅ |
| **21** | **13:03** | **13시 발굴 1차** | round1 | ❌ |
| **22** | **13:05** | **13시 발굴 2차** | round2 | ✅ |
| **23** | **13:30** | **13시 재발굴 1차** | round3 | ❌ |
| **24** | **13:33** | **13시 재발굴 2차 + 추적** | round4 (round22 추적) | ✅ |
| **25** | **15:03** | **15시 발굴 1차** | round1 | ❌ |
| **26** | **15:05** | **15시 발굴 2차** | round2 | ✅ |

---

## 3. 함수 구현 가이드

### 3.1 홀수 round (수집만) — round 9/11/13/15/17/19/21/23/25

**패턴 원본:** `_run_round1()` (line 88~ 부근)

**복제 시 변경 사항만:**
```python
def _run_round9(client, state: StateManager, dry_run: bool = False) -> int:
    volume_rows = _fetch_volume_rank(client)
    power_rows = _fetch_power_rank(client)
    fluct_rows = _fetch_fluctuation_rank(client)

    round_data = {
        "time": datetime.now().strftime("%H:%M"),
        "vol": _extract_codes(volume_rows),
        "pow": _extract_metric_map(power_rows, "tday_rltv"),
        "flc": _extract_metric_map(fluct_rows, "prdy_ctrt"),
        "acml_vol": _extract_metric_map(volume_rows, "acml_vol"),
        "names": _extract_name_map(volume_rows, power_rows, fluct_rows),
    }

    if dry_run:
        print(
            f"[dry-run] round9 state 저장 스킵 "
            f"(거래량 {len(round_data['vol'])} / 체결강도 {len(round_data['pow'])} / 등락률 {len(round_data['flc'])})",
            file=sys.stderr,
        )
        return 0

    state.update("intraday_discovery", {"round9": round_data}, caller="intraday_discovery")
    print(
        f"[완료] round9 저장 완료 "
        f"(거래량 {len(round_data['vol'])} / 체결강도 {len(round_data['pow'])} / 등락률 {len(round_data['flc'])})",
        file=sys.stderr,
    )
    return 0
```

→ round 11/13/15/17/19/21/23/25 모두 같은 패턴, `round9` → `round11` 등으로만 변경.

### 3.2 짝수 발굴 round — round 10/14/18/22/26

**패턴 원본:** `_run_round2()` (line ~219)

**핵심 차이:** 짝수 발굴 round는 **추적(tracking) 섹션 없음** (재발굴이 아니므로).

**round 10 예시:**
```python
def _run_round10(client, state: StateManager, dry_run: bool = False, debug: bool = False) -> int:
    """10시 발굴 2차 — round9 데이터 + 현재 데이터 교집합."""
    round9 = state.get("intraday_discovery.round9") or {}
    if not round9:
        print("[경고] round9 데이터 없음 — 10시 발굴 스킵", file=sys.stderr)
        return 0

    volume_rows = _fetch_volume_rank(client)
    power_rows = _fetch_power_rank(client)
    fluct_rows = _fetch_fluctuation_rank(client)
    disparity_rows = _fetch_disparity_rank(client)
    hts_rows = _fetch_hts_rank(client)

    # round1 → round9 로 변경 (이전 라운드 참조)
    vol_1 = set(round9.get("vol", []))
    vol_2 = set(_extract_codes(volume_rows))
    pow_1 = set((round9.get("pow") or {}).keys())
    pow_2 = set(_extract_metric_map(power_rows, "tday_rltv").keys())
    flc_1 = set((round9.get("flc") or {}).keys())
    flc_2 = set(_extract_metric_map(fluct_rows, "prdy_ctrt").keys())

    # ... [round2의 디버그 + candidates + overheated + filtered + scored 부분 그대로 복사]

    metrics = {
        "pow_1": round9.get("pow", {}) or {},
        "pow_2": _extract_metric_map(power_rows, "tday_rltv"),
        "flc_1": round9.get("flc", {}) or {},
        "flc_2": _extract_metric_map(fluct_rows, "prdy_ctrt"),
        "vol_1": round9.get("acml_vol", {}) or {},
        "vol_2": _extract_metric_map(volume_rows, "acml_vol"),
        "disparity": _extract_metric_map(disparity_rows, "d20_dsrt"),
    }

    # ... [scored 부분 그대로]

    round10 = {
        "time": datetime.now().strftime("%H:%M"),
        "candidate_count": len(scored),
        "overheated_count": len(candidates & overheated),
        "candidates": [...],   # round2와 동일 구조
        "top_picks": [item["code"] for item in top_picks],
    }

    if not dry_run:
        state.update("intraday_discovery", {"round10": round10}, caller="intraday_discovery")
        _save_discovery_log(scored, volume_rows, session="morning_10")  # ← session 라벨 필요
    else:
        print(f"[dry-run] round10 state/discovery_log 저장 스킵 ({len(scored)}종목)", file=sys.stderr)

    message = _build_message(round10["time"], top_picks, len(scored), all_scored=scored)
    if dry_run:
        print("\n" + "=" * 50)
        print(message)
        print("=" * 50)
        print("\n[DRY-RUN] 텔레그램 전송 생략")
        return 0

    try:
        from telegram_sender import send_text
        ok = send_text(message)
    except Exception as exc:
        print(f"[오류] 텔레그램 전송 실패: {exc}", file=sys.stderr)
        return 1

    if ok:
        print(f"[완료] 텔레그램 전송 성공 ({len(scored)}개 후보)", file=sys.stderr)
        return 0
    print("[오류] 텔레그램 전송 실패", file=sys.stderr)
    return 1
```

→ round 14/18/22/26 모두 같은 패턴:
- round 14: round13 참조, session="morning_11"
- round 18: round17 참조, session="lunch_12"
- round 22: round21 참조, session="afternoon_13"
- round 26: round25 참조, session="afternoon_15"

### 3.3 짝수 재발굴 round — round 12/16/20/24

**패턴 원본:** `_run_round4()` (line ~365)

**핵심:** 같은 시간대의 첫 발굴 round 결과를 추적 (예: round12 → round10 추적)

**round 12 예시:**
```python
def _run_round12(client, state: StateManager, dry_run: bool = False, debug: bool = False) -> int:
    """10시 재발굴 — round11 데이터 + 현재 + round10 결과 추적."""
    round11 = state.get("intraday_discovery.round11") or {}
    round10 = state.get("intraday_discovery.round10") or {}
    if not round11:
        print("[경고] round11 데이터 없음 — 10시 재발굴 스킵", file=sys.stderr)
        return 0

    # ... [round4와 동일한 fetch + 교집합 + scored]
    # round1 → round11, round2 → round10 으로 변경

    # ⭐재확인 태그
    if not round10:
        print("[경고] round10 데이터 없음 — 10시 발굴 추적 및 재확인 태그 생략", file=sys.stderr)
        for item in scored:
            item["is_reconfirmed"] = False
    else:
        prev_codes = {c["code"] for c in round10.get("candidates", [])}
        for item in scored:
            reconfirmed = " ⭐재확인" if item.get("is_reconfirmed") else ""
            item["is_reconfirmed"] = item["code"] in prev_codes

    # 추적 (round10 상위 5개)
    tracking = _track_round10_picks(client, round10) if round10 else None

    round12 = {
        "time": datetime.now().strftime("%H:%M"),
        ...
    }

    # state.update + 텔레그램 전송 — round4 패턴 동일
    message = _build_message_round4(round12["time"], top_picks, len(scored), tracking=tracking, all_scored=scored)
    # ↑ round4의 빌더를 그대로 재사용 (헤더가 _time_header로 자동 처리되므로)
```

→ round 16/20/24 패턴:
- round 16: round15 데이터, round14 추적, _track_round14_picks
- round 20: round19 데이터, round18 추적, _track_round18_picks
- round 24: round23 데이터, round22 추적, _track_round22_picks

**선택:** 추적 함수도 신규 8개 추가하는 대신, **기존 `_track_round2_picks()` 같은 함수를 일반화**해서 round 번호를 인자로 받도록 리팩터링 권장.

```python
def _track_recent_picks(client, round_data: dict | None) -> list[dict] | None:
    """이전 발굴 round의 상위 5개 종목 현재가 추적 (모든 시간대 공용)."""
    if not round_data:
        return None
    # ... [기존 _track_round2_picks 또는 _track_round6_picks 로직 그대로]
```

기존 `_track_round2_picks` / `_track_round6_picks` 도 이 일반화 함수로 대체 가능 (선택 — 안전을 위해 유지하고 신규만 일반화 사용해도 OK).

### 3.4 dispatcher (run 함수) 확장

**위치:** `morning_report/intraday_discovery.py` line ~50 부근의 `run()` 함수

**현재 분기:**
```python
if round_no == 1: return _run_round1(...)
if round_no == 2: return _run_round2(...)
...
return _run_round8(...)  # else
```

**확장:**
```python
if round_no == 1: return _run_round1(client, state, dry_run=dry_run)
if round_no == 2: return _run_round2(client, state, dry_run=dry_run, debug=debug)
if round_no == 3: return _run_round3(client, state, dry_run=dry_run)
if round_no == 4: return _run_round4(client, state, dry_run=dry_run, debug=debug)
if round_no == 5: return _run_round5(client, state, dry_run=dry_run)
if round_no == 6: return _run_round6(client, state, dry_run=dry_run, debug=debug)
if round_no == 7: return _run_round7(client, state, dry_run=dry_run)
if round_no == 8: return _run_round8(client, state, dry_run=dry_run, debug=debug)
# 신규 시간대
if round_no == 9: return _run_round9(client, state, dry_run=dry_run)
if round_no == 10: return _run_round10(client, state, dry_run=dry_run, debug=debug)
if round_no == 11: return _run_round11(client, state, dry_run=dry_run)
if round_no == 12: return _run_round12(client, state, dry_run=dry_run, debug=debug)
if round_no == 13: return _run_round13(client, state, dry_run=dry_run)
if round_no == 14: return _run_round14(client, state, dry_run=dry_run, debug=debug)
if round_no == 15: return _run_round15(client, state, dry_run=dry_run)
if round_no == 16: return _run_round16(client, state, dry_run=dry_run, debug=debug)
if round_no == 17: return _run_round17(client, state, dry_run=dry_run)
if round_no == 18: return _run_round18(client, state, dry_run=dry_run, debug=debug)
if round_no == 19: return _run_round19(client, state, dry_run=dry_run)
if round_no == 20: return _run_round20(client, state, dry_run=dry_run, debug=debug)
if round_no == 21: return _run_round21(client, state, dry_run=dry_run)
if round_no == 22: return _run_round22(client, state, dry_run=dry_run, debug=debug)
if round_no == 23: return _run_round23(client, state, dry_run=dry_run)
if round_no == 24: return _run_round24(client, state, dry_run=dry_run, debug=debug)
if round_no == 25: return _run_round25(client, state, dry_run=dry_run)
if round_no == 26: return _run_round26(client, state, dry_run=dry_run, debug=debug)
raise ValueError(f"unknown round_no: {round_no}")
```

---

## 4. launchd plist 18개

### 4.1 위치
`/Users/geenya/Library/LaunchAgents/com.aigeenya.stockreport.discovery{N}.plist`

### 4.2 패턴 — 기존 plist 그대로 복제 (시각만 변경)

기준 파일: `com.aigeenya.stockreport.discovery1.plist` (09:03)

**복제 절차:**
```bash
# discovery1.plist 를 9.plist 로 복사 후 시각 + Label + 인자만 수정
cp /Users/geenya/Library/LaunchAgents/com.aigeenya.stockreport.discovery1.plist \
   /Users/geenya/Library/LaunchAgents/com.aigeenya.stockreport.discovery9.plist

/usr/libexec/PlistBuddy -c "Set :Label com.aigeenya.stockreport.discovery9" \
   /Users/geenya/Library/LaunchAgents/com.aigeenya.stockreport.discovery9.plist

/usr/libexec/PlistBuddy -c "Set :StartCalendarInterval:0:Hour 10" \
   /Users/geenya/Library/LaunchAgents/com.aigeenya.stockreport.discovery9.plist

/usr/libexec/PlistBuddy -c "Set :StartCalendarInterval:0:Minute 3" \
   /Users/geenya/Library/LaunchAgents/com.aigeenya.stockreport.discovery9.plist

# ProgramArguments 의 --round 값 수정 (PlistBuddy로 인자 인덱스 검색 후 변경)
/usr/libexec/PlistBuddy -c "Print :ProgramArguments" \
   /Users/geenya/Library/LaunchAgents/com.aigeenya.stockreport.discovery9.plist
# discovery1.plist 의 ProgramArguments[3] 가 "1" 이라면 그것을 "9" 로 바꾼다
/usr/libexec/PlistBuddy -c "Set :ProgramArguments:3 9" \
   /Users/geenya/Library/LaunchAgents/com.aigeenya.stockreport.discovery9.plist
```

### 4.3 시간 매핑 (Hour, Minute)

| Plist | Round | Hour | Minute |
|-------|-------|------|--------|
| discovery9 | 9 | 10 | 3 |
| discovery10 | 10 | 10 | 5 |
| discovery11 | 11 | 10 | 30 |
| discovery12 | 12 | 10 | 33 |
| discovery13 | 13 | 11 | 3 |
| discovery14 | 14 | 11 | 5 |
| discovery15 | 15 | 11 | 30 |
| discovery16 | 16 | 11 | 33 |
| discovery17 | 17 | 12 | 3 |
| discovery18 | 18 | 12 | 5 |
| discovery19 | 19 | 12 | 30 |
| discovery20 | 20 | 12 | 33 |
| discovery21 | 21 | 13 | 3 |
| discovery22 | 22 | 13 | 5 |
| discovery23 | 23 | 13 | 30 |
| discovery24 | 24 | 13 | 33 |
| discovery25 | 25 | 15 | 3 |
| discovery26 | 26 | 15 | 5 |

### 4.4 등록 (load)

```bash
for n in 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26; do
    launchctl load -w /Users/geenya/Library/LaunchAgents/com.aigeenya.stockreport.discovery${n}.plist
done
```

### 4.5 등록 확인

```bash
launchctl list | grep aigeenya.stockreport.discovery | sort
# 26개 (discovery + discovery1~26) 가 출력되어야 함
```

---

## 5. 검증 시나리오

### 5.1 문법 검사
```bash
cd /Users/geenya/projects/AI_Projects/stockpilot
venv/bin/python3 -m py_compile morning_report/intraday_discovery.py
```

### 5.2 dry-run 단위 테스트 (round 별)

```bash
# 홀수 round (수집)
for n in 9 11 13 15 17 19 21 23 25; do
    venv/bin/python3 morning_report/intraday_discovery.py --round $n --dry-run
done

# 짝수 round (발굴+텔레그램) — dry-run 시 텔레그램 전송 X
for n in 10 14 18 22 26; do
    # 직전 홀수 round의 데이터가 state에 있어야 동작 — 같은 시간대 홀수 round 먼저 실행 후 테스트
    venv/bin/python3 morning_report/intraday_discovery.py --round $((n-1))   # 실제 실행 1번
    venv/bin/python3 morning_report/intraday_discovery.py --round $n --dry-run
done

# 재발굴 round
for n in 12 16 20 24; do
    venv/bin/python3 morning_report/intraday_discovery.py --round $((n-1))   # 재발굴 1차
    venv/bin/python3 morning_report/intraday_discovery.py --round $n --dry-run
done
```

### 5.3 plist 검증
```bash
# 모든 plist 시각 점검
for n in 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26; do
    plist="/Users/geenya/Library/LaunchAgents/com.aigeenya.stockreport.discovery${n}.plist"
    h=$(/usr/libexec/PlistBuddy -c "Print :StartCalendarInterval:0:Hour" "$plist")
    m=$(/usr/libexec/PlistBuddy -c "Print :StartCalendarInterval:0:Minute" "$plist")
    printf "discovery%-3d %02d:%02d\n" $n $h $m
done
```

### 5.4 운영 검증 (다음 평일)

| 시각 | 검증 |
|------|------|
| 10:03 | round9 stderr 로그 + state 저장 |
| 10:05 | round10 텔레그램 발송 + 헤더 "10시 5분 발굴" |
| 10:30 | round11 stderr |
| 10:33 | round12 텔레그램 + ⭐재확인 + 추적 섹션 |
| 11:05 | round14 텔레그램 |
| 12:05 | round18 텔레그램 + "12시 5분 발굴 (점심 신뢰도 ↓)" |
| 12:33 | round20 |
| 13:05 | round22 |
| 13:33 | round24 |
| 15:05 | round26 (재발굴 없음 — 발굴 한 번만) |

---

## 6. 산출물 체크리스트

- [ ] `morning_report/intraday_discovery.py` — 18개 round 함수 추가 + dispatcher 분기 추가 + py_compile 통과
- [ ] `_track_recent_picks()` 일반화 함수 (또는 _track_round{N}_picks 8개) 추가
- [ ] launchd plist 18개 신규 작성 + Label / Hour / Minute / ProgramArguments 정확
- [ ] launchctl load 18개 모두 성공 + `launchctl list | grep aigeenya.stockreport.discovery | wc -l` = 27 (기존 1 + discovery + 1~26 = 28, "discovery" 미번호 항목 1개 포함 시)
- [ ] dry-run 테스트 각 round 통과
- [ ] HANDOFF.md 업데이트 (자동 실행 스케줄 표 18행 추가)

---

## 7. 보고 형식

```
status: Brief 13-A 완료 (또는 부분 완료 + blocker)
completion_reason:
- 추가 round 함수 18개
- 추가 plist 18개
- dispatcher 분기 26개
- py_compile / launchctl list / dry-run 모두 통과
files_changed:
- morning_report/intraday_discovery.py
- /Users/geenya/Library/LaunchAgents/com.aigeenya.stockreport.discovery{9..26}.plist
warnings:
- (있을 경우)
next_recommended_action:
- 다음 평일 10:03~15:05 자동 실행 모니터링
```

---

*Brief 13-A: 시간대 확장 (round 9~26 + plist 18)*
*Pre-work: A2 (시간대별 임계값) + A3 (12시 신뢰도) 이미 적용됨 — 함수만 복제하면 자동 동작*
