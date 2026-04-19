# stockpilot — 에이전트 운영 지침

> 최종 업데이트: 2026-04-19 (v2.0 에이전트 아키텍처)
> 이 파일은 새 세션을 시작할 때 가장 먼저 읽는 핵심 지침이다.
> 상세한 API/분석/리포트 작업 방법은 `.skills/*/SKILL.md` 를 참고한다.

---

## 1. 프로젝트 한 줄 요약

KIS Open API 기반 주식 자동화 시스템. 평일 자동 브리핑 + 텔레그램 양방향 명령 지원.

- **Python 환경:** `venv/bin/python3` (Python 3.14)
- **프로젝트 경로:** `/Users/geenya/projects/AI_Projects/stockpilot`
- **메인 스크립트:** `morning_report/` 폴더

---

## 2. 에이전트 구성

### 실행 에이전트 (launchd 자동 실행)

| 시각 | 스크립트 | 역할 |
|------|----------|------|
| 08:20 | `watchlist_sync.py` | 관심종목 동기화 → state 기록 |
| 08:30 | `morning_report.py` | 모닝 브리핑 → 시장/시그널 state 기록 |
| 09:10 | `intraday_report.py` | 장초기 분봉 분석 → 알림 state 기록 |
| 20:30 | `closing_report.py` | 장마감 결산 → 최종 시그널 state 기록 |
| 23:30 | `stock_discovery.py` | 종목 발굴 → 발굴 결과 state 기록 |
| 상시 | `telegram_bot.py` | 텔레그램 명령 수신 → orchestrator 전달 |

### 공유 상태 (에이전트 간 소통)

```
data/daily_state.json — 당일 컨텍스트 공유
  ├── market.us_sentiment   (morning/discovery 기록)
  ├── holdings.{code}.signal (morning/closing 기록)
  ├── alerts.intraday        (intraday 기록)
  ├── alerts.vol_spike       (closing 기록)
  └── discovery.candidates   (discovery 기록)
```

### 오케스트레이터 (양방향 명령)

```
telegram_bot.py (polling)
    ↓
orchestrator.py
    ├── /잔고    → KIS 잔고 즉시 조회
    ├── /상태    → daily_state 요약
    ├── /발굴    → stock_discovery 즉시 실행
    └── /도움말  → 명령어 목록
```

---

## 3. 절대 규칙 (보안)

```
❌ API키·계좌번호·토큰을 코드/로그에 평문 노출 금지
❌ KIS_ALLOW_LIVE_ORDER=1 없으면 실주문 절대 불가
✅ 모든 스크립트는 inject_to_env()로 Keychain에서 인증정보 로드
✅ 변경 전 반드시 --dry-run으로 먼저 확인
✅ 파일 생성·수정 후 python3 -m py_compile 로 문법 검사
```

### Keychain 인증정보 로드 패턴
```python
from keychain_manager import inject_to_env
inject_to_env()   # 반드시 첫 줄에 호출
```

---

## 4. 핵심 파일

| 파일 | 역할 |
|------|------|
| `morning_report/keychain_manager.py` | Keychain 관리, `inject_to_env()` 제공 |
| `morning_report/telegram_sender.py` | 텔레그램 단방향 전송 |
| `morning_report/telegram_bot.py` | 텔레그램 봇 데몬 (수신) |
| `morning_report/orchestrator.py` | 명령 라우팅 및 실행 |
| `morning_report/state_manager.py` | 에이전트 간 공유 상태 관리 |
| `.skills/kis-api/scripts/kis_client.py` | KIS API 클라이언트 |
| `data/watchlist.json` | 관심종목 목록 |
| `data/daily_state.json` | 당일 공유 상태 |
| `data/cache/` | KIS 토큰 캐시 |

---

## 5. 주요 명령어

```bash
cd /Users/geenya/projects/AI_Projects/stockpilot

# 테스트 (전송 없이)
venv/bin/python3 morning_report/morning_report.py --dry-run
venv/bin/python3 morning_report/closing_report.py --dry-run

# 봇 테스트 (1회 폴링)
venv/bin/python3 morning_report/telegram_bot.py --once

# 공유 상태 확인
venv/bin/python3 morning_report/state_manager.py

# Keychain 확인 / 재설정
venv/bin/python3 morning_report/keychain_manager.py
venv/bin/python3 morning_report/keychain_manager.py --reset

# 로그 확인
tail -50 logs/stockbot_error.log
tail -50 logs/closing_report.log
```

---

## 6. 스킬 참조

| 작업 | 참조 |
|------|------|
| KIS API 데이터 조회 | `.skills/kis-api/SKILL.md` |
| 기술적 분석 | `.skills/stock-analysis/SKILL.md` |
| 리포트/매매일지 | `.skills/trading-report/SKILL.md` |

---

## 7. 코드 검증 가이드

- 문법 검사: `venv/bin/python3 -m py_compile morning_report/<파일>.py`
- 복잡한 로직 변경 시: 새 세션에서 독립 검증 (WORKFLOW.md 독립 검증 프로토콜 참고)
- KIS API 궁금한 점: `docs/api/` 폴더의 xlsx 파일 참고

---

*현재 상태 및 다음 작업은 `HANDOFF.md` 참고*
