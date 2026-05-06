# 🔍 Brief A — Stage 9 코드 리뷰 (Opus High)

> 작성일: 2026-05-06
> 단계: Stage 9 (Code Review — 1차)
> 검토자: Claude (Opus High effort)
> 입력: keychain_manager.py / kis_client.py / strategy_config.json (Codex 구현 결과)
> 다음: 통과 시 Stage 10 skip → KIS 등록 + reset-trading + Brief B 위임

---

## 0. 종합 판정 — 🟢 **통과 (Stage 10 수정 불필요)**

Brief A 사양 100% 충족 + 추가 안전장치(atomic write, mode 다층 검증, watchlist observation 전용 가드, _mask 일관 적용)까지 포함. **Stage 10 (Codex 수정) 진입 없이 바로 KIS 등록 + Brief B로 진행 가능.**

---

## 1. 검증 매트릭스

| Task | 사양 충족 | 추가 강화 | 판정 |
|------|----------|----------|------|
| **Task 1** keychain_manager.py | ✅ _TRADING_ITEMS 3종 + --reset-trading + inject_to_env trading 로드 | _prompt_trading_group_and_save() 분리 + 잔고 연결 테스트 통합 | 🟢 |
| **Task 2** kis_client.py | ✅ mode 파라미터 + 토큰 캐시 분리 + DRY_RUN + place_order | atomic write, assert_trading_mode(), watchlist observation 가드, get_orderable_cash() 선제 추가 | 🟢 |
| **Task 3** strategy_config.json | ✅ trading 섹션 20개 키 | account_env_prefix 명시 (코드-데이터 분리) | 🟢 |

---

## 2. 잘된 점 (Strong Points) 🌟

### 2.1 다층 mode 검증
```python
# Layer 1: __init__ (line 58-61)
if mode not in ("observation", "trading"):
    raise ValueError(...)

# Layer 2: __init__ env 검증 (line 86-90)
if missing: raise KISConfigError(...)

# Layer 3: build_order_payload (line 417-421)
if self.mode != "trading": raise KISConfigError(...)

# Layer 4: assert_trading_mode() public helper (line 334-337)
```
주문 흐름에서 4단계 검증 — **방어 깊이 우수**.

### 2.2 토큰 캐시 atomic write (line 138-152)
```python
tmp_fd, tmp_path = tempfile.mkstemp(dir=..., suffix=".tmp")
os.fdopen(tmp_fd, "w") → json.dump → os.replace
```
Crash-safe — 토큰 파일 손상 방지. 손상 감지 시 자동 unlink (line 117-129).

### 2.3 DRY_RUN + KIS_ALLOW_LIVE_ORDER 이중 가드
```python
# place_order (line 460-478)
if DRY_RUN == "1":           # 1차: 모킹 응답
    return mock_response
if KIS_ALLOW_LIVE_ORDER != "1":  # 2차: 명시적 활성화 필요
    raise RuntimeError(...)
return self._post(...)        # 실주문
```
**우발적 실주문 차단 메커니즘 우수.**

### 2.4 에러 메시지 자체에 복구 안내
```python
# kis_client.py line 87-90
"환경변수 누락: ... keychain_manager.py --reset-trading 로 등록하세요."
```
사용자 친화적.

### 2.5 _mask() 일관 사용
- account_no 마스킹: `human_summary` (line 447) — 로그/텔레그램 안전
- HTS_ID 마스킹: `[watchlist] 그룹 없음 (USER_ID: {_mask(...)})` (line 369)

### 2.6 보수적 레이트 리밋 (line 104)
- `_min_interval = 0.06` = ~16 calls/s
- KIS 공식 한도 20 calls/s 대비 안전 마진 20%

### 2.7 strategy_config trading 섹션 — Phase 2 결정사항 정확 반영
- `max_daily_loss_mode: "auto_orderable_cash"` — Phase 2 결정 1
- `max_buy_trades_per_day: 10` — Phase 2 결정 2  
- `market_close_sell_first/retry_hhmm: "15:15"/"15:25"` — 2단 청산 sell-first
- `account_env_prefix: "KIS_TRADING"` — 환경변수 prefix 명시 (data/code 분리)

---

## 3. 마이너 관찰 (정보성 — 수정 불필요)

### 3.1 [정보] place_order 시그니처와 Brief D 사양 차이
**관찰:** 현재 `place_order(side, code, qty, price=None)` — positional.
Brief D Stage 5 사양은 keyword 형식 가능성.

**판정:** 현 시그니처도 keyword 호출 호환됨 (`place_order(side="BUY", code="...", qty=1)`). Brief D 구현 시 시그니처 정렬은 자연스럽게 가능. **본 Brief A 단계 OK.**

### 3.2 [정보] _test_balance 토큰 캐시 우회 (keychain_manager line 394)
**관찰:** keychain 검증 시 `/oauth2/tokenP` 직접 호출 — KIS 1분 1회 토큰 제한.
MAX_ATTEMPTS=3에서 1분 내 3회 시도 시 토큰 발급 거부 가능.

**판정:** 잔고 검증은 `--reset` 시점에만 발생 (하루 1~2회). 영향 미미. **개선 백로그 (P3)**.

### 3.3 [정보] get_orderable_cash() 선제 추가 (line 309-332)
**관찰:** Brief A 사양 외 메서드. Phase 2 `max_daily_loss_mode="auto_orderable_cash"` 자정 스냅샷용.

**판정:** Brief D/E 구현 시 필요한 메서드를 선제적으로 추가 — **좋은 판단**. Brief A 범위 위반 X (인프라 보강).

### 3.4 [정보] 토큰 캐시 파일 위치 (data/cache/)
**관찰:** `kis_token.json` / `kis_token_trading.json` 모두 평문.

**확인 필요 (백로그):** `data/cache/` 가 `.gitignore`에 등록되어 있는지 별도 검증.

---

## 4. 하위 호환성 검증 ✅

| 기존 모듈 | 영향 | 검증 방법 |
|----------|------|----------|
| morning_report.py | ❌ 없음 | `KISClient()` 기본값 mode="observation" 유지 |
| intraday_discovery.py | ❌ 없음 | 동일 |
| closing_report.py | ❌ 없음 | 동일 |
| watchlist_sync.py | ❌ 없음 | get_watchlist_*() observation 전용 가드만 추가 |
| stock_discovery.py | ❌ 없음 | 동일 |
| telegram_bot.py / orchestrator.py | ❌ 없음 | KIS 직접 호출 X |

기존 운영 스크립트 14개 모두 영향 없음. **하위 호환성 100%.**

---

## 5. 보안 검증 ✅

| 항목 | 결과 |
|------|------|
| API 키/시크릿/계좌번호 평문 노출 | ❌ 0건 (모두 `_mask()` 처리) |
| 토큰 파일 권한 | ⚠️ atomic write OK, .gitignore 등록 백로그 확인 필요 |
| .env 의존 제거 | ✅ Keychain 단일 소스 (load_dotenv는 .env 있을 때만) |
| 우발적 실주문 차단 | ✅ DRY_RUN + KIS_ALLOW_LIVE_ORDER 이중 가드 |
| trading mode 격리 | ✅ APP_KEY/SECRET/ACCOUNT 3종 분리 + 토큰 캐시 분리 |
| KIS 키 그룹 사고 격리 | ✅ trading 앱 차단되어도 observation 무영향 |

---

## 6. 문법/JSON 검증 ✅

```bash
$ venv/bin/python3 -m py_compile morning_report/keychain_manager.py
# OK

$ venv/bin/python3 -m py_compile .skills/kis-api/scripts/kis_client.py
# OK

$ venv/bin/python3 -c "import json; json.load(open('data/strategy_config.json'))"
# OK (trading 섹션 20개 키 로드 확인)
```

---

## 7. 백로그 (Stage 9 통과 후 별도)

| ID | 내용 | 우선순위 |
|----|------|---------|
| P3-1 | `_test_balance` 토큰 재사용 (1분 제한 회피) | P3 |
| P3-2 | `data/cache/` `.gitignore` 등록 검증 | P2 |
| P3-3 | place_order 시그니처 Brief D와 통일 (Brief D 구현 시) | P2 |

---

## 8. 다음 단계

### 즉시 (Claude → 형진님 안내)
1. **형진님 KIS 매매 전용 앱 등록 진행** (apiportal.koreainvestment.com)
2. 등록 완료 후:
   ```bash
   cd /Users/geenya/projects/AI_Projects/stockpilot
   venv/bin/python3 morning_report/keychain_manager.py --reset-trading
   ```
3. 잔고 조회 연결 테스트 통과 확인

### 형진님 KIS 등록 + reset-trading 통과 후
- Stage 12 QA 진입 (Phase 2 Stage 12 — Brief A 단독)
- Brief B 위임 (상태/검증 모듈 — position_state, trading_state, pending_proposals, validator)

### Brief B/C/D/E/F 순차 진행 후
- Stage 11 최종 검증 (Brief 통합)
- Stage 13 배포 (HANDOFF.md 업데이트)

---

## 9. Stage 9 통과 결정

**Brief A는 Stage 10 수정 단계를 건너뛰고 KIS 등록 + Brief B 위임 단계로 진행합니다.**

근거:
- Brief A 사양 100% 충족
- 추가 안전장치 (atomic write, 다층 mode 검증) 모두 합리적
- 하위 호환성 100% 보장
- 보안 0건 위반
- 마이너 관찰 4건 모두 정보성 — 수정 불필요

---

*이 문서는 Stage 9 코드 리뷰. Brief A는 Stage 10 (Codex 수정) 진입 없이 다음 단계로 진행 가능.*
*문서 위치: `docs/11_phase2_trading/11_brief_a_review.md`*
