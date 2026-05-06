# Codex Brief A — 인프라 (Phase 2 Stage 8)

> **입력 문서:** `docs/11_phase2_trading/05_technical_design.md` 전체
> **담당자:** Codex
> **작업 범위:** Stage 8의 1 / 2 / 3 태스크 (keychain + kis_client + strategy_config)
> **병렬 가능:** 3번은 독립. 1·2는 순차 (1 완료 후 2, 왜냐하면 kis_client가 신규 env var 참조).

---

## 0. 설계 개요 — **KIS 키 그룹 분리**

Phase 2 자동매매는 **관측/발굴용 키와 분리된 독립 KIS APP_KEY 그룹**을 사용한다. 이는:

- **사고 격리** — 실전 매매 앱의 토큰/레이트리밋이 관측용 앱에 영향 주지 않음 + 오작동 범위 제한
- **감사 용이성** — KIS 개발자센터에서 매매 전용 앱을 분리 등록 → 로그·쿼터가 매매 활동에만 집중
- **재난 복구** — 실전 매매 앱이 차단되어도 관측 파이프라인(morning_report, intraday_discovery)은 그대로 동작

### Keychain 키 구조

| 그룹 | 기존 (v2.x, 관측/발굴용) | 신규 (Phase 2, 실전 매매용) |
|------|--------------------------|------------------------------|
| APP_KEY | `KIS_APP_KEY` | `KIS_TRADING_APP_KEY` |
| APP_SECRET | `KIS_APP_SECRET` | `KIS_TRADING_APP_SECRET` |
| 계좌번호 | `KIS_ACCOUNT_NO` | `KIS_TRADING_ACCOUNT_NO` |
| HTS_ID | `KIS_HTS_ID` | (불필요 — 주문에는 HTS_ID 사용 안 함) |

### KISClient 사용 패턴

```python
# 기존 코드 — 그대로 동작 (mode 기본값 "observation")
obs_client = KISClient()
obs_client.get_balance()        # KIS_ACCOUNT_NO
obs_client.get_current_price(...)

# Phase 2 신규 — 트레이딩 전용 인스턴스 별도 생성
trading_client = KISClient(mode="trading")
trading_client.get_orderable_cash()         # KIS_TRADING_ACCOUNT_NO 기준
trading_client.place_order("BUY", ...)       # KIS_TRADING_APP_KEY로 주문
```

- 모드가 다르면 **토큰 캐시 파일도 다름** (`kis_token.json` vs `kis_token_trading.json`)
- `place_order()`는 `mode != "trading"` 인스턴스에서 호출 시 `KISConfigError` 발생

---

## 1. 공통 원칙

1. **기존 패턴 존중** — `keychain_manager.py`의 `_TELEGRAM_KEYS` 패턴, `kis_client.py`의 `_mask()` / `KISConfigError` / `_post()` 패턴 재사용.
2. **하위 호환성 유지** — 기존 관측 스크립트(`morning_report.py`, `intraday_discovery.py`, `closing_report.py`)는 수정하지 말 것. `KISClient()` 기본값(`mode="observation"`)으로 기존 동작 보존.
3. **문법 검사 필수** — 수정 후 `venv/bin/python3 -m py_compile <파일>` 통과 확인.
4. **비밀정보 로그 금지** — 계좌번호·APP_KEY는 로그 출력 시 반드시 `_mask()` 사용.
5. **Trading 그룹 미설정 시 Observation 기능 영향 無** — Trading 키가 비어 있어도 관측 기능은 완벽히 동작해야 함.

---

## Task 1 — `morning_report/keychain_manager.py` 수정

### 목표
실전 매매용 KIS 키 그룹(APP_KEY / APP_SECRET / ACCOUNT_NO) 3종을 Keychain에 저장하고, 저장 시 **연결 테스트(잔고 조회)**로 유효성 검증.

### 변경 사항

**1-1) 트레이딩 그룹 아이템 상수 추가** — `_ITEMS = [...]` 직후에 추가:

```python
# 실전 매매 전용 KIS 키 그룹 (Phase 2).
# 관측용 _ITEMS와 동일한 스키마 (key, 설명, masked) 유지 → _test_balance 재사용.
_TRADING_ITEMS = [
    ("KIS_TRADING_APP_KEY",     "실전 매매용 KIS 앱키      (KIS 개발자센터 → 신규 앱 생성 권장)", True),
    ("KIS_TRADING_APP_SECRET",  "실전 매매용 KIS 앱시크릿  (위 앱의 시크릿)",                   True),
    ("KIS_TRADING_ACCOUNT_NO",  "실전 매매용 소액계좌번호  (형식: 12345678-01)",                False),
]
```

`KIS_TRADING_HTS_ID`는 **추가하지 않는다** (주문 TR `TTTC0802U/TTTC0801U`에는 HTS_ID가 필요 없고, 관측용 `KIS_HTS_ID`를 관심종목 조회에 계속 쓰면 됨).

**1-2) `inject_to_env()` 확장** — 텔레그램 로드 블록 직후에 추가:

```python
# 실전 매매 그룹 로드 (미설정이어도 관측 기능에 영향 없음)
for key, _, _ in _TRADING_ITEMS:
    val = keyring.get_password(_SERVICE, key)
    if val:
        os.environ[key] = val
```

**1-3) `show_status()` 확장** — 텔레그램 섹션 뒤에 trading 그룹 출력 추가:

```python
print()
print("  💼 실전 매매 계좌 (Phase 2 승인형 매매)")
all_trading_ok = True
for key, _, _ in _TRADING_ITEMS:
    val = keyring.get_password(_SERVICE, key)
    if val:
        masked = val[:4] + "*" * min(len(val) - 4, 8) if len(val) > 4 else "****"
        print(f"  ✅ {key:<26} {masked}")
    else:
        print(f"  ⚠️  {key:<26} (미설정)")
        all_trading_ok = False
if not all_trading_ok:
    print("     → 등록: python3 morning_report/keychain_manager.py --reset-trading")
```

**1-4) 트레이딩 그룹 입력·테스트·저장 함수 추가** — `_prompt_test_and_save()` 함수 바로 아래에 추가:

```python
def _prompt_trading_group_and_save():
    """
    실전 매매 전용 KIS 키 그룹(APP_KEY/SECRET/ACCOUNT_NO) 입력 → 잔고 조회 테스트 → 저장.
    연결 테스트는 기존 _test_balance()를 재사용 (동일 스키마 dict 전달).
    최대 MAX_ATTEMPTS회 실패 시 sys.exit(1).
    """
    import getpass

    print()
    print("=" * 55)
    print("💼 실전 매매 전용 KIS 키 그룹 등록")
    print("=" * 55)
    print("Phase 2 자동매매는 이 키 그룹으로만 주문됩니다.")
    print("관측/발굴용(KIS_APP_KEY 등)과 **완전히 독립**된 앱 키입니다.")
    print()
    print("준비물:")
    print("  1. KIS 개발자센터(apiportal.koreainvestment.com)에서 새 앱 생성")
    print("  2. 해당 앱에 소액계좌 연결")
    print("  3. 발급된 APP_KEY / APP_SECRET")
    print("  4. 소액계좌 번호 (12345678-01 형식)")
    print()

    candidate = {}

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if attempt > 1:
            print()
            print(f"─── 재입력 ({attempt}/{MAX_ATTEMPTS}) ───────────────────────────")

        for key, desc, masked in _TRADING_ITEMS:
            current = candidate.get(key) or keyring.get_password(_SERVICE, key)
            if current:
                masked_current = current[:4] + "*" * (len(current) - 4) if len(current) > 4 else "****"
                hint = f" (현재값: {masked_current}, 엔터 시 유지)"
            else:
                hint = ""

            while True:
                prompt = f"  {desc}{hint}\n  → {key}: "
                val = (getpass.getpass(prompt) if masked else input(prompt).strip())
                if not val and current:
                    val = current
                    print("    (기존값 유지)")
                    break
                if val:
                    if key == "KIS_TRADING_ACCOUNT_NO" and "-" not in val:
                        print("    ⚠️  형식 오류. '12345678-01' 처럼 하이픈을 포함해야 합니다.")
                        continue
                    break
                print("    ⚠️  값을 입력해주세요.")
            candidate[key] = val

        # ── 연결 테스트: _test_balance()는 KIS_APP_KEY/SECRET/ACCOUNT_NO 키로 dict를 받음.
        #   → trading 그룹의 값을 해당 키로 "임시 리네임"해서 전달.
        test_creds = {
            "KIS_APP_KEY":     candidate["KIS_TRADING_APP_KEY"],
            "KIS_APP_SECRET":  candidate["KIS_TRADING_APP_SECRET"],
            "KIS_ACCOUNT_NO":  candidate["KIS_TRADING_ACCOUNT_NO"],
        }
        print()
        print(f"  [테스트 {attempt}/{MAX_ATTEMPTS}] 소액계좌 연결 확인 중...")
        ok, err, _token = _test_balance(test_creds)
        if ok:
            print("  ✅ 소액계좌 잔고 조회 성공")
            for key, _, _ in _TRADING_ITEMS:
                keyring.set_password(_SERVICE, key, candidate[key])
            print()
            print("=" * 55)
            print("✅ 실전 매매 키 그룹 저장 완료")
            print("=" * 55)
            print()
            return

        print(f"  ❌ 연결 실패: {err}")
        remaining = MAX_ATTEMPTS - attempt
        if remaining == 0:
            print()
            print("=" * 55)
            print("❌ 실전 매매 키 그룹 등록 실패 — 프로그램 종료")
            print("=" * 55)
            print("  확인 방법:")
            print("  1. KIS 개발자센터에서 해당 앱이 활성 상태인지 확인")
            print("  2. 앱에 해당 소액계좌가 연결되어 있는지 확인")
            print("  3. 앱키 / 앱시크릿 오타 없는지 확인")
            print()
            sys.exit(1)
        print(f"  남은 시도: {remaining}회")
```

**1-5) CLI 진입점 확장** — `if __name__ == "__main__":` 블록 내부를 다음과 같이 변경:

```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KIS API 인증정보 관리 (Keychain)")
    parser.add_argument(
        "--reset", nargs="*", metavar="KEY",
        help="관측용 항목 재입력 (지정 없으면 전체). 예: --reset KIS_APP_KEY"
    )
    parser.add_argument(
        "--reset-trading", action="store_true",
        help="실전 매매용 KIS 키 그룹(APP_KEY/SECRET/ACCOUNT_NO) 전체 재입력"
    )
    args = parser.parse_args()

    if args.reset_trading:
        _prompt_trading_group_and_save()
        show_status()
    elif args.reset is not None:
        reset_keys = args.reset if args.reset else [k for k, _, _ in _ITEMS]
        get_secrets(reset_keys=reset_keys)
        show_status()
    else:
        show_status()
```

**1-6) 모듈 docstring 업데이트** — 파일 최상단 주석:

```
저장 항목 (관측/발굴용 — 기존):
  KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCOUNT_NO, KIS_HTS_ID
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

저장 항목 (실전 매매용 — Phase 2):
  KIS_TRADING_APP_KEY, KIS_TRADING_APP_SECRET, KIS_TRADING_ACCOUNT_NO

사용법:
  python3 keychain_manager.py                      # 저장 상태 확인
  python3 keychain_manager.py --reset              # 관측용 전체 재입력
  python3 keychain_manager.py --reset KIS_APP_KEY  # 관측용 일부 재입력
  python3 keychain_manager.py --reset-trading      # 실전 매매 키 그룹 재입력 (3개 일괄)
```

### 수용 기준

- [ ] `venv/bin/python3 -m py_compile morning_report/keychain_manager.py` 통과
- [ ] `venv/bin/python3 morning_report/keychain_manager.py` 실행 시 `💼 실전 매매 계좌` 섹션 3줄 표시 (미설정 상태)
- [ ] `--reset-trading` 실행 → APP_KEY / APP_SECRET / ACCOUNT_NO 순서로 입력 요청
- [ ] 하이픈 없는 계좌번호 입력 시 재입력 요청
- [ ] 올바른 값 입력 시 잔고 조회 테스트 실행 → 성공 시 Keychain 저장 + status 재표시
- [ ] 잘못된 APP_KEY 입력 시 `"토큰 발급 실패"` 에러 + 재시도 (최대 3회)
- [ ] **기존 `--reset` 플로우는 관측용 전용으로 유지** (트레이딩 키는 건드리지 않음)
- [ ] **기존 스크립트 무영향 확인:** `venv/bin/python3 morning_report/morning_report.py --dry-run` 정상 동작

---

## Task 2 — `.skills/kis-api/scripts/kis_client.py` 수정

### 목표
1. `KISClient(mode: str = "observation")` — mode 파라미터 추가. `"observation"` / `"trading"` 2개 값 지원.
2. 모드별로 **다른 env var 그룹** + **다른 토큰 캐시 파일** 사용.
3. `DRY_RUN=1` 환경변수 시 `place_order`가 실제 HTTP 호출 없이 mock 응답 반환.
4. `place_order` / `build_order_payload`는 `mode="trading"` 에서만 호출 가능 (다른 모드 시 에러).

### 변경 사항

**2-1) 모듈 레벨 상수 변경** — 기존 `TOKEN_CACHE_PATH` 단일 상수를 모드별로 분리:

```python
# 기존: TOKEN_CACHE_PATH = PROJECT_ROOT / "data" / "cache" / "kis_token.json"
# 삭제하고 아래로 교체:

TOKEN_CACHE_DIR = PROJECT_ROOT / "data" / "cache"

def _token_cache_path(mode: str) -> Path:
    """모드별 토큰 캐시 파일 경로.
    - observation: data/cache/kis_token.json (기존 호환 — 파일명 유지)
    - trading:     data/cache/kis_token_trading.json
    """
    if mode == "observation":
        return TOKEN_CACHE_DIR / "kis_token.json"
    if mode == "trading":
        return TOKEN_CACHE_DIR / "kis_token_trading.json"
    raise ValueError(f"unknown KISClient mode: {mode}")
```

기존 코드 내 `TOKEN_CACHE_PATH` 참조들은 모두 `self._token_cache_path` (인스턴스 속성, __init__에서 설정) 로 교체.

**2-2) `KISClient.__init__` 재작성**:

```python
class KISClient:
    def __init__(self, mode: str = "observation") -> None:
        if mode not in ("observation", "trading"):
            raise ValueError(f"KISClient mode must be 'observation' or 'trading', got: {mode}")
        self.mode = mode

        # 모드별 env var prefix
        if mode == "observation":
            key_envs = ("KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ACCOUNT_NO")
        else:  # trading
            key_envs = ("KIS_TRADING_APP_KEY", "KIS_TRADING_APP_SECRET", "KIS_TRADING_ACCOUNT_NO")

        self.app_key    = os.getenv(key_envs[0])
        self.app_secret = os.getenv(key_envs[1])
        self.account_no = os.getenv(key_envs[2], "")

        # HTS_ID는 observation 모드에서만 사용 (관심종목 조회 전용)
        self.hts_id = (
            os.getenv("KIS_HTS_ID", "").split("#")[0].strip() if mode == "observation" else ""
        )

        missing = [k for k, v in zip(key_envs, (self.app_key, self.app_secret, self.account_no)) if not v]
        if missing:
            raise KISConfigError(
                f"[mode={mode}] 환경변수 누락: {', '.join(missing)}. "
                f"{'keychain_manager.py --reset' if mode == 'observation' else 'keychain_manager.py --reset-trading'} 로 등록하세요."
            )
        if "-" not in self.account_no:
            raise KISConfigError(
                f"[mode={mode}] 계좌번호 형식 오류. '12345678-01' 형태여야 합니다."
            )
        self.cano, self.acnt_prdt_cd = self.account_no.split("-", 1)
        self.base_url = REAL_BASE_URL

        # 모드별 토큰 캐시 경로 (인스턴스 속성으로)
        self._token_cache_path = _token_cache_path(mode)
        self._token_cache_path.parent.mkdir(parents=True, exist_ok=True)
        RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)

        self._min_interval = 0.06
        self._last_call = 0.0
```

**2-3) 기존 `TOKEN_CACHE_PATH` 전역 참조 제거** — `_load_cached_token()`, `_save_token()` 안의 `TOKEN_CACHE_PATH` → `self._token_cache_path` 로 모두 치환. 파일 내 `TOKEN_CACHE_PATH` 문자열이 사라져야 함.

**2-4) `build_order_payload` 수정** — trading 전용 가드 추가:

```python
def build_order_payload(
    self, side: str, code: str, qty: int, price: int | None = None
) -> dict:
    if self.mode != "trading":
        raise KISConfigError(
            f"주문은 mode='trading' 인스턴스에서만 가능합니다. 현재 mode={self.mode}. "
            f"KISClient(mode='trading') 으로 생성하세요."
        )
    side = side.upper()
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")
    if qty <= 0:
        raise ValueError("qty must be positive")

    tr_id = "TTTC0802U" if side == "BUY" else "TTTC0801U"
    ord_dvsn = "01" if price is None else "00"
    body = {
        "CANO": self.cano,                # trading 계좌 (mode="trading" 시 KIS_TRADING_ACCOUNT_NO 파싱값)
        "ACNT_PRDT_CD": self.acnt_prdt_cd,
        "PDNO": code,
        "ORD_DVSN": ord_dvsn,
        "ORD_QTY": str(qty),
        "ORD_UNPR": "0" if price is None else str(int(price)),
    }
    return {
        "endpoint": "/uapi/domestic-stock/v1/trading/order-cash",
        "method": "POST",
        "tr_id": tr_id,
        "body": body,
        "human_summary": (
            f"{'매수' if side == 'BUY' else '매도'} | 종목 {code} | "
            f"수량 {qty}주 | "
            f"{'시장가' if price is None else f'지정가 {price:,}원'} | "
            f"계좌 {_mask(self.account_no)}"
        ),
    }
```

**2-5) `place_order`에 DRY_RUN 분기 + mode 가드 추가**:

```python
def place_order(self, side: str, code: str, qty: int, price: int | None = None) -> dict:
    """
    실제 주문 전송. 안전장치:
      1. self.mode == "trading"  (build_order_payload에서 검증)
      2. DRY_RUN=1 이면 mock 응답 반환 (payload validation은 실행)
      3. KIS_ALLOW_LIVE_ORDER=1 환경변수 필수
    """
    # 1. mode 및 payload validation (실제 HTTP 전에 먼저 수행 → DRY_RUN에서도 잘못된 호출 탐지)
    draft = self.build_order_payload(side, code, qty, price)

    # 2. DRY_RUN 분기
    if os.getenv("DRY_RUN") == "1":
        import uuid
        return {
            "rt_cd": "0",
            "msg_cd": "DRY_RUN",
            "msg1": f"DRY_RUN {draft['human_summary']}",
            "output": {
                "KRX_FWDG_ORD_ORGNO": "00000",
                "ODNO": f"DRY{uuid.uuid4().hex[:10].upper()}",
                "ORD_TMD": datetime.now().strftime("%H%M%S"),
            },
        }

    # 3. 실주문 가드
    if os.getenv("KIS_ALLOW_LIVE_ORDER") != "1":
        raise RuntimeError(
            "실주문 전송이 차단됨. 환경변수 KIS_ALLOW_LIVE_ORDER=1 을 명시적으로 설정해야 함. "
            "현재는 build_order_payload()로 초안만 생성 가능."
        )
    return self._post(draft["endpoint"], draft["tr_id"], draft["body"])
```

**2-6) `get_balance` / `get_orderable_cash` 는 수정 불필요** — 이미 `self.cano` / `self.acnt_prdt_cd`를 사용하므로 mode에 맞는 계좌로 자동 동작.

**단, 호출자가 의도를 명확히 하도록 트레이딩 전용 읽기 헬퍼 추가 권장:**

```python
def assert_trading_mode(self):
    """트레이딩 전용 메서드를 호출하기 전 mode 검증 (읽기 호출에도 명시적 guard)."""
    if self.mode != "trading":
        raise KISConfigError(f"트레이딩 모드 전용 호출. 현재 mode={self.mode}")
```

position_monitor에서 `client.assert_trading_mode()` 호출 후 `client.get_orderable_cash()` 사용하는 패턴. **assert_trading_mode는 선택적 추가** — Brief B 설계 시 재확인.

### 수용 기준

- [ ] `venv/bin/python3 -m py_compile .skills/kis-api/scripts/kis_client.py` 통과
- [ ] `KISClient()` 기본값으로 생성 → mode="observation", 기존 동작 (관측용 env var 사용) 그대로
- [ ] `KISClient(mode="observation")` 명시 생성 → 위와 동일
- [ ] `KISClient(mode="trading")` 생성 시 `KIS_TRADING_*` env var 미설정이면 `KISConfigError("[mode=trading] 환경변수 누락")`
- [ ] `KISClient(mode="invalid")` → `ValueError`
- [ ] observation 인스턴스에서 `place_order(...)` 호출 → `KISConfigError("주문은 mode='trading' 인스턴스에서만 가능")`
- [ ] trading 인스턴스 + `DRY_RUN=1` + `KIS_ALLOW_LIVE_ORDER` 미설정:
  - `place_order("BUY", "005930", 1)` → `{"rt_cd":"0","msg_cd":"DRY_RUN","output":{"ODNO":"DRY..."}}` 반환
- [ ] trading 인스턴스 + `DRY_RUN` 미설정 + `KIS_ALLOW_LIVE_ORDER` 미설정 → `RuntimeError`
- [ ] 토큰 캐시 파일 분리 확인:
  - observation 인스턴스로 토큰 요청 → `data/cache/kis_token.json` 생성
  - trading 인스턴스로 토큰 요청 → `data/cache/kis_token_trading.json` 생성 (두 파일 독립)
- [ ] **기존 기능 무영향:** `morning_report.py --dry-run`, `intraday_discovery.py --round 2 --dry-run` 모두 정상

### 단위 테스트 예시 (`tests/test_kis_client_phase2.py`)

```python
import os
import pytest
from pathlib import Path

# observation 기본값
def test_default_mode_is_observation(monkeypatch, mock_kis_env_observation):
    from kis_client import KISClient
    c = KISClient()
    assert c.mode == "observation"

# trading 인스턴스에서 주문 경로 가드
def test_trading_mode_requires_trading_env(monkeypatch):
    monkeypatch.delenv("KIS_TRADING_APP_KEY", raising=False)
    from kis_client import KISClient, KISConfigError
    with pytest.raises(KISConfigError, match="\\[mode=trading\\]"):
        KISClient(mode="trading")

def test_observation_cannot_place_order(monkeypatch, mock_kis_env_observation):
    from kis_client import KISClient, KISConfigError
    c = KISClient()  # observation
    with pytest.raises(KISConfigError, match="trading"):
        c.build_order_payload("BUY", "005930", 1)

def test_dry_run_returns_mock(monkeypatch, mock_kis_env_trading):
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.delenv("KIS_ALLOW_LIVE_ORDER", raising=False)
    from kis_client import KISClient
    c = KISClient(mode="trading")
    resp = c.place_order("BUY", "005930", 1)
    assert resp["rt_cd"] == "0"
    assert resp["output"]["ODNO"].startswith("DRY")

def test_live_guard_still_works(monkeypatch, mock_kis_env_trading):
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.delenv("KIS_ALLOW_LIVE_ORDER", raising=False)
    from kis_client import KISClient
    c = KISClient(mode="trading")
    with pytest.raises(RuntimeError, match="KIS_ALLOW_LIVE_ORDER"):
        c.place_order("BUY", "005930", 1)

def test_token_cache_paths_are_separate(mock_kis_env_observation, mock_kis_env_trading):
    from kis_client import KISClient
    obs = KISClient(mode="observation")
    trd = KISClient(mode="trading")
    assert obs._token_cache_path != trd._token_cache_path
    assert "trading" in trd._token_cache_path.name
```

`mock_kis_env_observation` / `mock_kis_env_trading` fixture는 각 env var 세트를 `monkeypatch.setenv`로 설정하는 pytest fixture로 작성.

---

## Task 3 — `data/strategy_config.json` 수정

### 목표
Phase 2 매매 튜너블 섹션을 추가. 기존 블록(`entry` / `exit` / `risk_reward` / `notes`)은 수정하지 않음.

### 변경 사항

**3-1) 버전 번호 갱신**:
```json
"_version": "2.0",
"_updated": "2026-04-23",
```

**3-2) `trading` 섹션 신설** — `risk_reward` 블록 뒤, `notes` 블록 앞에 삽입:

```json
  "trading": {
    "_comment": "Phase 2 승인형 매수 + 자동 매도 튜너블. position_monitor/validator가 참조.",
    "account_env_prefix": "KIS_TRADING",
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
    "max_daily_loss_mode": "auto_orderable_cash",
    "max_daily_loss_krw_override": null,
    "max_buy_trades_per_day": 10,
    "trial_mode_default_max_buys": 1,
    "market_close_sell_first_hhmm": "15:15",
    "market_close_sell_retry_hhmm": "15:25",
    "telegram_send_rate_per_sec": 1
  },
```

주의: `account_env_prefix`는 정보성 필드 (`KIS_TRADING_*` prefix를 설정 파일에서도 명시). 실제 값 읽기는 KISClient가 직접 env var에서.

**3-3) 기존 `notes` 배열에 Phase 2 안내 항목 추가**:
```json
  "notes": [
    "수치(%)는 며칠 테스트 후 조정 예정",
    "진입 조건 3개 모두 충족 시에만 매수",
    "매도 조건은 우선순위 순서대로 체크 (① → ④)",
    "Phase 2 trading 섹션: max_daily_loss_mode='auto_orderable_cash'는 자정마다 KIS_TRADING_ACCOUNT_NO의 주문가능금액 스냅샷을 손실한도로 사용",
    "Phase 2 주문은 KIS_TRADING_APP_KEY 그룹 전용 (관측용 KIS_APP_KEY와 완전 분리)"
  ]
```

### 수용 기준

- [ ] `venv/bin/python3 -c 'import json; json.load(open("data/strategy_config.json"))'` 통과
- [ ] `entry` / `exit` / `risk_reward` 블록 값 변경 없음 (git diff 확인)
- [ ] 스모크 테스트:
  ```python
  import json
  cfg = json.load(open("data/strategy_config.json"))
  assert cfg["_version"] == "2.0"
  assert cfg["trading"]["account_env_prefix"] == "KIS_TRADING"
  assert abs(sum(cfg["trading"]["split_weights"]) - 1.0) < 1e-9
  assert cfg["trading"]["max_daily_loss_mode"] in ("auto_orderable_cash", "fixed_krw")
  assert cfg["trading"]["max_buy_trades_per_day"] > 0
  ```

---

## 4. 최종 체크리스트 (Codex 제출 전)

- [ ] 세 파일 모두 `py_compile` 통과 (또는 JSON 유효)
- [ ] 기존 regression: `venv/bin/python3 morning_report/morning_report.py --dry-run` 성공
- [ ] 기존 regression: `venv/bin/python3 morning_report/intraday_discovery.py --round 2 --dry-run` 성공
- [ ] 신규 unit test 5건 이상 (Task 2) 통과
- [ ] 각 파일의 git diff 를 리뷰어(Claude)에게 전달
- [ ] 작업 요약(변경 파일 목록 + 핵심 차이 3줄) 제출

## 5. 비작업 (Out of Scope)

이 Brief A에서는 **하지 않음**:

- `position_monitor.py` 신규 생성 (Brief C)
- `validator.py` 신규 생성 (Brief B)
- `trading_state.json` / `position_state.json` / `pending_proposals.json` 파일 생성 (Brief B)
- `orchestrator.py` 신규 명령어 추가 (Brief D)
- `intraday_discovery.py` 훅 추가 (Brief D)
- launchd plist 작성 (Brief E)
- 통합 dry-run 시나리오 (Brief F)
- KIS 개발자센터에서 실제 신규 앱 생성 (형진님 수동 작업)

## 6. 형진님 사전 작업 (Codex 구현 전)

Brief A 구현은 **형진님의 다음 작업과 병렬 진행 가능**:

1. KIS 개발자센터(apiportal.koreainvestment.com) 로그인
2. **내 앱 → 앱 신규 등록** (앱 이름: 예 `stockpilot-trading`)
3. 새 앱에 **소액계좌 연결**
4. APP_KEY / APP_SECRET 복사 → 안전한 곳에 임시 보관
5. Codex의 Brief A 구현 완료 후 `--reset-trading` 명령으로 등록

---

*stockpilot Phase 2 Stage 8 — Codex Brief A (v2: KIS 키 그룹 분리 반영)*
