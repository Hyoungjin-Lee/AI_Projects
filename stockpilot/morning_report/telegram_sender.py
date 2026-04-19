"""
telegram_sender.py — 텔레그램 봇 메시지 전송 모듈

설정 필요 항목 (Keychain 서비스명: AI주식매매):
  TELEGRAM_BOT_TOKEN   BotFather에서 발급
  TELEGRAM_CHAT_ID     본인 chat_id (숫자 문자열)
"""

import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / ".env")

_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"
_KEYCHAIN_SERVICE = "AI주식매매"
_KC_BOT_TOKEN = "TELEGRAM_BOT_TOKEN"
_KC_CHAT_ID = "TELEGRAM_CHAT_ID"
_MSG_LIMIT = 4000  # 텔레그램 4096자 제한에 여유 확보


def _load_keyring():
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError(
            "keyring 패키지가 없습니다. venv/bin/pip install keyring 을 실행하세요."
        ) from exc
    return keyring


def _kc_get(key: str) -> str | None:
    return _load_keyring().get_password(_KEYCHAIN_SERVICE, key)


def _kc_set(key: str, value: str) -> None:
    _load_keyring().set_password(_KEYCHAIN_SERVICE, key, value)


def _get_credentials() -> tuple[str, str]:
    token = _kc_get(_KC_BOT_TOKEN)
    chat_id = _kc_get(_KC_CHAT_ID)

    if not token or not chat_id:
        raise ValueError(
            "텔레그램 설정이 없습니다. morning_report/setup_telegram.py를 먼저 실행하세요."
        )

    return token.strip(), chat_id.strip()


def _split_message(text: str, limit: int = _MSG_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks = [text[i:i + limit] for i in range(0, len(text), limit)]
    total = len(chunks)
    return [f"[{i+1}/{total}]\n{chunk}" for i, chunk in enumerate(chunks)]


def _send_raw(token: str, chat_id: str, text: str) -> bool:
    try:
        resp = requests.post(
            _API_BASE.format(token=token),
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except requests.RequestException as exc:
        print(f"[텔레그램] 전송 실패: {exc}", file=sys.stderr)
        return False

    try:
        result = resp.json()
    except ValueError:
        result = {
            "ok": False,
            "status_code": resp.status_code,
            "body": resp.text[:300],
        }

    if resp.status_code != 200 or not result.get("ok"):
        print(f"[텔레그램] 전송 실패: {result}", file=sys.stderr)
        return False

    return True


def send_text(text: str) -> bool:
    """카카오 send_text와 동일 시그니처"""
    try:
        token, chat_id = _get_credentials()
    except (RuntimeError, ValueError) as exc:
        print(f"[텔레그램] {exc}", file=sys.stderr)
        return False

    chunks = _split_message(text)

    for idx, chunk in enumerate(chunks, start=1):
        if len(chunks) > 1:
            print(f"[텔레그램] {idx}/{len(chunks)} 청크 전송")

        if not _send_raw(token, chat_id, chunk):
            return False  # 실패 즉시 중단

        if idx < len(chunks):
            time.sleep(1)

    return True


def send_report(report_text: str, title: str = "📈 오늘의 주식 브리핑") -> bool:
    """카카오 send_report와 동일 시그니처"""
    full_text = f"{title}\n{'=' * 30}\n{report_text}"
    ok = send_text(full_text)
    if ok:
        print(f"[텔레그램] 전송 완료 ({len(full_text)}자)")
    else:
        print("[텔레그램] 전송 실패", file=sys.stderr)
    return ok


if __name__ == "__main__":
    test_msg = (
        f"✅ 텔레그램 연결 테스트\n"
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        "연결이 정상입니다!"
    )
    ok = send_text(test_msg)
    sys.exit(0 if ok else 1)
