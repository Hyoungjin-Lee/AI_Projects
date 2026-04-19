# 🤝 stockpilot — Handoff 문서

> 최종 업데이트: 2026-04-19 (v2.0 에이전트 아키텍처 완료)
> 목적: 새 대화창에서 즉시 작업을 이어받을 수 있도록 현재 상태 전달

---

## 1. 프로젝트 개요

한국투자증권(KIS) Open API 기반 주식 자동화 시스템.
평일 자동 브리핑 + **텔레그램 양방향 명령** 지원.

- **프로젝트 경로:** `/Users/geenya/projects/AI_Projects/stockpilot`
- **Python 환경:** `venv/` (Python 3.14)
- **실행 방법:** `venv/bin/python3 morning_report/[스크립트].py`

---

## 2. 자동 실행 스케줄 (launchd, 평일 기준)

| 시각 | 스크립트 | 내용 |
|------|----------|------|
| 08:20 | `watchlist_sync.py` | KIS HTS 관심종목 → watchlist.json + state 기록 |
| 08:30 | `morning_report.py` | 모닝 브리핑 텔레그램 전송 + state 기록 |
| 09:10 | `intraday_report.py` | 장초기 현황 텔레그램 전송 + state 기록 |
| 20:30 | `closing_report.py` | 장마감 결산 텔레그램 전송 + state 기록 |
| 23:30 | `stock_discovery.py` | 야간 종목 발굴 텔레그램 전송 + state 기록 (월~토) |
| 상시 | `telegram_bot.py` | 텔레그램 명령 수신 (부팅 시 자동 시작) |

---

## 3. 핵심 파일 구조

```
stockpilot/
├── morning_report/
│   ├── morning_report.py       # 모닝 브리핑 (state 기록 포함)
│   ├── intraday_report.py      # 장초기 브리핑 (state 기록 포함)
│   ├── closing_report.py       # 장마감 결산 (state 기록 포함)
│   ├── stock_discovery.py      # 야간 종목 발굴 (state 기록 포함)
│   ├── watchlist_sync.py       # 관심종목 동기화 (state 기록 포함)
│   ├── telegram_sender.py      # 텔레그램 단방향 전송
│   ├── telegram_bot.py         # 텔레그램 봇 데몬 (양방향 수신) ← NEW
│   ├── orchestrator.py         # 명령 라우팅 (/잔고 /상태 /발굴 /도움말) ← NEW
│   ├── state_manager.py        # 에이전트 간 공유 상태 관리 ← NEW
│   ├── keychain_manager.py     # macOS Keychain 인증정보 관리
│   └── setup_telegram.py       # 텔레그램 최초 설정 도우미
├── .skills/
│   ├── kis-api/scripts/kis_client.py
│   ├── stock-analysis/
│   └── trading-report/
├── data/
│   ├── watchlist.json          # 관심종목
│   ├── daily_state.json        # 에이전트 간 공유 상태 ← NEW
│   └── cache/                  # KIS 토큰 캐시
├── docs/
│   ├── 06_agent_architecture/  # v2.0 에이전트 설계 문서 ← NEW
│   ├── 05_qa_release/          # QA 리포트
│   └── api/                    # KIS API xlsx 문서
├── logs/
│   ├── stockbot.log            # telegram_bot.py stdout ← NEW
│   └── stockbot_error.log      # telegram_bot.py stderr ← NEW
└── ~/Library/LaunchAgents/
    ├── com.aigeenya.stockbot.plist     # 봇 데몬 (상시) ← NEW
    ├── com.aigeenya.stockreport.plist  # morning
    ├── com.aigeenya.stockreport.closing.plist
    ├── com.aigeenya.stockreport.discovery.plist
    ├── com.aigeenya.stockreport.intraday.plist
    └── com.aigeenya.stockreport.watchlist.plist
```

---

## 4. 보안 구조 (Keychain 통합)

### Keychain 저장 항목 (서비스명: `AI주식매매`)

| 키 | 내용 |
|----|------|
| `KIS_APP_KEY` | KIS API 앱키 |
| `KIS_APP_SECRET` | KIS API 앱시크릿 |
| `KIS_ACCOUNT_NO` | 계좌번호 |
| `KIS_HTS_ID` | MTS 로그인 ID |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 텔레그램 chat_id |

### 모든 스크립트 공통 진입점
```python
from keychain_manager import inject_to_env
inject_to_env()  # Keychain → os.environ 자동 주입
```

---

## 5. v2.0 에이전트 아키텍처 (2026-04-19 완료)

### 구현된 기능

| 구성요소 | 파일 | 상태 |
|---------|------|------|
| 공유 상태 | `state_manager.py` + `data/daily_state.json` | ✅ 완료 |
| 5개 스크립트 state 연동 | morning/intraday/closing/discovery/watchlist | ✅ 완료 |
| 텔레그램 명령 수신 | `telegram_bot.py` | ✅ 완료 |
| 명령 라우팅 | `orchestrator.py` | ✅ 완료 |
| 봇 데몬 launchd | `com.aigeenya.stockbot.plist` | ✅ 완료 |
| AGENTS.md 문서화 | `AGENTS.md` | ✅ 완료 |
| WORKFLOW.md 독립검증 프로토콜 | 섹션 10 | ✅ 완료 |

### 사용 가능한 텔레그램 명령어

```
/잔고    — KIS 잔고 즉시 조회
/상태    — 오늘 시장/시그널 요약
/발굴    — 종목 발굴 즉시 실행
/도움말  — 명령어 목록
```

### daily_state.json 구조

```json
{
  "date": "2026-04-21",
  "market": { "us_sentiment": "...", "usd_krw": 0, "fear_greed": "..." },
  "holdings": { "종목코드": { "signal": "BUY/SELL/HOLD", "pnl_pct": 0.0 } },
  "alerts": { "intraday": "...", "vol_spike": [] },
  "discovery": { "candidates": [], "top_pick": "..." },
  "watchlist_changed": false
}
```

---

## 6. 수동 설정 필요 항목 (다음 로그인 시)

### 6-1. 텔레그램 봇 데몬 launchd 등록

```bash
launchctl load ~/Library/LaunchAgents/com.aigeenya.stockbot.plist
launchctl list | grep stockbot  # 확인
```

### 6-2. 기존 5개 plist 경로 변경 후 재등록

```bash
# 경로가 변경되었으므로 unload → load 필요
launchctl unload ~/Library/LaunchAgents/com.aigeenya.stockreport.plist
launchctl load   ~/Library/LaunchAgents/com.aigeenya.stockreport.plist
# (나머지 4개도 동일하게)
```

### 6-3. GitHub push (최신 변경사항)

```bash
cd /Users/geenya/projects/AI_Projects/stockpilot
git add -p  # 변경된 파일 선택적 스테이징
git commit -m "feat: v2.0 에이전트 아키텍처 — 공유상태/텔레그램봇/오케스트레이터"
git push origin main
```

---

## 7. 다음 세션에서 할 작업

> **현재 상태: v2.0 에이전트 아키텍처 구현 완료 ✅**
> **월요일(2026-04-21) 자동 실행으로 전체 검증 예정**

### 운영 모니터링 (2026-04-21 이후)
- [ ] `morning_report.py` 08:30 자동 실행 확인
- [ ] `telegram_bot.py` 봇 데몬 상시 실행 확인 (`launchctl list | grep stockbot`)
- [ ] `/잔고`, `/상태` 명령 텔레그램에서 테스트
- [ ] `closing_report.py` 20:30 자동 실행 + state 기록 확인
- [ ] `stock_discovery.py` 23:30 자동 실행 확인

### 다음 프로젝트 후보
- [ ] stock_discovery 스크리닝 조건 고도화 (기술적 지표 추가)
- [ ] 보유 종목 자동 매도 시그널 (Phase 2 — 실주문 포함)
- [ ] 텔레그램 `/매수`, `/매도` 명령 구현 (Phase 2)

---

## 8. 주요 명령어 모음

```bash
cd /Users/geenya/projects/AI_Projects/stockpilot

# 테스트 (전송 없이)
venv/bin/python3 morning_report/morning_report.py --dry-run
venv/bin/python3 morning_report/closing_report.py --dry-run
venv/bin/python3 morning_report/intraday_report.py --dry-run

# 봇 1회 테스트 (텔레그램 명령 수신 확인)
venv/bin/python3 morning_report/telegram_bot.py --once

# 공유 상태 확인
venv/bin/python3 morning_report/state_manager.py

# Keychain 확인
venv/bin/python3 morning_report/keychain_manager.py

# 봇 데몬 상태 확인
launchctl list | grep stockbot

# 로그 확인
tail -50 logs/stockbot_error.log
tail -50 logs/closing_report.log
```

---

## 9. 전체 작업 히스토리 (누적)

1. 장마감 시간 변경: 16:00 → 20:30
2. watchlist 자동 동기화: KIS HTS 관심종목 API 연동
3. macOS Keychain 보안 통합
4. closing_report.py: OHLCV + 거래량 + 내일 전략 + 매매일지
5. 스케줄러 5개 launchd 등록 완료
6. 운영자/사용자 매뉴얼 작성
7. Opus 보안 검증 완료
8. AGENTS.md (구 CLAUDE.md) 생성
9. **카카오톡 → 텔레그램 전환 완료** (v1.0.0 — 2026-04-18)
10. **closing_report 총자산/정산현황/예수금 섹션 분리**
11. **morning_report / intraday_report 예수금 섹션 통일**
12. **프로젝트 경로 재구조화**: `project/stockpilot` → `projects/AI_Projects/stockpilot`
13. **GitHub 저장소 연결**: `Hyoungjin-Lee/AI_Projects` 최초 push
14. **v2.0 에이전트 아키텍처 완료** (2026-04-19):
    - `state_manager.py` — 에이전트 간 공유 상태
    - 5개 스크립트 state 연동
    - `telegram_bot.py` — 텔레그램 명령 수신 데몬
    - `orchestrator.py` — 명령 라우팅 (`/잔고` `/상태` `/발굴`)
    - `com.aigeenya.stockbot.plist` — 부팅 시 자동 시작
    - AGENTS.md 전면 재작성 (v2.0 반영)
    - WORKFLOW.md 독립 검증 프로토콜 추가 (섹션 10)

---

*자동 생성 | stockpilot v2.0 — AI 주식 자동화 시스템*
