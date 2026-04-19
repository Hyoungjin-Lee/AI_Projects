"""
telegram_bot.py — 텔레그램 봇 데몬 (상시 실행)

역할:
  - 텔레그램 메시지 polling (2초 간격)
  - 수신 명령을 orchestrator로 전달
  - launchd에 의해 부팅 시 자동 시작, 크래시 시 재시작

실행 방법:
  venv/bin/python3 morning_report/telegram_bot.py        # 상시 실행
  venv/bin/python3 morning_report/telegram_bot.py --once # 1회만 확인 후 종료 (테스트용)
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from keychain_manager import inject_to_env
inject_to_env()

import urllib.request
import urllib.error


def _get_updates(bot_token: str, offset: int, timeout: int = 30) -> list:
    """텔레그램 업데이트 목록 조회 (long polling)."""
    url = (
        f"https://api.telegram.org/bot{bot_token}/getUpdates"
        f"?offset={offset}&timeout={timeout}&allowed_updates=[\"message\"]"
    )
    try:
        with urllib.request.urlopen(url, timeout=timeout + 5) as resp:
            data = json.loads(resp.read().decode())
            if data.get("ok"):
                return data.get("result", [])
    except urllib.error.URLError as e:
        print(f"[bot] 네트워크 오류: {e}", file=sys.stderr)
    except Exception as e:
        print(f"[bot] getUpdates 오류: {e}", file=sys.stderr)
    return []


def run(once: bool = False):
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        print("[bot] TELEGRAM_BOT_TOKEN 없음. 종료.", file=sys.stderr)
        sys.exit(1)

    print(f"[bot] 텔레그램 봇 시작 ({datetime.now().strftime('%H:%M:%S')})", file=sys.stderr)

    from orchestrator import handle_command

    offset = 0
    retry_delay = 5

    while True:
        try:
            updates = _get_updates(bot_token, offset)
            retry_delay = 5  # 성공 시 재시도 딜레이 리셋

            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                text = msg.get("text", "").strip()
                chat_id = str(msg.get("chat", {}).get("id", ""))

                if text.startswith("/"):
                    print(f"[bot] {chat_id}: {text}", file=sys.stderr)
                    handle_command(text, chat_id)

            if once:
                break

            time.sleep(2)

        except KeyboardInterrupt:
            print("[bot] 종료 (KeyboardInterrupt)", file=sys.stderr)
            break
        except Exception as e:
            print(f"[bot] 예외 발생: {e} — {retry_delay}초 후 재시도", file=sys.stderr)
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)  # 최대 60초까지 지수 백오프


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="텔레그램 봇 데몬")
    parser.add_argument("--once", action="store_true", help="1회만 폴링 후 종료 (테스트용)")
    args = parser.parse_args()
    run(once=args.once)
