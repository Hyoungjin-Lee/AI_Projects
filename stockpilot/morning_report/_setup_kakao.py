"""
_setup_kakao.py — 카카오톡 최초 인증 설정 도우미

최초 1회만 실행하면 됩니다.
이후에는 토큰 자동 갱신으로 재인증 불필요.

실행 방법:
  python3 _setup_kakao.py
"""

import json
import os
import sys
import webbrowser
from pathlib import Path
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv, set_key

_ROOT = Path(__file__).parent.parent
_ENV_FILE = _ROOT / ".env"
_TOKEN_CACHE = _ROOT / "data" / "cache" / "kakao_token.json"

load_dotenv(_ENV_FILE)


def main():
    print("=" * 50)
    print("카카오톡 연동 최초 설정")
    print("=" * 50)
    print()

    # ── Step 1: REST API 키 확인 ──────────────────────────────────────────────
    rest_key = os.getenv("KAKAO_REST_API_KEY", "").strip()
    if not rest_key:
        print("📌 Step 1: 카카오 REST API 키를 입력하세요.")
        print()
        print("  아직 카카오 앱을 만들지 않았다면:")
        print("  1. https://developers.kakao.com 접속 → 로그인")
        print("  2. '내 애플리케이션' → '애플리케이션 추가하기'")
        print("  3. 앱 이름 입력 후 저장")
        print("  4. '앱 키' 탭 → 'REST API 키' 복사")
        print("  5. '카카오 로그인' 메뉴 → 활성화 ON")
        print("  6. '카카오 로그인' → 'Redirect URI' → 다음 주소 추가:")
        print("     https://example.com/oauth")
        print()
        rest_key = input("REST API 키 입력: ").strip()
        if not rest_key:
            print("키를 입력하지 않았습니다. 종료합니다.")
            sys.exit(1)

        # .env에 저장
        set_key(str(_ENV_FILE), "KAKAO_REST_API_KEY", rest_key)
        print("✅ REST API 키 저장 완료")
    else:
        print(f"✅ REST API 키 확인: {rest_key[:8]}...")

    print()

    # ── Step 2: 인증 코드 받기 ───────────────────────────────────────────────
    print("📌 Step 2: 카카오 로그인 인증")
    print()

    redirect_uri = "https://example.com/oauth"
    auth_url = (
        "https://kauth.kakao.com/oauth/authorize?"
        + urlencode({
            "client_id":     rest_key,
            "redirect_uri":  redirect_uri,
            "response_type": "code",
            "scope":         "talk_message",
        })
    )

    print("  아래 URL을 브라우저에서 열고 카카오 로그인 후")
    print("  리디렉션된 주소창의 URL을 복사해 붙여넣으세요.")
    print()
    print(f"  {auth_url}")
    print()

    try:
        webbrowser.open(auth_url)
        print("  (브라우저가 자동으로 열렸습니다)")
    except Exception:
        print("  (브라우저를 직접 열어주세요)")

    print()
    print("  로그인 후 주소창 URL 예시:")
    print("  https://example.com/oauth?code=XXXXXXXXXXXXXX")
    print()

    redirect_url = input("리디렉션된 전체 URL 붙여넣기: ").strip()
    if "code=" not in redirect_url:
        print("URL에서 code를 찾을 수 없습니다. 다시 시도해주세요.")
        sys.exit(1)

    auth_code = redirect_url.split("code=")[1].split("&")[0]
    print(f"  인증 코드 확인: {auth_code[:10]}...")

    print()

    # ── Step 3: 토큰 발급 ────────────────────────────────────────────────────
    print("📌 Step 3: 액세스 토큰 발급 중...")

    client_secret = os.getenv("KAKAO_CLIENT_SECRET", "").strip()

    token_payload = {
        "grant_type":   "authorization_code",
        "client_id":    rest_key,
        "redirect_uri": redirect_uri,
        "code":         auth_code,
    }
    if client_secret:
        token_payload["client_secret"] = client_secret

    resp = requests.post("https://kauth.kakao.com/oauth/token", data=token_payload)
    token_data = resp.json()

    if "error" in token_data:
        print(f"❌ 토큰 발급 실패: {token_data}")
        sys.exit(1)

    # 토큰 캐시 저장
    from datetime import datetime, timedelta
    _TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    cache = {
        "access_token":  token_data["access_token"],
        "refresh_token": token_data["refresh_token"],
        "expires_at":    (datetime.now() + timedelta(seconds=token_data.get("expires_in", 21600))).isoformat(),
    }
    with open(_TOKEN_CACHE, "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    # .env에 리프레시 토큰 저장
    set_key(str(_ENV_FILE), "KAKAO_REFRESH_TOKEN", token_data["refresh_token"])

    print("✅ 토큰 발급 및 저장 완료")
    print()

    # ── Step 4: 테스트 메시지 전송 ───────────────────────────────────────────
    print("📌 Step 4: 테스트 메시지 전송 중...")

    sys.path.insert(0, str(Path(__file__).parent))
    from _kakao_sender import send_text

    ok = send_text("✅ 카카오톡 연동 성공!\n주식 AI 브리핑 시스템이 정상 연결됐습니다. 🎉")
    if ok:
        print("✅ 카카오톡으로 테스트 메시지를 보냈습니다. 확인해보세요!")
    else:
        print("❌ 테스트 메시지 전송 실패. 설정을 다시 확인하세요.")
        sys.exit(1)

    print()
    print("=" * 50)
    print("설정 완료! 이제 morning_report.py를 실행하면")
    print("매일 아침 카카오톡으로 주식 브리핑을 받을 수 있습니다.")
    print("=" * 50)


if __name__ == "__main__":
    main()
