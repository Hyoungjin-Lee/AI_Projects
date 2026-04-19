# Stage 2~4: 기획 통합본 — 카카오톡 → 텔레그램 전환

> 날짜: 2026-04-18 | 담당: Claude Sonnet | Effort: Medium

---

## 프로젝트 개요

stockpilot의 알림 채널을 카카오톡 → 텔레그램 봇으로 전환한다.
기존 `kakao_sender.py`를 `telegram_sender.py`로 교체하고,
호출부 5개 스크립트에서 import 경로만 변경한다.

---

## 목표

- 평일 4회 브리핑 알림이 텔레그램으로 정상 수신되어야 한다
- 카카오 관련 코드·인증정보를 완전히 제거한다
- 기존 메시지 형식(텍스트, 이모지, 분할 전송)은 그대로 유지한다
- 보안 구조(Keychain)는 그대로 유지한다

---

## 핵심 기능

1. **telegram_sender.py 신규 작성**
   - `send_text(text: str) → bool` — kakao_sender와 동일 시그니처
   - `send_report(report_text: str, title: str) → bool` — 동일 시그니처
   - 4096자 초과 시 자동 분할 전송 (텔레그램 제한)
   - 봇 토큰 / chat_id → Keychain에서 로드

2. **기존 스크립트 5개 import 교체**
   - `from kakao_sender import send_report` → `from telegram_sender import send_report`
   - 대상: `morning_report.py`, `closing_report.py`, `intraday_report.py`, `stock_discovery.py`, `setup_kakao.py` (→ `setup_telegram.py`로 대체)

3. **Keychain 항목 추가**
   - `TELEGRAM_BOT_TOKEN` — BotFather에서 발급
   - `TELEGRAM_CHAT_ID` — 본인 chat_id

4. **setup_telegram.py 신규 작성**
   - Keychain에 봇 토큰 / chat_id 저장
   - 테스트 메시지 전송 확인

---

## 제외 범위 (이번 버전)

- 양방향 명령 처리 (향후 확장)
- 인라인 버튼, 이미지 전송
- 다중 chat_id (1명에게만 전송)

---

## 기능 우선순위

| 우선순위 | 항목 |
|---------|------|
| P0 | telegram_sender.py 작성 + Keychain 연동 |
| P0 | 기존 5개 스크립트 import 교체 |
| P1 | setup_telegram.py 작성 |
| P2 | kakao_sender.py / setup_kakao.py 제거 또는 보관 |

---

## 운영 제약

- Python 환경: `venv/bin/python3` (Python 3.14)
- 모든 인증정보는 Keychain 저장 — 평문 노출 절대 금지
- 변경 후 `py_compile` 문법 검사 필수
- 실제 전송 테스트는 `--dry-run` 없이 직접 실행으로 확인

---

## 리스크

| 리스크 | 대응 |
|-------|------|
| 텔레그램 봇 미설정 | setup_telegram.py로 사전 설정 안내 |
| 메시지 길이 초과 | 4096자 분할 로직 구현 |
| Keychain 저장 실패 | 에러 메시지 출력 + 수동 입력 안내 |

---

## 설계 단계 전달 메모

- `kakao_sender.py`의 구조(함수 시그니처, Keychain 로드 패턴)를 최대한 유지
- `keychain_manager.py`의 `inject_to_env()` 패턴 그대로 사용
- `telegram_sender.py`는 `morning_report/` 폴더에 위치

---

## 다음 단계: technical_design
