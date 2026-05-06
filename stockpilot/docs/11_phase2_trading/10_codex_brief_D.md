# Codex Brief D — 텔레그램 명령 + 주문 요청 파이프라인 (Phase 2)

> **날짜:** 2026-04-23 | **작성자:** Claude | **근거:** `09_brief_d_plan.md` (Stage 4 승인) + `05_technical_design.md` §3
> **의존:** Brief A (KIS 키 그룹 분리, `KISClient(mode="trading")`), Brief B (position_state / trading_state / pending_proposals / validator), Brief C (position_monitor 골격·5초 tick 루프)
> **산출물:** 신규 2개 + 수정 5개 파일 + 통합 테스트 1개
> **실행 전제:** `venv/bin/python3` (Python 3.14), macOS 키체인 기반 `inject_to_env()` 로드 완료, position_monitor 데몬 구동 중

---

## 0. 배경 & 범위

Brief A/B/C가 **인프라·상태·데몬 골격**을 완성했다면, Brief D는 **사용자 접점 + 주문 실행 파이프라인**을 완성한다.
발굴이 제안을 만들고 → 텔레그램이 형진님에게 질의하고 → 응답이 들어오면 실제 KIS 주문이 나가고 → 체결 결과가 position_state에 반영되는 루프 전체를 닫는다.

### Brief D 제외 범위

| 기능 | 이관처 |
|------|--------|
| 손절/익절/트레일링 exit 결정 엔진 (`_evaluate_exit`) | 별도 Brief (C2 또는 E) |
| 장마감 15:15 강제청산 | Brief E |
| position_monitor launchd plist 배포 | Brief E |
| closing_report 매매 섹션 추가 | Brief E |
| dry-run 통합 시나리오 테스트 | Brief F |

### 불변 원칙 (Brief B/C 계승)

1. **단일 라이터** — `position_state.json` / `trading_state.json` / `pending_proposals.json`은 `position_monitor`만 쓴다. orchestrator는 request JSONL(append-only)만 쓴다.
2. **초당 1건 throttle** — 텔레그램 전송 경로는 모두 `enqueue_text()`를 통과한다. 단, 기존 리포트 스크립트의 `send_text()`는 예외 (유지).
3. **DRY_RUN 가드** — `KIS_ALLOW_LIVE_ORDER` 미설정 시 `place_order` 절대 호출 불가 (Brief A Task 2에서 구현됨, 호출만).
4. **계좌번호 마스킹** — 로그에 계좌번호 평문 금지 (`***1234` 형식).

---

## 스키마 확장 (Brief B 파일 수정 필수)

Brief D에서 두 파일의 스키마를 확장한다. Codex는 Brief B 파일을 수정 후 기존 테스트를 모두 그린으로 유지해야 한다.

### 1. `morning_report/pending_proposals.py` — Proposal 필드 추가

Brief B의 `Proposal` 데이터클래스에 다음 필드를 추가한다:

```python
@dataclass
class Proposal:
    # ── 기존 필드 (Brief B) ────────────────────────────────────────────
    id: str
    code: str
    name: str
    round: int
    rank: int
    stage: str
    score: float
    tday_rltv: float
    chg: float
    price_ref: float
    status: str       # "pending" | "accepted" | "declined" | "exhausted" | "expired"
    count: int        # 재권유 발송 횟수
    created_at: str   # ISO 8601
    last_sent: str | None

    # ── Brief D 추가 필드 ─────────────────────────────────────────────
    qty_ref: int = 0                    # 권유 수량 (1차 분할 기준)
    top5: list[dict] = field(default_factory=list)  # 대안 TOP5 [{rank, code, name, score, price_ref}]
    kind: str = "BUY"                   # "BUY" | "FORCED_LIQUIDATION"
```

`field(default_factory=list)` 임포트: `from dataclasses import dataclass, field`

**직렬화 주의:** JSON 저장 시 `top5`는 `list[dict]` 그대로 저장. `qty_ref`는 `int`, `kind`는 `str`.
기존 테스트의 `Proposal(...)` 생성자 호출은 `qty_ref=0, top5=[], kind="BUY"` 기본값으로 자동 호환.

### 2. `morning_report/trading_state.py` — TradingState 필드 추가

Brief B의 `TradingState`에 다음 필드를 추가한다:

```python
@dataclass
class TradingState:
    # ── 기존 필드 (Brief B) ────────────────────────────────────────────
    # ...

    # ── Brief D 추가 필드 ─────────────────────────────────────────────
    liquidation_query_sent_at: str | None = None  # 강제청산 질의 전송 시각 (중복 방지)
```

`reset_daily()` 메서드에 다음 초기화 추가:
```python
self.liquidation_query_sent_at = None
```

**직렬화:** JSON 저장 시 `null` (None). `reset_daily()` 호출 시 `None`으로 초기화.

---

## Task D1 — `request_queue.py` 신설

### 책임

- JSONL 파일 3종(`discovery_result.jsonl`, `buy_request.jsonl`, `sell_request.jsonl`) + cursor 파일(`request_cursor.json`) 관리
- `append_line(queue_name, payload)`: dict → JSON 라인 append (원자적 쓰기)
- `read_new_lines(queue_name)`: cursor 이후 새 라인 목록 반환
- `reset_cursors()`: 자정 리셋 시 cursor 파일 초기화 (position_monitor 자정 리셋에서 호출)

### 파일: `morning_report/request_queue.py` (신규)

```python
"""request_queue.py — Phase 2 IPC JSONL 큐 유틸."""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parent.parent
_DATA_DIR = _ROOT / "data"
_CURSOR_FILE = _DATA_DIR / "request_cursor.json"

# 큐 이름 → 파일 경로
_QUEUE_FILES: dict[str, Path] = {
    "discovery": _DATA_DIR / "discovery_result.jsonl",
    "buy":       _DATA_DIR / "buy_request.jsonl",
    "sell":      _DATA_DIR / "sell_request.jsonl",
}

_lock = threading.Lock()  # append 원자성 보장 (프로세스 내 멀티스레드 대비)


# ── cursor ──────────────────────────────────────────────────────────────────

def _load_cursors() -> dict[str, int]:
    """cursor 파일 로드. 없으면 {queue: 0}."""
    try:
        raw = json.loads(_CURSOR_FILE.read_text(encoding="utf-8"))
        return {k: int(v) for k, v in raw.items()}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {k: 0 for k in _QUEUE_FILES}


def _save_cursors(cursors: dict[str, int]) -> None:
    tmp = _CURSOR_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cursors, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_CURSOR_FILE)


# ── 공개 API ─────────────────────────────────────────────────────────────────

def append_line(queue_name: str, payload: dict[str, Any]) -> None:
    """
    queue_name 큐에 payload를 JSON 라인으로 append.
    ts 필드가 없으면 자동 추가.
    """
    if queue_name not in _QUEUE_FILES:
        raise ValueError(f"알 수 없는 큐: {queue_name}. 허용: {list(_QUEUE_FILES)}")
    if "ts" not in payload:
        payload = {**payload, "ts": datetime.now().isoformat(timespec="seconds")}
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    path = _QUEUE_FILES[queue_name]
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(line)


def read_new_lines(queue_name: str) -> list[str]:
    """
    cursor 이후 새 라인을 읽고 cursor 전진.
    반환: 새 라인 목록 (JSON 문자열, 개행 제거됨).
    """
    if queue_name not in _QUEUE_FILES:
        raise ValueError(f"알 수 없는 큐: {queue_name}")
    path = _QUEUE_FILES[queue_name]
    if not path.exists():
        return []

    with _lock:
        cursors = _load_cursors()
        offset = cursors.get(queue_name, 0)

        with path.open("rb") as f:
            f.seek(offset)
            raw = f.read()
        new_offset = offset + len(raw)

        lines = [ln.decode("utf-8").rstrip("\n") for ln in raw.splitlines() if ln.strip()]
        cursors[queue_name] = new_offset
        _save_cursors(cursors)

    return lines


def reset_cursors() -> None:
    """자정 리셋 시 호출 — cursor 파일을 0으로 초기화 + JSONL 파일 아카이브."""
    today_str = datetime.now().strftime("%Y%m%d")
    with _lock:
        for name, path in _QUEUE_FILES.items():
            if path.exists() and path.stat().st_size > 0:
                archive = path.with_name(f"{path.stem}_{today_str}.jsonl")
                path.rename(archive)
        # 빈 cursor 저장
        _save_cursors({k: 0 for k in _QUEUE_FILES})
```

### 중요 설계 주석

1. **원자성**: `append_line`은 `with open("a")` 블록 내 단일 `write`로 원자성 확보. POSIX append는 커널 수준에서 원자적 (write < PIPE_BUF=4096).
2. **cursor 파일**: 바이트 오프셋 저장. 재시작 후에도 이미 처리한 라인 재처리 없음. `_save_cursors`는 tmp→rename 원자성.
3. **아카이브**: `reset_cursors()` 호출 시 당일 JSONL을 `_YYYYMMDD.jsonl`로 이름 바꿔 보존. 다음날 파일은 새로 시작.
4. **멀티프로세스**: orchestrator와 intraday_discovery는 **쓰기만**, position_monitor는 **읽기만**. 프로세스 간 경합은 OS append 원자성으로 해결. `_lock`은 동일 프로세스 내 스레드 경합 방지용.

### Acceptance

- [ ] `append_line("buy", {"action": "buy"})` 호출 시 `data/buy_request.jsonl`에 JSON 라인 1건 추가
- [ ] `read_new_lines("buy")` 호출 시 cursor 이후 새 라인만 반환 (이전 라인 제외)
- [ ] 두 번 연속 `read_new_lines("buy")` 호출 시 두 번째는 빈 목록 반환 (cursor 전진됨)
- [ ] `reset_cursors()` 호출 시 기존 JSONL을 `_YYYYMMDD.jsonl`로 아카이브 + cursor=0 초기화
- [ ] JSONL 파일 없는 경우 `read_new_lines` → 빈 목록 (예외 없음)
- [ ] 알 수 없는 queue_name에 `ValueError` 발생

---

## Task D2 — `telegram_sender.py` throttle 큐 추가

### 책임

- 기존 `send_text(text)` 동기 전송 함수는 **변경 없이 유지** (기존 리포트 스크립트 호환)
- 신규 `enqueue_text(text)` 추가: 내부 큐 → 백그라운드 스레드가 초당 1건씩 소비
- `start_throttle_worker()` 모듈 임포트 시 자동 1회 기동 (daemon thread)

### 파일: `morning_report/telegram_sender.py` (수정)

기존 코드 하단에 다음 블록을 추가한다 (기존 함수 수정 없음):

```python
# ── Phase 2 throttle 큐 ───────────────────────────────────────────────────
import queue as _queue_mod
import threading as _threading_mod

_throttle_q: _queue_mod.Queue[str] = _queue_mod.Queue()
_throttle_worker_started = False
_throttle_lock = _threading_mod.Lock()
_THROTTLE_INTERVAL = 1.0   # 초당 1건


def _throttle_worker() -> None:
    """백그라운드 스레드 — 큐에서 꺼내 초당 1건 전송."""
    import time
    while True:
        text = _throttle_q.get()
        try:
            send_text(text)
        except Exception as exc:
            print(f"[throttle] 전송 실패: {exc}", file=sys.stderr)
        finally:
            _throttle_q.task_done()
        time.sleep(_THROTTLE_INTERVAL)


def start_throttle_worker() -> None:
    """모듈 import 시 1회 자동 호출 (하단 참고). 중복 기동 방지."""
    global _throttle_worker_started
    with _throttle_lock:
        if _throttle_worker_started:
            return
        t = _threading_mod.Thread(target=_throttle_worker, daemon=True, name="tg-throttle")
        t.start()
        _throttle_worker_started = True


def enqueue_text(text: str) -> None:
    """
    Phase 2 전용 비동기 전송 — throttle 큐를 통해 초당 1건 제한.
    반환 즉시 (블로킹 없음). 실제 전송은 백그라운드 스레드.
    """
    _throttle_q.put(text)


# 모듈 로드 시 worker 자동 기동
start_throttle_worker()
```

### 중요 설계 주석

1. **기존 `send_text` 호환**: 모닝 리포트·클로징 리포트 등 기존 스크립트는 `send_text`를 직접 호출 → 변경 없음. `enqueue_text`는 Phase 2 내부 경로(position_monitor·orchestrator)에서만 사용.
2. **daemon=True**: 메인 프로세스 종료 시 worker 자동 종료. 큐에 미전송 항목이 남아있어도 강제 종료.
3. **큐 크기 무제한**: `Queue()` 기본값. 메모리 상한은 실운영에서 문제 없음 (하루 발송 건수 < 100건).
4. **worker thread 1개**: 초당 1건 직렬 처리. 순서 보장. 동시성 불필요.
5. **모듈 임포트 시 자동 기동**: `start_throttle_worker()`가 모듈 하단에서 즉시 호출됨. `position_monitor`·`orchestrator` 양쪽에서 `from telegram_sender import enqueue_text` 만 해도 worker가 뜬다.

### Acceptance

- [ ] `enqueue_text("test")` 호출 후 즉시 반환 (블로킹 없음)
- [ ] 연속 3건 `enqueue_text` 호출 시 약 3초 후 텔레그램에 3건 도달 (throttle 동작)
- [ ] `start_throttle_worker()` 2회 호출해도 worker thread 1개만 생성
- [ ] `send_text()` 기존 동작 변경 없음 (동기 전송)

---

## Task D3 — `proposal_notifier.py` 신설

### 책임

- 매수 제안 카드 포맷터 (`format_buy_proposal_card`)
- 체결 성공/실패 통지 포맷터 (`format_fill_notification`, `format_fill_failure`)
- 강제청산 질의 카드 포맷터 (`format_liquidation_query`)
- 모두 **순수 함수** — I/O 없음, 테스트 용이

### 파일: `morning_report/proposal_notifier.py` (신규)

```python
"""proposal_notifier.py — Phase 2 텔레그램 카드 포맷터 (순수 함수)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pending_proposals import Proposal


def format_buy_proposal_card(proposal: "Proposal") -> str:
    """
    매수 제안 카드 포맷.
    proposal.count에 따라 "(재권유 N회차)" 표시.
    """
    retry_note = f" (재권유 {proposal.count}회차)" if proposal.count > 0 else ""
    lines = [
        f"📢 매수 제안{retry_note} — {proposal.name} ({proposal.code})",
        f"Round {proposal.round} · 순위 {proposal.rank}위 · {proposal.stage}",
        f"점수 {proposal.score:.0f} / 체결강도 {proposal.tday_rltv:.0f} / 당일 {proposal.chg:+.1f}%",
        f"권유가 {proposal.price_ref:,.0f}원 · 수량 {proposal.qty_ref}주 (1차 50%)",
        "",
    ]

    if proposal.top5:
        lines.append("📋 TOP5 대안")
        for item in proposal.top5[:5]:
            marker = " ← 현재 제안" if item.get("rank", 0) == 1 else ""
            lines.append(
                f"  {item.get('rank', '?')}. {item.get('name', '')} ({item.get('code', '')}){marker}"
            )
        lines.append("")

    lines += [
        "응답:",
        "  /매수함         (현재 제안 승인)",
        "  /매수안함       (거절)",
        "  /종목변경 2~5   (TOP5 중 다른 종목 선택)",
        "",
        "⏱ 3분 내 응답 없으면 재권유 (최대 3회)",
    ]
    return "\n".join(lines)


def format_fill_notification(order_type: str, code: str, name: str, qty: int, fill_price: float) -> str:
    """체결 성공 통지 포맷."""
    emoji = "🟢" if order_type == "BUY" else "🔴"
    action = "매수" if order_type == "BUY" else "매도"
    return (
        f"{emoji} 체결 완료: {name}({code})\n"
        f"   {action} {qty}주 @ {fill_price:,.0f}원\n"
        f"   (DRY_RUN: 실제 주문 없음)" if _is_dry_run() else
        f"{emoji} 체결 완료: {name}({code})\n"
        f"   {action} {qty}주 @ {fill_price:,.0f}원"
    )


def format_fill_failure(order_type: str, code: str, name: str, qty: int, reason: str) -> str:
    """체결 실패 통지 포맷."""
    action = "매수" if order_type == "BUY" else "매도"
    return (
        f"❌ 주문 실패: {name}({code})\n"
        f"   {action} {qty}주\n"
        f"   사유: {reason[:200]}"
    )


def format_liquidation_query(
    holdings_list: list[dict],
    realized_pnl: int,
    daily_limit: int,
) -> str:
    """강제청산 질의 카드 포맷."""
    lines = ["🚨 일일 손실한도 도달 — 강제청산 여부를 3분 안에 결정해주세요"]
    lines.append("")
    for h in holdings_list:
        code = h.get("code", "")
        name = h.get("name", "")
        cur  = h.get("cur_price", 0)
        avg  = h.get("avg_price", 0)
        pnl_pct = ((cur - avg) / avg * 100) if avg else 0
        lines.append(
            f"  {name}({code}) 현재가 {cur:,.0f}원 · 평단 {avg:,.0f}원 · {pnl_pct:+.1f}%"
        )
    lines.append("")
    lines.append(f"일일 실현손실: {realized_pnl:+,}원  (한도: -{daily_limit:,}원)")
    lines.append("")
    lines.append("⏱ 3분 안에 응답해주세요 (무응답 = 청산 안 함)")
    for h in holdings_list:
        code = h.get("code", "")
        name = h.get("name", "")
        lines.append(f"  /청산함 {code}   ({name} 전량 시장가 청산)")
    lines.append("")
    lines.append("※ /청산안함 <코드>  또는 무응답 → 보유 유지 (신규 매수만 차단)")
    return "\n".join(lines)


def _is_dry_run() -> bool:
    import os
    return os.environ.get("DRY_RUN", "0") == "1"
```

**주의:** `format_fill_notification`의 `if _is_dry_run()` 삼항은 파이썬 삼항 문법으로 정리할 것:

```python
def format_fill_notification(order_type: str, code: str, name: str, qty: int, fill_price: float) -> str:
    emoji = "🟢" if order_type == "BUY" else "🔴"
    action = "매수" if order_type == "BUY" else "매도"
    dry_note = "\n   (DRY_RUN: 실제 주문 없음)" if _is_dry_run() else ""
    return (
        f"{emoji} 체결 완료: {name}({code})\n"
        f"   {action} {qty}주 @ {fill_price:,.0f}원{dry_note}"
    )
```

### 중요 설계 주석

1. **순수 함수**: proposal_notifier는 import만 하면 사용 가능. 상태 없음. 테스트에서 직접 assert 가능.
2. **top5 인덱스**: `item.get("rank", 0) == 1`로 현재 제안 마커 판별. top5 dict는 `{rank, code, name, score, price_ref}`.
3. **holdings_list 형식**: `[{"code": "005930", "name": "삼성전자", "cur_price": 83900, "avg_price": 87200}]`.

### Acceptance

- [ ] `format_buy_proposal_card(proposal)` — 필수 키워드 포함 확인: 종목명·코드·점수·권유가·수량·응답 옵션
- [ ] `proposal.count > 0` 시 "(재권유 N회차)" 표시
- [ ] `format_liquidation_query` — holdings_list 0건이어도 예외 없이 동작
- [ ] `format_fill_notification("BUY", "005930", "삼성전자", 50, 87300.0)` — "체결 완료" 포함

---

## Task D4 — `orchestrator.py` 5개 명령 추가

### 책임

- `/매수함` → 현재 active pending proposal의 매수 요청을 `buy_request.jsonl`에 발행
- `/매수안함` → decline 요청 발행
- `/종목변경 N` (N=2~5) → change 요청 발행
- `/청산함 <코드>` → `sell_request.jsonl`에 sell 요청 발행
- `/청산안함 <코드>` → decline_sell 요청 발행
- 모든 명령: chat_id 검증 → JSONL 발행 → "접수" 즉시 응답 (체결 결과는 별도 통지)

### 파일: `morning_report/orchestrator.py` (수정)

#### 1. import 추가 (파일 상단)

```python
from pending_proposals import PendingProposalsStore, Proposal
from request_queue import append_line as _rq_append
from telegram_sender import enqueue_text
```

#### 2. `handle_command` 함수 — cmd_map 확장

기존 `cmd_map` 딕셔너리 아래에 Phase 2 명령 라우팅을 추가한다:

```python
    # ── Phase 2 명령 (접두사 매칭) ───────────────────────────────────────────
    phase2_prefixes = {
        "/매수함":   _cmd_buy_approve,
        "/매수안함": _cmd_buy_decline,
        "/종목변경": _cmd_change_ticker,
        "/청산함":   _cmd_liquidate_approve,
        "/청산안함": _cmd_liquidate_decline,
    }
    for prefix, func in phase2_prefixes.items():
        if text == prefix or text.startswith(prefix + " "):
            try:
                arg = text[len(prefix):].strip()  # 인수 추출 (없으면 "")
                func(arg)
            except Exception as e:
                enqueue_text(f"❌ 명령 실행 중 오류\n{e}")
                print(f"[bot] Phase2 명령 오류: {e}", file=sys.stderr)
            return True
```

#### 3. Phase 2 명령 핸들러 추가 (함수)

```python
# ── Phase 2 명령 핸들러 ────────────────────────────────────────────────────

def _get_active_proposal() -> Proposal | None:
    """
    현재 active pending 제안 반환.
    조건: status="pending", last_sent is not None (최소 1회 이상 발송된 것).
    여러 건이면 last_sent 기준 최신 1건.
    """
    store = PendingProposalsStore()
    candidates = [
        p for p in store.proposals
        if p.status == "pending" and p.last_sent is not None
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.last_sent or "")


def _cmd_buy_approve(_arg: str) -> None:
    """/매수함 — 현재 제안 매수 승인."""
    proposal = _get_active_proposal()
    if proposal is None:
        enqueue_text("❓ 현재 대기 중인 매수 제안이 없습니다.")
        return

    _rq_append("buy", {
        "action":      "buy",
        "proposal_id": proposal.id,
        "code":        proposal.code,
        "name":        proposal.name,
        "qty":         proposal.qty_ref,
        "price_ref":   proposal.price_ref,
    })
    enqueue_text(
        f"✅ 접수: /매수함 — {proposal.name}({proposal.code}) {proposal.qty_ref}주\n"
        f"   주문 실행 중... (체결 결과는 잠시 후 통지)"
    )


def _cmd_buy_decline(_arg: str) -> None:
    """/매수안함 — 현재 제안 거절."""
    proposal = _get_active_proposal()
    if proposal is None:
        enqueue_text("❓ 현재 대기 중인 매수 제안이 없습니다.")
        return

    _rq_append("buy", {
        "action":      "decline",
        "proposal_id": proposal.id,
        "code":        proposal.code,
    })
    enqueue_text(f"📌 거절: {proposal.name}({proposal.code}) — 제안 취소됨")


def _cmd_change_ticker(arg: str) -> None:
    """/종목변경 N — TOP5 중 N번째로 변경 (N=2~5)."""
    try:
        pick = int(arg.strip())
    except (ValueError, AttributeError):
        enqueue_text("❓ 사용법: /종목변경 2   (2~5 중 선택)")
        return
    if not (2 <= pick <= 5):
        enqueue_text(f"❓ {pick}은 유효하지 않습니다. 2~5 사이로 입력하세요.")
        return

    proposal = _get_active_proposal()
    if proposal is None:
        enqueue_text("❓ 현재 대기 중인 매수 제안이 없습니다.")
        return
    if not proposal.top5 or pick - 1 >= len(proposal.top5):
        enqueue_text(f"❓ {pick}번 대안이 없습니다. TOP5 목록을 확인하세요.")
        return

    alt = proposal.top5[pick - 1]
    _rq_append("buy", {
        "action":      "change",
        "proposal_id": proposal.id,
        "code":        proposal.code,   # 원래 제안 코드 (decline 대상)
        "pick":        pick,
        "alt_code":    alt.get("code", ""),
        "alt_name":    alt.get("name", ""),
    })
    enqueue_text(
        f"🔄 종목 변경: {pick}번 {alt.get('name', '')}({alt.get('code', '')}) 으로 변경 요청\n"
        f"   새 제안을 잠시 후 전송합니다."
    )


def _cmd_liquidate_approve(arg: str) -> None:
    """/청산함 <코드> — 특정 종목 전량 시장가 청산."""
    code = arg.strip().upper()
    if not code:
        enqueue_text("❓ 사용법: /청산함 005930")
        return

    _rq_append("sell", {
        "action": "sell",
        "code":   code,
    })
    enqueue_text(f"✅ 접수: /청산함 {code} — 전량 시장가 청산 요청\n   체결 결과는 잠시 후 통지")


def _cmd_liquidate_decline(arg: str) -> None:
    """/청산안함 <코드> — 강제청산 거절, 보유 유지."""
    code = arg.strip().upper()
    if not code:
        enqueue_text("❓ 사용법: /청산안함 005930")
        return

    _rq_append("sell", {
        "action": "decline_sell",
        "code":   code,
    })
    enqueue_text(f"📌 /청산안함 {code} — 보유 유지 (신규 매수 차단 유지)")
```

#### 4. `/도움말` 업데이트

`cmd_help()` 메시지 끝에 다음 추가:

```python
        "\n"
        "📊 Phase 2 매매 명령\n"
        "  /매수함         — 매수 제안 승인\n"
        "  /매수안함       — 매수 제안 거절\n"
        "  /종목변경 2~5   — 대안 종목으로 변경\n"
        "  /청산함 <코드>  — 전량 시장가 청산\n"
        "  /청산안함 <코드>— 강제청산 거절 (보유 유지)\n"
```

### 중요 설계 주석

1. **`_get_active_proposal()` 정의**: `last_sent is not None` 조건으로 "최소 1회 발송된 pending"만 대상. 아직 전송 전인 제안은 제외 (사용자가 카드를 못 받았으므로).
2. **single pending 가정**: 운영상 동시 pending proposal은 1건이 대부분. 여러 건이면 `last_sent` 최신 기준 선택.
3. **즉시 응답 + 실제 실행 분리**: orchestrator는 "접수" 응답만. 실제 주문 실행은 position_monitor의 `_tick_process_requests()`가 담당.
4. **코드 대소문자**: `/청산함 005930` → `code.strip().upper()`. KIS 종목코드는 대문자 6자리.
5. **기존 `/발굴` 명령**: Phase 2 이후에도 동작 유지. orchestrator의 기존 cmd_map은 변경 없음.

### Acceptance

- [ ] `/매수함` 호출 시 `data/buy_request.jsonl`에 `{"action": "buy", ...}` 라인 추가 + "접수" 응답
- [ ] `/매수안함` 호출 시 `{"action": "decline", ...}` 라인 추가
- [ ] `/종목변경 2` 호출 시 `{"action": "change", "pick": 2, ...}` 라인 추가
- [ ] `/청산함 005930` 호출 시 `data/sell_request.jsonl`에 `{"action": "sell", "code": "005930"}` 추가
- [ ] `/청산안함 005930` 호출 시 `{"action": "decline_sell", "code": "005930"}` 추가
- [ ] 대기 제안 없을 때 `/매수함` 호출 시 "대기 중인 매수 제안이 없습니다" 응답
- [ ] `/종목변경 1` 또는 `/종목변경 6` 호출 시 유효하지 않다는 오류 응답
- [ ] 기존 `/잔고`, `/상태`, `/발굴`, `/도움말` 명령 정상 동작 (regression)

---

## Task D5 — `telegram_bot.py` 인수 파서 강화

### 책임

- 현재 `text.strip()` 만 사용 중 → `/종목변경 2` 등 공백 포함 명령 정상 처리 확인
- 멀티라인 메시지에서 첫 줄만 명령으로 인식
- 크게 수정할 필요 없음 — orchestrator의 `text.startswith(prefix + " ")` 패턴이 이미 처리함

### 파일: `morning_report/telegram_bot.py` (경미한 수정)

기존 `text = msg.get("text", "").strip()` 이후에 멀티라인 보호 추가:

```python
text = msg.get("text", "").strip()
# 멀티라인 메시지에서 첫 줄만 명령으로 사용
if "\n" in text:
    text = text.split("\n", 1)[0].strip()
```

### Acceptance

- [ ] `/종목변경 2` (공백 포함) → orchestrator에 그대로 전달
- [ ] 멀티라인 메시지 `/매수함\n추가설명` → `/매수함` 만 전달

---

## Task D6 — `position_monitor.py` 4개 tick 추가

### 책임

Brief C의 `tick()` 메서드에 4개 tick 함수를 통합한다:

1. `_tick_ingest_discovery_result(now)` — discovery_result.jsonl → pending_proposals enqueue
2. `_tick_notify_pending_proposals(now)` — pending 제안 카드 전송 (재권유 포함)
3. `_tick_process_requests(now)` — buy/sell_request.jsonl → validator → place_order → state 갱신
4. `_notify_loss_limit(now)` — block_new_orders False→True 전환 감지 → 강제청산 질의

### 파일: `morning_report/position_monitor.py` (수정)

#### import 추가

```python
try:
    from .request_queue import RequestQueue
    from .proposal_notifier import (
        format_buy_proposal_card,
        format_fill_notification,
        format_fill_failure,
        format_liquidation_query,
    )
    from .pending_proposals import Proposal
    from .telegram_sender import enqueue_text
    from .validator import Validator
except ImportError:
    from request_queue import RequestQueue
    from proposal_notifier import (
        format_buy_proposal_card,
        format_fill_notification,
        format_fill_failure,
        format_liquidation_query,
    )
    from pending_proposals import Proposal
    from telegram_sender import enqueue_text
    from validator import Validator
```

**주의:** `request_queue.py`의 `append_line`/`read_new_lines` 함수를 직접 임포트:

```python
try:
    from .request_queue import read_new_lines as _rq_read, reset_cursors as _rq_reset
except ImportError:
    from request_queue import read_new_lines as _rq_read, reset_cursors as _rq_reset
```

#### `PositionMonitor.__init__` 에 validator 추가

```python
    def __init__(self, *, ...):
        # 기존 필드들 ...
        self.validator = Validator()   # Brief B 구현
```

#### `tick()` 메서드 확장

```python
    def tick(self, now: datetime) -> None:
        """단일 폴링 사이클 (수정판 — Brief D 4개 tick 추가)."""
        self._check_midnight_reset(now)
        self._tick_expire_proposals(now)     # Brief C Task 4b

        # ── Brief D 추가 ──────────────────────────────────────────────────
        self._tick_ingest_discovery_result(now)
        self._tick_notify_pending_proposals(now)
        self._notify_loss_limit(now)         # block 전환 감지 후 질의

        if not is_market_open(now):
            return

        snapshot = self._fetch_kis_snapshot()
        self._diff_and_apply(snapshot, now)
        self._check_loss_limit(now)          # Brief C — block_new_orders 플립

        self._tick_process_requests(now)     # 주문 요청 처리 (장 중만)
```

#### `_check_midnight_reset` 에 `reset_cursors()` 추가

```python
    def _check_midnight_reset(self, now: datetime) -> None:
        # ... 기존 로직 ...
        # orderable_cash 조회 성공 후:
        self.trading.reset_daily(today=today, new_orderable_cash=orderable_cash)
        _rq_reset()          # ← 추가: JSONL 파일 아카이브 + cursor 초기화
        self.trading.persist()
        self.logger.info("자정 리셋 완료 + request 큐 아카이브")
```

#### `_tick_ingest_discovery_result(now)` 구현

```python
    def _tick_ingest_discovery_result(self, now: datetime) -> None:
        """discovery_result.jsonl 새 라인 → pending_proposals enqueue."""
        new_lines = _rq_read("discovery")
        for line in new_lines:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                self.logger.warning("discovery_result: JSON 파싱 실패: %.100s", line)
                continue

            code = str(data.get("code", "")).strip()
            if not code:
                continue

            ts = self.trading.data

            # ── 각종 차단 조건 ────────────────────────────────────────────
            if ts.block_new_orders:
                self.logger.info("ingest: block_new_orders=True → 스킵 (%s)", code)
                continue
            if self.trading.is_in_cooldown(code, now):
                self.logger.info("ingest: COOLDOWN → 스킵 (%s)", code)
                continue
            if ts.trial_mode and ts.buy_count_today >= ts.trial_max_buys:
                self.logger.info("ingest: 시범운영 매수한도 초과 → 스킵 (%s)", code)
                continue
            if ts.buy_count_today >= ts.max_trades_per_day:
                self.logger.info("ingest: 일일 매수한도 초과 → 스킵 (%s)", code)
                continue

            # ── qty_ref 계산 ──────────────────────────────────────────────
            price_ref = float(data.get("price_ref", 0))
            orderable = ts.daily_start_orderable_cash
            split_weight_1st = 0.5   # strategy_config에서 읽어야 하지만 기본값 사용
            qty_ref = 0
            if price_ref > 0 and orderable > 0:
                raw_qty = (orderable * split_weight_1st) / price_ref
                qty_ref = max(1, int(raw_qty))   # 최소 1주

            # ── Proposal 생성 ─────────────────────────────────────────────
            proposal = Proposal(
                id=f"P{now.strftime('%Y%m%d%H%M%S')}_{code}",
                code=code,
                name=str(data.get("name", "")).strip(),
                round=int(data.get("round", 0)),
                rank=int(data.get("rank", 1)),
                stage=str(data.get("stage", "")),
                score=float(data.get("score", 0)),
                tday_rltv=float(data.get("tday_rltv", 0)),
                chg=float(data.get("chg", 0)),
                price_ref=price_ref,
                qty_ref=qty_ref,
                top5=data.get("top5", []),
                kind="BUY",
                status="pending",
                count=0,
                created_at=now.isoformat(timespec="seconds"),
                last_sent=None,
            )
            self.proposals.enqueue(proposal)
            self.proposals.persist()
            self.logger.info("제안 enqueue: %s (%s) qty=%d", code, proposal.name, qty_ref)
```

#### `_tick_notify_pending_proposals(now)` 구현

```python
    def _tick_notify_pending_proposals(self, now: datetime) -> None:
        """pending 제안 카드 전송 또는 재권유 (최대 3회)."""
        changed = False
        for proposal in self.proposals.proposals:
            if proposal.status != "pending" or proposal.kind != "BUY":
                continue

            if proposal.count >= 3:
                # 재권유 한도 초과 → exhausted
                proposal.status = "exhausted"
                changed = True
                self.logger.info("제안 exhausted (3회 초과): %s", proposal.code)
                continue

            # 첫 전송 또는 3분 경과
            if proposal.last_sent is None:
                should_send = True
            else:
                try:
                    last_dt = datetime.fromisoformat(proposal.last_sent)
                    should_send = (now - last_dt).total_seconds() >= self.config.proposal_expire_seconds
                except ValueError:
                    should_send = True

            if not should_send:
                continue

            card = format_buy_proposal_card(proposal)
            enqueue_text(card)
            proposal.count += 1
            proposal.last_sent = now.isoformat(timespec="seconds")
            changed = True
            self.logger.info("제안 카드 전송: %s (count=%d)", proposal.code, proposal.count)

        if changed:
            self.proposals.persist()
```

#### `_notify_loss_limit(now)` 구현

```python
    def _notify_loss_limit(self, now: datetime) -> None:
        """block_new_orders True 전환 감지 → 강제청산 질의 카드 전송 (1회만)."""
        if not self.trading.data.block_new_orders:
            return
        # 이미 질의 보냈으면 스킵
        if self.trading.data.liquidation_query_sent_at is not None:
            return

        holdings_list = [
            {
                "code":      code,
                "name":      pos.name,
                "cur_price": pos.peak_price_since_entry or pos.avg_price,
                "avg_price": pos.avg_price,
            }
            for code, pos in self.positions.holdings.items()
        ]
        card = format_liquidation_query(
            holdings_list=holdings_list,
            realized_pnl=self.trading.data.realized_pnl,
            daily_limit=self.trading.data.daily_start_orderable_cash,
        )
        enqueue_text(card)
        self.trading.data.liquidation_query_sent_at = now.isoformat(timespec="seconds")
        self.trading.persist()
        self.logger.warning("강제청산 질의 전송: %d종목", len(holdings_list))
```

#### `_tick_process_requests(now)` 구현

```python
    def _tick_process_requests(self, now: datetime) -> None:
        """buy_request.jsonl + sell_request.jsonl 새 라인 처리."""
        # ── 매수 요청 ──────────────────────────────────────────────────────────
        for line in _rq_read("buy"):
            if not line.strip():
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                self.logger.warning("buy_request: JSON 파싱 실패: %.100s", line)
                continue

            action = req.get("action", "buy")
            proposal_id = req.get("proposal_id", "")

            if action == "decline":
                self._handle_buy_decline(proposal_id, now)

            elif action == "change":
                pick = int(req.get("pick", 2))
                self._handle_buy_change(proposal_id, pick, now)

            elif action == "buy":
                code     = str(req.get("code", "")).strip()
                qty      = int(req.get("qty", 0))
                price_ref = float(req.get("price_ref", 0))
                name     = str(req.get("name", code))
                self._handle_buy_execute(
                    code=code, qty=qty, price_ref=price_ref,
                    name=name, proposal_id=proposal_id, now=now
                )

        # ── 매도 요청 ──────────────────────────────────────────────────────────
        for line in _rq_read("sell"):
            if not line.strip():
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue

            action = req.get("action", "sell")
            code = str(req.get("code", "")).strip().upper()

            if action == "decline_sell":
                enqueue_text(f"📌 강제청산 거절 — {code} 보유 유지 (신규 매수 차단 유지)")
                self.logger.info("강제청산 거절: %s", code)

            elif action == "sell" and code:
                self._handle_sell_execute(code=code, now=now)

    # ── 내부 핸들러 ──────────────────────────────────────────────────────────────

    def _handle_buy_decline(self, proposal_id: str, now: datetime) -> None:
        if proposal_id:
            self.proposals.transition(proposal_id, "declined", at=now)
            self.proposals.persist()
        self.logger.info("제안 거절: %s", proposal_id)

    def _handle_buy_change(self, proposal_id: str, pick: int, now: datetime) -> None:
        proposal = self.proposals.get(proposal_id) if proposal_id else None
        if proposal is None:
            self.logger.warning("change: 제안 없음: %s", proposal_id)
            return
        if not proposal.top5 or pick - 1 >= len(proposal.top5):
            enqueue_text(f"❓ {pick}번 대안이 없습니다.")
            return

        alt = proposal.top5[pick - 1]
        self.proposals.transition(proposal_id, "declined", at=now)

        # 대안 종목 새 Proposal 생성
        new_p = Proposal(
            id=f"P{now.strftime('%Y%m%d%H%M%S')}_{alt['code']}",
            code=alt.get("code", ""),
            name=alt.get("name", ""),
            round=proposal.round,
            rank=pick,
            stage=proposal.stage,
            score=float(alt.get("score", 0)),
            tday_rltv=proposal.tday_rltv,
            chg=proposal.chg,
            price_ref=float(alt.get("price_ref", proposal.price_ref)),
            qty_ref=proposal.qty_ref,
            top5=proposal.top5,
            kind="BUY",
            status="pending",
            count=0,
            created_at=now.isoformat(timespec="seconds"),
            last_sent=None,
        )
        self.proposals.enqueue(new_p)
        self.proposals.persist()
        self.logger.info("종목 변경: %s → %s", proposal.code, new_p.code)

    def _handle_buy_execute(
        self, code: str, qty: int, price_ref: float, name: str, proposal_id: str, now: datetime
    ) -> None:
        if not code or qty <= 0:
            self.logger.warning("buy_execute: 잘못된 요청 code=%s qty=%d", code, qty)
            return

        valid, reason = self.validator.validate_order(
            code=code, qty=qty, order_type="BUY",
            trading_state=self.trading.data,
            position_state=self.positions,
        )
        if not valid:
            enqueue_text(f"❌ 주문 거절: {name}({code})\n   사유: {reason}")
            self.logger.warning("주문 거절 (%s): %s", code, reason)
            return

        self.trading.mark_in_flight(code, "BUY", now)
        try:
            result = self.kis.place_order(code=code, qty=qty, order_type="BUY", price=0)
            fill_price = float(result.get("avg_price") or price_ref)
            self.trading.clear_in_flight(code)
            if proposal_id:
                self.proposals.transition(proposal_id, "accepted", at=now)
                self.proposals.persist()
            enqueue_text(format_fill_notification("BUY", code, name, qty, fill_price))
            self.logger.info("매수 완료: %s %d주 @%.0f", code, qty, fill_price)
        except Exception as exc:
            self.trading.clear_in_flight(code)
            enqueue_text(format_fill_failure("BUY", code, name, qty, str(exc)))
            self.logger.error("매수 실패: %s — %s", code, exc)

    def _handle_sell_execute(self, code: str, now: datetime) -> None:
        local = self.positions.get(code)
        if local is None:
            enqueue_text(f"⚠️ 보유 없음: {code}")
            self.logger.warning("sell_execute: 보유 없음 %s", code)
            return

        qty = local.qty
        self.trading.mark_in_flight(code, "SELL", now)
        try:
            result = self.kis.place_order(code=code, qty=qty, order_type="SELL", price=0)
            fill_price = float(result.get("avg_price") or local.avg_price)
            self.trading.clear_in_flight(code)
            enqueue_text(format_fill_notification("SELL", code, local.name, qty, fill_price))
            self.logger.info("매도 완료: %s %d주 @%.0f", code, qty, fill_price)
        except Exception as exc:
            self.trading.clear_in_flight(code)
            enqueue_text(format_fill_failure("SELL", code, local.name, qty, str(exc)))
            self.logger.error("매도 실패: %s — %s", code, exc)
```

### 중요 설계 주석

1. **`_tick_process_requests`는 장중만**: `tick()` 내 위치를 `if not is_market_open(now): return` 이후에 배치. 장외 명령은 처리 안 함. (`/청산함`은 장외에서도 허용해야 하는가? 현재 설계는 장중만 — 09_brief_d_plan.md §1 "KRX 정규장 09:00~15:30" 준수.)
2. **낙관적 주문 vs. diff 확인**: `place_order` 성공 시 체결 통지를 즉시 보내지만, 실제 position_state 업데이트는 다음 tick의 `_diff_and_apply`에서 KIS 잔고 확인 후 적용. 이중 확인 구조로 누락 방지.
3. **qty_ref 계산**: `daily_start_orderable_cash × 0.5 / price_ref`. strategy_config에서 split_weight를 읽는 것이 이상적이지만, 초기 구현에서는 0.5 하드코딩. Brief F 이후 config화 검토.
4. **`_notify_loss_limit` 중복 방지**: `liquidation_query_sent_at` 필드로 재시작 후에도 중복 발송 방지. 자정 리셋 시 None으로 초기화됨.
5. **Brief C 기존 테스트 유지**: 4개 tick 추가 후 `test_position_monitor.py` 14건 모두 PASS 유지. 기존 `tick()` 호출 구조 변경 없음.

### Acceptance

- [ ] `_tick_ingest_discovery_result` — discovery_result.jsonl 새 라인 감지 → Proposal enqueue + persist
- [ ] block_new_orders=True 상태에서 ingest 스킵 (Proposal enqueue 없음)
- [ ] `_tick_notify_pending_proposals` — pending 제안 3분 경과 시 카드 재전송 + count 증가
- [ ] count=3인 pending → exhausted 전환
- [ ] `_notify_loss_limit` — block_new_orders False→True 전환 후 1회만 질의 전송
- [ ] `_handle_buy_execute` — validate_order 실패 시 주문 없이 실패 통지
- [ ] `_handle_buy_execute` — place_order 성공 시 체결 통지 + proposal accepted 전환
- [ ] `_handle_sell_execute` — 보유 없는 코드 요청 시 경고 메시지
- [ ] Brief C 기존 14건 테스트 모두 PASS (regression)

---

## Task D7 — `intraday_discovery.py` discovery_result enqueue

### 책임

- round 2 / 4 / 6 / 8 종료 직후 1위 종목을 `discovery_result.jsonl`에 append
- round가 짝수(교집합 분석 완료)일 때만 실행
- dry-run 시 스킵 (기존 dry-run 가드 패턴 동일)

### 파일: `morning_report/intraday_discovery.py` (수정)

#### import 추가 (상단)

```python
from request_queue import append_line as _rq_append_discovery
```

#### round2, round4, round6, round8 함수 내에 1위 종목 enqueue 추가

각 짝수 round 함수에서 최종 결과(`scored_list` 또는 유사 변수)를 구성한 직후, 텔레그램 전송 직전에 다음 블록 추가:

```python
    # ── discovery_result.jsonl enqueue (Phase 2) ──────────────────────────
    if not dry_run and scored_list:
        top1 = scored_list[0]
        top5_payload = [
            {
                "rank":      i + 1,
                "code":      item.get("code", ""),
                "name":      item.get("name", ""),
                "score":     item.get("score", 0),
                "price_ref": item.get("cur_price", 0),
            }
            for i, item in enumerate(scored_list[:5])
        ]
        _rq_append_discovery("discovery", {
            "round":     round_num,       # 2, 4, 6, 8 중 하나
            "rank":      1,
            "code":      top1.get("code", ""),
            "name":      top1.get("name", ""),
            "score":     top1.get("score", 0),
            "tday_rltv": top1.get("tday_rltv", 0),
            "chg":       top1.get("chg", 0),
            "price_ref": top1.get("cur_price", 0),
            "stage":     f"Round{round_num}교집합",
            "top5":      top5_payload,
        })
```

**변수명 참고:** 기존 코드의 실제 변수명(`scored_list`, `cur_price` 등)에 맞춰 수정할 것. 핵심 필드:
- `code`: 종목코드 6자리
- `name`: 종목명
- `score`: 발굴 점수
- `tday_rltv`: 체결강도 (100 이상이면 매수 우세)
- `chg`: 당일 등락률 (%)
- `price_ref`: 현재가 (권유가 기준)
- `top5`: 상위 5종목 (rank, code, name, score, price_ref)

### 중요 설계 주석

1. **dry-run 가드**: `if not dry_run and scored_list:` — dry-run 실행 시 enqueue 스킵 (v2.7.3 패치 패턴 계승).
2. **round_num 변수**: 각 round 함수에서 `round_num` 상수를 사용하거나, 함수명으로 추출. 기존 코드 구조에 맞게.
3. **scored_list 없을 때**: `if scored_list:` 조건으로 0건이면 스킵.
4. **enqueue 실패 허용**: `_rq_append_discovery` 실패는 예외 catch + 로그만. 텔레그램 전송은 정상 진행.

```python
    try:
        _rq_append_discovery("discovery", {...})
    except Exception as exc:
        import sys
        print(f"[discovery] request_queue append 실패: {exc}", file=sys.stderr)
```

### Acceptance

- [ ] round 2 실행 후 `data/discovery_result.jsonl`에 1위 종목 라인 추가
- [ ] dry-run 실행 시 JSONL 파일 변경 없음
- [ ] scored_list 0건일 때 enqueue 스킵 (예외 없음)
- [ ] enqueue 실패해도 텔레그램 전송 정상 진행

---

## Task D8 — 통합 테스트 `tests/test_request_pipeline.py`

### 책임

- request_queue → orchestrator → position_monitor `_tick_process_requests` 파이프라인 통합 테스트
- KISClient mock, tmp_path 격리, telegram_sender.enqueue_text mock

### 파일: `tests/test_request_pipeline.py` (신규)

```python
"""test_request_pipeline.py — Brief C+D 통합 파이프라인 테스트."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from morning_report.pending_proposals import PendingProposalsStore, Proposal
from morning_report.position_monitor import MonitorConfig, PositionMonitor
from morning_report.position_state import PositionStateStore
from morning_report.request_queue import append_line, read_new_lines, reset_cursors
from morning_report.trading_state import TradingStateStore

_MARKET_HOUR = datetime(2026, 4, 23, 10, 0)


def _build_monitor(tmp_path: Path, kis_stub: MagicMock) -> PositionMonitor:
    """테스트용 monitor — 파일 경로 tmp_path 격리."""
    import morning_report.request_queue as rq_mod
    # request_queue의 경로를 tmp_path로 override
    rq_mod._DATA_DIR = tmp_path
    rq_mod._CURSOR_FILE = tmp_path / "request_cursor.json"
    rq_mod._QUEUE_FILES = {
        "discovery": tmp_path / "discovery_result.jsonl",
        "buy":       tmp_path / "buy_request.jsonl",
        "sell":      tmp_path / "sell_request.jsonl",
    }

    position_store = PositionStateStore(path=tmp_path / "position_state.json")
    trading_store = TradingStateStore(path=tmp_path / "trading_state.json")
    proposals_store = PendingProposalsStore(path=tmp_path / "pending_proposals.json")
    config = MonitorConfig(proposal_expire_seconds=180)
    return PositionMonitor(
        kis_client=kis_stub,
        position_store=position_store,
        trading_store=trading_store,
        proposals_store=proposals_store,
        config=config,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 1. request_queue — append + read 라운드트립
# ─────────────────────────────────────────────────────────────────────────────
def test_request_queue_roundtrip(tmp_path, monkeypatch):
    import morning_report.request_queue as rq
    monkeypatch.setattr(rq, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(rq, "_CURSOR_FILE", tmp_path / "request_cursor.json")
    monkeypatch.setattr(rq, "_QUEUE_FILES", {"buy": tmp_path / "buy.jsonl"})

    append_line("buy", {"action": "buy", "code": "005930"})
    append_line("buy", {"action": "decline", "code": "066570"})

    lines = read_new_lines("buy")
    assert len(lines) == 2
    assert json.loads(lines[0])["action"] == "buy"
    assert json.loads(lines[1])["action"] == "decline"

    # 두 번째 read → 빈 목록
    assert read_new_lines("buy") == []


# ─────────────────────────────────────────────────────────────────────────────
# Test 2. ingest — discovery_result.jsonl → pending_proposals enqueue
# ─────────────────────────────────────────────────────────────────────────────
def test_ingest_discovery_result_creates_proposal(tmp_path):
    kis = MagicMock()
    monitor = _build_monitor(tmp_path, kis)
    monitor.trading.data.daily_start_orderable_cash = 1_000_000
    monitor.trading.data.block_new_orders = False

    # discovery_result.jsonl에 직접 라인 추가 (intraday_discovery 역할)
    append_line("discovery", {
        "round": 2, "rank": 1,
        "code": "005930", "name": "삼성전자",
        "score": 85.0, "tday_rltv": 125.0, "chg": 3.2,
        "price_ref": 87200.0,
        "stage": "Round2교집합",
        "top5": [{"rank": 1, "code": "005930", "name": "삼성전자", "score": 85.0, "price_ref": 87200}],
    })

    monitor._tick_ingest_discovery_result(_MARKET_HOUR)

    proposals = monitor.proposals.proposals
    assert len(proposals) == 1
    p = proposals[0]
    assert p.code == "005930"
    assert p.status == "pending"
    assert p.qty_ref > 0   # 1_000_000 * 0.5 / 87200 ≈ 5
    assert len(p.top5) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Test 3. ingest — block_new_orders=True 시 enqueue 스킵
# ─────────────────────────────────────────────────────────────────────────────
def test_ingest_blocked_when_block_new_orders(tmp_path):
    kis = MagicMock()
    monitor = _build_monitor(tmp_path, kis)
    monitor.trading.data.block_new_orders = True

    append_line("discovery", {"round": 2, "code": "005930", "name": "삼성전자",
                               "score": 85.0, "tday_rltv": 125.0, "chg": 3.2,
                               "price_ref": 87200.0, "stage": "S", "top5": []})
    monitor._tick_ingest_discovery_result(_MARKET_HOUR)
    assert monitor.proposals.proposals == []


# ─────────────────────────────────────────────────────────────────────────────
# Test 4. notify — 첫 전송 (last_sent=None → count=1)
# ─────────────────────────────────────────────────────────────────────────────
def test_notify_sends_card_on_first_pending(tmp_path):
    kis = MagicMock()
    monitor = _build_monitor(tmp_path, kis)
    proposal = Proposal(
        id="P1", code="005930", name="삼성전자", round=2, rank=1, stage="S",
        score=85.0, tday_rltv=125.0, chg=3.2, price_ref=87200.0, qty_ref=5,
        top5=[], status="pending", count=0,
        created_at=_MARKET_HOUR.isoformat(), last_sent=None,
    )
    monitor.proposals.enqueue(proposal)

    with patch("morning_report.position_monitor.enqueue_text") as mock_enqueue:
        monitor._tick_notify_pending_proposals(_MARKET_HOUR)

    mock_enqueue.assert_called_once()
    p = monitor.proposals.get("P1")
    assert p.count == 1
    assert p.last_sent is not None


# ─────────────────────────────────────────────────────────────────────────────
# Test 5. notify — count=3 → exhausted 전환
# ─────────────────────────────────────────────────────────────────────────────
def test_notify_exhausted_after_3_retries(tmp_path):
    kis = MagicMock()
    monitor = _build_monitor(tmp_path, kis)
    old_sent = (_MARKET_HOUR - timedelta(minutes=5)).isoformat(timespec="seconds")
    proposal = Proposal(
        id="P2", code="005930", name="삼성전자", round=2, rank=1, stage="S",
        score=85.0, tday_rltv=125.0, chg=3.2, price_ref=87200.0, qty_ref=5,
        top5=[], status="pending", count=3,
        created_at=old_sent, last_sent=old_sent,
    )
    monitor.proposals.enqueue(proposal)

    with patch("morning_report.position_monitor.enqueue_text"):
        monitor._tick_notify_pending_proposals(_MARKET_HOUR)

    p = monitor.proposals.get("P2")
    assert p.status == "exhausted"


# ─────────────────────────────────────────────────────────────────────────────
# Test 6. process_requests — /매수함 → validate_order 실패 → 주문 없음
# ─────────────────────────────────────────────────────────────────────────────
def test_process_buy_rejected_by_validator(tmp_path):
    kis = MagicMock()
    monitor = _build_monitor(tmp_path, kis)
    monitor.trading.data.block_new_orders = True   # 강제 차단

    append_line("buy", {"action": "buy", "proposal_id": "P1",
                         "code": "005930", "name": "삼성전자", "qty": 5, "price_ref": 87200})

    with patch("morning_report.position_monitor.enqueue_text") as mock_enqueue:
        monitor._tick_process_requests(_MARKET_HOUR)

    kis.place_order.assert_not_called()
    # 실패 통지 발송됨
    mock_enqueue.assert_called_once()
    assert "거절" in mock_enqueue.call_args[0][0]


# ─────────────────────────────────────────────────────────────────────────────
# Test 7. process_requests — /매수함 → place_order 성공 → 체결 통지 + accepted
# ─────────────────────────────────────────────────────────────────────────────
def test_process_buy_success(tmp_path):
    kis = MagicMock()
    kis.place_order.return_value = {"avg_price": 87300.0}
    monitor = _build_monitor(tmp_path, kis)
    monitor.trading.data.block_new_orders = False
    monitor.trading.data.buy_count_today = 0
    monitor.trading.data.daily_start_orderable_cash = 1_000_000

    proposal = Proposal(
        id="P3", code="005930", name="삼성전자", round=2, rank=1, stage="S",
        score=85.0, tday_rltv=125.0, chg=3.2, price_ref=87200.0, qty_ref=5,
        top5=[], status="pending", count=1,
        created_at=_MARKET_HOUR.isoformat(),
        last_sent=_MARKET_HOUR.isoformat(),
    )
    monitor.proposals.enqueue(proposal)

    append_line("buy", {"action": "buy", "proposal_id": "P3",
                         "code": "005930", "name": "삼성전자", "qty": 5, "price_ref": 87200})

    with patch("morning_report.position_monitor.enqueue_text") as mock_enqueue:
        monitor._tick_process_requests(_MARKET_HOUR)

    kis.place_order.assert_called_once_with(code="005930", qty=5, order_type="BUY", price=0)
    p = monitor.proposals.get("P3")
    assert p.status == "accepted"
    assert "체결 완료" in mock_enqueue.call_args[0][0]


# ─────────────────────────────────────────────────────────────────────────────
# Test 8. process_requests — /매수안함 → proposal declined
# ─────────────────────────────────────────────────────────────────────────────
def test_process_buy_decline(tmp_path):
    kis = MagicMock()
    monitor = _build_monitor(tmp_path, kis)
    proposal = Proposal(
        id="P4", code="005930", name="삼성전자", round=2, rank=1, stage="S",
        score=85.0, tday_rltv=125.0, chg=3.2, price_ref=87200.0, qty_ref=5,
        top5=[], status="pending", count=1,
        created_at=_MARKET_HOUR.isoformat(),
        last_sent=_MARKET_HOUR.isoformat(),
    )
    monitor.proposals.enqueue(proposal)

    append_line("buy", {"action": "decline", "proposal_id": "P4", "code": "005930"})
    monitor._tick_process_requests(_MARKET_HOUR)

    p = monitor.proposals.get("P4")
    assert p.status == "declined"
    kis.place_order.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Test 9. process_requests — /종목변경 2 → 새 proposal 생성
# ─────────────────────────────────────────────────────────────────────────────
def test_process_change_ticker_creates_new_proposal(tmp_path):
    kis = MagicMock()
    monitor = _build_monitor(tmp_path, kis)
    top5 = [
        {"rank": 1, "code": "005930", "name": "삼성전자", "score": 85, "price_ref": 87200},
        {"rank": 2, "code": "066570", "name": "LG전자", "score": 78, "price_ref": 72000},
    ]
    proposal = Proposal(
        id="P5", code="005930", name="삼성전자", round=2, rank=1, stage="S",
        score=85.0, tday_rltv=125.0, chg=3.2, price_ref=87200.0, qty_ref=5,
        top5=top5, status="pending", count=1,
        created_at=_MARKET_HOUR.isoformat(),
        last_sent=_MARKET_HOUR.isoformat(),
    )
    monitor.proposals.enqueue(proposal)

    append_line("buy", {"action": "change", "proposal_id": "P5",
                         "code": "005930", "pick": 2, "alt_code": "066570", "alt_name": "LG전자"})
    monitor._tick_process_requests(_MARKET_HOUR)

    p5 = monitor.proposals.get("P5")
    assert p5.status == "declined"

    # 새 proposal 생성됨 (LG전자)
    new_p = next(
        (p for p in monitor.proposals.proposals if p.code == "066570"),
        None
    )
    assert new_p is not None
    assert new_p.status == "pending"
    assert new_p.count == 0


# ─────────────────────────────────────────────────────────────────────────────
# Test 10. process_requests — /청산함 → place_order SELL
# ─────────────────────────────────────────────────────────────────────────────
def test_process_sell_executes_market_order(tmp_path):
    kis = MagicMock()
    kis.place_order.return_value = {"avg_price": 83900.0}
    monitor = _build_monitor(tmp_path, kis)
    monitor.positions.apply_buy(
        "005930", "삼성전자", qty=5, price=87200.0, stage=1, at=_MARKET_HOUR
    )

    append_line("sell", {"action": "sell", "code": "005930"})

    with patch("morning_report.position_monitor.enqueue_text") as mock_enqueue:
        monitor._tick_process_requests(_MARKET_HOUR)

    kis.place_order.assert_called_once_with(code="005930", qty=5, order_type="SELL", price=0)
    assert "체결 완료" in mock_enqueue.call_args[0][0]


# ─────────────────────────────────────────────────────────────────────────────
# Test 11. process_requests — /청산함 보유 없음 → 경고 통지
# ─────────────────────────────────────────────────────────────────────────────
def test_process_sell_no_position_sends_warning(tmp_path):
    kis = MagicMock()
    monitor = _build_monitor(tmp_path, kis)

    append_line("sell", {"action": "sell", "code": "999999"})

    with patch("morning_report.position_monitor.enqueue_text") as mock_enqueue:
        monitor._tick_process_requests(_MARKET_HOUR)

    kis.place_order.assert_not_called()
    assert "보유 없음" in mock_enqueue.call_args[0][0]


# ─────────────────────────────────────────────────────────────────────────────
# Test 12. notify_loss_limit — block_new_orders True 전환 시 1회 질의
# ─────────────────────────────────────────────────────────────────────────────
def test_notify_loss_limit_sends_query_once(tmp_path):
    kis = MagicMock()
    monitor = _build_monitor(tmp_path, kis)
    monitor.trading.data.block_new_orders = True
    monitor.trading.data.liquidation_query_sent_at = None
    monitor.trading.data.realized_pnl = -500_000
    monitor.trading.data.daily_start_orderable_cash = 500_000

    with patch("morning_report.position_monitor.enqueue_text") as mock_enqueue:
        monitor._notify_loss_limit(_MARKET_HOUR)
        monitor._notify_loss_limit(_MARKET_HOUR)  # 두 번 호출

    # 1회만 전송됨
    assert mock_enqueue.call_count == 1
    assert "강제청산" in mock_enqueue.call_args[0][0]
    assert monitor.trading.data.liquidation_query_sent_at is not None


# ─────────────────────────────────────────────────────────────────────────────
# Test 13. reset_cursors — 아카이브 생성 + cursor 초기화
# ─────────────────────────────────────────────────────────────────────────────
def test_reset_cursors_archives_and_resets(tmp_path, monkeypatch):
    import morning_report.request_queue as rq
    monkeypatch.setattr(rq, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(rq, "_CURSOR_FILE", tmp_path / "request_cursor.json")
    monkeypatch.setattr(rq, "_QUEUE_FILES", {
        "buy": tmp_path / "buy_request.jsonl",
    })

    append_line("buy", {"action": "buy"})
    read_new_lines("buy")  # cursor 전진

    reset_cursors()

    # 아카이브 파일 생성됨
    archives = list(tmp_path.glob("buy_request_*.jsonl"))
    assert len(archives) == 1

    # 새 라인 append 후 read → 새 offset=0부터
    append_line("buy", {"action": "new"})
    lines = read_new_lines("buy")
    assert len(lines) == 1
    assert json.loads(lines[0])["action"] == "new"
```

### Acceptance (테스트 건수)

- [ ] 최소 13건 이상 통과 (Test 1 ~ Test 13)
- [ ] KIS API mock으로 외부 호출 0건
- [ ] `tmp_path` 기반 격리 (실제 `data/*.json` / `data/*.jsonl` 미영향)
- [ ] Brief C 기존 14건 테스트 regression PASS
- [ ] 테스트 실행: `venv/bin/python3 -m pytest tests/test_request_pipeline.py -v` 모두 PASS

---

## 구현 순서 권장

1. **스키마 확장 (Proposal + TradingState)** → 기존 Brief B 테스트 모두 PASS 확인
2. **Task D1 (request_queue)** → 단위 테스트 2~3건 먼저
3. **Task D2 (telegram_sender throttle)** → `enqueue_text("test")` 동작 확인
4. **Task D3 (proposal_notifier)** → 순수 함수 pytest 3~4건
5. **Task D7 (intraday_discovery enqueue)** → dry-run 시 JSONL 변경 없는지 확인
6. **Task D4 (orchestrator 5개 명령)** → `python3 -m py_compile` 통과
7. **Task D5 (telegram_bot 파서)** → 멀티라인 메시지 확인
8. **Task D6 (position_monitor 4개 tick)** → Brief C 기존 테스트 모두 PASS 유지 확인
9. **Task D8 (통합 테스트)** → 전체 13건 PASS

---

## 통합 검증 체크리스트 (Codex 구현 완료 후 Claude가 실행)

```bash
cd /Users/geenya/projects/AI_Projects/stockpilot

# 1. 문법 검사
venv/bin/python3 -m py_compile morning_report/request_queue.py
venv/bin/python3 -m py_compile morning_report/proposal_notifier.py
venv/bin/python3 -m py_compile morning_report/telegram_sender.py
venv/bin/python3 -m py_compile morning_report/orchestrator.py
venv/bin/python3 -m py_compile morning_report/telegram_bot.py
venv/bin/python3 -m py_compile morning_report/position_monitor.py
venv/bin/python3 -m py_compile morning_report/intraday_discovery.py

# 2. 전체 테스트 (Brief B+C+D regression)
venv/bin/python3 -m pytest tests/ -v

# 3. position_monitor dry-run (1 tick)
DRY_RUN=1 KIS_ALLOW_LIVE_ORDER=0 \
    venv/bin/python3 morning_report/position_monitor.py --once

# 4. intraday_discovery dry-run (enqueue 스킵 확인)
venv/bin/python3 morning_report/intraday_discovery.py --round 2 --dry-run
ls data/discovery_result.jsonl 2>/dev/null && echo "WARN: dry-run인데 파일 생성됨" || echo "OK: 파일 없음"

# 5. 로그 확인
tail -20 logs/trading.log
```

### 예상 로그 (position_monitor --once)

```
2026-04-23 10:00:00 INFO position_monitor 기동
2026-04-23 10:00:00 INFO 재시작 복구 시작
2026-04-23 10:00:01 INFO 복구: KIS와 로컬 일치. position_state 유지
2026-04-23 10:00:01 INFO 재시작 복구 완료
```

---

## 경계 체크 (Brief D 범위 외 기능 금지)

### Brief D에서 **구현하지 말 것**

- ❌ 손절/익절/트레일링 stop 자동 결정 (`_evaluate_exit`)
- ❌ 장마감 15:15 강제청산 (Brief E)
- ❌ closing_report 매매 섹션 추가 (Brief E)
- ❌ launchd plist 배포 (Brief E)
- ❌ dry-run 통합 시나리오 (Brief F)

### Brief D에서 **반드시 구현할 것**

- ✅ `request_queue.py` (append/read/reset)
- ✅ `telegram_sender.py` throttle 큐 (`enqueue_text`, `start_throttle_worker`)
- ✅ `proposal_notifier.py` 카드 포맷터 (순수 함수)
- ✅ `orchestrator.py` 5개 Phase 2 명령 라우팅
- ✅ `telegram_bot.py` 멀티라인 파서 보호
- ✅ `position_monitor.py` 4개 tick 추가 (ingest / notify / process / notify_loss_limit)
- ✅ `intraday_discovery.py` round 2/4/6/8 enqueue (dry-run 가드 포함)
- ✅ `pending_proposals.py` Proposal 스키마 확장 (qty_ref, top5, kind)
- ✅ `trading_state.py` TradingState 스키마 확장 (liquidation_query_sent_at)
- ✅ 13+건 통합 테스트

---

## 완료 보고 포맷 (Codex → Claude)

```
=== Brief D 구현 완료 ===
신규 파일:
  - morning_report/request_queue.py (XXX줄)
  - morning_report/proposal_notifier.py (XXX줄)
  - tests/test_request_pipeline.py (YY테스트)

수정 파일:
  - morning_report/pending_proposals.py (+qty_ref/top5/kind 필드)
  - morning_report/trading_state.py (+liquidation_query_sent_at)
  - morning_report/telegram_sender.py (+enqueue_text/throttle worker)
  - morning_report/orchestrator.py (+5개 Phase 2 명령)
  - morning_report/telegram_bot.py (파서 경미한 수정)
  - morning_report/position_monitor.py (+4개 tick)
  - morning_report/intraday_discovery.py (+round 2/4/6/8 enqueue)

테스트 결과:
  tests/test_request_pipeline.py: N/N PASS
  tests/test_position_monitor.py: 14/14 PASS (regression)
  tests/test_position_state.py: X/X PASS (regression)
  tests/test_trading_state.py: X/X PASS (regression)
  tests/test_pending_proposals.py: X/X PASS (regression)
  tests/test_validator.py: X/X PASS (regression)
  합계: XX/XX PASS

dry-run --once 결과:
  - [recover_on_boot OK / FAIL: 사유]
  - [tick OK / FAIL: 사유]

설계 결정 변경사항 (있는 경우):
  - ...

알려진 한계:
  - qty_ref 계산 시 split_weight 0.5 하드코딩 (Brief F 이후 config화 예정)
  - _tick_process_requests는 장중만 동작 (09:00~15:30)
  - ...
```

---

*Brief D Stage 5 기술 설계 — 2026-04-23*
