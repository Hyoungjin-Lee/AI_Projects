# Stage 8: 구현 요청서 — 텔레그램 전환

> 날짜: 2026-04-18 | 담당: Codex | Effort: High
> 기준 문서: `docs/03_design/technical_design.md`

---

## 구현 대상 요약

카카오톡 전송 모듈(`kakao_sender.py`)을 텔레그램 봇 전송 모듈(`telegram_sender.py`)로 교체한다.
기존 호출부 4개 스크립트의 import 경로만 변경하고, 함수 시그니처는 동일하게 유지한다.

---

## 구현 우선순위

### P0 — 반드시 구현

**1. `morning_report/telegram_sender.py` 신규 작성**

아래 구조를 반드시 따를 것:

```python
"""
telegram_sender.py — 텔레그램 봇 메시지 전송 모듈

설정 필요 항목 (Keychain 서비스명: AI주식매매):
  TELEGRAM_BOT_TOKEN   BotFather에서 발급
  TELEGRAM_CHAT_ID     본인 chat_id (숫자 문자열)
"""

import sys
import time
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


def _kc_get(key: str) -> str | None:
    # keyring으로 Keychain에서 읽기
    ...

def _kc_set(key: str, value: str) -> None:
    # keyring으로 Keychain에 저장
    ...

def _get_credentials() -> tuple[str, str]:
    # TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 반환
    # 없으면 ValueError 발생
    ...

def _split_message(text: str) -> list[str]:
    # 4000자 단위로 분할, 2개 이상이면 [1/N] 접두사 추가
    ...

def _send_raw(token: str, chat_id: str, text: str) -> bool:
    # Telegram sendMessage API 단건 호출
    # 성공 시 True, 실패 시 stderr 출력 후 False
    ...

def send_text(text: str) -> bool:
    """카카오 send_text와 동일 시그니처"""
    ...

def send_report(report_text: str, title: str = "📈 오늘의 주식 브리핑") -> bool:
    """카카오 send_report와 동일 시그니처"""
    ...

if __name__ == "__main__":
    # 테스트 메시지 전송
    ...
```

**2. 기존 스크립트 4개 import 교체**

아래 4개 파일에서:
```python
from kakao_sender import send_report
```
를:
```python
from telegram_sender import send_report
```
로 교체한다.

- `morning_report/morning_report.py` (2곳)
- `morning_report/closing_report.py` (2곳)
- `morning_report/intraday_report.py` (1곳)
- `morning_report/stock_discovery.py` (1곳)

**3. 카카오 파일 보관 (삭제 금지)**

```bash
mv morning_report/kakao_sender.py morning_report/_kakao_sender.py
mv morning_report/setup_kakao.py morning_report/_setup_kakao.py
```

---

### P1 — 가능하면 구현

**4. `morning_report/setup_telegram.py` 신규 작성**

```
실행 흐름:
1. BotFather 토큰 입력받기 (input)
2. https://api.telegram.org/bot{token}/getUpdates 호출
3. 응답에서 chat_id 자동 추출
   (없으면 "봇에게 메시지를 먼저 보내세요" 안내)
4. Keychain에 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 저장
5. 테스트 메시지 전송 확인
```

---

## 구현 원칙 (반드시 준수)

```
✅ kakao_sender.py의 함수 시그니처(send_text, send_report)를 동일하게 유지
✅ 모든 인증정보는 Keychain에서 로드 (평문 하드코딩 절대 금지)
✅ keyring 패키지로 Keychain 접근 (기존 패턴과 동일)
✅ 에러는 stderr로 출력, 성공은 stdout
✅ 작성 완료 후 py_compile로 문법 검사
```

---

## 참조 파일 (반드시 읽을 것)

- `morning_report/kakao_sender.py` — 구조 참고 (Keychain 패턴, 함수 시그니처)
- `morning_report/keychain_manager.py` — Keychain 서비스명, keyring 사용 패턴
- `docs/03_design/technical_design.md` — 전체 설계 명세

---

## 확인해야 할 TODO

- [ ] `telegram_sender.py` 작성 완료
- [ ] `py_compile` 문법 검사 통과
- [ ] 4개 스크립트 import 교체 완료
- [ ] 카카오 파일 보관 (`_` 접두사로 이름 변경)
- [ ] `setup_telegram.py` 작성 완료 (P1)
- [ ] `venv/bin/python3 morning_report/telegram_sender.py` 실행 시 에러 없음

---

## 다음 단계: code_review (Stage 9, Claude Sonnet)
