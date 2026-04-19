"""
_kakao_sender.py — 카카오톡 "나에게 보내기" 메시지 전송 모듈

카카오 디벨로퍼스 REST API 사용 (무료, 서버 불필요)
액세스 토큰은 macOS Keychain에 저장 (P1 보안 개선)
리프레시 토큰도 Keychain 우선, .env는 폴백용

설정 필요 항목 (.env 또는 Keychain):
  KAKAO_REST_API_KEY=    카카오 앱의 REST API 키
  KAKAO_CLIENT_SECRET=   카카오 앱 시크릿
  KAKAO_REFRESH_TOKEN=   최초 1회 발급 후 자동 갱신 (Keychain에 저장됨)
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

# 프로젝트 루트 기준
_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / ".env")

_KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
_KAKAO_SEND_URL  = "https://kapi.kakao.com/v2/api/talk/memo/default/send"

# Keychain 서비스명 / 키 이름
_KEYCHAIN_SERVICE      = "AI주식매매"
_KC_ACCESS_TOKEN       = "KAKAO_ACCESS_TOKEN"
_KC_ACCESS_EXPIRES_AT  = "KAKAO_ACCESS_EXPIRES_AT"
_KC_REFRESH_TOKEN      = "KAKAO_REFRESH_TOKEN"


# ── Keychain 헬퍼 ─────────────────────────────────────────────────────────────

def _kc_get(key: str) -> str | None:
    try:
        import keyring
        return keyring.get_password(_KEYCHAIN_SERVICE, key)
    except Exception:
        return None


def _kc_set(key: str, value: str) -> None:
    try:
        import keyring
        keyring.set_password(_KEYCHAIN_SERVICE, key, value)
    except Exception as e:
        print(f"[카카오] ⚠️ Keychain 저장 실패 ({key}): {e}", file=sys.stderr)


# ── 토큰 관리 ─────────────────────────────────────────────────────────────────

def _refresh_access_token(refresh_token: str) -> str:
    """리프레시 토큰으로 액세스 토큰 재발급 후 Keychain 저장."""
    rest_key = os.getenv("KAKAO_REST_API_KEY")
    if not rest_key:
        raise ValueError("KAKAO_REST_API_KEY 환경변수가 없습니다.")

    client_secret = os.getenv("KAKAO_CLIENT_SECRET", "").strip()
    token_payload = {
        "grant_type":    "refresh_token",
        "client_id":     rest_key,
        "refresh_token": refresh_token,
    }
    if client_secret:
        token_payload["client_secret"] = client_secret

    resp = requests.post(_KAKAO_TOKEN_URL, data=token_payload, timeout=10)
    data = resp.json()

    if "error" in data:
        raise RuntimeError(f"카카오 토큰 갱신 실패: {data}")

    access_token = data["access_token"]
    expires_in   = data.get("expires_in", 21600)
    expires_at   = (datetime.now() + timedelta(seconds=expires_in)).isoformat()

    # 액세스 토큰 + 만료시각 → Keychain 저장
    _kc_set(_KC_ACCESS_TOKEN, access_token)
    _kc_set(_KC_ACCESS_EXPIRES_AT, expires_at)

    # 리프레시 토큰 갱신된 경우 → Keychain + .env 모두 업데이트
    if "refresh_token" in data:
        new_refresh = data["refresh_token"]
        _kc_set(_KC_REFRESH_TOKEN, new_refresh)
        try:
            from dotenv import set_key
            set_key(str(_ROOT / ".env"), "KAKAO_REFRESH_TOKEN", new_refresh)
            print("[카카오] 리프레시 토큰 자동 업데이트 완료 (Keychain + .env)", file=sys.stderr)
        except Exception as e:
            print(f"[카카오] ⚠️ 리프레시 토큰 .env 업데이트 실패: {e}", file=sys.stderr)
            print(f"         수동으로 .env에 추가하세요: KAKAO_REFRESH_TOKEN={new_refresh}", file=sys.stderr)

    return access_token


def get_access_token() -> str:
    """
    유효한 액세스 토큰 반환 (만료 시 자동 갱신).
    액세스 토큰은 Keychain에서 로드. 만료 10분 전이면 재발급.
    리프레시 토큰은 Keychain 우선, 없으면 .env 폴백.
    """
    # 액세스 토큰 유효성 확인 (Keychain)
    access_token = _kc_get(_KC_ACCESS_TOKEN)
    expires_at_str = _kc_get(_KC_ACCESS_EXPIRES_AT)

    if access_token and expires_at_str:
        try:
            expires_dt = datetime.fromisoformat(expires_at_str)
            if datetime.now() < expires_dt - timedelta(minutes=10):
                return access_token
        except (ValueError, TypeError):
            pass  # 잘못된 형식이면 재발급

    # 리프레시 토큰 로드 (Keychain 우선 → .env 폴백)
    refresh_token = _kc_get(_KC_REFRESH_TOKEN) or os.getenv("KAKAO_REFRESH_TOKEN")

    if not refresh_token:
        raise ValueError(
            "카카오 리프레시 토큰이 없습니다.\n"
            "_setup_kakao.py를 실행해 최초 인증을 완료하세요."
        )

    return _refresh_access_token(refresh_token)


# ── 메시지 전송 ───────────────────────────────────────────────────────────────

def send_text(text: str) -> bool:
    """
    카카오톡 나에게 텍스트 메시지 전송.

    Parameters
    ----------
    text : 전송할 텍스트 (최대 1000자)

    Returns
    -------
    bool : 성공 여부
    """
    token = get_access_token()

    # 1000자 초과 시 분할 전송
    chunks = [text[i:i+900] for i in range(0, len(text), 900)]
    success = True

    for i, chunk in enumerate(chunks):
        if len(chunks) > 1:
            chunk = f"[{i+1}/{len(chunks)}]\n{chunk}"

        template = {
            "object_type": "text",
            "text": chunk,
            "link": {
                "web_url": "https://finance.naver.com",
                "mobile_web_url": "https://finance.naver.com",
            },
        }

        resp = requests.post(
            _KAKAO_SEND_URL,
            headers={"Authorization": f"Bearer {token}"},
            data={"template_object": json.dumps(template, ensure_ascii=False)},
        )

        result = resp.json()
        if result.get("result_code") != 0:
            print(f"[카카오] 전송 실패: {result}", file=sys.stderr)
            success = False

    return success


def send_report(report_text: str, title: str = "📈 오늘의 주식 브리핑"):
    """
    보고서 전송 — 제목 + 본문 형식으로 전송.
    긴 보고서는 자동 분할.
    """
    full_text = f"{title}\n{'='*30}\n{report_text}"
    ok = send_text(full_text)
    if ok:
        print(f"[카카오] 전송 완료 ({len(full_text)}자)")
    else:
        print("[카카오] 전송 실패", file=sys.stderr)
    return ok


# ── CLI 테스트 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_msg = f"✅ 카카오톡 연결 테스트\n{datetime.now().strftime('%Y-%m-%d %H:%M')}\n연결이 정상입니다!"
    ok = send_text(test_msg)
    sys.exit(0 if ok else 1)
