# Stage 5: 기술 설계 — 카카오톡 → 텔레그램 전환

> 날짜: 2026-04-18 | 담당: Claude Opus | Effort: High

---

## 전체 아키텍처

```
[launchd 스케줄러]
    ↓ 실행
[morning_report.py / closing_report.py / intraday_report.py / stock_discovery.py]
    ↓ import
[telegram_sender.py]  ← 신규 (kakao_sender.py 대체)
    ↓ Keychain 로드
[keychain_manager.inject_to_env()]
    ↓ HTTP POST
[Telegram Bot API]
    ↓
[형진님 텔레그램 앱 알림]
```

---

## 신규/변경 파일 목록

| 파일 | 작업 | 설명 |
|------|------|------|
| `morning_report/telegram_sender.py` | **신규** | 텔레그램 전송 모듈 |
| `morning_report/setup_telegram.py` | **신규** | 최초 봇 설정 도우미 |
| `morning_report/morning_report.py` | **수정** | import 교체 |
| `morning_report/closing_report.py` | **수정** | import 교체 |
| `morning_report/intraday_report.py` | **수정** | import 교체 |
| `morning_report/stock_discovery.py` | **수정** | import 교체 |
| `morning_report/kakao_sender.py` | **보관** | 삭제 말고 `_kakao_sender.py`로 이름 변경 |
| `morning_report/setup_kakao.py` | **보관** | `_setup_kakao.py`로 이름 변경 |

---

## 모듈 역할

### telegram_sender.py (핵심)

**Keychain 저장 항목:**
- 서비스명: `AI주식매매` (기존과 동일)
- `TELEGRAM_BOT_TOKEN` — BotFather 발급 토큰
- `TELEGRAM_CHAT_ID` — 본인 chat_id (숫자)

**공개 함수 (kakao_sender.py와 동일 시그니처):**
```python
def send_text(text: str) -> bool
def send_report(report_text: str, title: str = "📈 오늘의 주식 브리핑") -> bool
```

**내부 함수:**
```python
def _kc_get(key: str) -> str | None       # Keychain 읽기
def _kc_set(key: str, value: str) -> None  # Keychain 저장
def _get_credentials() -> tuple[str, str]  # 토큰+chat_id 로드
def _split_message(text: str, limit: int = 4000) -> list[str]  # 분할
def _send_raw(token: str, chat_id: str, text: str) -> bool      # 단건 전송
```

### setup_telegram.py

1. BotFather 토큰 입력받기
2. chat_id 자동 획득 (`getUpdates` API 사용)
3. Keychain에 저장
4. 테스트 메시지 전송 확인

---

## 데이터 흐름

```
send_report(text, title) 호출
    → full_text = f"{title}\n{'='*30}\n{text}"
    → _split_message(full_text, limit=4000)
    → 각 청크마다 _send_raw(token, chat_id, chunk) 호출
    → POST https://api.telegram.org/bot{token}/sendMessage
       body: {"chat_id": chat_id, "text": chunk, "parse_mode": "HTML" 생략}
    → 응답 {"ok": true} 확인
    → 성공/실패 bool 반환
```

---

## Telegram Bot API 스펙

- **엔드포인트:** `https://api.telegram.org/bot{BOT_TOKEN}/sendMessage`
- **메서드:** POST
- **파라미터:**
  ```json
  {
    "chat_id": "123456789",
    "text": "메시지 내용"
  }
  ```
- **응답:**
  ```json
  {"ok": true, "result": {...}}
  ```
- **메시지 길이 제한:** 4096자 → 4000자 단위로 분할 (여유 확보)
- **rate limit:** 초당 1건 이하 권장 → 분할 전송 시 1초 간격

---

## 예외 처리 포인트

| 상황 | 처리 방법 |
|------|---------|
| Keychain에 토큰/chat_id 없음 | `ValueError` + 안내 메시지 출력 |
| API 응답 `ok: false` | 에러 내용 `stderr` 출력, `False` 반환 |
| 네트워크 오류 | `requests.RequestException` 캐치, `False` 반환 |
| 메시지 4096자 초과 | 자동 분할, 각 청크 앞에 `[1/3]` 표기 |
| keyring 미설치 | ImportError 캐치 + 설치 안내 |

---

## 로깅 포인트

- 전송 성공: `print(f"[텔레그램] 전송 완료 ({len(full_text)}자)")`
- 전송 실패: `print(f"[텔레그램] 전송 실패: {result}", file=sys.stderr)`
- 분할 전송: `print(f"[텔레그램] {i+1}/{n} 청크 전송")`

---

## 테스트 포인트

1. `venv/bin/python3 morning_report/telegram_sender.py` — 테스트 메시지 전송
2. `venv/bin/python3 morning_report/morning_report.py --dry-run` — 전송 없이 실행
3. `venv/bin/python3 morning_report/closing_report.py --dry-run` — 전송 없이 실행
4. `venv/bin/python3 -m py_compile morning_report/telegram_sender.py` — 문법 검사

---

## 확장 포인트 (이번 범위 외)

- `telegram_sender.py`에 `send_photo()` 추가 → 차트 이미지 전송
- `/잔고`, `/매수` 명령 처리 → polling 또는 webhook 방식
- 다중 수신자 → chat_id 목록으로 확장

---

## 다음 단계: Codex 구현 (Stage 8)

산출물: `docs/04_implementation/implementation_request.md` 참고
