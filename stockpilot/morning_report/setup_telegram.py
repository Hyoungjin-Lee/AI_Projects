"""
setup_telegram.py — 텔레그램 봇 최초 설정 도우미

실행 방법:
  python3 setup_telegram.py
"""

import getpass
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from telegram_sender import _kc_set, send_text


def _get_updates(token: str) -> dict:
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            timeout=10,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Telegram API 호출 실패: {exc}") from exc

    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"Telegram 응답 파싱 실패: {resp.text[:300]}") from exc

    if resp.status_code != 200 or not data.get("ok"):
        raise RuntimeError(f"Telegram getUpdates 실패: {data}")

    return data


def _extract_chat_id(data: dict) -> str | None:
    updates = data.get("result") or []
    fallback_chat_id = None

    for update in reversed(updates):
        candidates = []

        for key in ("message", "edited_message", "channel_post"):
            payload = update.get(key)
            if isinstance(payload, dict):
                candidates.append(payload)

        callback = update.get("callback_query")
        if isinstance(callback, dict):
            message = callback.get("message")
            if isinstance(message, dict):
                candidates.append(message)

        for candidate in candidates:
            chat = candidate.get("chat")
            if not isinstance(chat, dict):
                continue

            chat_id = chat.get("id")
            if chat_id is None:
                continue

            if fallback_chat_id is None:
                fallback_chat_id = str(chat_id)

            if chat.get("type") == "private":
                return str(chat_id)

    return fallback_chat_id


def main():
    print("=" * 50)
    print("텔레그램 봇 연동 최초 설정")
    print("=" * 50)
    print()
    print("1. BotFather에서 봇을 만든 뒤 토큰을 복사하세요.")
    print("2. 텔레그램 앱에서 해당 봇에게 아무 메시지나 먼저 보내세요.")
    print()

    token = getpass.getpass("BotFather 토큰 입력: ").strip()
    if not token:
        print("토큰을 입력하지 않았습니다. 종료합니다.", file=sys.stderr)
        sys.exit(1)

    input("봇에게 메시지를 보냈다면 Enter를 누르세요... ")

    print()
    print("📌 chat_id 조회 중...")
    try:
        updates = _get_updates(token)
        chat_id = _extract_chat_id(updates)
    except RuntimeError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        sys.exit(1)

    if not chat_id:
        print("❌ chat_id를 찾지 못했습니다.", file=sys.stderr)
        print("   텔레그램에서 봇에게 먼저 메시지를 보낸 뒤 다시 실행하세요.", file=sys.stderr)
        sys.exit(1)

    try:
        _kc_set("TELEGRAM_BOT_TOKEN", token)
        _kc_set("TELEGRAM_CHAT_ID", chat_id)
    except RuntimeError as exc:
        print(f"❌ Keychain 저장 실패: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"✅ chat_id 확인: {chat_id}")
    print("✅ Keychain 저장 완료")
    print()

    print("📌 테스트 메시지 전송 중...")
    ok = send_text("✅ 텔레그램 연동 성공!\n주식 AI 브리핑 시스템이 정상 연결됐습니다. 🎉")
    if not ok:
        print("❌ 테스트 메시지 전송 실패. 설정을 다시 확인하세요.", file=sys.stderr)
        sys.exit(1)

    print("✅ 텔레그램으로 테스트 메시지를 보냈습니다. 확인해보세요!")
    print()
    print("=" * 50)
    print("설정 완료! 이제 morning_report.py를 실행하면")
    print("매일 텔레그램으로 주식 브리핑을 받을 수 있습니다.")
    print("=" * 50)


if __name__ == "__main__":
    main()
