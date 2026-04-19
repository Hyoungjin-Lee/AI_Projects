# Codex 구현 프롬프트 — 텔레그램 전환

## 작업 개요

이 프로젝트(stockpilot)는 KIS Open API 기반 주식 자동화 시스템이다.
현재 카카오톡으로 브리핑을 전송하는데, 텔레그램 봇으로 전환한다.

## 프로젝트 구조

```
/Users/geenya/projects/AI_Projects/stockpilot/
├── morning_report/
│   ├── kakao_sender.py       ← 교체 대상 (구조 참고용)
│   ├── keychain_manager.py   ← Keychain 패턴 참고
│   ├── morning_report.py     ← import 교체 필요
│   ├── closing_report.py     ← import 교체 필요
│   ├── intraday_report.py    ← import 교체 필요
│   └── stock_discovery.py    ← import 교체 필요
└── docs/
    ├── 03_design/technical_design.md   ← 설계 명세 (반드시 읽을 것)
    └── 04_implementation/implementation_request.md  ← 구현 요청서 (반드시 읽을 것)
```

## 작업 순서

**1단계: 설계 문서 읽기**
- `docs/03_design/technical_design.md` 전체 읽기
- `docs/04_implementation/implementation_request.md` 전체 읽기
- `morning_report/kakao_sender.py` 구조 파악 (참고용)
- `morning_report/keychain_manager.py` Keychain 패턴 파악

**2단계: telegram_sender.py 작성**
- 경로: `morning_report/telegram_sender.py`
- `kakao_sender.py`와 동일한 함수 시그니처 유지
- Keychain 서비스명: `AI주식매매`
- Keychain 키: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- 메시지 4000자 초과 시 자동 분할

**3단계: 기존 스크립트 import 교체**
- `from kakao_sender import send_report` → `from telegram_sender import send_report`
- 4개 파일 수정: morning_report.py, closing_report.py, intraday_report.py, stock_discovery.py

**4단계: 카카오 파일 보관**
- `kakao_sender.py` → `_kakao_sender.py` (이름 변경, 삭제 금지)
- `setup_kakao.py` → `_setup_kakao.py` (이름 변경, 삭제 금지)

**5단계: setup_telegram.py 작성**
- BotFather 토큰 입력 → chat_id 자동 획득 → Keychain 저장 → 테스트 메시지

**6단계: 문법 검사**
```bash
cd /Users/geenya/projects/AI_Projects/stockpilot
venv/bin/python3 -m py_compile morning_report/telegram_sender.py
venv/bin/python3 -m py_compile morning_report/setup_telegram.py
```

## 절대 규칙

- API 토큰, chat_id를 코드에 하드코딩하지 말 것 (반드시 Keychain에서 로드)
- `send_text()`, `send_report()` 함수 시그니처는 kakao_sender.py와 동일하게 유지
- kakao_sender.py는 삭제하지 말고 `_kakao_sender.py`로 이름만 변경
- Python 가상환경: `venv/bin/python3` 사용

## 완료 기준

- [ ] `morning_report/telegram_sender.py` 생성됨
- [ ] `morning_report/setup_telegram.py` 생성됨
- [ ] 4개 스크립트 import 교체 완료
- [ ] 카카오 파일 `_` 접두사로 보관 완료
- [ ] py_compile 문법 검사 통과
