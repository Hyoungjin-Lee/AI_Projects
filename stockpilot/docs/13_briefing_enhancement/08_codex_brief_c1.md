# Codex Brief 13-C — C1 pattern_lifecycle.py + plist 등록

> **입력 문서:** `docs/13_briefing_enhancement/04_plan_final.md` §3 + Pattern Integration `04_plan_final.md` §6
> **담당자:** Codex
> **작업 범위:** 신규 pattern_lifecycle.py + launchd plist + 후속 추적 자동화

---

## 0. 작업 개요

`data/discovery_log.json` 발굴 종목의 후속 가격을 자동 추적하여 시간대별/점수별 승률 통계 산출:

- **+24h 종가 추적** — 발굴일 기준 다음 거래일 종가
- **+72h 종가 추적** — 발굴일 기준 3거래일 후 종가
- **outcome 판정** — true_positive / false_positive / neutral
- **launchd 23:35 자동 실행** (closing_report 5분 후, 의존성 보장)

`closing_report.py` 가 이미 당일 close_price/return_pct 를 업데이트하므로, 본 작업은 **+24h/+72h 후속 추적 + outcome 라벨**에 집중.

---

## 1. 공통 원칙

1. **closing_report 와 비파괴적 통합** — 기존 close_price/return_pct 필드 건드리지 않음
2. **신규 필드 추가만:** `lifecycle_24h_close`, `lifecycle_72h_close`, `outcome`, `outcome_judged_at`
3. **launchd 23:35 시작** — closing_report (23:30) 5분 후 (의존성 보장 — 23:30 실행은 20:30 부터 변경됨? 확인 필요)
4. **재실행 안전** — 이미 추적된 항목은 재호출하지 않음 (멱등성)

---

## 2. discovery_log.json 스키마 확장

### 2.1 기존 필드 (유지)

```json
{
  "date": "2026-04-21",
  "disc_time": "09:05",
  "code": "375500",
  "name": "DL이앤씨",
  "disc_price": 98300,
  "score": 5,
  "pow_2": 245.7,
  "flc_2": 2.93,
  "close_price": 100600,        // ← closing_report 가 업데이트 (당일)
  "return_pct": 2.34,           // ← 동상 (당일)
  "updated_at": "2026-04-21T20:30:07"
}
```

### 2.2 신규 필드 (lifecycle 추가)

```json
{
  ... (위 동일) ...
  "lifecycle_24h_close": 102500,        // +24h 후 종가 (다음 거래일)
  "lifecycle_72h_close": 99800,         // +72h 후 종가 (3거래일 후)
  "outcome_24h": "true_positive",       // "true_positive" | "false_positive" | "neutral"
  "outcome_72h": "neutral",
  "lifecycle_updated_at": "2026-04-24T23:35:10"
}
```

---

## 3. 신규 파일: `morning_report/pattern_lifecycle.py`

### 3.1 시그니처

```python
"""
pattern_lifecycle.py — 발굴 종목 후속 가격 추적 (C1)

실행 시점: 매일 23:35 (launchd com.aigeenya.stockreport.pattern_lifecycle)

기능:
  1. data/discovery_log.json 읽어 lifecycle_24h_close / lifecycle_72h_close 업데이트
  2. outcome_24h / outcome_72h 판정
  3. 통계 출력 (stderr) — 시간대별 / 점수별 승률

사용:
  venv/bin/python3 morning_report/pattern_lifecycle.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / ".skills" / "kis-api" / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))

from keychain_manager import inject_to_env
inject_to_env()
from kis_client import KISClient

_LOG_FILE = _ROOT / "data" / "discovery_log.json"


def _previous_trading_day(d: date, n: int = 1) -> date:
    """n 거래일 전 (주말 제외, 단순 weekday 기반)."""
    cur = d
    for _ in range(n):
        cur -= timedelta(days=1)
        while cur.weekday() >= 5:
            cur -= timedelta(days=1)
    return cur


def _next_trading_day(d: date, n: int = 1) -> date:
    """n 거래일 후 (주말 제외)."""
    cur = d
    for _ in range(n):
        cur += timedelta(days=1)
        while cur.weekday() >= 5:
            cur += timedelta(days=1)
    return cur


def _judge_outcome(disc_price: float, future_close: float | None) -> str:
    """
    수익률 기반 outcome 판정.
    
    +2% 이상 = true_positive
    -2% 이하 = false_positive
    그 외 = neutral
    
    None 입력 시 "pending"
    """
    if future_close is None or disc_price is None or disc_price == 0:
        return "pending"
    pct = (future_close - disc_price) / disc_price * 100
    if pct >= 2.0:
        return "true_positive"
    if pct <= -2.0:
        return "false_positive"
    return "neutral"


def _fetch_close_price(client: KISClient, code: str, target_date: date) -> int | None:
    """
    target_date 의 종가 조회 (KIS daily chart).
    
    target_date 가 미래면 None 반환.
    """
    if target_date > date.today():
        return None
    try:
        # get_daily_chart 의 days 인자 = 가져올 일수. target_date 까지 충분히 fetch.
        days_ago = (date.today() - target_date).days + 5  # 여유 5일
        chart = client.get_daily_chart(code, days=days_ago)
        target_str = target_date.strftime("%Y%m%d")
        for row in chart:
            if row.get("stck_bsop_date") == target_str:
                return int(row.get("stck_clpr", 0))
    except Exception as e:
        print(f"[lifecycle] {code} {target_date} 종가 조회 실패: {e}", file=sys.stderr)
    return None


def update_lifecycle(dry_run: bool = False) -> int:
    """
    discovery_log.json 의 lifecycle 필드 업데이트.
    
    대상:
      - lifecycle_24h_close 가 None 이고 +24h 거래일이 today 이전인 레코드
      - lifecycle_72h_close 가 None 이고 +72h 거래일이 today 이전인 레코드
    """
    if not _LOG_FILE.exists():
        print("[lifecycle] discovery_log.json 없음 — 종료", file=sys.stderr)
        return 0

    try:
        data = json.loads(_LOG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[lifecycle] discovery_log 로드 실패: {e}", file=sys.stderr)
        return 1

    if not isinstance(data, list):
        return 1

    today = date.today()
    client = KISClient()  # observation 모드 (관측용)

    updated_24h = 0
    updated_72h = 0

    for record in data:
        try:
            disc_date_str = record.get("date")
            if not disc_date_str:
                continue
            disc_date = date.fromisoformat(disc_date_str)
            code = record.get("code")
            disc_price = record.get("disc_price")

            # +24h 추적 (다음 거래일)
            if record.get("lifecycle_24h_close") is None:
                target_24h = _next_trading_day(disc_date, n=1)
                if target_24h <= today:
                    close_24h = _fetch_close_price(client, code, target_24h)
                    if close_24h is not None:
                        record["lifecycle_24h_close"] = close_24h
                        record["outcome_24h"] = _judge_outcome(disc_price, close_24h)
                        updated_24h += 1

            # +72h 추적 (3거래일 후)
            if record.get("lifecycle_72h_close") is None:
                target_72h = _next_trading_day(disc_date, n=3)
                if target_72h <= today:
                    close_72h = _fetch_close_price(client, code, target_72h)
                    if close_72h is not None:
                        record["lifecycle_72h_close"] = close_72h
                        record["outcome_72h"] = _judge_outcome(disc_price, close_72h)
                        updated_72h += 1

            if updated_24h > 0 or updated_72h > 0:
                record["lifecycle_updated_at"] = datetime.now().isoformat()
        except Exception as e:
            print(f"[lifecycle] 레코드 처리 실패 ({record.get('code', '?')}): {e}", file=sys.stderr)

    if dry_run:
        print(f"[dry-run] lifecycle +24h {updated_24h}건 / +72h {updated_72h}건 업데이트 가능", file=sys.stderr)
        return 0

    if updated_24h > 0 or updated_72h > 0:
        _LOG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[lifecycle] 업데이트 완료: +24h {updated_24h}건 / +72h {updated_72h}건", file=sys.stderr)

    # 통계 출력
    _print_statistics(data)
    return 0


def _print_statistics(data: list[dict]) -> None:
    """누적 통계 stderr 출력 — 시간대별 / 점수별 승률."""
    completed = [r for r in data if r.get("outcome_24h") in ("true_positive", "false_positive", "neutral")]
    if len(completed) < 5:
        print(f"[lifecycle] 통계 — 표본 {len(completed)}건 (5건 이상 누적 시 출력)", file=sys.stderr)
        return

    # 전체
    tp_24 = sum(1 for r in completed if r.get("outcome_24h") == "true_positive")
    fp_24 = sum(1 for r in completed if r.get("outcome_24h") == "false_positive")
    ne_24 = sum(1 for r in completed if r.get("outcome_24h") == "neutral")
    total = len(completed)

    print(f"\n[lifecycle 통계] 표본 {total}건 (+24h 기준)", file=sys.stderr)
    print(f"  true_positive : {tp_24:3d}건 ({tp_24/total*100:.1f}%)", file=sys.stderr)
    print(f"  false_positive: {fp_24:3d}건 ({fp_24/total*100:.1f}%)", file=sys.stderr)
    print(f"  neutral       : {ne_24:3d}건 ({ne_24/total*100:.1f}%)", file=sys.stderr)

    # 시간대별
    from collections import defaultdict
    by_hour = defaultdict(lambda: {"tp": 0, "fp": 0, "total": 0})
    for r in completed:
        time_str = r.get("disc_time", "")
        if ":" in time_str:
            try:
                h = int(time_str.split(":", 1)[0])
                by_hour[h]["total"] += 1
                if r.get("outcome_24h") == "true_positive":
                    by_hour[h]["tp"] += 1
                elif r.get("outcome_24h") == "false_positive":
                    by_hour[h]["fp"] += 1
            except ValueError:
                pass

    print("\n  시간대별 승률 (+24h):", file=sys.stderr)
    for h in sorted(by_hour.keys()):
        s = by_hour[h]
        win_rate = s["tp"] / s["total"] * 100 if s["total"] else 0
        print(f"    {h:2d}시: {s['total']:3d}건 → 승률 {win_rate:.1f}% (TP {s['tp']} / FP {s['fp']})", file=sys.stderr)

    # 점수별
    by_score = defaultdict(lambda: {"tp": 0, "fp": 0, "total": 0})
    for r in completed:
        sc = r.get("score", 0)
        by_score[sc]["total"] += 1
        if r.get("outcome_24h") == "true_positive":
            by_score[sc]["tp"] += 1
        elif r.get("outcome_24h") == "false_positive":
            by_score[sc]["fp"] += 1

    print("\n  점수별 승률 (+24h):", file=sys.stderr)
    for sc in sorted(by_score.keys(), reverse=True):
        s = by_score[sc]
        win_rate = s["tp"] / s["total"] * 100 if s["total"] else 0
        print(f"    {sc}점: {s['total']:3d}건 → 승률 {win_rate:.1f}% (TP {s['tp']} / FP {s['fp']})", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="발굴 종목 후속 추적 (C1)")
    parser.add_argument("--dry-run", action="store_true", help="실제 저장 없이 시뮬레이션")
    args = parser.parse_args()
    return update_lifecycle(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
```

---

## 4. launchd plist 신규: `com.aigeenya.stockreport.pattern_lifecycle.plist`

### 4.1 위치
`/Users/geenya/Library/LaunchAgents/com.aigeenya.stockreport.pattern_lifecycle.plist`

### 4.2 작성 (PlistBuddy 또는 직접)

기존 closing.plist 복제 후 시각/Label/인자만 변경:

```bash
cp /Users/geenya/Library/LaunchAgents/com.aigeenya.stockreport.closing.plist \
   /Users/geenya/Library/LaunchAgents/com.aigeenya.stockreport.pattern_lifecycle.plist

# Label 변경
/usr/libexec/PlistBuddy -c "Set :Label com.aigeenya.stockreport.pattern_lifecycle" \
   /Users/geenya/Library/LaunchAgents/com.aigeenya.stockreport.pattern_lifecycle.plist

# 시각 = 23:35 (closing 23:30 + 5분)
# closing 의 실제 시각 확인 — 본 프로젝트는 closing 이 20:30 인지 확인 필요
# 만약 20:30 이면 pattern_lifecycle 도 20:35 (5분 후) 권장
/usr/libexec/PlistBuddy -c "Set :StartCalendarInterval:0:Hour 20" \
   /Users/geenya/Library/LaunchAgents/com.aigeenya.stockreport.pattern_lifecycle.plist
/usr/libexec/PlistBuddy -c "Set :StartCalendarInterval:0:Minute 35" \
   /Users/geenya/Library/LaunchAgents/com.aigeenya.stockreport.pattern_lifecycle.plist

# ProgramArguments — closing_report.py 를 pattern_lifecycle.py 로 변경
# (인덱스는 closing.plist 의 ProgramArguments 배열 확인 후 결정)
/usr/libexec/PlistBuddy -c "Print :ProgramArguments" \
   /Users/geenya/Library/LaunchAgents/com.aigeenya.stockreport.pattern_lifecycle.plist
# 예시: ProgramArguments[1] 이 ".../morning_report/closing_report.py" 이면
/usr/libexec/PlistBuddy -c "Set :ProgramArguments:1 /Users/geenya/projects/AI_Projects/stockpilot/morning_report/pattern_lifecycle.py" \
   /Users/geenya/Library/LaunchAgents/com.aigeenya.stockreport.pattern_lifecycle.plist

# 로그 경로 변경
/usr/libexec/PlistBuddy -c "Set :StandardOutPath /Users/geenya/projects/AI_Projects/stockpilot/logs/pattern_lifecycle.log" \
   /Users/geenya/Library/LaunchAgents/com.aigeenya.stockreport.pattern_lifecycle.plist
/usr/libexec/PlistBuddy -c "Set :StandardErrorPath /Users/geenya/projects/AI_Projects/stockpilot/logs/pattern_lifecycle_error.log" \
   /Users/geenya/Library/LaunchAgents/com.aigeenya.stockreport.pattern_lifecycle.plist
```

### 4.3 등록

```bash
launchctl load -w /Users/geenya/Library/LaunchAgents/com.aigeenya.stockreport.pattern_lifecycle.plist
launchctl list | grep pattern_lifecycle
```

---

## 5. 검증 시나리오

### 5.1 단위 테스트

```bash
venv/bin/python3 -c "
import sys
sys.path.insert(0, 'morning_report')
from pattern_lifecycle import _judge_outcome, _previous_trading_day, _next_trading_day
from datetime import date

# outcome 판정
print(_judge_outcome(100, 105))   # +5% → 'true_positive'
print(_judge_outcome(100, 97))    # -3% → 'false_positive'
print(_judge_outcome(100, 100.5)) # +0.5% → 'neutral'
print(_judge_outcome(100, None))  # → 'pending'

# 거래일 계산 (2026-05-04 월요일)
print(_previous_trading_day(date(2026, 5, 4)))  # 5/1 금요일
print(_next_trading_day(date(2026, 5, 1)))      # 5/4 월요일
print(_next_trading_day(date(2026, 5, 1), n=3)) # 5/6 수요일
"
```

### 5.2 dry-run 실행

```bash
cd /Users/geenya/projects/AI_Projects/stockpilot
venv/bin/python3 morning_report/pattern_lifecycle.py --dry-run
# stderr 출력에 "+24h N건 / +72h M건 업데이트 가능" 확인
```

### 5.3 실제 실행 + 결과 검증

```bash
venv/bin/python3 morning_report/pattern_lifecycle.py
# discovery_log.json 의 lifecycle_24h_close 필드 채워졌는지 확인
venv/bin/python3 -c "
import json
data = json.load(open('data/discovery_log.json'))
with_lifecycle = [r for r in data if r.get('lifecycle_24h_close')]
print(f'lifecycle 추가된 레코드: {len(with_lifecycle)}/{len(data)}')
"
```

### 5.4 launchd 검증

```bash
launchctl list | grep pattern_lifecycle
# - 0 com.aigeenya.stockreport.pattern_lifecycle 출력 기대

# 다음 평일 20:35 자동 실행 확인 (또는 직접 trigger)
launchctl start com.aigeenya.stockreport.pattern_lifecycle
tail -f logs/pattern_lifecycle.log
```

---

## 6. 산출물 체크리스트

- [ ] `morning_report/pattern_lifecycle.py` 신규 작성 (~250줄)
- [ ] `/Users/geenya/Library/LaunchAgents/com.aigeenya.stockreport.pattern_lifecycle.plist` 신규
- [ ] `launchctl load -w` 성공
- [ ] `discovery_log.json` lifecycle_24h_close / outcome_24h 필드 추가됨
- [ ] py_compile 통과
- [ ] 단위 테스트 4건 통과 (_judge_outcome / _previous/_next_trading_day)
- [ ] dry-run 실행 통과 (실제 데이터로)
- [ ] 통계 출력 정상 (5건 이상 누적 시)

---

## 7. 보고 형식

```
status: Brief 13-C 완료
completion_reason:
- pattern_lifecycle.py 신규
- launchd plist 신규 (20:35 closing 5분 후)
- discovery_log.json 후속 필드 자동 추가
- 단위 테스트 4건 통과
- 첫 실제 실행 시 +24h N건 / +72h M건 업데이트 확인
files_changed:
- morning_report/pattern_lifecycle.py (신규)
- /Users/geenya/Library/LaunchAgents/com.aigeenya.stockreport.pattern_lifecycle.plist (신규)
- data/discovery_log.json (스키마 확장 — 신규 4개 필드)
warnings:
- 시간 — closing_report 가 23:30 인지 20:30 인지 확인 후 plist 시각 결정
  (HANDOFF.md 와 launchctl list 교차 확인 권고)
- KIS API rate limit — discovery_log 누적 100건 이상 시 한 번에 fetch 부담
  (현재 구조는 멱등성 — 재실행해도 안전)
next_recommended_action:
- 1주일 운영 후 통계 stderr 로그 확인
- C2 (closing_report 통계 대시보드) brief 작성 — 통계 시각화
```

---

*Brief 13-C: 발굴 후속 추적 자동화 (Pattern Integration §5 일부)*
*Phase 2 매매 모듈과 독립 — Phase 2 검증 무관하게 도입 가능*
