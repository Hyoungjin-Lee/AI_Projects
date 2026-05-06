# Stage 5: 기술 설계 — Phase 2 텔레그램 승인형 매수 + 자동 매도

> 날짜: 2026-04-22 | 담당: Claude (Opus 수준 효등) | Effort: High
> 입력: `04_plan_final.md` (형진님 승인 후 진입)
> 산출물: 이 문서 — **Codex 구현 브리프**. 읽고 즉시 Stage 8로 진입 가능해야 함.
> 우선순위 표기: [P0]는 필수, [P1]은 Phase 2.1+로 연기.

---

## 0. 설계 원칙 (SoC)

1. **단일 쓰기 프로세스** — `position_monitor`만이 3종 state JSON에 쓴다. 다른 모듈은 read + request queue.
2. **단일 preflight** — 모든 주문은 `validator.validate_order()`를 통과해야 `kis_client.place_order()` 호출 가능.
3. **기존 kis_client 재사용** — v0.1의 `buy_order/sell_order` 이식은 **하지 않는다**. `KISClient.place_order()`를 그대로 쓴다.
4. **dry-run 일급 시민** — `DRY_RUN=1` 환경변수에서 실제 호출 없이 전체 상태머신이 동작해야 한다.
5. **기존 스크립트·패턴 준수** — `orchestrator.cmd_map` 디스패치, `keychain_manager.inject_to_env()`, `state_manager` JSON 영속화 패턴을 그대로 확장.

---

## 1. 전체 아키텍처

### 프로세스 구성

```
[launchd 등록 프로세스]
┌────────────────────────────────────┐    ┌───────────────────────────────┐
│ telegram_bot.py                    │    │ position_monitor.py (신규)    │
│ (기존 상시 데몬, polling)          │    │ 10초 / 60초 이중 루프         │
│                                    │    │ - 매수 제안 전송 + 재권유     │
│ /매수함 /매수안함 /종목변경         │    │ - 보유 종목 손절/익절 감시    │
│ /잔고 /상태 /발굴 ...              │    │ - 장마감 강제청산             │
└──────────┬─────────────────────────┘    │ - 자정 카운터 리셋            │
           │                              │ - 재시작 복구 스캔            │
           │ handle_command()             │ - pending 만료 처리           │
           ▼                              │ - **유일한 JSON writer**     │
┌────────────────────────────────────┐    └──────┬────────────────────────┘
│ orchestrator.py                    │           │
│ (명령 핸들러 디스패치, 확장)       │           │
│ cmd_buy_yes / cmd_buy_no / ...     │           │
└──────────┬─────────────────────────┘           │
           │                                      │
           │ (요청) buy_request.jsonl queue       │ (소비)
           │◄─────────────────────────────────────┤
           │                                      │
           ▼                                      ▼
┌────────────────────────────────────────────────────────┐
│ validator.py (신규) — validate_order()                 │
│  모든 preflight: 시장시간 · 실전가드 · 잔고 · COOLDOWN │
│  · 손실한도 · 매매횟수한도 · 가격이탈 · 중복방지       │
└──────────┬─────────────────────────────────────────────┘
           │  OK
           ▼
┌────────────────────────────────────────────────────────┐
│ .skills/kis-api/scripts/kis_client.py (기존)           │
│  KISClient.place_order / get_orderable_cash / get_balance│
│  TR TTTC0802U (매수) / TTTC0801U (매도) 실전 확정      │
└────────────────────────────────────────────────────────┘
```

### 트리거 소스 (제안 큐잉)

```
intraday_discovery.py --round {2,4,6,8}
       │ (round 종료 직후)
       ▼
 pending_proposals.json 에 1위 제안 enqueue (via proposal_request.jsonl)
       │
       ▼
 position_monitor 루프가 enqueue 요청 소비 → pending_proposals.json 기록
       │
       ▼
 telegram_sender 통해 메시지 발송 (초당 1건 throttle)
```

---

## 2. 모듈 책임 & 인터페이스

### 2.1 `morning_report/position_monitor.py` [신규, P0]

**책임:**
- 10초(포지션 1+ 보유) / 60초(미보유) 이중 루프
- 보유 종목 손절/익절/트레일링/장마감 판정 + 자동 매도
- 재권유 상태머신 진행 (3분 타임아웃, 최대 3회)
- 자정(00:00) 일일 카운터 리셋
- 부팅 첫 틱의 재시작 복구 스캔 (놓친 손절 + pending 만료)
- **3종 state JSON의 유일한 writer**

**핵심 함수 (의사 코드):**

```python
def main() -> None:
    inject_to_env()
    setup_logging("trading")
    _recovery_scan_on_boot()            # 부팅 복구
    while True:
        now = datetime.now()
        _process_requests()             # buy_request.jsonl · proposal_request.jsonl · trial_request.jsonl 소비
        _check_midnight_reset(now)      # trading_state 리셋
        if is_market_open(now):
            _tick_positions(now)        # 손절/익절/트레일링/장마감
            _tick_proposals(now)        # 재권유 · 만료
        sleep(_adaptive_interval())

def _tick_positions(now) -> None:
    for ticker, pos in position_state.holdings.items():
        cur = kis_client.get_current_price(ticker)
        _update_trailing_peak(pos, cur)
        decision = _evaluate_exit(pos, cur, now)
        if decision.should_exit:
            _execute_sell(ticker, pos.qty, reason=decision.reason)

def _tick_proposals(now) -> None:
    for p in pending_proposals:
        if p.status != "pending": continue
        if (now - p.last_sent) >= timedelta(minutes=3):
            if p.count < 3:
                _send_resuggestion(p)
            else:
                p.status = "exhausted"; _persist()

def _execute_buy(ticker, price_ref, stage) -> None:
    qty = _calc_qty(price_ref, stage)
    ok, reason = validator.validate_order("BUY", ticker, qty, price_ref)
    if not ok: _notify(f"⛔ 매수 거절: {reason}"); return
    cur = kis_client.get_current_price(ticker)
    if abs(cur - price_ref) / price_ref > 0.03:
        _notify(f"⚠️ 권유가 {price_ref} → 현재 {cur}, ±3% 이탈 매수 보류"); return
    resp = kis_client.place_order("BUY", ticker, qty)  # DRY_RUN 시 mock
    if _verify_order(resp):
        _confirm_by_balance_check(ticker)  # 잔고 조회로 실제 체결량 확정
        position_state.apply_buy(ticker, qty, cur, stage)  # 가중평단 갱신
        trading_state.buy_count_today += 1                  # 매수 횟수 카운트
        _persist_all()
        _notify(f"✅ 체결: {ticker} {qty}주 @ {cur:,}원 ({_stage_label(stage)})")

def _execute_sell(ticker, qty, reason) -> None:
    ok, r = validator.validate_order("SELL", ticker, qty, None)
    if not ok: _notify(f"⛔ 매도 거절: {r}"); return
    resp = kis_client.place_order("SELL", ticker, qty)
    if _verify_order(resp):
        cur = kis_client.get_current_price(ticker)
        pnl = position_state.apply_sell(ticker, qty, cur)  # 실현손익 반환
        trading_state.realized_pnl += pnl
        trading_state.sell_count_today += 1                 # 매도 횟수 (참고용, 한도 적용 X)
        trading_state.cooldown_until[ticker] = now + COOLDOWN
        # 일일 손실한도 = 당일 시작 시점 주문가능금액 전액 (자정 스냅샷)
        if trading_state.realized_pnl <= -trading_state.daily_start_orderable_cash:
            trading_state.block_new_orders = True
            _notify("🛑 일일 손실한도 초과. 오늘 신규 주문 차단. 00:00 자동 해제.")
        _persist_all()
        _notify(f"{_sell_emoji(reason)} {reason}: {ticker} {qty}주 @ {cur:,}원 ({pnl:+,}원)")

def _check_midnight_reset(now) -> None:
    if now.date() > trading_state.last_reset_date:
        trading_state.realized_pnl = 0
        trading_state.buy_count_today = 0
        trading_state.sell_count_today = 0
        trading_state.block_new_orders = False
        trading_state.last_reset_date = now.date()
        # 당일 시작 주문가능금액 스냅샷 → 일일 손실한도 기준값
        trading_state.daily_start_orderable_cash = kis_client.get_orderable_cash()
        _persist_all()
        _notify(
            f"🔓 일일 한도 해제. 오늘 손실한도={trading_state.daily_start_orderable_cash:,}원 "
            f"({'시범' if trading_state.trial_mode else '정상'} 모드, "
            f"매수 최대 {_effective_max_buys()}건)"
        )

def _recovery_scan_on_boot() -> None:
    # 놓친 손절
    for ticker, pos in position_state.holdings.items():
        cur = kis_client.get_current_price(ticker)
        d = _evaluate_exit(pos, cur, datetime.now())
        if d.should_exit:
            _execute_sell(ticker, pos.qty, reason=f"재시작감지-{d.reason}")
    # 만료된 pending
    cutoff = datetime.now() - timedelta(minutes=5)
    for p in pending_proposals:
        if p.status == "pending" and p.last_sent < cutoff:
            p.status = "expired"
    _persist_all()

def _adaptive_interval() -> float:
    return 10.0 if position_state.holdings else 60.0
```

**예외 처리:** 모든 틱은 try/except로 감싸고 실패 시 `logs/trading.log`에 `ERROR` 레벨 기록 + 다음 틱 계속. 연속 5회 실패 시 텔레그램 경고 + 10분 휴면.

### 2.2 `morning_report/validator.py` [신규, P0]

**단일 진입점:**
```python
def validate_order(action: str, ticker: str, qty: int, price_ref: float | None) -> tuple[bool, str]:
    """
    action: "BUY" | "SELL"
    returns: (True, "") or (False, reason_str_for_user)
    """
```

**체크 순서 (실패 시 즉시 반환):**

| # | 체크 | 실패 문구 예시 |
|---|---|---|
| 1 | `KIS_ALLOW_LIVE_ORDER` 환경변수 = "1" | "실전 가드 미설정 (KIS_ALLOW_LIVE_ORDER)" |
| 2 | `is_market_open(now)` | "장 시간 외 주문 불가" |
| 3 | `qty > 0` | "수량 0 이하" |
| 4 | action=="BUY" 시 `trading_state.block_new_orders == False` (실현손실 ≥ `daily_start_orderable_cash` 시 true) | "일일 손실한도 초과 — 소액계좌 시작금액 전액 손실. 00:00 자동 해제" |
| 5 | action=="BUY" 시 `trading_state.buy_count_today < _effective_max_buys()` (시범모드면 `trial_max_buys`, 아니면 `max_buy_trades_per_day`) | "일일 매수 횟수 초과 (Y/N건)" |
| 6 | action=="BUY" 시 `ticker` COOLDOWN 만료 | "종목 COOLDOWN 중 (남은 Xs)" |
| 7 | action=="BUY" 시 `orderable_cash >= qty * price_ref` | "주문가능금액 부족" |
| 8 | action=="SELL" 시 `position_state.holdings[ticker].qty >= qty` | "보유 수량 부족" |
| 9 | action=="SELL" 시 해당 종목 SELL 중복 진행 중이 아님 | "매도 주문 진행 중 (중복 차단)" |

**헬퍼 함수 `_effective_max_buys()`:**
```python
def _effective_max_buys() -> int:
    if trading_state.trial_mode:
        return trading_state.trial_max_buys  # 보통 1
    return strategy_config.trading["max_buy_trades_per_day"]  # 기본 10
```

**가격 이탈 가드(±3%)는 validator 안이 아니라 monitor `_execute_buy`에서 체크** — validator는 "구조적·한도성" 체크에 집중, 실시간 시세 비교는 호출자 책임.

### 2.3 `.skills/kis-api/scripts/kis_client.py` [수정, P0]

**기존:**
- `place_order(side, code, qty, price=None)` — 실전 TR 확정 (`TTTC0802U/TTTC0801U`) ✅
- `get_orderable_cash()` ✅
- `get_balance()` ✅
- `get_current_price`(≈`get_quote`) ✅

**핵심 변경: mode 파라미터 도입 → KIS 키 그룹 분리**

실전 매매용 KIS 앱을 관측용과 **완전히 분리**한다 (APP_KEY/SECRET/ACCOUNT_NO 3종 모두 별도 env var). 동일 KISClient 클래스에서 생성 시 모드 선택:

```python
# 기존 (관측용) — mode 기본값 "observation". 기존 코드 수정 없음
obs_client = KISClient()
obs_client.get_balance()         # KIS_ACCOUNT_NO

# Phase 2 신규 (매매용)
trading_client = KISClient(mode="trading")
trading_client.get_orderable_cash()      # KIS_TRADING_ACCOUNT_NO
trading_client.place_order("BUY", ...)    # KIS_TRADING_APP_KEY로 TR TTTC0802U 전송
```

**mode별 사용 env var:**

| 필드 | mode="observation" (기본) | mode="trading" |
|------|---------------------------|----------------|
| APP_KEY | `KIS_APP_KEY` | `KIS_TRADING_APP_KEY` |
| APP_SECRET | `KIS_APP_SECRET` | `KIS_TRADING_APP_SECRET` |
| ACCOUNT_NO | `KIS_ACCOUNT_NO` | `KIS_TRADING_ACCOUNT_NO` |
| HTS_ID | `KIS_HTS_ID` | (불필요 — 주문 TR은 HTS_ID 미사용) |
| 토큰 캐시 | `data/cache/kis_token.json` | `data/cache/kis_token_trading.json` |

**place_order 로직 (DRY_RUN + mode 가드):**
```python
def place_order(self, side: str, code: str, qty: int, price: int | None = None) -> dict:
    # 1. mode 및 payload validation (build_order_payload가 mode!="trading"이면 예외)
    draft = self.build_order_payload(side, code, qty, price)
    # 2. DRY_RUN=1 이면 실제 호출 없이 mock
    if os.getenv("DRY_RUN") == "1":
        return {"rt_cd": "0", "msg_cd": "DRY_RUN",
                "msg1": f"DRY_RUN {draft['human_summary']}",
                "output": {"ODNO": f"DRY{uuid4().hex[:10].upper()}", ...}}
    # 3. 실전 가드
    if os.getenv("KIS_ALLOW_LIVE_ORDER") != "1":
        raise RuntimeError("실주문 전송이 차단됨...")
    return self._post(draft["endpoint"], draft["tr_id"], draft["body"])
```

**build_order_payload 가드:** `self.mode != "trading"` 시 `KISConfigError`. observation 인스턴스에서 주문 호출 자체를 구조적으로 차단.

**추가 메서드 (선택):**
- `inquire_balance_by_ticker(code)` — 특정 종목 보유 잔고 재확인 (체결 확인 2단계)
- `assert_trading_mode()` — 트레이딩 전용 읽기 호출 전 mode 검증 헬퍼

### 2.4 `morning_report/keychain_manager.py` [수정, P0]

**신규 상수 — 실전 매매 전용 KIS 키 그룹 3종:**
```python
_TRADING_ITEMS = [
    ("KIS_TRADING_APP_KEY",     "실전 매매용 KIS 앱키",     True),
    ("KIS_TRADING_APP_SECRET",  "실전 매매용 KIS 앱시크릿", True),
    ("KIS_TRADING_ACCOUNT_NO",  "실전 매매용 계좌번호",     False),
]
```

**등록 명령:** `venv/bin/python3 morning_report/keychain_manager.py --reset-trading`
- 3종 일괄 입력 → 입력된 키로 **잔고 조회 테스트**(기존 `_test_balance()` 재사용) → 성공 시 Keychain 저장, 실패 시 최대 3회 재시도 후 종료

**`inject_to_env()`:** 3종 모두 `os.environ`에 주입 (미설정이어도 관측 기능 영향 없음).

**`show_status()`:** 기존 관측용 섹션 + 텔레그램 섹션 뒤에 `💼 실전 매매 계좌` 섹션 3줄 추가.

**CLI 진입점:** 기존 `--reset` 는 관측용 전용으로 유지. `--reset-trading` 플래그 신설로 트레이딩 그룹 전용 플로우 분리.

**이점:**
- 관측용 키가 망가져도 매매 기능 영향 없음 (역도 성립)
- KIS 개발자센터에서 매매 전용 앱으로 쿼터·로그·레이트리밋 격리
- 실수로 관측 앱을 실전 매매에 사용하는 경로가 구조적으로 차단됨 (mode 파라미터로 강제)

### 2.5 `morning_report/telegram_bot.py` [수정, P0]

- 기존 polling 루프 유지
- 메시지 전송 쪽에 **초당 1건 throttle 큐** 신설:
  ```python
  _send_queue: list[tuple[datetime, str]] = []
  def send_throttled(text: str): _send_queue.append(...)
  # 내부 스레드가 1Hz로 flush
  ```
- `handle_command` 위임은 그대로 `orchestrator.handle_command()`.

### 2.6 `morning_report/orchestrator.py` [수정, P0]

**cmd_map 확장:**
```python
cmd_map = {
    # 기존
    "/잔고":   cmd_balance, "/상태": cmd_state, "/발굴": cmd_discovery, "/도움말": cmd_help,
    # 신규 (Phase 2 — 승인형 매수)
    "/매수함":     cmd_buy_yes,       # 인수 없음 → 현재 pending 1건에 대한 승인
    "/매수안함":   cmd_buy_no,
    "/종목변경":   cmd_buy_alt,       # /종목변경 2  (1~5 순위 선택)
    # 신규 (Phase 2 — 시범 운영 제어)
    "/시범시작":   cmd_trial_start,   # "/시범시작" 또는 "/시범시작 2" (매수 한도 오버라이드)
    "/시범종료":   cmd_trial_stop,    # 즉시 시범모드 해제
    "/시범상태":   cmd_trial_status,  # 현재 모드·한도·잔여 매수 횟수 표시
}
```

**핸들러 (요청 큐 패턴):**
```python
def cmd_buy_yes():
    top = pending_proposals.peek_oldest_pending()
    if not top:
        send_text("ℹ️ 대기 중인 매수 제안 없음."); return
    _enqueue_buy_request(top.id)   # buy_request.jsonl append
    send_text(f"⏳ {top.name} 매수 진행 중...")

def cmd_buy_no():
    top = pending_proposals.peek_oldest_pending()
    if not top: send_text("ℹ️ 대기 중인 매수 제안 없음."); return
    _enqueue_decline(top.id); send_text(f"❎ {top.name} 매수 거절.")

def cmd_buy_alt():
    # /종목변경 2 → 순위 2번으로 전환
    ...

def cmd_trial_start(arg: str = ""):
    # /시범시작        → trial_max_buys = strategy_config.trial_mode_default_max_buys (기본 1)
    # /시범시작 2      → trial_max_buys = 2
    n = int(arg) if arg.isdigit() and int(arg) > 0 else None
    _enqueue_trial_request(op="start", max_buys=n)
    send_text(f"🧪 시범 운영 시작 요청 (매수 한도={n or '기본'}). monitor 다음 틱에서 반영.")

def cmd_trial_stop():
    _enqueue_trial_request(op="stop")
    send_text("🧪 시범 운영 종료 요청. monitor 다음 틱에서 반영.")

def cmd_trial_status():
    # trading_state.json 을 읽기 전용으로 열어 현재 상태 표시 (orchestrator는 read만 OK)
    s = load_trading_state()
    effective = s.trial_max_buys if s.trial_mode else strategy_config.trading["max_buy_trades_per_day"]
    send_text(
        f"📊 모드={'시범' if s.trial_mode else '정상'} / "
        f"매수한도={effective}건 / "
        f"오늘체결={s.buy_count_today}건 / "
        f"실현손익={s.realized_pnl:+,}원 / "
        f"손실한도={s.daily_start_orderable_cash:,}원"
    )
```

오케스트레이터는 **쓰기 안 함**. `jsonl` append-only 큐에 요청만 넣고 monitor가 소비.

**시범 운영 요청 큐 스키마 (`data/queue/trial_request.jsonl`):**
```json
{"op":"start","max_buys":1,"requested_at":"2026-04-25T09:00:00"}
{"op":"stop","requested_at":"2026-04-25T15:30:00"}
```

**시범 모드 수명 규칙:**
- `/시범시작` → `trading_state.trial_mode=true, trial_max_buys=N, trial_started_at=now` 갱신 (monitor가 수행).
- `/시범종료` → `trading_state.trial_mode=false` 즉시 해제.
- **자정 리셋 시 trial_mode는 유지하지 않고 false로 초기화** (매일 명시적으로 `/시범시작`을 호출해야 함 → 시범 운영 일자 관리의 명확성 확보). `trial_mode_persist_across_days` 같은 옵션은 P2에서 고려.
- 시범 모드 활성 상태에서 `max_buy_trades_per_day`와 `trial_max_buys` 중 **작은 값**을 적용하고 싶으면 추후 `_effective_max_buys()`를 `min(...)`으로 변경. P0은 시범모드 오버라이드가 우선.

### 2.7 `morning_report/intraday_discovery.py` [수정, P0]

`run_round(2|4|6|8)` 종료 시점에 결과 상위 5를 받아:
```python
def _enqueue_top_proposal(top5, round_num):
    first = _pick_first_passing_thresholds(top5)  # 점수/체결강도/등락률 임계 + COOLDOWN 배제
    if first is None: return
    proposal = {
        "id": f"{round_num}-{first.code}-{int(time.time())}",
        "code": first.code, "name": first.name,
        "round": round_num, "rank": 1,
        "score": first.score, "tday_rltv": first.tday_rltv, "chg": first.chg,
        "price_ref": first.current_price,
        "top5": top5[:5],               # 종목변경 대안
        "stage": "최초진입",
        "created_at": datetime.now().isoformat(),
    }
    _append_jsonl("data/proposal_request.jsonl", proposal)
```

### 2.8 `morning_report/closing_report.py` [수정, P0]

- 장마감 블록에 **"오늘 체결 요약"** 섹션 추가 (trading_state.realized_pnl, trades_today, 차단 이력)
- 장마감 강제청산 자체는 **position_monitor가 수행** (15:15 시장가 → 15:25 동시호가 재시도). closing_report는 트리거하지 않음.

---

## 3. 데이터 스키마

### 3.1 `data/position_state.json`

```json
{
  "updated_at": "2026-04-23T09:05:12",
  "holdings": {
    "005930": {
      "name": "삼성전자",
      "qty": 50,
      "avg_price": 87200.0,
      "stage": 1,                       // 1=최초 50% / 2=1차추가 / 3=2차추가
      "first_entry_at": "2026-04-23T09:05:12",
      "last_entry_at":  "2026-04-23T09:05:12",
      "peak_price_since_entry": 87500.0,
      "trailing_active": false,         // 평단 +2% 돌파 여부
      "entry_history": [
        {"at": "...", "qty": 50, "price": 87200, "stage": 1}
      ]
    }
  }
}
```

**가중평단 공식 (신규):**
```
new_avg = (old_avg * old_qty + new_price * new_qty) / (old_qty + new_qty)
```
매수 후 avg_price 재계산, stage++, last_entry_at 갱신, peak 재설정.

### 3.2 `data/trading_state.json`

```json
{
  "last_reset_date": "2026-04-23",
  "realized_pnl": 0,                    // 원, 당일 실현손익 누적 (음수면 손실)
  "daily_start_orderable_cash": 3000000, // 원, 자정 리셋 시 소액계좌 주문가능금액 스냅샷
                                         // → 일일 손실한도 기준값 (이만큼 잃으면 block_new_orders=true)
  "buy_count_today": 0,                 // 당일 체결 성공 매수 건수 (MAX_BUY_TRADES_PER_DAY 대상)
  "sell_count_today": 0,                // 당일 체결 성공 매도 건수 (참고용, 한도 없음)
  "block_new_orders": false,
  "trial_mode": false,                  // 시범 운영 on/off (텔레그램 /시범시작 <N>)
  "trial_started_at": null,             // 시범 시작 시각 ISO (log용)
  "trial_max_buys": 1,                  // 시범 모드 활성 시 max_buy_trades_per_day 오버라이드
  "cooldown_until": {
    "005930": "2026-04-23T10:35:00"
  },
  "in_flight_orders": {                 // 중복 주문 차단용 (SELL 진행 중)
    "005930": {"side": "SELL", "started_at": "..."}
  }
}
```

**필드 의미 요약:**
- `daily_start_orderable_cash` — **일일 손실한도의 기준값**. 자정 리셋 시 `kis_client.get_orderable_cash()` 호출 결과를 스냅샷. `realized_pnl <= -daily_start_orderable_cash` 면 `block_new_orders=true`. (형진님 결정: 고정 500,000원 대신 소액계좌 주문가능금액 전액으로 기본값 설정)
- `buy_count_today` / `sell_count_today` — **매수만 한도 대상**. 매도 건수는 참고용으로만 기록. (형진님 결정: `max_trades_per_day`는 매수 기준 10건)
- `trial_mode` / `trial_max_buys` — **시범 운영 별도 제어**. `/시범시작 1` → `trial_mode=true, trial_max_buys=1` → 해당 날 매수 최대 1건. `/시범종료` 또는 자정 리셋 시 기본값 복귀 규칙은 Section 2.6 참조.

### 3.3 `data/pending_proposals.json`

```json
{
  "proposals": [
    {
      "id": "2-005930-1745200000",
      "code": "005930", "name": "삼성전자",
      "round": 2, "rank": 1, "stage": "최초진입",
      "score": 85, "tday_rltv": 125, "chg": 3.2,
      "price_ref": 87200,
      "top5": [ ... ],
      "status": "pending",              // pending|accepted|declined|exhausted|expired
      "count": 0,                       // 0~3
      "created_at": "...",
      "last_sent": "...",
      "resolved_at": null
    }
  ]
}
```

**분할 단계별 독립 카운터**: 같은 종목의 `최초진입`·`1차_추가매수`·`2차_추가매수`는 **별도 proposal id**로 생성. 각자 `count: 0→3` 소진 가능.

### 3.4 Append-only 요청 큐 (파일 기반 IPC)

파일 경로와 포맷:

| 파일 | writer | reader | 내용 (JSONL 한 줄당 1요청) |
|---|---|---|---|
| `data/queue/proposal_request.jsonl` | intraday_discovery | monitor | `{"op":"enqueue", "proposal":{...}}` |
| `data/queue/buy_request.jsonl` | orchestrator | monitor | `{"op":"buy_yes"\|"buy_no"\|"buy_alt", "proposal_id":"...","alt_rank":n}` |
| `data/queue/trial_request.jsonl` | orchestrator | monitor | `{"op":"start"\|"stop", "max_buys":n?, "requested_at":"..."}` |

monitor는 매 틱마다 파일 끝에서 읽고 처리 후 오프셋을 `data/queue/.offsets.json`에 저장. 처리된 파일은 1일 1회 archive로 로테이션.

### 3.5 `data/strategy_config.json` — `trading` 섹션 (신규)

```json
{
  "trading": {
    "account_env_var": "KIS_TRADING_ACCOUNT_NO",
    "reserve_ratio": 0.10,
    "split_weights": [0.5, 0.3, 0.2],
    "stop_loss_pct": 0.03,
    "take_profit_pct": 0.05,
    "trailing_activate_pct": 0.02,
    "trailing_window_days": 5,
    "trailing_drop_pct": 0.03,
    "price_deviation_guard_pct": 0.03,
    "resuggest_timeout_seconds": 180,
    "resuggest_max_count": 3,
    "cooldown_seconds": 300,
    "max_daily_loss_mode": "auto_orderable_cash",  // "auto_orderable_cash" | "fixed_krw"
    "max_daily_loss_krw_override": null,            // 수동 고정값 (mode=="fixed_krw"일 때만 사용)
    "max_buy_trades_per_day": 10,                   // 매수 기준 하루 최대 건수 (매도는 포함 X)
    "trial_mode_default_max_buys": 1,               // /시범시작 인수 생략 시 기본값
    "market_close_sell_first_hhmm": "15:15",
    "market_close_sell_retry_hhmm": "15:25",
    "telegram_send_rate_per_sec": 1
  }
}
```

**튜너블 해설:**
- `max_daily_loss_mode` — `"auto_orderable_cash"`가 기본. 매일 자정 리셋 시 `kis_client.get_orderable_cash()`를 스냅샷해 `trading_state.daily_start_orderable_cash`로 저장하고, 그 금액만큼 실현손실이 나면 신규 주문 차단. (예: 소액계좌 300만원 → 당일 실현손실 -300만원에 도달 시 차단. 단, 이 수치는 보유 평가손실이 아니라 확정 실현손실만 카운트.)
- `max_daily_loss_krw_override` — 예외 상황에서 수동 고정값으로 전환하고 싶을 때만 `"fixed_krw"` 모드와 함께 사용. Phase 2 P0에서는 기본 모드 유지.
- `max_buy_trades_per_day` — 매수 체결 성공 건수만 카운트. `validate_order(BUY)` 5번 체크에서 `buy_count_today < max_buy_trades_per_day` 검사.
- `trial_mode_default_max_buys` — `/시범시작`(인수 생략) 시 적용할 매수 한도. 인수가 있으면 `/시범시작 2` → `trial_max_buys=2`.

---

## 4. 데이터 / 제어 흐름 (상세)

### 4.1 제안 → 체결 경로

```
09:05:00  intraday_discovery round 2 종료
          └─ 상위 5 산출
          └─ 1위가 임계치·COOLDOWN 통과 → proposal_request.jsonl append
09:05:02  position_monitor 틱
          └─ proposal_request.jsonl 소비
          └─ pending_proposals.json 에 status=pending 등록
          └─ telegram 메시지 전송 (throttle 큐)
09:05:05  사용자 텔레그램 수신
09:06:30  사용자 "/매수함"
          └─ telegram_bot → orchestrator.cmd_buy_yes
          └─ buy_request.jsonl append {"op":"buy_yes","proposal_id":"2-..."}
          └─ "⏳ 매수 진행 중..." 응답
09:06:32  position_monitor 틱
          └─ buy_request 소비
          └─ validator.validate_order("BUY", ...)
          └─ 현재가 재조회 → ±3% 가드
          └─ calc_qty → kis_client.place_order("BUY", ...)
          └─ verify + 잔고 재조회로 실체결 수량 확정
          └─ position_state.apply_buy (가중평단)
          └─ 체결 통지
09:06:35  사용자 "✅ 체결: 삼성전자 50주 @ 87,200원 (1차 50%)" 수신
```

### 4.2 자동 매도 경로 (트레일링 예시)

```
09:20  평단 +2% 도달 → trailing_active=true, peak 기록
09:45  peak = 91,400 (평단 +4.8%)
10:02  현재가 88,650 (peak -3.0% 이탈) → 전량 매도
       └─ validator OK → place_order("SELL", ...) → apply_sell → 통지
```

### 4.3 장마감 2단 청산 (15:15 / 15:25)

```
15:15:00  monitor: 보유 전체 전량 시장가 매도
15:15:10  일부 미체결 → in_flight 기록
15:25:00  monitor: 미체결 종목 재매도 (이제 동시호가 시간대, 시장가는 동시호가로 편입)
15:29:00  체결 최종 확인, 미체결 시 "⚠️ 잔여 보유: X종목 — 익일 처리" 알림
```

### 4.4 자정 리셋

```
00:00:00  monitor: _check_midnight_reset
          realized_pnl=0, trades_today=0, block_new_orders=false
          cooldown_until 만료 건 청소
          "🔓 일일 한도 해제 완료" 통지
```

### 4.5 재시작 복구 (부팅 첫 틱)

```
monitor 부팅
  └─ pending_proposals 로드 → last_sent > 5분 전 pending → expired
  └─ position_state 로드 → 각 보유 종목 현재가 조회
  └─ 손절 조건 즉시 판정 → 해당 시 즉시 매도
  └─ 로그: "[recovery] 놓친 손절 N건 감지, 처리 완료"
```

---

## 5. 상태 머신

### 5.1 Proposal 5상태

```
                ┌──────────────┐
                │  (생성)      │
                │  pending     │
                └──┬────┬──┬──┘
                   │    │  │
   /매수함         │    │  │  /매수안함
       ┌───────────┘    │  └───────────┐
       ▼                │              ▼
   accepted       (3회 재권유 소진)  declined
   (체결 진행)    exhausted
                        │
                        │  (부팅 시 5분 경과)
                        ▼
                    expired
```

전이 규칙:
- `pending → accepted`: `/매수함` + validate OK + place_order 성공
- `pending → declined`: `/매수안함` 또는 `/종목변경` 로 교체됨
- `pending → exhausted`: `count >= 3` + 타임아웃
- `pending → expired`: 재시작 시 `last_sent > 5분`
- 종결 상태(`accepted/declined/exhausted/expired`)는 불변

### 5.2 Position 진입 단계

```
미보유 ──(1차 50%)──▶ stage=1 ──(조건+1차추가 P1)──▶ stage=2 ──▶ stage=3
                         │                            │            │
                         └────────────────────────────┴────────────┤
                                                                   ▼
                                                   미보유 (전량 매도)
```

P0 범위는 stage=1까지만. 2차/3차 자동 제안은 P1.

### 5.3 Trading 차단 상태

```
정상 ──(realized_pnl ≤ -MAX_DAILY_LOSS)──▶ block_new_orders=true
 ▲                                              │
 │                                              │ (자정 00:00)
 └──────────────────────────────────────────────┘
```

---

## 6. 예외 처리 포인트

| 위치 | 예외 | 처리 |
|---|---|---|
| `kis_client.place_order` 타임아웃 | requests.Timeout | 5초 타임아웃 설정, 재시도 **없음**, in_flight 해제, "❗ 주문 타임아웃" 통지, proposal 상태 `pending` 복귀 |
| `place_order` rt_cd != "0" | KISAPIError | 메시지 그대로 통지, proposal `pending` 복귀 |
| 부분 체결 | balance_check 결과 < 요청 qty | 실제 체결량으로 position_state 기록, 잔여분은 "⚠️ 부분 체결: N/M주" 통지, 쿨다운 그대로 적용 |
| 잔고 조회 타임아웃 | | 5초 재시도 1회, 실패 시 place_order 성공으로 간주하되 "체결 확인 실패 — 수동 확인 필요" 통지 |
| `position_state.json` 파싱 오류 | JSONDecodeError | 부팅 실패, 텔레그램 긴급 알림 ("🚨 state 손상 — 수동 복구"), 데몬 정지 |
| 파일 쓰기 실패 | OSError | 임시파일 생성 실패 시 in-memory 상태만 유지, 다음 틱에 재시도, ERROR 로그 |
| validator 체크 실패 | returns (False, reason) | 사용자에게 reason 그대로 통지 |
| `_recovery_scan` 중 API 실패 | | ERROR 로그, 5초 후 재시도 1회, 그래도 실패 시 "⚠️ 재시작 복구 스캔 실패 — 수동 확인" 통지 |
| telegram rate limit 도달 | Telegram 429 | throttle 큐에서 1초 sleep 후 재송신 |
| Keychain `KIS_TRADING_ACCOUNT_NO` 미등록 | | 부팅 시 감지, 텔레그램 "⚙️ 실전 계좌 미등록 — keychain_manager --reset 필요" 통지, 데몬 정지 |
| `KIS_ALLOW_LIVE_ORDER=1` 미설정 | | validator가 모든 주문 거절, 매분 1회만 텔레그램 경고 (스팸 방지) |

---

## 7. 로깅 / 모니터링

### 7.1 신규 로그 파일

`logs/trading.log` — JSONL 한 줄당 1이벤트. 샘플:

```json
{"ts":"2026-04-23T09:06:32.103","lvl":"INFO","ev":"order_attempt","side":"BUY","code":"005930","qty":50,"price_ref":87200,"actual_price":87250,"proposal_id":"2-005930-1745200000","account":"******1234"}
{"ts":"2026-04-23T09:06:32.889","lvl":"INFO","ev":"order_result","rt_cd":"0","ODNO":"12345","filled_qty":50,"avg_fill":87200}
{"ts":"2026-04-23T10:02:12.440","lvl":"INFO","ev":"exit_auto","reason":"trailing","code":"005930","pnl":215000}
{"ts":"2026-04-23T14:05:00.000","lvl":"WARN","ev":"block_new_orders","cause":"max_daily_loss","realized_pnl":-501200}
```

### 7.2 민감정보 마스킹

- 계좌번호: 표시할 때 `******1234` (뒤 4자리만) — kis_client `_mask()` 재사용 또는 복제
- API 키/토큰: 로그에 절대 출력 금지 (기존 규칙 유지)

### 7.3 텔레그램 알림 카테고리

| 이벤트 | 이모지 | 전송 대상 |
|---|---|---|
| 매수 제안 / 재권유 | 📢 | 항상 |
| 체결 성공 | ✅ | 항상 |
| 손절 | 🚨 | 항상 |
| 트레일링/익절 | 💰 | 항상 |
| 장마감 청산 | 🔔 | 항상 |
| 주문 거절/보류 | ⚠️ / ⛔ | 항상 |
| 시스템 경고 | ❗ | 항상 |
| 일일 한도 도달 | 🛑 | 항상 |
| 한도 해제 | 🔓 | 1회 (자정) |

---

## 8. 테스트 포인트

### 8.1 Unit (pytest 또는 단일 스크립트)

| 대상 | 케이스 |
|---|---|
| `validator.validate_order` | 9개 체크 각각의 성공/실패 케이스, 순서 |
| `position_state.apply_buy` | 가중평단 재계산 (단독 매수, 1차 + 2차), 수치 검증 |
| `position_state.apply_sell` | 실현손익 계산, holdings 정리 |
| `_evaluate_exit` | 하드스탑·트레일링·목표·장마감 각 분기 |
| `_adaptive_interval` | 보유 유무에 따른 10s / 60s |
| `proposal` 상태 전이 | 5상태 모든 전이 + 불변성 |
| 장 시간 게이트 | 08:59 / 09:00 / 15:30 / 15:31 |

### 8.2 Integration (dry-run 모드, `DRY_RUN=1`)

시나리오 A~E (plan_final 시나리오 그대로) 5종을 dry-run으로 전체 흐름 재현:
- 제안 → /매수함 → mock 체결 → 사후 통지
- 가격 이탈 가드 트리거
- 자동 손절 트리거
- MAX_DAILY_LOSS 초과 → 차단 → 자정 해제
- 재시작 시 놓친 손절 복구

각 시나리오의 `logs/trading.log` JSONL을 검증 스크립트로 파싱하여 기대 이벤트 시퀀스와 비교.

### 8.3 실전 시범 (P0 12번)

Phase 2 가동 첫날, **1주 매수** 1회로 전체 흐름 검증:
1. 실제 매수 제안 수신 (실전 데이터 기반)
2. /매수함 → 1주 주문 (임시로 `max_trades_per_day=1`)
3. 체결 확인 → position_state 정상 기록 검증
4. 수동 /매도 명령으로 익일 청산 (또는 자동 매도 대기)
5. 로그 전수 리뷰 → 이상 없으면 다음날 정상 5:3:2 수량으로 전환

---

## 9. 보안 체크리스트

- [x] 모든 주문 경로가 `KIS_ALLOW_LIVE_ORDER=1` 가드 통과 (validator 1번 체크)
- [x] **KIS 키 그룹 완전 분리** — observation 인스턴스에서 `place_order`/`build_order_payload` 호출 시 `KISConfigError` (구조적 차단)
- [x] `KIS_TRADING_APP_KEY` / `KIS_TRADING_APP_SECRET` / `KIS_TRADING_ACCOUNT_NO` 3종 필요. 1개라도 빠지면 `KISClient(mode="trading")` 생성 실패
- [x] 토큰 캐시 파일 분리 (`kis_token.json` vs `kis_token_trading.json`) — 관측용 토큰이 매매에 사용되지 않음
- [x] 로그에 계좌번호 `******1234` 마스킹
- [x] 로그에 API 키·토큰 출력 금지
- [x] `chat_id` 검증(orchestrator 기존) 유지
- [x] `DRY_RUN=1` 강제 시 실제 주문 API 경로 실행 불가
- [ ] 민감 로그 파일 권한 `chmod 600` (선택, Stage 12 QA)

---

## 10. 확장 포인트 (P1/P2 대비 훅)

- **`/설정 <key.path> <value>`** — orchestrator `cmd_map`에 훅만 남겨두고 실제 핸들러는 P1에서 구현. `strategy_config.json` 파일 변경 시 monitor가 SIGHUP 또는 mtime 변화 감지로 리로드.
- **2차·3차 분할매수** — `_tick_positions` 내부에 `_check_add_entry_conditions()` 훅. P0에서는 `pass`.
- **NXT 시간외** — `is_market_open()` 내부를 `is_regular_open()`과 `is_extended_open()`으로 분리 가능하도록 구조만 남김.
- **주문 슬리피지** — `logs/trading.log`에 이미 `price_ref`와 `avg_fill` 병기 → 후처리 스크립트만 추가.

---

## 11. 구현 순서 & 의존성 (Codex 브리프)

| 순 | 대상 | 의존 | 내용 |
|---|---|---|---|
| 1 | keychain_manager.py | 없음 | `KIS_TRADING_ACCOUNT_NO` 추가, inject_to_env 확장 |
| 2 | kis_client.py | 1 | DRY_RUN 분기, `KIS_TRADING_ACCOUNT_NO` 우선 사용, (옵션) `inquire_balance_by_ticker` |
| 3 | strategy_config.json | 없음 | `trading` 섹션 신설 |
| 4 | position_state.json 스키마 + helper | 3 | 가중평단 apply_buy/apply_sell, persist |
| 5 | trading_state.json 스키마 + helper | 3 | counter·block·cooldown·in_flight |
| 6 | pending_proposals.json 스키마 + helper | 3 | 5상태 전이 |
| 7 | validator.py | 2,4,5,6 | 9체크 단일 함수 |
| 8 | position_monitor.py (골격) | 4,5,6,7 | 이중 루프, tick 함수들 의사 시그니처대로 구현 |
| 9 | _recovery_scan_on_boot | 8 | 부팅 복구 |
| 10 | _check_midnight_reset | 8 | 자정 리셋 |
| 11 | telegram throttle 큐 | 없음 | telegram_sender/bot 내부 초당 1건 |
| 12 | orchestrator 신규 cmd 3종 | 6,11 | cmd_buy_yes/no/alt + jsonl append |
| 13 | intraday_discovery round 2/4/6/8 훅 | 6 | _enqueue_top_proposal |
| 14 | closing_report 오늘 체결 요약 섹션 | 5 | 표시만 |
| 15 | launchd plist | 8 | com.aigeenya.stockreport.position_monitor.plist |
| 16 | dry-run 통합 테스트 스크립트 | 1~14 | 시나리오 5종 자동 검증 |
| 17 | 실전 시범 체크리스트 (P0 12번) | 1~15 | Stage 12 QA에서 체크 |

**병렬 가능**: 1·3·11은 독립. 나머지는 의존 트리 순서.

**Codex 1차 브리프 단위 권장**:
- Brief A: 1 + 2 + 3 (인프라)
- Brief B: 4 + 5 + 6 + 7 (상태·검증)
- Brief C: 8 + 9 + 10 (monitor 코어)
- Brief D: 11 + 12 + 13 (입출력 연결)
- Brief E: 14 + 15 (마감·배포)
- Brief F: 16 (테스트)

---

## 12. 주요 설계 결정 (의사결정 기록)

| # | 결정 | 대안 | 선택 사유 |
|---|---|---|---|
| 1 | position_monitor 독립 데몬 | telegram_bot 내부 스레드 | 단일 쓰기 프로세스 원칙 → 독립이 자연스러움. launchd KeepAlive로 수명 관리 일원화 |
| 2 | 3종 JSON **monitor 단독 쓰기** + append-only jsonl 요청 큐 | 파일 락 또는 SQLite | 디버깅 용이, 기존 state_manager 스타일 유지, 초기 부하 낮음. 다만 jsonl 로테이션 필요 |
| 3 | v0.1 buy_order/sell_order 이식 **하지 않음** | 전면 이식 | stockpilot `kis_client.place_order`가 이미 실전 TR + KIS_ALLOW_LIVE_ORDER 가드 반영. 중복 유지보수 부담만 생김 |
| 4 | 가격 이탈 가드는 validator 밖 | validator 안에 포함 | validator는 구조적·한도성 체크. 시세는 호출자(monitor)가 직접 재조회하는 것이 로직 흐름상 자연스러움 |
| 5 | dry-run을 환경변수(DRY_RUN=1)로 | CLI 플래그 | monitor가 장기 데몬이므로 환경변수가 적합. place_order 내부 조기분기가 최소 침습 |
| 6 | realized_pnl만으로 MAX_DAILY_LOSS 판정 | 평가손익 포함 | 실현된 손실만이 일일 한도의 의미. 평가손익은 변동성이 커 오탐 유발 |
| 7 | 장마감 15:15 / 15:25 2단 | 15:18:50 단일 | v0.1의 15:18:50은 동시호가 직전 → 실패 위험. 앞당겨 재시도 여유 확보 |
| 8 | 재권유 분할 단계 독립 카운터 | 종목별 단일 카운터 | 1차 거절 후 1차추가매수는 별개의 결정 → 카운터 섞이면 오작동 |
| 9 | telegram 초당 1건 throttle | 제한 없음 | 제안·재권유·체결·경고가 동시 발생 시 rate limit(30/s) 블록 위험, 보수적으로 1/s |
| 10 | `max_daily_loss`를 **소액계좌 당일 시작 주문가능금액**으로 자동 설정 (자정 스냅샷) | 고정 500,000원 | 소액계좌 자체가 "잃어도 되는 돈"의 상한이므로, 잔액 전액을 한도로 쓰는 것이 운영 의도와 일치. 계좌 증액·감액 시 자동 재조정됨 |
| 11 | `max_trades_per_day`는 **매수 기준**만 카운트 | 매수+매도 합산 | 매도는 포지션 정리/리스크 관리라서 억제할 이유가 없음. 매수 빈도만 제한하는 것이 리스크 관리 의도에 부합 |
| 12 | 시범 운영을 **텔레그램 명령어 on/off**로 제어 (`/시범시작 [N]`, `/시범종료`), launchd 별도 스케줄 없음 | 특정 일자 launchd 지정 / 자동 시범 모드 | 운영 시점을 유연하게 잡고 싶다는 요구. 자정 리셋 시 trial_mode는 false로 되돌려, 매일 명시적으로 켜도록 함 (실수로 장기간 시범 유지 방지) |
| 13 | **KIS APP_KEY 그룹 전체 분리** (APP_KEY/SECRET/ACCOUNT_NO) + `KISClient(mode)` 파라미터로 구분 | `KIS_ACCOUNT_NO`만 분리 / `KIS_TRADING_ACCOUNT_NO`만 추가 | 계좌만 분리하면 동일 앱 키를 공유 → 레이트리밋·토큰 충돌·로그 혼재. KIS 개발자센터에서 매매 전용 앱을 별도 등록해 쿼터 격리. 관측 인스턴스에서 `place_order` 호출 시 구조적 차단 |

---

## 13. Stage 8 Codex 진입 전 체크리스트

### 형진님 결정 사항 (2026-04-23 합의)

- [x] **본 문서 훑어보기** → 진행 (이번 세션에서 검토 + 결정 4건 반영 완료)
- [x] `max_daily_loss_krw` 초기값 → **`max_daily_loss_mode = "auto_orderable_cash"`** (소액계좌 당일 시작 주문가능금액을 자정 스냅샷해 한도로 사용, 고정 500,000원 폐기)
- [x] `max_trades_per_day` 초기값 → **`max_buy_trades_per_day = 10`** (매수 기준만 카운트, 매도는 한도 없음)
- [x] 첫 시범 운영 일자 → **별도 텔레그램 명령어** `/시범시작 [N]` / `/시범종료`로 제어. 1일 운영 계획은 Stage 8 완료 후 형진님이 임의 날짜에 `/시범시작 1` 실행
- [x] **KIS 키 그룹 전체 분리** → `KIS_TRADING_APP_KEY` / `KIS_TRADING_APP_SECRET` / `KIS_TRADING_ACCOUNT_NO` 3종 별도 그룹, `KISClient(mode="trading")` 파라미터로 구분 (결정 #13)

### Stage 8 진입 전 병렬 작업

**🧑 형진님 수동 작업:**
- [ ] KIS 개발자센터 로그인 → 매매 전용 앱 신규 등록 (예: `stockpilot-trading`)
- [ ] 해당 앱에 **실전 소액계좌** 연결
- [ ] 발급된 APP_KEY / APP_SECRET 안전 보관 (Brief A Task 1 구현 완료 후 `--reset-trading` 명령으로 입력)

**🤖 Codex 작업 (Brief A):**
- [ ] Task 1 — keychain_manager.py: `_TRADING_ITEMS` 추가, `--reset-trading` CLI, `show_status()` 트레이딩 섹션
- [ ] Task 2 — kis_client.py: `mode` 파라미터, 토큰 캐시 분리, `place_order` DRY_RUN + mode 가드
- [ ] Task 3 — strategy_config.json: `trading` 섹션 신설

**🧠 Claude 작업 (Brief A 완료 후):**
- [ ] Stage 9 Opus high effort 코드 리뷰
- [ ] 형진님께 `--reset-trading` 실행 안내 → 소액계좌 연결 테스트 통과 확인
- [ ] Brief B 작성 진입

---

*자동 생성 | stockpilot Phase 2 Stage 5 — Technical Design*
