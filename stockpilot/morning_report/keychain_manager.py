"""
keychain_manager.py — macOS Keychain 기반 민감정보 관리

저장 항목:
  KIS_APP_KEY      KIS API 앱키
  KIS_APP_SECRET   KIS API 앱시크릿
  KIS_ACCOUNT_NO   계좌번호 (12345678-01 형식)
  KIS_HTS_ID       MTS/홈페이지 로그인 ID

사용법:
  from keychain_manager import inject_to_env
  inject_to_env()   # Keychain에서 로드 → os.environ 주입. 없으면 입력 받아 저장.

CLI로 직접 실행 시:
  python3 keychain_manager.py          # 현재 저장값 확인
  python3 keychain_manager.py --reset  # 전체 재입력 + 연결 테스트
  python3 keychain_manager.py --reset KIS_APP_KEY   # 특정 항목만 재입력

초기 설정 흐름:
  1. 앱키 → 앱시크릿 → 계좌번호 → 로그인 ID 순서로 입력
  2. [테스트 1] 잔고 조회 → 앱키 / 앱시크릿 / 계좌번호 검증
  3. [테스트 2] 관심종목 그룹 조회 → 로그인 ID 검증
  4. 모두 통과 시 Keychain에 저장
  5. 3회 실패 시 어느 항목이 잘못됐는지 안내 후 프로그램 종료
"""

import argparse
import os
import sys
import time
from pathlib import Path

try:
    import keyring
except ImportError:
    print("[오류] keyring 패키지가 없습니다. venv/bin/pip install keyring 을 실행하세요.", file=sys.stderr)
    sys.exit(1)

# Keychain 서비스명 (macOS 키체인 앱에서 이 이름으로 검색 가능)
_SERVICE = "AI주식매매"

# 저장할 항목 정의: (키 이름, 설명, 입력 마스킹 여부)
_ITEMS = [
    ("KIS_APP_KEY",    "KIS API 앱키         (KIS 개발자센터 → 앱 관리)", True),
    ("KIS_APP_SECRET", "KIS API 앱시크릿     (KIS 개발자센터 → 앱 관리)", True),
    ("KIS_ACCOUNT_NO", "계좌번호             (형식: 12345678-01)",         False),
    ("KIS_HTS_ID",     "로그인 ID            (MTS/홈페이지 로그인 ID)",    False),
]

MAX_ATTEMPTS = 3  # 연결 테스트 최대 재시도 횟수


# ── 공개 API ──────────────────────────────────────────────────────────────────

def get_secrets(reset_keys: list[str] | None = None) -> dict[str, str]:
    """
    Keychain에서 민감정보를 로드.
    없거나 reset_keys에 포함된 항목은 입력 받아 연결 테스트 후 저장.
    반환: {KIS_APP_KEY: ..., KIS_APP_SECRET: ..., KIS_ACCOUNT_NO: ..., KIS_HTS_ID: ...}
    """
    secrets = {}
    need_input = []

    for key, desc, masked in _ITEMS:
        val = keyring.get_password(_SERVICE, key)
        if val and (reset_keys is None or key not in reset_keys):
            secrets[key] = val
        else:
            need_input.append((key, desc, masked))

    if need_input:
        _prompt_test_and_save(need_input, secrets)

    return secrets


def inject_to_env(reset_keys: list[str] | None = None):
    """
    Keychain에서 로드하여 현재 프로세스 환경변수에 주입.
    모든 스크립트의 진입점에서 호출하면 됨.
    """
    secrets = get_secrets(reset_keys=reset_keys)
    for k, v in secrets.items():
        os.environ[k] = v


def show_status():
    """현재 Keychain 저장 상태 출력."""
    print()
    print("🔐 Keychain 저장 상태 — 서비스명:", _SERVICE)
    print("-" * 55)
    all_ok = True
    for key, desc, _ in _ITEMS:
        val = keyring.get_password(_SERVICE, key)
        if val:
            masked = val[:4] + "*" * min(len(val) - 4, 8) if len(val) > 4 else "****"
            print(f"  ✅ {key:<20} {masked}")
        else:
            print(f"  ❌ {key:<20} (미설정)")
            all_ok = False
    print("-" * 55)
    if all_ok:
        print("  모든 항목이 설정되어 있습니다.")
    else:
        print("  ⚠️  미설정 항목이 있습니다. --reset 으로 입력하세요.")
    print()


# ── 내부 함수 ─────────────────────────────────────────────────────────────────

def _prompt_test_and_save(items: list, secrets: dict):
    """
    입력 → 연결 테스트 → 성공 시 Keychain 저장.
    최대 MAX_ATTEMPTS회 실패 시 안내 후 sys.exit(1).
    실패 단계에 따라 재입력 범위를 좁힘:
      - 1단계(앱키/시크릿/계좌번호) 실패 → 전체 재입력
      - 2단계(ID) 실패 → ID만 재입력
    """
    import getpass

    print()
    print("=" * 55)
    print("🔐 한국투자증권 API 인증정보 설정")
    print("=" * 55)
    print("입력한 정보는 연결 테스트 후 macOS 키체인에 저장됩니다.")
    print(".env 파일에는 저장되지 않습니다.")
    print()

    # 입력이 필요한 항목 키 목록 (전체)
    input_keys = {key for key, _, _ in items}

    # 처음에는 전달받은 items 전체를 입력 대상으로 설정
    retry_keys: set[str] | None = None  # None = 전체, set = 해당 항목만

    candidate = dict(secrets)  # 기존 Keychain 값 기반으로 시작
    ok1 = False
    saved_token: str | None = None  # P2: ok1 통과 후 토큰 루프 전체에서 보존

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if attempt > 1:
            print()
            print(f"─── 재입력 ({attempt}/{MAX_ATTEMPTS}) ───────────────────────────")

        # ── 이번 시도에서 입력받을 항목 결정 ──────────────────────────────────
        if retry_keys is None:
            # 전체 입력 (첫 시도 or 1단계 실패)
            items_to_ask = items
        else:
            # ID만 재입력 (2단계 실패)
            items_to_ask = [(k, d, m) for k, d, m in items if k in retry_keys]

        # ── 각 항목 입력 ──────────────────────────────────────────────────────
        for key, desc, masked in items_to_ask:
            current = candidate.get(key) or keyring.get_password(_SERVICE, key)
            if current:
                masked_current = current[:4] + "*" * (len(current) - 4) if len(current) > 4 else "****"
                hint = f" (현재값: {masked_current}, 엔터 시 유지)"
            else:
                hint = ""

            while True:
                prompt = f"  {desc}{hint}\n  → {key}: "
                if masked:
                    val = getpass.getpass(prompt)
                else:
                    val = input(prompt).strip()

                if not val and current:
                    val = current
                    print("    (기존값 유지)")
                    break
                elif val:
                    if key == "KIS_ACCOUNT_NO" and "-" not in val:
                        print("    ⚠️  형식 오류. '12345678-01' 처럼 하이픈(-)을 포함해야 합니다.")
                        continue
                    break
                else:
                    print("    ⚠️  값을 입력해주세요.")

            candidate[key] = val

        # ── 연결 테스트 ───────────────────────────────────────────────────────
        print()
        print(f"  [테스트 {attempt}/{MAX_ATTEMPTS}] KIS API 연결 확인 중...")

        # 1단계는 이전에 통과했으면 다시 하지 않음 (P2: 토큰도 보존)
        if not ok1:
            ok1, err1, saved_token = _test_balance(candidate)

        ok2, err2 = (False, None)

        if ok1:
            print("  ✅ [1/2] 앱키 / 앱시크릿 / 계좌번호 확인")
            ok2, err2 = _test_watchlist(candidate, saved_token or "")
            if ok2:
                print("  ✅ [2/2] 로그인 ID 확인")
            else:
                print(f"  ❌ [2/2] 로그인 ID 오류: {err2}")
        else:
            print(f"  ❌ [1/2] 앱키 / 앱시크릿 / 계좌번호 오류: {err1}")

        if ok1 and ok2:
            # ── 성공 → Keychain 저장 ─────────────────────────────────────────
            print()
            for key, _, _ in items:
                keyring.set_password(_SERVICE, key, candidate[key])
            secrets.update(candidate)
            print("=" * 55)
            print("✅ 연결 테스트 통과! 인증정보를 Keychain에 저장했습니다.")
            print("=" * 55)
            print()
            return

        # ── 실패 안내 및 다음 재입력 범위 결정 ───────────────────────────────
        remaining = MAX_ATTEMPTS - attempt
        if remaining > 0:
            _print_retry_hint(ok1, ok2, input_keys)
            print(f"  남은 시도: {remaining}회")
            # 2단계만 실패 → 다음엔 ID만 재입력
            if ok1 and not ok2:
                retry_keys = {"KIS_HTS_ID"} & input_keys
            else:
                # 1단계 실패 → 전체 재입력, ok1 리셋
                retry_keys = None
                ok1 = False
        else:
            # 3회 모두 실패 → 원인 안내 후 종료
            print()
            print("=" * 55)
            print("❌ 인증 실패 — 프로그램을 종료합니다")
            print("=" * 55)
            _print_failure_guide(ok1, ok2)
            print()
            print("  설정 후 다시 실행하세요:")
            print("    python3 morning_report/keychain_manager.py --reset")
            print("=" * 55)
            sys.exit(1)


def _test_balance(creds: dict) -> tuple[bool, str | None, str | None]:
    """
    잔고 조회로 앱키 / 앱시크릿 / 계좌번호 검증.
    토큰 캐시를 우회하기 위해 직접 HTTP 요청.
    반환: (성공여부, 오류메시지|None, 발급된토큰|None)
    """
    try:
        import requests as req

        account_no = creds.get("KIS_ACCOUNT_NO", "")
        if "-" not in account_no:
            return False, "계좌번호 형식 오류 (12345678-01 형태여야 함)", None
        cano, acnt_cd = account_no.split("-", 1)

        # 토큰 발급 (테스트용이므로 캐시 무시하고 직접 발급)
        token_url = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
        token_resp = req.post(token_url, json={
            "grant_type": "client_credentials",
            "appkey":     creds.get("KIS_APP_KEY", ""),
            "appsecret":  creds.get("KIS_APP_SECRET", ""),
        }, timeout=10)
        token_data = token_resp.json()
        if "access_token" not in token_data:
            return False, f"토큰 발급 실패 — 앱키 또는 앱시크릿을 확인하세요 ({token_data.get('msg1', '')})", None
        token = token_data["access_token"]

        # 잔고 조회
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey":    creds.get("KIS_APP_KEY", ""),
            "appsecret": creds.get("KIS_APP_SECRET", ""),
            "tr_id":     "TTTC8434R",
            "custtype":  "P",
        }
        params = {
            "CANO": cano, "ACNT_PRDT_CD": acnt_cd,
            "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02",
            "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
        }
        resp = req.get(
            "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/trading/inquire-balance",
            headers=headers, params=params, timeout=10,
        )
        data = resp.json()
        if data.get("rt_cd") != "0":
            msg = data.get("msg1", "")
            return False, f"계좌번호를 확인하세요 ({data.get('msg_cd')} {msg})", None
        return True, None, token

    except Exception as e:
        return False, str(e), None


def _test_watchlist(creds: dict, token: str) -> tuple[bool, str | None]:
    """
    관심종목 그룹 조회로 로그인 ID 검증.
    token: _test_balance에서 발급한 토큰을 재사용 (중복 발급 방지)
    반환: (성공여부, 오류메시지|None)
    """
    try:
        import requests as req

        # 작은따옴표 등 불필요한 문자 제거
        hts_id = creds.get("KIS_HTS_ID", "").strip().strip("'\"")
        if not hts_id:
            return False, "로그인 ID가 비어있습니다"

        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey":    creds.get("KIS_APP_KEY", ""),
            "appsecret": creds.get("KIS_APP_SECRET", ""),
            "tr_id":     "HHKCM113004C7",
            "custtype":  "P",
        }
        params = {
            "TYPE":             "1",
            "FID_ETC_CLS_CODE": "00",
            "USER_ID":          hts_id,
        }
        resp = req.get(
            "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/intstock-grouplist",
            headers=headers, params=params, timeout=10,
        )
        data = resp.json()
        if data.get("rt_cd") != "0":
            msg = data.get("msg1", "")
            return False, f"로그인 ID를 확인하세요 (입력값: '{hts_id}', {data.get('msg_cd')} {msg})"
        return True, None

    except Exception as e:
        return False, str(e)


def _print_retry_hint(ok1: bool, ok2: bool, input_keys: set):
    """재입력 시 어떤 항목을 집중 확인할지 안내."""
    print()
    if not ok1:
        print("  💡 힌트: 앱키 / 앱시크릿 / 계좌번호를 다시 확인하세요.")
        if "KIS_APP_KEY" in input_keys:
            print("     - 앱키: KIS 개발자센터 → 내 앱 → 앱키 복사")
        if "KIS_APP_SECRET" in input_keys:
            print("     - 앱시크릿: KIS 개발자센터 → 내 앱 → 시크릿 복사")
        if "KIS_ACCOUNT_NO" in input_keys:
            print("     - 계좌번호: HTS/MTS에서 확인 (형식: 12345678-01)")
    elif not ok2:
        print("  💡 힌트: 로그인 ID만 다시 확인하세요.")
        print("     - MTS(앱) 또는 홈페이지 로그인 시 사용하는 ID")
        print("     - 카카오/네이버 소셜 로그인 사용 시 해당 계정 이메일")
    print()


def _print_failure_guide(ok1: bool, ok2: bool):
    """3회 실패 시 최종 안내."""
    print()
    if not ok1:
        print("  원인: 앱키 / 앱시크릿 / 계좌번호 인증 실패")
        print()
        print("  확인 방법:")
        print("  1. https://apiportal.koreainvestment.com 접속")
        print("  2. 내 앱 → 앱키(AppKey) / 앱시크릿(AppSecret) 재확인")
        print("  3. 계좌번호: MTS 앱 → 계좌 선택 → 전체 번호 확인 (12345678-01 형식)")
    elif not ok2:
        print("  원인: 로그인 ID 인증 실패")
        print()
        print("  확인 방법:")
        print("  1. MTS(앱) 또는 https://www.truefriend.com 로그인 시 사용하는 ID")
        print("  2. 카카오/네이버 소셜 로그인 사용 중이라면 해당 계정 이메일 주소")
        print("  3. ID 확인: MTS 앱 → 설정 → 내 정보")


# ── CLI 진입점 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KIS API 인증정보 관리 (Keychain)")
    parser.add_argument(
        "--reset", nargs="*", metavar="KEY",
        help="재입력할 항목 (지정 없으면 전체 재입력). 예: --reset KIS_APP_KEY"
    )
    args = parser.parse_args()

    if args.reset is not None:
        reset_keys = args.reset if args.reset else [k for k, _, _ in _ITEMS]
        get_secrets(reset_keys=reset_keys)
        show_status()
    else:
        show_status()
